"""Conversation session, timers, and kiosk state fan-out."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Coroutine

from app.audio.stt import SpeechToText
from app.audio.tts import TextToSpeech
from app.grok import GrokClient, GrokError
from app.tools.builtins import register_all
from app.tools.registry import ToolRegistry

log = logging.getLogger("grokbot.session")

Listener = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class TimerHub:
    def __init__(self, on_fire: Callable[[str, str], Coroutine[Any, Any, None]]):
        self._on_fire = on_fire
        self._tasks: dict[str, asyncio.Task] = {}

    def add(self, seconds: int, message: str) -> str:
        timer_id = uuid.uuid4().hex[:8]
        self._tasks[timer_id] = asyncio.create_task(self._run(timer_id, seconds, message))
        return timer_id

    async def _run(self, timer_id: str, seconds: int, message: str) -> None:
        try:
            await asyncio.sleep(seconds)
            await self._on_fire(timer_id, message)
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(timer_id, None)


class KioskSession:
    def __init__(self, settings: Any):
        self.settings = settings
        self.state = "idle"
        self.history: list[dict[str, Any]] = []
        self.listeners: set[Listener] = set()
        self.busy = asyncio.Lock()
        self.stt = SpeechToText(settings)
        self.tts = TextToSpeech(settings)
        self.grok = GrokClient(settings)
        self.timers = TimerHub(self._timer_fired)
        self.tools = ToolRegistry()
        register_all(self.tools, settings, scheduler=self.timers)
        self.last_error: str | None = None

    async def emit(self, event: dict[str, Any]) -> None:
        dead = []
        for listener in list(self.listeners):
            try:
                await listener(event)
            except Exception:
                dead.append(listener)
        for listener in dead:
            self.listeners.discard(listener)

    async def set_state(self, state: str, **extra: Any) -> None:
        self.state = state
        payload = {"type": "state", "state": state, **extra}
        await self.emit(payload)

    async def _timer_fired(self, timer_id: str, message: str) -> None:
        await self.emit({"type": "timer", "id": timer_id, "message": message})
        await self.set_state("speaking", reason="timer")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.tts.speak, f"Reminder: {message}")
        await self.set_state("idle")

    def subscribe(self, listener: Listener) -> None:
        self.listeners.add(listener)

    def unsubscribe(self, listener: Listener) -> None:
        self.listeners.discard(listener)

    def _trim_history(self) -> None:
        if len(self.history) > 40:
            self.history = self.history[-40:]

    async def handle_user_text(self, text: str, source: str = "text") -> str:
        text = (text or "").strip()
        if not text:
            return ""
        async with self.busy:
            return await self._turn(text, source)

    async def _turn(self, text: str, source: str) -> str:
        self.last_error = None
        await self.emit({"type": "transcript", "text": text, "final": True, "source": source})
        self.history.append({"role": "user", "content": text})
        self._trim_history()
        await self.set_state("thinking")

        async def on_token(token: str) -> None:
            await self.emit({"type": "assistant_delta", "text": token})

        async def on_tool(name: str, payload: dict[str, Any]) -> None:
            await self.emit({"type": "tool", "name": name, "result": payload})
            tool = self.tools.get(name)
            if tool and tool.ui_event:
                await self.emit({"type": tool.ui_event, **payload})

        try:
            reply = await self.grok.chat_turn(
                history=self.history,
                tool_schemas=self.tools.schemas(),
                execute_tool=self.tools.call,
                on_token=on_token,
                on_tool=on_tool,
            )
        except GrokError as exc:
            self.last_error = str(exc)
            await self.set_state("error", message=str(exc))
            await self.emit({"type": "error", "message": str(exc)})
            return str(exc)
        except Exception as exc:
            log.exception("Grok turn failed")
            self.last_error = str(exc)
            msg = f"Something went wrong talking to Grok: {exc}"
            await self.set_state("error", message=msg)
            await self.emit({"type": "error", "message": msg})
            return msg

        self.history.append({"role": "assistant", "content": reply})
        await self.emit({"type": "assistant", "text": reply})
        await self.set_state("speaking")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.tts.speak, reply)
        await self.set_state("idle")
        return reply

    async def transcribe_pcm(self, pcm: bytes, sample_rate: int = 16000) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.stt.transcribe_pcm16, pcm, sample_rate)

    def status(self) -> dict[str, Any]:
        pub = self.settings.as_public_dict()
        pub.update(
            {
                "state": self.state,
                "stt": self.stt.backend,
                "tts": self.tts.backend,
                "has_api_key": bool(self.settings.api_key),
                "tools": self.tools.names(),
                "last_error": self.last_error,
            }
        )
        return pub
