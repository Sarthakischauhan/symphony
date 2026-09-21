"""Per-action Jev handlers. Policy chooses ``action``; this module actuates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from coding_agent.evaluation.policy import PolicyDecision, critic_message
from coding_agent.evaluation.protocol import CONTINUE_NORMALLY

# Read-only allowlist: write/edit/bash (and other implement tools) stay gated.
READ_ONLY_TOOLS = frozenset({"read_file", "search", "ask_user", "memory"})


@dataclass(frozen=True)
class HandlerResult:
    note: Optional[str] = None
    allow: Optional[frozenset[str]] = None


def handle_replan(decision: PolicyDecision) -> HandlerResult:
    return HandlerResult(note=critic_message(decision), allow=READ_ONLY_TOOLS)


def handle_retry(decision: PolicyDecision) -> HandlerResult:
    return HandlerResult(note=critic_message(decision))


def handle_review(decision: PolicyDecision) -> HandlerResult:
    return HandlerResult(note=critic_message(decision))


def handle_gather(decision: PolicyDecision) -> HandlerResult:
    return HandlerResult(note=critic_message(decision), allow=READ_ONLY_TOOLS)


def handle_ask(decision: PolicyDecision) -> HandlerResult:
    return HandlerResult(note=critic_message(decision), allow=READ_ONLY_TOOLS)


def handle_finish(decision: PolicyDecision) -> HandlerResult:
    del decision
    return HandlerResult()


def handle_unsupported_claims(decision: PolicyDecision) -> HandlerResult:
    return handle_review(decision)


HANDLERS: dict[str, Callable[[PolicyDecision], HandlerResult]] = {
    "replan": handle_replan,
    "retry": handle_retry,
    "review": handle_review,
    "gather": handle_gather,
    "ask": handle_ask,
    CONTINUE_NORMALLY: handle_finish,
    "unsupported_claims": handle_unsupported_claims,
}


def dispatch(decision: PolicyDecision) -> HandlerResult:
    """Named handler for ``last_decision.action`` (plus unsupported_claims)."""
    finding = decision.finding
    if decision.action == "review" and finding is not None and finding.question == "unsupported_claims":
        return handle_unsupported_claims(decision)
    return HANDLERS.get(decision.action, handle_finish)(decision)
