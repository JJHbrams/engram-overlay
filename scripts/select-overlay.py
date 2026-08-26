"""Safely select one installed renderer without rewriting unrelated settings."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def without_renderer_selection(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    overlay = normalized.get("overlay")
    if isinstance(overlay, dict):
        overlay.pop("external_renderer", None)
        if not overlay:
            normalized.pop("overlay")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engram-source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--user-config", type=Path, required=True)
    parser.add_argument("--mode", choices=("observer", "replace"), default="replace")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(args.engram_source.resolve()))
    external_renderer = importlib.import_module("overlay.external_renderer")
    renderer = external_renderer.load_renderer_manifest(args.manifest)

    original_text = args.user_config.read_text(encoding="utf-8") if args.user_config.exists() else ""
    loaded: Any = yaml.safe_load(original_text) if original_text else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise RuntimeError("overlay.user.yaml root must be a mapping")
    user_config: dict[str, Any] = loaded
    unrelated_before = without_renderer_selection(user_config)
    overlay_before = user_config.get("overlay")
    previous = overlay_before.get("external_renderer") if isinstance(overlay_before, dict) else None

    if not external_renderer.apply_renderer_selection(user_config, renderer, args.mode):
        raise RuntimeError("renderer mode is not supported by the manifest")
    if without_renderer_selection(user_config) != unrelated_before:
        raise RuntimeError("selection unexpectedly changed unrelated settings")

    selected = user_config["overlay"]["external_renderer"]
    print(f"PREVIOUS_SELECTION={'none' if previous is None else 'configured'}")
    print(f"NEXT_SELECTION={renderer.id}:{args.mode}")
    print(f"UNRELATED_SETTINGS_PRESERVED={len(unrelated_before)}")
    if not args.apply:
        print("DRY_RUN=PASS")
        return 0

    args.user_config.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = args.user_config.with_name(f"{args.user_config.name}.bak-{renderer.id}-{timestamp}")
    if args.user_config.exists():
        shutil.copy2(args.user_config, backup)

    rendered = yaml.safe_dump(user_config, allow_unicode=True, sort_keys=False)
    descriptor, temporary_name = tempfile.mkstemp(prefix="overlay.user.", suffix=".tmp", dir=args.user_config.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, args.user_config)
    except Exception:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise

    verified: Any = yaml.safe_load(args.user_config.read_text(encoding="utf-8"))
    if not isinstance(verified, dict) or verified.get("overlay", {}).get("external_renderer") != selected:
        raise RuntimeError("written renderer selection did not verify")
    print(f"BACKUP={backup if backup.exists() else 'not-needed'}")
    print(f"CONFIG_SHA256={file_digest(args.user_config)}")
    print("APPLY=PASS restart-required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
