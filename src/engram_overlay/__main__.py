"""Command-line entry point for the custom overlay child process."""

from __future__ import annotations

import argparse
import sys

from .app import OverlayApp
from .protocol import JsonlTransport, hello_message
from .state import OverlayState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Engram custom overlay renderer")
    parser.add_argument("--mode", choices=("observer", "replace"), default="observer")
    parser.add_argument("--headless", action="store_true", help="exercise the JSONL contract without opening Tk")
    return parser


def run_headless(transport: JsonlTransport) -> None:
    state = OverlayState()
    for message in transport.messages():
        state.apply(message)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    transport = JsonlTransport(sys.stdin, sys.stdout, sys.stderr)
    # The API requires this to be the renderer's first stdout line. Send it
    # before constructing a window or starting the reader.
    transport.send(hello_message())
    if args.headless:
        run_headless(transport)
    else:
        OverlayApp(transport, mode=args.mode).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
