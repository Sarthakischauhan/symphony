"""Harness add-on that records coding-agent runs in Langfuse.

One Langfuse trace is one ``CoreHarness.run`` (one agent task). Nested
observations capture the conversation actually sent on each model turn, each
tool call, and compaction. Credentials come from the environment
(``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` / optional
``LANGFUSE_BASE_URL``). Missing keys or a missing SDK keep the add-on silent.
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any, Optional

from core_ai.types import Message
from core_harness.addons import Addon

from coding_agent.config import LangfuseConfig
from coding_agent.langfuse.serialize import (
    serialize_messages,
    serialize_run_output,
    serialize_task,
    serialize_tool_arguments,
    serialize_tool_result,
    serialize_turn_output,
    usage_payload,
)

logger = logging.getLogger(__name__)


def _env_enabled() -> bool:
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    return bool(public_key and secret_key)


class LangfuseAddon(Addon):
    """Trace agent runs, model turns, and tools when Langfuse is configured."""

    name = "langfuse"

    def __init__(
        self,
        *,
        enabled: bool = True,
        sample_rate: float = 1.0,
        max_payload_chars: int = 32_000,
        client: Any = None,
    ) -> None:
        self.enabled = enabled
        self.sample_rate = sample_rate
        self.max_payload_chars = max_payload_chars
        self._injected_client = client
        self._client: Any = None
        self._harness: Any = None
        self._run_observation: Any = None
        self._turn_observation: Any = None
        self._tool_observations: dict[str, Any] = {}

    def attach(self, harness: Any) -> None:
        self._harness = harness
        if self._injected_client is not None:
            self._client = self._injected_client
            return
        if not self.enabled or not _env_enabled():
            return
        try:
            from langfuse import Langfuse
        except ImportError:
            logger.warning(
                "Langfuse tracing is enabled but the langfuse package is not installed. "
                "Install it with: pip install 'symphony-code[langfuse]'"
            )
            return
        # Pass credentials explicitly instead of relying on the SDK to read
        # them from its own environment.  This matters when the TUI has just
        # written ~/.symphony/.env (or when the addon is used as a library).
        kwargs: dict[str, Any] = {
            "public_key": os.environ["LANGFUSE_PUBLIC_KEY"].strip(),
            "secret_key": os.environ["LANGFUSE_SECRET_KEY"].strip(),
        }
        # LANGFUSE_HOST is the name used by the Langfuse SDK/documentation;
        # BASE_URL is retained for Symphony's existing setup screen.
        base_url = (
            os.environ.get("LANGFUSE_BASE_URL", "").strip()
            or os.environ.get("LANGFUSE_HOST", "").strip()
        )
        if base_url:
            kwargs["base_url"] = base_url
            kwargs["host"] = base_url
        try:
            self._client = Langfuse(**kwargs)
        except TypeError:
            kwargs.pop("base_url", None)
            try:
                self._client = Langfuse(**kwargs)
            except Exception:
                logger.exception("Failed to initialize Langfuse client")
                self._client = None
        except Exception:
            logger.exception("Failed to initialize Langfuse client")
            self._client = None

    def fork_for_child(self, parent_harness: Any) -> LangfuseAddon:
        del parent_harness
        return LangfuseAddon(
            enabled=self.enabled,
            sample_rate=self.sample_rate,
            max_payload_chars=self.max_payload_chars,
            client=self._injected_client if self._injected_client is not None else self._client,
        )

    def _active(self) -> bool:
        return self._client is not None and self._run_observation is not None

    def _observation_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        """Drop keys Langfuse v3/v4 ``start_observation`` / ``update`` reject."""
        blocked = {"session_id", "user_id", "tags", "trace_id"}
        return {key: value for key, value in kwargs.items() if key not in blocked and value is not None}

    def _trace_context(self, parent: Any) -> Optional[dict[str, str]]:
        if parent is None:
            return None
        trace_id = getattr(parent, "trace_id", None)
        span_id = getattr(parent, "id", None)
        if not trace_id:
            return None
        context: dict[str, str] = {"trace_id": str(trace_id)}
        if span_id:
            context["parent_span_id"] = str(span_id)
        return context

    def _call_start(self, host: Any, *, name: str, as_type: str, payload: dict[str, Any]) -> Any:
        starter = getattr(host, "start_observation", None)
        if not callable(starter):
            return None
        try:
            return starter(name=name, as_type=as_type, **payload)
        except TypeError:
            try:
                return starter(name=name, **payload)
            except TypeError:
                trimmed = dict(payload)
                trimmed.pop("trace_context", None)
                try:
                    return starter(name=name, as_type=as_type, **trimmed)
                except Exception:
                    logger.exception("Langfuse start_observation failed")
                    return None
            except Exception:
                logger.exception("Langfuse start_observation failed")
                return None
        except Exception:
            logger.exception("Langfuse start_observation failed")
            return None

    def _start(
        self,
        *,
        name: str,
        as_type: str,
        parent: Any = None,
        **kwargs: Any,
    ) -> Any:
        payload = self._observation_kwargs(**kwargs)
        observation = None
        if parent is not None:
            observation = self._call_start(parent, name=name, as_type=as_type, payload=payload)
        if observation is None and self._client is not None:
            context = self._trace_context(parent)
            client_payload = dict(payload)
            if context:
                client_payload["trace_context"] = context
            observation = self._call_start(
                self._client, name=name, as_type=as_type, payload=client_payload
            )
        self._apply_trace_attributes(observation)
        return observation

    def _update(self, observation: Any, **kwargs: Any) -> None:
        if observation is None or not kwargs:
            return
        updater = getattr(observation, "update", None)
        if not callable(updater):
            return
        payload = self._observation_kwargs(**kwargs)
        if not payload:
            return
        try:
            updater(**payload)
        except TypeError:
            logger.exception("Langfuse observation update failed")
        except Exception:
            logger.exception("Langfuse observation update failed")

    def _end(self, observation: Any, **kwargs: Any) -> None:
        if observation is None:
            return
        if kwargs:
            self._update(observation, **kwargs)
        ender = getattr(observation, "end", None)
        if callable(ender):
            try:
                ender()
            except Exception:
                logger.exception("Langfuse observation end failed")

    def _session_id(self) -> Optional[str]:
        if self._harness is None:
            return None
        return getattr(self._harness, "_active_session_id", None) or getattr(self._harness, "session_id", None)

    def _run_id(self) -> Optional[str]:
        if self._harness is None:
            return None
        return getattr(self._harness, "_active_run_id", None)

    def _model_id(self) -> Optional[str]:
        if self._harness is None:
            return None
        return getattr(self._harness, "model_id", None)

    def _metadata(self, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent": "symphony-code",
            "model_id": self._model_id(),
            "run_id": self._run_id(),
            "agent_id": getattr(self._harness, "agent_id", None) if self._harness else None,
            "parent_id": getattr(self._harness, "parent_id", None) if self._harness else None,
        }
        if extra:
            payload.update(extra)
        return {key: value for key, value in payload.items() if value is not None}

    def _apply_trace_attributes(self, observation: Any) -> None:
        """Attach session_id without passing it to ``start_observation``.

        Langfuse v4 ``start_observation`` rejects ``session_id`` (that TypeError
        was swallowed, so every run created zero traces). v4 stores the id on
        the OTEL span as ``session.id``; v3 used ``update_trace``.
        """
        if observation is None:
            return
        session_id = self._session_id()
        if not session_id:
            return
        otel_span = getattr(observation, "_otel_span", None)
        set_attribute = getattr(otel_span, "set_attribute", None)
        if callable(set_attribute):
            try:
                set_attribute("session.id", session_id)
            except Exception:
                logger.exception("Langfuse session attribute failed")
        setter = getattr(observation, "update_trace", None)
        if callable(setter):
            try:
                setter(session_id=session_id)
            except Exception:
                logger.exception("Langfuse update_trace failed")

    async def before_run(self, **payload: Any) -> None:
        if self._client is None:
            return
        if self.sample_rate < 1.0 and random.random() >= self.sample_rate:
            return
        messages = payload.get("messages") or []
        task = ""
        for message in reversed(list(messages)):
            if isinstance(message, Message) and message.role == "user":
                task = serialize_task(message.content, max_chars=self.max_payload_chars)
                break
        self._run_observation = self._start(
            name="coding-agent-run",
            as_type="span",
            input=task,
            metadata=self._metadata({"message_count": len(messages)}),
        )
        self._update(
            self._run_observation,
            input=task,
            metadata=self._metadata({"message_count": len(messages)}),
        )

    async def before_turn(self, **payload: Any) -> None:
        if not self._active():
            return
        messages = payload.get("messages") or []
        turn = payload.get("turn")
        serialized = serialize_messages(messages, max_chars=self.max_payload_chars)
        self._end_turn()
        self._turn_observation = self._start(
            name="model-turn",
            as_type="generation",
            parent=self._run_observation,
            model=self._model_id(),
            input=serialized,
            metadata=self._metadata({"turn": turn, "message_count": len(messages)}),
        )
        self._update(
            self._turn_observation,
            input=serialized,
            metadata=self._metadata({"turn": turn, "message_count": len(messages)}),
        )

    async def after_turn(self, **payload: Any) -> None:
        if not self._active():
            return
        messages = payload.get("messages") or []
        assistant: Any = ""
        tool_calls: list[Any] = []
        for message in reversed(list(messages)):
            if isinstance(message, Message) and message.role == "assistant":
                assistant = message.content
                tool_calls = list(message.tool_calls or [])
                break
        self._end_turn(
            output=serialize_turn_output(
                assistant, tool_calls, max_chars=self.max_payload_chars
            ),
            metadata=self._metadata({
                "turn": payload.get("turn"),
                "had_tool_calls": payload.get("had_tool_calls"),
            }),
        )

    async def before_tool(self, **payload: Any) -> Optional[str]:
        if not self._active():
            return None
        tool_call = payload.get("tool_call")
        tool_name = payload.get("tool_name") or getattr(tool_call, "name", "tool")
        arguments = payload.get("arguments")
        if arguments is None:
            arguments = getattr(tool_call, "arguments", {})
        call_id = getattr(tool_call, "id", None) or str(tool_name)
        observation = self._start(
            name=str(tool_name),
            as_type="tool",
            parent=self._run_observation,
            input=serialize_tool_arguments(arguments, max_chars=self.max_payload_chars),
            metadata=self._metadata({"tool_call_id": call_id}),
        )
        self._tool_observations[str(call_id)] = observation
        return None

    async def on_tool(self, **payload: Any) -> None:
        if not self._active():
            return
        tool_call = payload.get("tool_call")
        call_id = getattr(tool_call, "id", None)
        if not call_id:
            return
        observation = self._tool_observations.pop(str(call_id), None)
        result = payload.get("result")
        status = getattr(result, "status", None)
        level = "ERROR" if status not in (None, "success") else "DEFAULT"
        self._end(
            observation,
            output=serialize_tool_result(result, max_chars=self.max_payload_chars),
            level=level,
            metadata=self._metadata({"tool_name": getattr(tool_call, "name", None), "status": status}),
        )

    async def on_evaluation(self, **payload: Any) -> None:
        if self._client is None:
            return
        result = payload.get("result")
        phase = payload.get("phase") or "evaluation"
        # Do not pass the run observation as parent: Jev is intentionally a
        # separate Langfuse trace. ``_apply_trace_attributes`` still attaches
        # the harness session id to that trace.
        observation = self._start(
            name="evaluator",
            as_type="span",
            input={"phase": phase, "evaluator": payload.get("evaluator", "jev")},
            metadata=self._metadata({"phase": phase, "evaluator": payload.get("evaluator", "jev")}),
        )
        self._end(
            observation,
            output={
                "status": getattr(result, "status", None),
                "findings": [
                    {
                        "question": finding.question,
                        "kind": finding.kind,
                        "label": finding.label,
                        "rationale": finding.rationale,
                    }
                    for finding in (getattr(result, "findings", None) or [])
                ],
            },
        )
        flusher = getattr(self._client, "flush", None)
        if callable(flusher):
            try:
                flusher()
            except Exception:
                logger.exception("Langfuse evaluator flush failed")

    async def on_compact(self, **payload: Any) -> None:
        if not self._active():
            return
        messages = payload.get("messages") or []
        observation = self._start(
            name="compaction",
            as_type="span",
            parent=self._run_observation,
            input={
                "turn": payload.get("turn"),
                "tokens_used": payload.get("tokens_used"),
                "context_limit": payload.get("context_limit"),
                "context_left": payload.get("context_left"),
            },
            output={"message_count": len(messages)},
            metadata=self._metadata({"turn": payload.get("turn")}),
        )
        self._end(observation)

    async def after_run(self, **payload: Any) -> None:
        if self._client is None or self._run_observation is None:
            return
        self._end_turn()
        for observation in list(self._tool_observations.values()):
            self._end(observation)
        self._tool_observations.clear()
        result = payload.get("result")
        output = serialize_run_output(
            getattr(result, "output_text", None) or payload.get("task"),
            max_chars=self.max_payload_chars,
        )
        usage = usage_payload(getattr(result, "usage", None))
        update: dict[str, Any] = {"output": output, "metadata": self._metadata()}
        if usage:
            update["usage_details"] = usage
        self._end(self._run_observation, **update)
        self._run_observation = None
        flusher = getattr(self._client, "flush", None)
        if callable(flusher):
            try:
                flusher()
            except Exception:
                logger.exception("Langfuse flush failed")

    def _end_turn(self, **kwargs: Any) -> None:
        observation = self._turn_observation
        self._turn_observation = None
        self._end(observation, **kwargs)


def langfuse_from_config(config: LangfuseConfig) -> Optional[LangfuseAddon]:
    """Build the add-on when config enables it. Attach still no-ops without keys."""
    if not config.enabled:
        return None
    return LangfuseAddon(
        enabled=True,
        sample_rate=config.sample_rate,
        max_payload_chars=config.max_payload_chars,
    )


__all__ = ["LangfuseAddon", "langfuse_from_config"]
