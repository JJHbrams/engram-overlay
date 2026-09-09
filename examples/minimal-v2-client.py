"""Minimal metadata-only Event API v2 registration example (stdlib only)."""
from __future__ import annotations
import argparse
import json
import socket
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, required=True)
    args = parser.parse_args()
    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    registration = {"schema_version": 2, "type": "overlay.register", "payload": {"token": discovery["token"], "instance_id": discovery["instance_id"], "renderer_id": "example.minimal", "name": "Minimal Example", "supported_modes": ["observer"]}}
    with socket.create_connection((discovery["host"], discovery["port"]), timeout=2) as client:
        client.sendall((json.dumps(registration, separators=(",", ":")) + "\n").encode("utf-8"))
        while line := client.makefile("r", encoding="utf-8").readline():
            print(json.loads(line).get("type", "unknown"))
    return 0
if __name__ == "__main__": raise SystemExit(main())
