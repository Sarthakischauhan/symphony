"""``symphony-browser``: Jev drives a page, one choice per step."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import Error as PlaywrightError

from browser_agent.agent import BrowserAgent
from browser_agent.demo_site import DEMO_GOAL, DemoSite
from browser_agent.jev_answers import DecisionError
from browser_agent.jev_policy import build_policy
from browser_agent.session import PlaywrightBrowser
from browser_agent.text_writer import build_text_writer
from browser_agent.validate_url import require_http_url

_FIXTURE_NOTICE = (
    "No Jev credentials found. Running the offline fixture policy, not typesafe-ai/jev.\n"
    "Set AI_GATEWAY_API_KEY, TYPESAFE_API_KEY, or OPENROUTER_API_KEY to let Jev drive."
)


def parser() -> argparse.ArgumentParser:
    """The ``demo`` and ``run`` subcommands."""
    tool = argparse.ArgumentParser(
        prog="symphony-browser",
        description="Browser-use agent. Jev picks every action; a text model writes only when typing.",
    )
    sub = tool.add_subparsers(dest="command", required=True)
    _add_common(sub.add_parser("demo", help="Search the local Symphony Books catalog."), max_steps=6)
    run = sub.add_parser("run", help="Open a URL and pursue a goal.")
    run.add_argument("--url", required=True, help="http or https page to open.")
    run.add_argument(
        "--goal",
        required=True,
        help="What to achieve. Never put credentials here: the goal is emitted, sent to Jev, and traced.",
    )
    _add_common(run, max_steps=12)
    return tool


def _add_common(sub: argparse.ArgumentParser, max_steps: int) -> None:
    """Flags shared by ``demo`` and ``run``; only the step default differs."""
    sub.add_argument("--policy", choices=("auto", "jev", "fixture"), default="auto")
    sub.add_argument("--max-steps", type=int, default=max_steps)
    sub.add_argument("--headed", action="store_true", help="Show the browser window.")
    sub.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Disable the Chromium sandbox. Only for root or containers.",
    )
    sub.add_argument("--trace", default="", help="Write the JSON result to this path.")
    sub.add_argument(
        "--text-model",
        default="",
        help="Grok model used only for TYPE_TEXT when the goal has no literal, e.g. grok:grok-4.6.",
    )


async def _execute(args: argparse.Namespace, url: str, goal: str) -> int:
    """Run one goal and print the JSON result. 0 done, 1 not done, 2 setup or page-load error."""
    try:
        policy = build_policy(args.policy)
        text_writer = build_text_writer(args.text_model)
    except (DecisionError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    if policy.provider == "fixture":
        print(_FIXTURE_NOTICE, file=sys.stderr)
    browser = PlaywrightBrowser()
    try:
        try:
            await browser.start(headless=not args.headed, sandbox=not args.no_sandbox)
        except PlaywrightError as exc:
            print(
                f"Chromium failed to launch: {exc}\n"
                "Install it with `uv run playwright install chromium`. "
                "As root or in a container, add --no-sandbox.",
                file=sys.stderr,
            )
            return 2
        try:
            session = await browser.open(url)
        except PlaywrightError as exc:
            print(f"Could not load {url}: {exc}", file=sys.stderr)
            return 2
        result = await BrowserAgent(policy, max_steps=args.max_steps, text_writer=text_writer).run(goal, session)
    finally:
        await browser.stop()
    text = json.dumps(result.model_dump(), indent=2)
    if args.trace:
        Path(args.trace).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.status == "done" else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``symphony-browser``."""
    args = parser().parse_args(argv)
    if args.command == "demo":
        site = DemoSite()
        try:
            return asyncio.run(_execute(args, site.url, DEMO_GOAL))
        finally:
            site.close()
    try:
        require_http_url(args.url)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return asyncio.run(_execute(args, args.url, args.goal))


__all__ = ["main", "parser"]
