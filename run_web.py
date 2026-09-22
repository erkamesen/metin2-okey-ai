"""Kart UI'ini baslatir:  python run_web.py  ->  http://127.0.0.1:8000"""
from __future__ import annotations

import argparse
import webbrowser

import uvicorn

from okey.rules import DEFAULT_CONFIG_PATH
from okey.web.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Metin2 Okey web arayuzu")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--log-dir", default=".", help="CSV kayitlarinin yazilacagi kok dizin")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")
    uvicorn.run(create_app(args.config, args.log_dir), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
