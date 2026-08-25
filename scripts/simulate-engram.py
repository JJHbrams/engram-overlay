"""Open an overlay for a short visual smoke test using a simulated Engram host."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", default="xeyes")
    parser.add_argument("--seconds", type=float, default=8.0)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    launcher = repository / ".venv" / "Scripts" / "engram-custom-overlay.exe"
    child = subprocess.Popen(
        [str(launcher), "--overlay", args.overlay, "--mode", "replace"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        assert child.stdout is not None
        hello = json.loads(child.stdout.readline())
        if hello.get("type") != "overlay.hello":
            raise RuntimeError(f"invalid hello: {hello}")
        assert child.stdin is not None
        messages = (
            {"schema_version": 1, "type": "engram.welcome", "display_hint": "idle", "payload": {}},
            {"schema_version": 1, "type": "state.snapshot", "display_hint": "idle", "payload": {}},
            {"schema_version": 1, "type": "generation.started", "display_hint": "generating", "payload": {}},
        )
        for message in messages:
            child.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        child.stdin.flush()
        time.sleep(args.seconds)
    finally:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

