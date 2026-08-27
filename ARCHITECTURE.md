# Architecture

pi-grok-bot is a small local web app, not a chat site in browser chrome. A Python backend serves a fullscreen character UI; Chromium `--kiosk` on the Pi is just a renderer.

```
  mic / keyboard          Chromium kiosk                 Python (venv)
  -------------           --------------                 -------------
  tap-to-talk WAV  --->   ui/index.html  --WebSocket-->  app.server (FastAPI)
  "hey grok" PCM   --------------------sounddevice---->  app.audio.mic + Vosk
  typed text       --->   composer                       app.session
                                                         app.grok  -->  api.x.ai/v1
                                                         app.tools     (allowlist)
                                                         app.audio.tts (Piper)
                                                         speakers
```

## Processes

1. **Backend** (`python -m app`) — uvicorn + FastAPI on `127.0.0.1:8080`
   - static UI from `ui/`
   - `GET /api/status`, `POST /api/chat`, `POST /api/transcribe`
   - `WS /ws` for live state: idle / listening / thinking / speaking / error
   - optional wake-word loop (`app/audio/mic.py`) when not in DEV_MODE
2. **Kiosk** (`scripts/kiosk.sh`) — Chromium `--kiosk --app=http://127.0.0.1:8080/`
3. **systemd user unit** (`systemd/grok-bot.service`) — starts the backend at login
4. **autostart** (`systemd/grok-bot-kiosk.desktop`) — starts Chromium on the desktop session

Never run the unit as root.

## Config

Load order:

1. `config.default.yaml` (shipped)
2. `config.yaml` (local overlay, gitignored)
3. `.env` via python-dotenv (`XAI_API_KEY`, `GROK_MODEL`, `DEV_MODE`, `GROK_BOT_HOST`, `GROK_BOT_PORT`)

`Settings.as_public_dict()` is what the UI sees — no secrets.

## Brain

`app/grok.py` uses the official OpenAI Python SDK pointed at `https://api.x.ai/v1` (Chat Completions, streaming). Default model: `grok-4.6`.

Tool loop:

1. Stream a completion with `tools=` (OpenAI function schema)
2. If `tool_calls` arrive, execute them locally through `ToolRegistry.call`
3. Append `role=tool` results and stream again (max 6 rounds)
4. Fan tokens to the UI as `assistant_delta`

xAI also has a Responses API; this project stays on Chat Completions because the task asked for the OpenAI-compatible surface and it keeps the tool loop simple.

## Tools

`app/tools/registry.py` is a name → JSON schema + handler map. Built-ins live in `app/tools/builtins.py`.

Rules:

- No `shell=True`
- No user-supplied argv
- `run_allowlisted_command` only runs `argv` lists from `config.yaml`
- `play_music` only opens a basename inside `tools.music_dir`
- `open_url` requires `http://` or `https://`

### Adding a tool

1. Write a handler `def handle(args: dict) -> dict` that returns JSON-serializable data (set `error` on failure).
2. Register it:

```python
registry.register(Tool(
    name="ha_toggle_light",
    description="Toggle a Home Assistant light by entity_id.",
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string"},
        },
        "required": ["entity_id"],
        "additionalProperties": False,
    },
    handler=handle_ha_toggle,
))
```

3. If the UI should react, set `ui_event="some_name"` and handle that event in `ui/js/app.js`.

### GPIO sketch

Use `gpiozero` on a Pi. Keep pin numbers in `config.yaml`, never let the model pick arbitrary chips.

```yaml
# gpio:
#   pins:
#     desk_lamp: 17
```

Handler reads the named pin, toggles it, returns `{pin, state}`.

### Home Assistant sketch

Add a long-lived token to `.env` as `HA_TOKEN` (never commit it) and a base URL in config. Handler POSTs to `/api/services/light/toggle` with a hard-coded allowlist of `entity_id`s. Same pattern as `run_allowlisted_command`.

## Audio

| Piece | Module | Notes |
| --- | --- | --- |
| STT | `app/audio/stt.py` | Vosk `vosk-model-small-en-us-0.15`. Browser sends WAV; server-side loop sends PCM16. |
| TTS | `app/audio/tts.py` | Piper ONNX, then espeak-ng, then print. Speaking state stays on until playback returns. |
| Wake | `app/audio/mic.py` | sounddevice callback → Vosk. Skipped in DEV_MODE. |
| Volume | `set_volume` tool | `wpctl` (PipeWire / Bookworm), `pactl`, `amixer` |

Models live in `models/` (gitignored). `scripts/download-models.sh` fetches:

- https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
- Piper `en_US-lessac-medium` via `python -m piper.download_voices` or Hugging Face

## UI

`ui/` is vanilla HTML/CSS/JS. No framework. The orb/face is SVG + CSS keyed off `document.body.dataset.state`.

States: `idle`, `listening`, `thinking`, `speaking`, `error`.

## DEV_MODE

Set `DEV_MODE=1` or `python -m app --dev`.

- Typed input always works
- Vosk/Piper load if models exist; otherwise STT/TTS mock
- Wake-word loop is skipped
- `python -m app.devcheck` exercises tools without calling xAI

## Security posture

- Bind default is `127.0.0.1` (not `0.0.0.0`)
- User systemd unit, not root
- Allowlist argv, not a shell
- `.env` gitignored; `.env.example` has a fake key
- Screenshots and music stay under `data/`

Treat the Pi like a kiosk on your desk, not a hardened multi-user server.
