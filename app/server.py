"""Local FastAPI server: kiosk UI, WebSocket events, STT upload, chat."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import wave
from typing import Any

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.audio.mic import run_wake_loop
from app.config import Settings, get_settings
from app.paths import UI_DIR
from app.session import KioskSession

log = logging.getLogger("grokbot.server")


class ChatIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    session = KioskSession(settings)
    app = FastAPI(title="Pi Grok Bot", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.session = session
    stop = asyncio.Event()

    @app.on_event("startup")
    async def _startup() -> None:
        app.state.wake_task = asyncio.create_task(run_wake_loop(session, stop))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        stop.set()
        task = getattr(app.state, "wake_task", None)
        if task:
            task.cancel()

    if UI_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return session.status()

    @app.post("/api/chat")
    async def chat(body: ChatIn) -> dict[str, Any]:
        reply = await session.handle_user_text(body.text, source="text")
        return {"reply": reply, "state": session.state}

    @app.post("/api/listen/start")
    async def listen_start() -> dict[str, Any]:
        await session.set_state("listening")
        return {"state": session.state}

    @app.post("/api/listen/stop")
    async def listen_stop() -> dict[str, Any]:
        if session.state == "listening":
            await session.set_state("idle")
        return {"state": session.state}

    @app.post("/api/transcribe")
    async def transcribe(file: UploadFile = File(...)) -> dict[str, Any]:
        raw = await file.read()
        pcm, rate = _to_pcm16(raw, file.filename or "audio.wav")
        await session.set_state("listening")
        text = await session.transcribe_pcm(pcm, sample_rate=rate)
        if not text:
            await session.set_state("idle")
            hint = (
                "STT mock/empty. Type in the box, or install the Vosk model."
                if settings.dev_mode
                else "I did not catch that."
            )
            return {"text": "", "error": hint, "stt": session.stt.backend}
        reply = await session.handle_user_text(text, source="voice")
        return {"text": text, "reply": reply, "stt": session.stt.backend}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()

        async def listener(event: dict[str, Any]) -> None:
            await ws.send_json(event)

        session.subscribe(listener)
        try:
            await ws.send_json({"type": "hello", **session.status()})
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await _handle_ws_message(session, msg)
        except WebSocketDisconnect:
            pass
        finally:
            session.unsubscribe(listener)

    return app


async def _handle_ws_message(session: KioskSession, msg: dict[str, Any]) -> None:
    kind = msg.get("type")
    if kind == "chat":
        await session.handle_user_text(str(msg.get("text") or ""), source="text")
    elif kind == "listen_start":
        await session.set_state("listening")
    elif kind == "listen_stop":
        if session.state == "listening":
            await session.set_state("idle")
    elif kind == "ping":
        await session.emit({"type": "pong"})


def _to_pcm16(raw: bytes, filename: str) -> tuple[bytes, int]:
    name = filename.lower()
    if name.endswith(".wav") or raw[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw), "rb") as wf:
            rate = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
        if sw != 2:
            raise ValueError("WAV must be 16-bit PCM")
        if ch > 1:
            out = bytearray()
            step = sw * ch
            for i in range(0, len(frames), step):
                out.extend(frames[i : i + sw])
            frames = bytes(out)
        return frames, rate
    return raw, 16000
