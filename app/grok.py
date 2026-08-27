"""xAI Grok client via the OpenAI-compatible Chat Completions API."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

log = logging.getLogger("grokbot.grok")


class GrokError(RuntimeError):
    pass


class GrokClient:
    def __init__(self, settings: Any):
        self.settings = settings
        key = settings.api_key
        self.enabled = bool(key)
        self.client: AsyncOpenAI | None = None
        if key:
            self.client = AsyncOpenAI(api_key=key, base_url=settings.base_url, timeout=90.0)

    def _messages(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system = self.settings.grok.get("system_prompt") or "You are Grok on a Raspberry Pi kiosk."
        return [{"role": "system", "content": system}, *history]

    async def chat_turn(
        self,
        history: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        execute_tool,
        on_token=None,
        on_tool=None,
    ) -> str:
        """Run one user turn, including tool-call loops. Returns final assistant text."""
        if not self.client:
            raise GrokError(
                "No XAI_API_KEY. Copy .env.example to .env and add a key from https://console.x.ai/"
            )

        messages = self._messages(history)
        max_rounds = 6
        final_text = ""

        for _ in range(max_rounds):
            kwargs: dict[str, Any] = {
                "model": self.settings.model,
                "messages": messages,
                "temperature": float(self.settings.grok.get("temperature") or 0.7),
                "max_tokens": int(self.settings.grok.get("max_tokens") or 1024),
                "stream": True,
            }
            if tool_schemas:
                kwargs["tools"] = tool_schemas
                kwargs["tool_choice"] = "auto"

            stream = await self.client.chat.completions.create(**kwargs)
            assistant_text = ""
            tool_acc: dict[int, dict[str, str]] = {}

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    assistant_text += delta.content
                    if on_token:
                        await on_token(delta.content)
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments

            if tool_acc:
                tool_calls = []
                for idx in sorted(tool_acc):
                    slot = tool_acc[idx]
                    tool_calls.append(
                        {
                            "id": slot["id"] or f"call_{idx}",
                            "type": "function",
                            "function": {
                                "name": slot["name"],
                                "arguments": slot["arguments"] or "{}",
                            },
                        }
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text or None,
                        "tool_calls": tool_calls,
                    }
                )
                for call in tool_calls:
                    name = call["function"]["name"]
                    raw_args = call["function"]["arguments"]
                    result = execute_tool(name, raw_args)
                    payload = result.data if hasattr(result, "data") else result
                    if on_tool:
                        await on_tool(name, payload)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(payload, default=str),
                        }
                    )
                continue

            final_text = assistant_text.strip()
            break

        if not final_text:
            final_text = "I have nothing to add."
        return final_text
