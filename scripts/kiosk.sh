#!/usr/bin/env bash
# Launch Chromium in kiosk mode against the local Grok Bot UI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${GROK_BOT_URL:-http://127.0.0.1:8080/}"

# Wait for the backend.
for _ in $(seq 1 40); do
  if curl -fsS "$URL" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# Hide the mouse after idle if unclutter is present.
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 3 -root >/dev/null 2>&1 &
fi

CHROME=""
for c in chromium chromium-browser google-chrome; do
  if command -v "$c" >/dev/null 2>&1; then
    CHROME="$c"
    break
  fi
done
if [[ -z "$CHROME" ]]; then
  echo "No Chromium/Chrome found. Open $URL yourself." >&2
  exit 1
fi

exec "$CHROME" \
  --kiosk \
  --app="$URL" \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-restore-session-state \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  --ozone-platform=x11 \
  "$URL"
