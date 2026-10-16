"""web_search talks to Exa's hosted MCP endpoint. Every test mocks the transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import httpx

from coding_agent.addons.approvals import DENY, ApprovalAddon, ApprovalPolicy
from coding_agent.addons.plan.addon import PlanModeState
from coding_agent.config import ApprovalConfig, ToolsConfig, WebSearchConfig
from coding_agent.protocols.acp.mapping import TOOL_KINDS
from coding_agent.tools import WebSearchTool, build_tools
from coding_agent.tools.web_search import EXA_KEY_ENV, EXA_MCP_URL, rpc_message
from coding_agent.tui.tools.labels import tool_detail, tool_label
from core_harness import EventSink, HumanInteraction

RESULTS = "Title: Transports\nURL: https://www.python-httpx.org/advanced/transports/\nHighlights:\nMock transports"


def sse(result: dict[str, Any]) -> httpx.Response:
    body = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) + "\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def found(text: str = RESULTS) -> httpx.Response:
    return sse({"content": [{"type": "text", "text": text}]})


def search(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    config: WebSearchConfig | None = None,
    **args: Any,
) -> str:
    tool = WebSearchTool(
        tmp_path, config=config or WebSearchConfig(), transport=httpx.MockTransport(handler)
    )
    return asyncio.run(tool.execute(sink=None, args={"query": "httpx mock transport", **args}))


def test_search_sends_only_the_query_and_returns_the_result_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(EXA_KEY_ENV, raising=False)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return found()

    assert search(tmp_path, handler, max_results=3, activity={"verb": "Searching"}) == RESULTS
    (request,) = seen
    assert str(request.url) == EXA_MCP_URL
    assert "x-api-key" not in request.headers
    body = json.loads(request.content)
    assert body["method"] == "tools/call"
    assert body["params"] == {
        "name": "web_search_exa",
        "arguments": {
            "query": "httpx mock transport",
            "objective": "httpx mock transport",
            "numResults": 3,
        },
    }


def test_search_uses_the_configured_default_and_an_optional_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(EXA_KEY_ENV, " secret-key ")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "content": [{"type": "text", "text": RESULTS}],
        }})

    config = WebSearchConfig(default_max_results=2)
    assert search(tmp_path, handler, config=config) == RESULTS
    assert seen[0].headers["x-api-key"] == "secret-key"
    assert json.loads(seen[0].content)["params"]["arguments"]["numResults"] == 2
    tool = WebSearchTool(tmp_path, config=config)
    assert tool.parameters["properties"]["max_results"]["default"] == 2
    # Serial: a parallel batch would raise several approval prompts at once.
    assert tool.parallel is False


def test_search_reports_rate_limits_as_errors(tmp_path: Path) -> None:
    limited = "You've hit Exa's free MCP rate limit. Fix: update Exa MCP URL."
    flagged = sse({"_meta": {"ai.exa/rateLimited": True}, "content": [{"type": "text", "text": limited}]})
    for response in (flagged, found(limited), httpx.Response(429, text="slow down")):
        result = search(tmp_path, lambda _request, response=response: response)
        assert result.startswith("error: web search is rate limited")
        assert EXA_KEY_ENV in result
        assert "exaApiKey" not in result


def test_search_turns_failures_into_error_strings(tmp_path: Path) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    rpc_error = httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad args"}})
    cases = {
        "error: web search timed out after 20s": timeout,
        "error: web search request failed: no route": offline,
        "error: web search failed with HTTP 503": lambda _request: httpx.Response(503),
        "error: web search failed: bad args": lambda _request: rpc_error,
        "error: web search returned an unreadable response": lambda _request: httpx.Response(200, text="<html>"),
        "error: web search failed: upstream broke": lambda _request: sse(
            {"isError": True, "content": [{"type": "text", "text": "upstream broke"}]}
        ),
        "no web results for 'httpx mock transport'": lambda _request: sse({"content": []}),
    }
    for expected, handler in cases.items():
        assert search(tmp_path, handler) == expected


def test_search_caps_long_results(tmp_path: Path) -> None:
    result = search(
        tmp_path, lambda _request: found("URL: https://example.com\n" + "x" * 500),
        config=WebSearchConfig(max_output_chars=100),
    )
    assert result.endswith("\n… web results truncated")
    assert len(result) == 100 + len("\n… web results truncated")


def test_rpc_message_reads_json_and_the_last_sse_reply() -> None:
    assert rpc_message('{"jsonrpc": "2.0", "id": 1, "result": {}}') == {"jsonrpc": "2.0", "id": 1, "result": {}}
    stream = 'event: message\ndata: {"method": "notifications/progress"}\n\ndata: {"id": 1, "result": {"ok": 1}}\n'
    assert rpc_message(stream) == {"id": 1, "result": {"ok": 1}}
    assert rpc_message("data: not json") is None
    assert rpc_message("") is None


def test_web_search_can_be_disabled_and_is_allowed_while_planning(tmp_path: Path) -> None:
    disabled = ToolsConfig(web_search=WebSearchConfig(enabled=False))
    assert "web_search" in [tool.name for tool in build_tools(tmp_path)]
    assert "web_search" not in [tool.name for tool in build_tools(tmp_path, config=disabled)]
    plan = PlanModeState()
    plan.begin()
    assert plan.permits("web_search")


def test_web_search_prompts_and_matches_only_prefixed_rules(tmp_path: Path) -> None:
    policy = ApprovalPolicy(tmp_path)
    call = {"query": "git rebase docs", "max_results": 3}
    prompt = policy.prompt_for(ApprovalConfig(), "web_search", call)
    assert prompt == "Allow web search once?\n`git rebase docs`"
    assert policy.prompt_for(ApprovalConfig(require_for_web_search=False), "web_search", call) == ""
    assert policy.prompt_for(ApprovalConfig(mode="always_allow"), "web_search", call) == ""
    # A bash allow rule must not wave a search through. A prefixed rule does.
    assert policy.prompt_for(ApprovalConfig(allow=["git *"]), "web_search", call) == prompt
    assert policy.prompt_for(ApprovalConfig(allow=["web_search:git *"]), "web_search", call) == ""


def test_web_search_approval_asks_denies_and_logs_unattended_runs(tmp_path: Path) -> None:
    async def scenario() -> None:
        sink = EventSink()
        sink.interaction = HumanInteraction(sink)
        addon = ApprovalAddon(tmp_path, sink, approvals=ApprovalConfig(deny=["web_search:*password*"]))
        pending = asyncio.create_task(addon.before_tool(tool_name="web_search", arguments={"query": "textual docs"}))
        await asyncio.sleep(0)
        (asked,) = [e.payload for e in sink.events if e.event_type == "question_asked"]
        assert asked["question"] == "Allow web search once?\n`textual docs`"
        sink.interaction.answer(asked["request_id"], DENY)
        assert await pending == "tool call denied by user"

        denied = await addon.before_tool(tool_name="web_search", arguments={"query": "my password hunter2"})
        assert denied == "tool call denied by rule 'web_search:*password*'"

        unattended = EventSink()
        robot = ApprovalAddon(tmp_path, unattended, approvals=ApprovalConfig(), unattended=True)
        assert await robot.before_tool(tool_name="web_search", arguments={"query": "textual docs"}) is None
        assert [e.payload for e in unattended.events] == [
            {"kind": "approval", "tool": "web_search", "decision": "allow", "rule": "unattended"}
        ]

    asyncio.run(scenario())


def test_web_search_card_and_acp_kind() -> None:
    assert tool_label("web_search") == ("Web Search", "⌕")
    assert tool_detail("web_search", {"query": "textual docs", "max_results": 3}) == "textual docs"
    assert TOOL_KINDS["web_search"] == "fetch"
