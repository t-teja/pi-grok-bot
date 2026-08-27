"""Optional server-side mic loop for wake-word + follow-up on a Pi.

Tap-to-talk in the browser is the primary path. This loop is extra: when a
USB/I2S mic is attached and Vosk is loaded, saying the wake phrase starts a
command capture without touching the screen.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("grokbot.mic")


async def run_wake_loop(session: Any, stop: asyncio.Event) -> None:
    settings = session.settings
    wake_cfg = (settings.audio or {}).get("wake_word") or {}
    if not wake_cfg.get("enabled", True):
        return
    if settings.dev_mode:
        log.info("Wake-word loop skipped in DEV_MODE")
        return
    if not session.stt.available:
        log.info("Wake-word loop skipped (Vosk not loaded)")
        return
    try:
        import sounddevice as sd  # type: ignore
        from vosk import KaldiRecognizer  # type: ignore
    except ImportError:
        log.info("Wake-word loop skipped (sounddevice/vosk missing)")
        return

    rate = int((settings.audio or {}).get("sample_rate") or 16000)
    phrase = str(wake_cfg.get("phrase") or "hey grok").lower()
    model = session.stt._model
    rec = KaldiRecognizer(model, rate)
    rec.SetWords(True)
    log.info("Wake-word loop listening for %r", phrase)

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)

    def callback(indata, frames, time_info, status):  # noqa: ANN001
        if status:
            log.debug("mic status: %s", status)
        try:
            q.put_nowait(bytes(indata))
        except asyncio.QueueFull:
            pass

    try:
        stream = sd.RawInputStream(
            samplerate=rate,
            blocksize=4000,
            dtype="int16",
            channels=1,
            callback=callback,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not open microphone: %s", exc)
        return

    capturing = False
    follow_pcm = bytearray()
    silence_chunks = 0

    with stream:
        while not stop.is_set():
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if rec.AcceptWaveform(chunk):
                payload = json.loads(rec.Result())
                text = (payload.get("text") or "").strip()
            else:
                payload = json.loads(rec.PartialResult())
                text = (payload.get("partial") or "").strip()

            if not capturing and phrase in text.lower():
                capturing = True
                follow_pcm = bytearray()
                silence_chunks = 0
                await session.set_state("listening", reason="wake")
                log.info("Wake word heard: %s", text)
                continue

            if capturing:
                follow_pcm.extend(chunk)
                if text:
                    silence_chunks = 0
                else:
                    silence_chunks += 1
                if silence_chunks > 6 or len(follow_pcm) > rate * 2 * 8:
                    capturing = False
                    pcm = bytes(follow_pcm)
                    follow_pcm = bytearray()
                    uttered = await loop.run_in_executor(
                        None, session.stt.transcribe_pcm16, pcm, rate
                    )
                    uttered = uttered.lower().replace(phrase, "").strip(" ,.-")
                    if uttered:
                        await session.handle_user_text(uttered, source="wake")
                    else:
                        await session.set_state("idle")
