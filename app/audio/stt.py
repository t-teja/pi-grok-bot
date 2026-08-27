"""Local STT via Vosk. Falls back to mock in DEV_MODE."""

from __future__ import annotations

import json
import logging
import wave
from pathlib import Path
from typing import Any

from app.paths import resolve

log = logging.getLogger("grokbot.stt")


class SpeechToText:
    def __init__(self, settings: Any):
        self.settings = settings
        audio = settings.audio or {}
        stt = audio.get("stt") or {}
        self.sample_rate = int(audio.get("sample_rate") or 16000)
        self.engine = str(stt.get("engine") or "vosk")
        self.model_dir = resolve(stt.get("model_dir") or "models/vosk-model-small-en-us-0.15")
        self.wake_phrase = str((audio.get("wake_word") or {}).get("phrase") or "hey grok").lower()
        self._model = None
        self.available = False
        self.backend = "mock"
        if self.engine == "mock" or settings.dev_mode:
            # Still try Vosk if the model is present so DEV_MODE can use a real mic.
            if self.model_dir.is_dir():
                self._try_load_vosk()
            if not self.available:
                self.backend = "mock"
                log.info("STT: mock (DEV_MODE or missing Vosk model at %s)", self.model_dir)
            return
        self._try_load_vosk()

    def _try_load_vosk(self) -> None:
        if not self.model_dir.is_dir():
            log.warning("Vosk model not found at %s", self.model_dir)
            return
        try:
            from vosk import Model  # type: ignore
        except ImportError:
            log.warning("vosk package not installed")
            return
        try:
            self._model = Model(str(self.model_dir))
            self.available = True
            self.backend = "vosk"
            log.info("STT: Vosk model loaded from %s", self.model_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load Vosk model: %s", exc)

    def transcribe_wav(self, path: Path) -> str:
        if not self.available or self._model is None:
            return ""
        from vosk import KaldiRecognizer  # type: ignore

        with wave.open(str(path), "rb") as wf:
            rec = KaldiRecognizer(self._model, wf.getframerate())
            rec.SetWords(True)
            parts: list[str] = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    payload = json.loads(rec.Result())
                    if payload.get("text"):
                        parts.append(payload["text"])
            final = json.loads(rec.FinalResult())
            if final.get("text"):
                parts.append(final["text"])
        return " ".join(parts).strip()

    def transcribe_pcm16(self, pcm: bytes, sample_rate: int | None = None) -> str:
        if not self.available or self._model is None:
            return ""
        from vosk import KaldiRecognizer  # type: ignore

        rate = sample_rate or self.sample_rate
        rec = KaldiRecognizer(self._model, rate)
        rec.SetWords(True)
        chunk = 4000
        parts: list[str] = []
        for i in range(0, len(pcm), chunk):
            piece = pcm[i : i + chunk]
            if rec.AcceptWaveform(piece):
                payload = json.loads(rec.Result())
                if payload.get("text"):
                    parts.append(payload["text"])
        final = json.loads(rec.FinalResult())
        if final.get("text"):
            parts.append(final["text"])
        return " ".join(parts).strip()

    def contains_wake_word(self, text: str) -> bool:
        t = (text or "").lower().strip()
        phrase = self.wake_phrase
        return phrase in t or t.replace("-", " ") == phrase
