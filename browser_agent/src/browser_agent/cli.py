"""`symphony-browser` — Jev drives a page, one choice per step."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from browser_agent.agent import BrowserAgent
from browser_agent.demo_site import DEMO_GOAL, DemoSite
from browser_agent.policy import DecisionError, build_policy
from browser_agent.session import PlaywrightBrowser
from browser_agent.text import build_text_writer


def parser() -> argparse.ArgumentParser:
    tool = argparse.ArgumentParser(
        prog="symphony-browser",
        description="Browser-use agent. Jev picks every action; a text model writes only when typing.",
    )
    sub = tool.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Search the local Symphony Books catalog.")
    demo.add_argument("--policy", choices=("auto", "jev", "fixture"), default="auto")
    demo.add_argument("--max-steps", type=int, default=6)
    demo.add_argument("--headed", action="store_true")
    demo.add_argument("--trace", default="", help="Write the JSON trace to this path.")
    _add_text_model(demo)

    run = sub.add_parser("run", help="Open a URL and pursue a goal.")
    run.add_argument("--url", required=True)
    run.add_argument("--goal", required=True)
    run.add_argument("--policy", choices=("auto", "jev", "fixture"), default="auto")
    run.add_argument("--max-steps", type=int, default=12)
    run.add_argument("--headed", action="store_true")
    run.add_argument("--trace", default="")
    _add_text_model(run)
    return tool


def _add_text_model(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--text-model",
        default="",
        help="Chat model used only for TYPE_TEXT when the goal has no literal. Example: grok:grok-4.5",
    )


async def _execute(args: argparse.Namespace, url: str, goal: str) -> int:
    try:
        policy = build_policy(args.policy)
    except DecisionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if policy.provider == "fixture":
        print(
            "No Jev credentials found. Running the offline fixture policy, not typesafe-ai/jev.\n"
            "Set AI_GATEWAY_API_KEY, TYPESAFE_API_KEY, or OPENROUTER_API_KEY to let Jev drive.",
            file=sys.stderr,
        )
    browser = PlaywrightBrowser()
    await browser.start(headless=not args.headed)
    try:
        session = await browser.open(url)
        agent = BrowserAgent(
            policy,
            max_steps=args.max_steps,
            text_writer=build_text_writer(args.text_model),
        )
        result = await agent.run(goal, session)
    finally:
        await browser.stop()
    payload = result.model_dump()
    text = json.dumps(payload, indent=2)
    if args.trace:
        with open(args.trace, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0 if result.status == "done" else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "demo":
        site = DemoSite()
        try:
            return asyncio.run(_execute(args, site.url, DEMO_GOAL))
        finally:
            site.close()
    if args.url.startswith(("http://", "https://")):
        return asyncio.run(_execute(args, args.url, args.goal))
    print("Only http and https URLs are allowed.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "parser"]
