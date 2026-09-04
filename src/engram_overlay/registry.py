"""Built-in overlay registry.

Each entry owns its rendering stack. Only the Event API transport and lifecycle
contract are shared, so future OpenGL, WebView, or Live2D implementations do not
need to pretend to be Tk views.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Callable, Protocol, cast

from .protocol import JsonlTransport


class OverlayRunner(Protocol):
    def run(self) -> None: ...


OverlayFactory = Callable[..., OverlayRunner]


@dataclass(frozen=True)
class OverlaySpec:
    """One bundled preset. ``name`` is the label Engram shows in Settings > Overlay.

    The display name lives here rather than only in ``manifests/<id>/manifest.yaml`` so
    it travels with the installed package: the CLI listing and the install script both
    read it from here instead of keeping their own copy of the roster.
    """

    id: str
    backend: str
    module: str
    factory: str
    name: str
    summary: str


OVERLAYS: dict[str, OverlaySpec] = {
    "bolttagu-2d": OverlaySpec(
        "bolttagu-2d", "tk-sprite-sheet", "engram_overlay.overlays.bolttagu_2d", "create_bolttagu_2d", "Bolttagu", "Sprite character with a random blink, rising mug steam, and pointer-facing mirroring"
    ),
    "rabbit-2d": OverlaySpec("rabbit-2d", "tk-sprite-grid", "engram_overlay.overlays.rabbit_2d", "create_rabbit_2d", "Rabbit", "Hand-drawn rabbit rotating through five poses per semantic state"),
    "robot-arm": OverlaySpec("robot-arm", "tk", "engram_overlay.overlays.robot_arm", "create_robot_arm", "Engram 3-Link Robot Arm", "Ceiling-mounted single-eye 3-link arm with iris, LED and ambient expressions"),
    "robot-arm-3d": OverlaySpec(
        "robot-arm-3d", "tk-software-3d", "engram_overlay.overlays.robot_arm_3d", "create_robot_arm_3d", "Engram 3D Robot Arm", "The same arm under CPU perspective projection, depth sorting and face lighting"
    ),
    "robot-arm-3d-v2": OverlaySpec(
        "robot-arm-3d-v2",
        "tk-textured-software-3d",
        "engram_overlay.overlays.robot_arm_3d_v2",
        "create_robot_arm_3d_v2",
        "Engram Textured 3D Robot Arm V2",
        "Industrial arm sampling a generated material atlas over subdivided quads",
    ),
    "robot-arm-3d-v3": OverlaySpec(
        "robot-arm-3d-v3",
        "tk-textured-software-3d",
        "engram_overlay.overlays.robot_arm_3d_v3",
        "create_robot_arm_3d_v3",
        "CCTV",
        "Surveillance scene where a small traveller hides and peeks from the V2 arm's real gaze",
    ),
    "xeyes": OverlaySpec("xeyes", "tk", "engram_overlay.overlays.xeyes", "create_xeyes", "Engram XEyes", "Two eyes tracking the screen-wide mouse pointer; the first API and input smoke test"),
}


def overlay_ids() -> tuple[str, ...]:
    return tuple(sorted(OVERLAYS))


def overlay_catalog() -> tuple[OverlaySpec, ...]:
    """Every bundled preset, ordered by id."""
    return tuple(OVERLAYS[overlay_id] for overlay_id in overlay_ids())


def format_catalog() -> str:
    """Human-readable preset roster for ``--list-overlays``."""
    specs = overlay_catalog()
    width = max(len(spec.id) for spec in specs)
    lines = [f"Bundled overlay presets ({len(specs)})", ""]
    for spec in specs:
        lines.append(f"  {spec.id.ljust(width)}  {spec.name}")
        lines.append(f"  {' ' * width}  {spec.backend} - {spec.summary}")
    lines.append("")
    lines.append("Install one with scripts/install-dev.ps1 -Overlay <id>, or all of them with -All.")
    return "\n".join(lines)


def create_overlay(
    overlay_id: str,
    transport: JsonlTransport,
    mode: str,
    *,
    eye_emission: bool = False,
    face_pointer: bool = True,
    scale: float = 1.0,
    launcher_managed: bool = False,
) -> OverlayRunner:
    try:
        spec = OVERLAYS[overlay_id]
    except KeyError as exc:
        raise ValueError(f"unknown overlay: {overlay_id}") from exc
    module = importlib.import_module(spec.module)
    factory = cast(OverlayFactory, getattr(module, spec.factory))
    if overlay_id in {"robot-arm-3d-v2", "robot-arm-3d-v3"}:
        return factory(transport, mode, eye_emission=eye_emission)
    if eye_emission:
        raise ValueError("eye emission is only supported by robot-arm-3d-v2 and robot-arm-3d-v3")
    if overlay_id == "bolttagu-2d":
        return factory(
            transport, mode, face_pointer=face_pointer, scale=scale, launcher_managed=launcher_managed
        )
    if not face_pointer:
        raise ValueError("pointer facing is only supported by bolttagu-2d")
    if scale != 1.0:
        raise ValueError("scale is only supported by bolttagu-2d")
    if launcher_managed:
        raise ValueError("launcher-managed presentation is only supported by bolttagu-2d")
    return factory(transport, mode)
