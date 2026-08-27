"""python -m app  |  python -m app --dev"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from app.config import get_settings
from app.paths import ROOT


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Unofficial Raspberry Pi Grok Bot kiosk")
    parser.add_argument("--dev", action="store_true", help="Force DEV_MODE (typed input, mock audio)")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    if args.dev:
        os.environ["DEV_MODE"] = "1"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    # Import after DEV_MODE is set so Settings.dev_mode is correct.
    from app.server import create_app

    app = create_app(settings)
    log = logging.getLogger("grokbot")
    log.info(
        "Starting %s on http://%s:%s  dev_mode=%s  model=%s  cwd=%s",
        settings.app.get("name", "Grok Bot"),
        host,
        port,
        settings.dev_mode,
        settings.model,
        ROOT,
    )
    if not settings.api_key:
        log.warning("XAI_API_KEY is not set. Chat will error until you add it to .env")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main(sys.argv[1:])
