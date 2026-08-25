"""Validate the installed manifest with Engram and run a real JSONL round trip."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engram-source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.engram_source.resolve()))
    external_renderer = importlib.import_module("overlay.external_renderer")
    event_api = importlib.import_module("overlay.event_api")

    renderer = external_renderer.load_renderer_manifest(args.manifest)
    failures: list[str] = []
    command = [*renderer.command, "--headless"]
    config = {"overlay": {"external_renderer": {"mode": "replace", "command": command}}}
    publisher = event_api.OverlayEventPublisher(config, on_failure=lambda: failures.append("publisher failure"))
    if not publisher.start():
        raise RuntimeError("Engram rejected the renderer handshake")
    publisher.publish("generation.started", "generating", {})
    publisher.publish("tool.started", "search", {"category": "search"})
    publisher.publish("generation.completed", "success", {"outcome": "success"})
    publisher.stop()
    if failures:
        raise RuntimeError(", ".join(failures))

    print(f"MANIFEST=PASS id={renderer.id} modes={','.join(renderer.supported_modes)}")
    print("ENGRAM_JSONL_ROUNDTRIP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

