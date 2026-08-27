# pi-grok-bot

Unofficial Raspberry Pi kiosk companion powered by the xAI Grok API.

This is **not** the Cursor Grok Bot PC/iOS app. It is a Pi-native character on a HDMI/DSI display: it listens (tap-to-talk or "hey grok"), thinks via Grok, talks back with local TTS, and runs a small allowlist of tools (time, stats, volume, timers, music, screenshots). It never exposes an unbounded root shell.

Built for Raspberry Pi 4 and Pi 5, Raspberry Pi OS Bookworm 64-bit, a ~7-10 inch HDMI (or 1920x1080) screen, a USB or I2S mic, and speakers.

## Honesty

- Community project. Not affiliated with xAI, Cursor, or Raspberry Pi Ltd.
- Requires your own xAI API key from https://console.x.ai/ and paid API usage.
- Default chat model is `grok-4.6` (current xAI flagship as of August 2026). Override in `config.yaml` or `GROK_MODEL`.
- Speech-to-text and speech-to-audio stay on the Pi. Only the text of a turn is sent to `https://api.x.ai/v1`.

## Hardware

| Piece | Notes |
| --- | --- |
| Pi 4 (2 GB+) or Pi 5 | 4 GB+ recommended. Pi 5 is snappier for Piper TTS. |
| Raspberry Pi OS Bookworm 64-bit with desktop | Needed for Chromium kiosk. Lite works for the backend only. |
| Display | HDMI or DSI, 7-10 inch is the sweet spot; 1920x1080 looks great. |
| Mic | USB mic is easiest. I2S mics need a dtoverlay in `/boot/firmware/config.txt`. |
| Speakers | 3.5 mm, HDMI audio, or USB DAC. Bookworm uses PipeWire (`wpctl`); PulseAudio (`pactl`) is a fallback. |

### Pi 4 vs Pi 5

- Both run the default Vosk small English model (~40 MB, near real-time).
- Piper `en_US-lessac-medium` is fine on Pi 4; Pi 5 has headroom. If Pi 4 TTS feels laggy, switch `audio.tts.voice` to `en_US-lessac-low` and re-download.
- Pi 5 needs current Bookworm images; do not use old Buster.

## Quick start (DEV_MODE on a normal Linux box)

No Pi hardware required. Typed input always works. Mic/TTS mock if models are missing.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# put XAI_API_KEY in .env
cp config.default.yaml config.yaml
DEV_MODE=1 python -m app --dev --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080/ — tap the orb (browser mic) or type in the box.

Sanity check with no network:

```bash
python -m app.devcheck
```

## Install on a Raspberry Pi

```bash
git clone https://github.com/t-teja/pi-grok-bot.git
cd pi-grok-bot
chmod +x install.sh
./install.sh --systemd --kiosk
nano .env
```

Set `XAI_API_KEY` in `.env`.

What `install.sh` does:

1. apt packages (Python, PortAudio, Chromium, scrot, ffmpeg, espeak-ng)
2. `venv` plus `pip install -r requirements.txt`
3. copies `.env.example` to `.env` and `config.default.yaml` to `config.yaml`
4. downloads Vosk `vosk-model-small-en-us-0.15` and Piper `en_US-lessac-medium` into `models/`
5. optional systemd user unit (`grok-bot.service`) and autostart Chromium kiosk

Windowed (SSH plus a browser, or a desktop window):

```bash
./venv/bin/python -m app
```

Fullscreen kiosk on the attached display:

```bash
./scripts/kiosk.sh
```

On boot: enable desktop autologin in `raspi-config`, then `./install.sh --systemd --kiosk`. The user service starts the API; the `.desktop` autostart launches Chromium `--kiosk`.

Laptop-only install (skip apt kiosk packages and model download):

```bash
./install.sh --dev
```

## xAI key and model

1. Create a key at https://console.x.ai/
2. Put it in `.env` as `XAI_API_KEY=...` (never commit `.env`)
3. Default model: `grok-4.6`, OpenAI-compatible Chat Completions at `https://api.x.ai/v1`
4. Override: `GROK_MODEL=grok-4.5` or `grok.model` in `config.yaml`

Streaming replies and function calling are used for the Pi tools.

## Voice

| Direction | Engine | Why |
| --- | --- | --- |
| In (STT) | Vosk small en-us 0.15 | Lightweight, offline, usable on Pi 4/5. |
| Out (TTS) | Piper en_US-lessac-medium | Neural, CPU real-time on Pi; espeak-ng fallback. |
| Wake word | Vosk loop, phrase `hey grok` (configurable) | Optional. Tap-to-talk is the primary UI. |
| DEV_MODE | typed input plus mock STT/TTS | No mic/speaker required. |

Models are not in git (`models/` is gitignored). `scripts/download-models.sh` (called by `install.sh`) fetches them.

Browser tap-to-talk records 16 kHz WAV in Chromium and POSTs it to `/api/transcribe`. On a Pi with a system mic, the wake-word loop can capture without touching the screen.

## Tools (allowlisted)

The model can only call these. There is no generic shell runner.

| Tool | What it does |
| --- | --- |
| `get_datetime` | UTC, IST (Asia/Calcutta), and local |
| `get_system_stats` | CPU percent, load, temp (`vcgencmd` or `/sys`), memory, disk |
| `list_allowlisted_commands` | Names from `config.yaml` |
| `run_allowlisted_command` | Runs a named argv list only (for example `uptime`) |
| `open_url` | Sends http(s) URL to the UI |
| `set_timer` | Speaks a reminder when due |
| `set_volume` | `wpctl` / `pactl` / `amixer` |
| `take_screenshot` | Saves under `data/screenshots/` |
| `list_music` / `play_music` | Files in `tools.music_dir` |

Add more (GPIO, Home Assistant) — see ARCHITECTURE.md.

## Layout

```
app/           Python package (server, grok client, tools, audio)
ui/            fullscreen kiosk (HTML/CSS/JS character + orb)
scripts/       kiosk.sh, download-models.sh
systemd/       user service + autostart desktop file
config.default.yaml
.env.example
```

## License

MIT. Grok and xAI are trademarks of their owners.
