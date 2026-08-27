#!/usr/bin/env bash
# Fetch Vosk STT + Piper TTS models into ./models
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$ROOT/models"
mkdir -p "$MODELS"
cd "$MODELS"

VOSK_NAME="vosk-model-small-en-us-0.15"
VOSK_ZIP="${VOSK_NAME}.zip"
VOSK_URL="https://alphacephei.com/vosk/models/${VOSK_ZIP}"

if [[ ! -d "$MODELS/$VOSK_NAME" ]]; then
  echo "Downloading Vosk $VOSK_NAME (~40MB)…"
  curl -fL --retry 3 -o "$VOSK_ZIP" "$VOSK_URL"
  unzip -q "$VOSK_ZIP"
  rm -f "$VOSK_ZIP"
else
  echo "Vosk model already present."
fi

# Piper voice via the package helper if venv exists, else Hugging Face files.
VOICE="en_US-lessac-medium"
ONNX="$MODELS/${VOICE}.onnx"
if [[ ! -f "$ONNX" ]]; then
  echo "Downloading Piper voice $VOICE…"
  PY="${ROOT}/venv/bin/python"
  if [[ -x "$PY" ]] && "$PY" -c "import piper" 2>/dev/null; then
    "$PY" -m piper.download_voices --download-dir "$MODELS" "$VOICE" || true
  fi
  if [[ ! -f "$ONNX" ]]; then
    BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium"
    curl -fL --retry 3 -o "$ONNX" "${BASE}/${VOICE}.onnx?download=true"
    curl -fL --retry 3 -o "${ONNX}.json" "${BASE}/${VOICE}.onnx.json?download=true"
  fi
else
  echo "Piper voice already present."
fi

echo "Models ready in $MODELS"
ls -lh "$MODELS" || true
