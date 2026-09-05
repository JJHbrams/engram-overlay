"""Command-line entry point for the custom overlay child process."""

from __future__ import annotations

import argparse
import io
import sys

from .client import Registration, sessions
from .discovery import SCHEMA_VERSION as V2_SCHEMA_VERSION
from .protocol import PRESENTATION_CAPABILITY, JsonlTransport, hello_message
from .registry import OVERLAYS, create_overlay, format_catalog, overlay_ids, renderer_id
from .state import OverlayState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Engram custom overlay renderer")
    parser.add_argument("--overlay", choices=overlay_ids(), default="xeyes")
    parser.add_argument(
        "--list-overlays",
        action="store_true",
        help="print the bundled overlay presets and exit without starting a renderer",
    )
    parser.add_argument("--mode", choices=("observer", "replace"), default="observer")
    parser.add_argument("--headless", action="store_true", help="exercise the JSONL contract without opening Tk")
    parser.add_argument(
        "--eye-emission",
        action="store_true",
        help="enable gaze-directed mood glow for robot-arm-3d-v2/v3 (default: off)",
    )
    parser.add_argument(
        "--no-face-pointer",
        action="store_true",
        help="stop bolttagu-2d from mirroring itself toward the pointer (default: it faces the pointer)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="resize the bolttagu-2d window; 1.0 is the artwork's own 270x302",
    )
    parser.add_argument(
        "--v1-stdio",
        action="store_true",
        help="speak Event API v1 over stdin/stdout instead of connecting to the v2 host",
    )
    parser.add_argument(
        "--presentation",
        action="store_true",
        help="let Engram's launcher icon show and hide bolttagu-2d; start collapsed",
    )
    return parser


def run_headless(transport: JsonlTransport) -> None:
    state = OverlayState()
    for message in transport.messages():
        state.apply(message)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_overlays:
        # A standalone utility mode: it exits before any transport exists, so the
        # JSONL-only rule for a running renderer's stdout is not in play.
        print(format_catalog())
        return 0
    if args.eye_emission and args.overlay not in {"robot-arm-3d-v2", "robot-arm-3d-v3"}:
        parser.error("--eye-emission is only supported by robot-arm-3d-v2 and robot-arm-3d-v3")
    if args.no_face_pointer and args.overlay != "bolttagu-2d":
        parser.error("--no-face-pointer is only supported by bolttagu-2d")
    if args.scale != 1.0 and args.overlay != "bolttagu-2d":
        parser.error("--scale is only supported by bolttagu-2d")
    if args.presentation and args.overlay != "bolttagu-2d":
        parser.error("--presentation is only supported by bolttagu-2d")
    capabilities = ["overlay.set_size"] if args.overlay == "bolttagu-2d" else []
    if args.presentation:
        # Advertised only when asked for, so an Engram without the launcher never
        # leaves a collapsed renderer with no way to appear.
        capabilities.append(PRESENTATION_CAPABILITY)

    if args.v1_stdio or args.headless:
        # v1 is retired on Engram's side; this path stays for the headless
        # contract check and for driving a renderer without a host.
        transport = JsonlTransport(sys.stdin, sys.stdout, sys.stderr)
        transport.send(hello_message(capabilities=capabilities or None))
        if args.headless:
            run_headless(transport)
            return 0
        create_overlay(
            args.overlay,
            transport,
            args.mode,
            eye_emission=args.eye_emission,
            face_pointer=not args.no_face_pointer,
            scale=args.scale,
            launcher_managed=args.presentation,
        ).run()
        return 0

    return run_v2(args, tuple(capabilities))


def run_v2(args: argparse.Namespace, capabilities: tuple[str, ...]) -> int:
    """Open the window, then keep it connected to whatever host is there.

    The window is created before any host exists and outlives every socket: a
    renderer starts with the session, waits for Engram, and survives its restarts.
    """
    spec = OVERLAYS[args.overlay]
    registration = Registration(
        renderer_id=renderer_id(args.overlay),
        name=spec.name,
        supported_modes=("observer", "replace"),
        capabilities=capabilities,
    )
    host = create_overlay(
        args.overlay,
        # Until a session exists there is nowhere to send; the reader swaps in a
        # real transport as soon as one registers.
        JsonlTransport(io.StringIO(), io.StringIO(), sys.stderr, schema_version=V2_SCHEMA_VERSION),
        args.mode,
        eye_emission=args.eye_emission,
        face_pointer=not args.no_face_pointer,
        scale=args.scale,
        launcher_managed=args.presentation,
    )
    host.use_connection(lambda: sessions(registration))
    host.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
