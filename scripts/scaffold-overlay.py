"""Create the minimal files for a new Tk-based Engram overlay."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

OVERLAY_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
REGISTRY_END = "\n}\n\n\ndef overlay_ids"


@dataclass(frozen=True)
class ScaffoldPlan:
    overlay_id: str
    display_name: str
    module_name: str
    class_name: str
    factory_name: str
    module_path: Path
    manifest_path: Path
    test_path: Path
    registry_path: Path


def build_plan(root: Path, overlay_id: str, display_name: str | None = None) -> ScaffoldPlan:
    if not OVERLAY_ID.fullmatch(overlay_id):
        raise ValueError("overlay id must be lowercase kebab-case")
    module_name = overlay_id.replace("-", "_")
    words = overlay_id.split("-")
    class_name = "".join(word.capitalize() for word in words) + "View"
    factory_name = "create_" + module_name
    return ScaffoldPlan(
        overlay_id=overlay_id,
        display_name=display_name or " ".join(word.capitalize() for word in words),
        module_name=module_name,
        class_name=class_name,
        factory_name=factory_name,
        module_path=root / "src" / "engram_overlay" / "overlays" / f"{module_name}.py",
        manifest_path=root / "manifests" / overlay_id / "manifest.yaml",
        test_path=root / "tests" / f"test_{module_name}.py",
        registry_path=root / "src" / "engram_overlay" / "registry.py",
    )


def module_source(plan: ScaffoldPlan) -> str:
    return f'''"""{plan.display_name} overlay."""

from __future__ import annotations

import tkinter as tk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState

TRANSPARENT = "#010203"


class {plan.class_name}:
    width = 320
    height = 240
    background = TRANSPARENT
    transparent_color = TRANSPARENT

    def __init__(self) -> None:
        self.canvas: tk.Canvas | None = None
        self.body_id: int | None = None

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.body_id = canvas.create_oval(80, 40, 240, 200, fill="#334155", outline="#94a3b8", width=4)

    def apply_state(self, state: OverlayState) -> None:
        if self.canvas is None or self.body_id is None:
            return
        color, _ = state.appearance
        self.canvas.itemconfigure(self.body_id, outline=color)

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        """Advance pointer-driven animation without emitting protocol output."""


def {plan.factory_name}(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, {plan.class_name}(), mode=mode, title={plan.display_name!r})
'''


def manifest_source(plan: ScaffoldPlan) -> str:
    display_name = json.dumps(plan.display_name)
    return f'''schema_version: 1
id: {plan.overlay_id}
name: {display_name}
command:
  - "C:/absolute/path/to/.venv/Scripts/engram-custom-overlay.exe"
  - "--overlay"
  - "{plan.overlay_id}"
  - "--mode"
  - "replace"
supported_modes: [observer, replace]
'''


def test_source(plan: ScaffoldPlan) -> str:
    return f'''import unittest

from engram_overlay.overlays.{plan.module_name} import {plan.class_name}
from engram_overlay.registry import OVERLAYS, overlay_ids


class {plan.class_name}Tests(unittest.TestCase):
    def test_registry_exposes_overlay(self) -> None:
        self.assertIn({plan.overlay_id!r}, overlay_ids())
        self.assertEqual(OVERLAYS[{plan.overlay_id!r}].backend, "tk")

    def test_view_has_positive_canvas_size(self) -> None:
        view = {plan.class_name}()
        self.assertGreater(view.width, 0)
        self.assertGreater(view.height, 0)


if __name__ == "__main__":
    unittest.main()
'''


def registry_source(plan: ScaffoldPlan, current: str) -> str:
    if f'"{plan.overlay_id}": OverlaySpec(' in current:
        raise FileExistsError(f"registry already contains {plan.overlay_id}")
    if REGISTRY_END not in current:
        raise ValueError("could not locate the OVERLAYS registry boundary")
    entry = (
        f'    "{plan.overlay_id}": OverlaySpec('
        f'"{plan.overlay_id}", "tk", "engram_overlay.overlays.{plan.module_name}", "{plan.factory_name}"),\n'
    )
    return current.replace(REGISTRY_END, "\n" + entry + REGISTRY_END, 1)


def scaffold(plan: ScaffoldPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
    if not plan.registry_path.is_file():
        raise FileNotFoundError(f"missing registry: {plan.registry_path}")
    generated = (plan.module_path, plan.manifest_path, plan.test_path)
    existing = [path for path in generated if path.exists()]
    if existing:
        raise FileExistsError("refusing to overwrite: " + ", ".join(str(path) for path in existing))
    registry = registry_source(plan, plan.registry_path.read_text(encoding="utf-8"))
    changed = (*generated, plan.registry_path)
    if dry_run:
        return changed
    contents = (module_source(plan), manifest_source(plan), test_source(plan))
    for path, content in zip(generated, contents, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    plan.registry_path.write_text(registry, encoding="utf-8", newline="\n")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlay_id", help="lowercase kebab-case overlay id")
    parser.add_argument("--name", help="human-readable overlay name")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = build_plan(args.root.resolve(), args.overlay_id, args.name)
    for path in scaffold(plan, dry_run=args.dry_run):
        print(path.relative_to(args.root.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
