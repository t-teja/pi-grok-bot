"""Allowlisted tool registry. Easy to extend — see ARCHITECTURE.md."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("grokbot.tools")

Handler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    # Optional websocket event name the UI should handle (e.g. open_url).
    ui_event: str | None = None

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    name: str
    ok: bool
    data: dict[str, Any]
    ui_event: str | None = None
    ui_payload: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.openai_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(self, name: str, arguments: dict[str, Any] | str | None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name=name, ok=False, data={"error": f"Unknown tool: {name}"})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                return ToolResult(name=name, ok=False, data={"error": f"Bad arguments JSON: {exc}"})
        arguments = arguments or {}
        try:
            data = tool.handler(arguments)
        except Exception as exc:  # noqa: BLE001 — surface to the model, don't crash the kiosk
            log.exception("Tool %s failed", name)
            return ToolResult(name=name, ok=False, data={"error": str(exc)})
        ok = not bool(data.get("error"))
        ui_payload = None
        if tool.ui_event:
            ui_payload = data
        return ToolResult(
            name=name,
            ok=ok,
            data=data,
            ui_event=tool.ui_event,
            ui_payload=ui_payload,
        )


def build_default_registry(settings: Any) -> ToolRegistry:
    from app.tools import builtins

    registry = ToolRegistry()
    builtins.register_all(registry, settings)
    return registry
