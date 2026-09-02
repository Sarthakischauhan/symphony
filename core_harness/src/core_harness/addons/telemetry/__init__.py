"""Telemetry add-on seam. No heavy implementation yet."""

from __future__ import annotations

from typing import Any, Dict, Protocol


class Telemetry(Protocol):
    """Emit run, tool, and usage observations. Implementations are product-owned."""

    async def emit_run(self, event: str, payload: Dict[str, Any]) -> None:
        ...

    async def emit_tool(self, event: str, payload: Dict[str, Any]) -> None:
        ...

    async def emit_usage(self, payload: Dict[str, Any]) -> None:
        ...


class NullTelemetry:
    """Discard telemetry."""

    async def emit_run(self, event: str, payload: Dict[str, Any]) -> None:
        return None

    async def emit_tool(self, event: str, payload: Dict[str, Any]) -> None:
        return None

    async def emit_usage(self, payload: Dict[str, Any]) -> None:
        return None


class TelemetryAddon:
    """Mount a ``Telemetry`` implementation and forward the tiny addon hooks."""

    name = "telemetry"

    def __init__(self, telemetry: Telemetry | None = None) -> None:
        self.telemetry = telemetry or NullTelemetry()

    def attach(self, harness: Any) -> None:
        harness.telemetry = self.telemetry

    async def before_turn(self, **payload: Any) -> None:
        await self.telemetry.emit_run("before_turn", payload)

    async def after_turn(self, **payload: Any) -> None:
        await self.telemetry.emit_run("after_turn", payload)

    async def on_tool(self, **payload: Any) -> None:
        await self.telemetry.emit_tool("on_tool", payload)

    async def on_compact(self, **payload: Any) -> None:
        await self.telemetry.emit_run("on_compact", payload)


__all__ = ["NullTelemetry", "Telemetry", "TelemetryAddon"]
