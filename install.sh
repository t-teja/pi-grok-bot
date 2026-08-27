#!/usr/bin/env bash
# Install pi-grok-bot on Raspberry Pi OS Bookworm 64-bit (Pi 4 / Pi 5).
# Also works on regular Debian/Ubuntu for DEV_MODE.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DEV_ONLY=0
WITH_SYSTEMD=0
WITH_KIOSK=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_ONLY=1 ;;
    --systemd) WITH_SYSTEMD=1 ;;
    --kiosk) WITH_KIOSK=1 ;;
    --help|-h)
      cat <<USAGE
Usage: ./install.sh [--dev] [--systemd] [--kiosk]

  --dev       Skip apt audio/kiosk packages; venv + pip only (laptop)
  --systemd   Enable a user systemd service for the backend
  --kiosk     Install autostart desktop file for Chromium kiosk
USAGE
      exit 0
      ;;
  esac
done

echo "==> pi-grok-bot installer"

if [[ "$DEV_ONLY" -eq 0 ]] && command -v apt-get >/dev/null 2>&1; then
  echo "==> apt packages"
  sudo apt-get update
  sudo apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    portaudio19-dev libasound2-dev \
    wget curl unzip \
    sox alsa-utils \
    || true
  sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser || true
  sudo apt-get install -y unclutter scrot ffmpeg pulseaudio-utils pipewire-pulse || true
  sudo apt-get install -y espeak-ng || sudo apt-get install -y espeak || true
fi

echo "==> python venv"
python3 -m venv "$ROOT/venv"
# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"
pip install --upgrade pip wheel
pip install -r "$ROOT/requirements.txt"

echo "==> config"
if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env — add your XAI_API_KEY from https://console.x.ai/"
fi
if [[ ! -f "$ROOT/config.yaml" ]]; then
  cp "$ROOT/config.default.yaml" "$ROOT/config.yaml"
  echo "Created config.yaml from defaults."
fi
mkdir -p "$ROOT/data/screenshots" "$ROOT/data/music" "$ROOT/models"

if [[ "$DEV_ONLY" -eq 0 ]]; then
  echo "==> STT/TTS models"
  bash "$ROOT/scripts/download-models.sh"
fi

if [[ "$WITH_SYSTEMD" -eq 1 ]]; then
  echo "==> systemd user service"
  mkdir -p "$HOME/.config/systemd/user"
  UNIT="$HOME/.config/systemd/user/grok-bot.service"
  cp "$ROOT/systemd/grok-bot.service" "$UNIT"
  systemctl --user daemon-reload
  systemctl --user enable --now grok-bot.service
  loginctl enable-linger "$USER" 2>/dev/null || true
  echo "Backend service enabled (systemctl --user status grok-bot)."
fi

if [[ "$WITH_KIOSK" -eq 1 ]]; then
  echo "==> kiosk autostart"
  chmod +x "$ROOT/scripts/kiosk.sh"
  AUTOSTART="$HOME/.config/autostart"
  mkdir -p "$AUTOSTART"
  sed "s|/home/REPLACE_USER|$HOME|g" \
    "$ROOT/systemd/grok-bot-kiosk.desktop" \
    > "$AUTOSTART/grok-bot-kiosk.desktop"
  echo "Autostart written to $AUTOSTART/grok-bot-kiosk.desktop"
fi

chmod +x "$ROOT/scripts/"*.sh "$ROOT/install.sh" || true

echo
echo "Done."
echo "  1. Edit $ROOT/.env and set XAI_API_KEY"
echo "  2. DEV / windowed:   DEV_MODE=1 $ROOT/venv/bin/python -m app --dev"
echo "  3. Pi kiosk:         $ROOT/venv/bin/python -m app"
echo "                       then ./scripts/kiosk.sh"
echo "  4. Sanity check:     $ROOT/venv/bin/python -m app.devcheck"
