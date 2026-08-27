"""Local TTS via Piper, then espeak, then mock (print)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

from app.paths import resolve

log = logging.getLogger("grokbot.tts")


class TextToSpeech:
    def __init__(self, settings: Any):
        self.settings = settings
        tts = (settings.audio or {}).get("tts") or {}
        self.engine = str(tts.get("engine") or "piper")
        self.voice = str(tts.get("voice") or "en_US-lessac-medium")
        self.model_path = resolve(tts.get("model_path") or f"models/{self.voice}.onnx")
        self._piper = None
        self.backend = "mock"
        self.available = False
        if self.engine == "mock" and settings.dev_mode:
            log.info("TTS: mock (DEV_MODE)")
            return
        if self._try_piper():
            return
        if shutil.which("espeak") or shutil.which("espeak-ng"):
            self.backend = "espeak"
            self.available = True
            log.info("TTS: espeak fallback")
            return
        self.backend = "mock"
        log.info("TTS: mock (no Piper voice / espeak)")

    def _try_piper(self) -> bool:
        if not self.model_path.is_file():
            log.warning("Piper voice not found at %s", self.model_path)
            return False
        try:
            from piper import PiperVoice  # type: ignore
        except ImportError:
            log.warning("piper-tts package not installed")
            return False
        try:
            self._piper = PiperVoice.load(str(self.model_path))
            self.backend = "piper"
            self.available = True
            log.info("TTS: Piper voice %s", self.model_path.name)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load Piper voice: %s", exc)
            return False

    def synthesize_wav(self, text: str, dest: Path | None = None) -> Path | None:
        text = (text or "").strip()
        if not text:
            return None
        if dest is None:
            dest = Path(tempfile.mkstemp(suffix=".wav", prefix="grok-tts-")[1])
        dest.parent.mkdir(parents=True, exist_ok=True)

        if self.backend == "piper" and self._piper is not None:
            try:
                with wave.open(str(dest), "wb") as wf:
                    if hasattr(self._piper, "synthesize_wav"):
                        self._piper.synthesize_wav(text, wf)
                    else:
                        self._piper.synthesize(text, wf)
                return dest
            except TypeError:
                try:
                    with wave.open(str(dest), "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(getattr(self._piper, "sample_rate", 22050))
                        for chunk in self._piper.synthesize(text):
                            audio = getattr(chunk, "audio_int16_bytes", None)
                            if audio:
                                wf.writeframes(audio)
                    return dest
                except Exception as exc:  # noqa: BLE001
                    log.warning("Piper synthesize failed: %s", exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("Piper synthesize failed: %s", exc)

        if self.backend == "espeak":
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if exe:
                proc = subprocess.run(
                    [exe, "-w", str(dest), text],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if proc.returncode == 0 and dest.is_file():
                    return dest

        log.info("TTS mock (would speak): %s", text[:200])
        return None

    def speak(self, text: str) -> Path | None:
        """Synthesize and play locally. Returns wav path if one was created."""
        wav = self.synthesize_wav(text)
        if wav is None:
            print(f"[TTS] {text}")
            return None
        self.play_wav(wav)
        return wav

    def play_wav(self, path: Path) -> None:
        for argv in (
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
            ["paplay", str(path)],
            ["aplay", str(path)],
            ["pw-play", str(path)],
        ):
            if shutil.which(argv[0]):
                subprocess.run(argv, check=False, timeout=120)
                return
        log.info("No WAV player found; skip playback of %s", path)
