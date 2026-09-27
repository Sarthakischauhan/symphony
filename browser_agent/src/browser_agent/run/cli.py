"""``symphony-browser``: a chat model drives a page through the core harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

from core_ai.providers.catalog import MissingProviderCredentials
from playwright.async_api import Error as PlaywrightError

from browser_agent.agent import BrowserAgent
from browser_agent.session import PlaywrightBrowser
from browser_agent.urls import require_http_url


def build_parser() -> argparse.ArgumentParser:
    """One positional query, optionally starting at ``--url``."""
    parser = argparse.ArgumentParser(
        prog="symphony-browser",
        description="Browser-use agent. The core harness loop calls the browser tools; its last message is the answer.",
    )
    parser.add_argument("query", help="What to do. This is the harness user message. Never put credentials here.")
    parser.add_argument(
        "--url",
        default="",
        help="Optional http or https page to open. Defaults to a DuckDuckGo HTML search for the query.",
    )
    parser.add_argument(
        "--model", default="", help="provider:model for the harness. Defaults to the configured chat model."
    )
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument(
        "--no-sandbox", action="store_true", help="Disable the Chromium sandbox. Only for root or containers."
    )
    parser.add_argument("--trace", default="", help="Write the JSON result to this path.")
    return parser


async def run_query(args: argparse.Namespace, url: str) -> int:
    """Run one query and print the JSON result. 0 done, 1 not done, 2 setup or page-load error."""
    try:
        agent = BrowserAgent(model_id=args.model, max_steps=args.max_steps)
    except (MissingProviderCredentials, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 2
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
        result = await agent.run(args.query, session)
    finally:
        await browser.stop()
    text = json.dumps(result.model_dump(), indent=2)
    if args.trace:
        Path(args.trace).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.status == "done" else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``symphony-browser``."""
    args = build_parser().parse_args(argv)
    # DuckDuckGo's HTML endpoint, not Google. A fresh Playwright Chromium is
    # routinely served Google's "this page was blocked" interstitial, and the
    # agent then treats that page as the site. This endpoint is static HTML
    # with no JavaScript challenge. It can still rate-limit or show a CAPTCHA;
    # it is not a guarantee. Pass --url to open a specific page instead.
    url = args.url or f"https://html.duckduckgo.com/html/?q={quote_plus(args.query)}"
    try:
        require_http_url(url)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return asyncio.run(run_query(args, url))


__all__ = ["build_parser", "main"]
