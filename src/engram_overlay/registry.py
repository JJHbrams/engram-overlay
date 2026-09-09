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
from .components import available_overlay_ids, require_installed


class OverlayRunner(Protocol):
    def run(self) -> None: ...


OverlayFactory = Callable[..., OverlayRunner]


@dataclass(frozen=True)
class OverlaySpec:
    """One bundled preset. ``name`` is the label Engram shows in Settings > Overlay.

    Under Event API v2 the name is not an install detail: it is sent in
    ``overlay.register`` and is what a user picks by. It lives here so it travels
    with the installed package, and the CLI listing, the install scripts and the
    registration all read it from here rather than keeping their own copy.
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


def renderer_id(overlay_id: str) -> str:
    """The id this renderer registers under with the v2 host.

    Engram keys a saved selection on it, so it is a compatibility surface: change
    it and every user's chosen overlay silently stops being the one they chose.
    """
    return f"engram.{overlay_id}"


def provider_catalog() -> tuple[dict[str, object], ...]:
    """Bounded v2 catalog preserving every preset's existing renderer ID."""
    return tuple({
        "renderer_id": renderer_id(spec.id),
        "name": spec.name,
        "supported_modes": ["observer", "replace"],
        "capabilities": ["overlay.presentation", *(["overlay.set_size"] if spec.id == "bolttagu-2d" else [])],
    } for spec in overlay_catalog())


def overlay_catalog() -> tuple[OverlaySpec, ...]:
    """Installed presets, ordered by stable ID.

    A legacy full wheel/source checkout has no marker and therefore retains the
    historical complete catalog. A core-only component wheel has neither a
    valid marker nor all modules, so it advertises nothing rather than lying.
    """
    return tuple(OVERLAYS[overlay_id] for overlay_id in available_overlay_ids())


def format_catalog() -> str:
    """Human-readable preset roster for ``--list-overlays``."""
    specs = overlay_catalog()
    if not specs:
        return "No overlay components are installed in this runtime."
    width = max(len(spec.id) for spec in specs)
    lines = [f"Bundled overlay presets ({len(specs)})", ""]
    for spec in specs:
        lines.append(f"  {spec.id.ljust(width)}  {spec.name}")
        lines.append(f"  {' ' * width}  {spec.backend} - {spec.summary}")
    lines.append("")
    lines.append("Run one with --overlay <id>; install it with scripts/install-runtime.ps1 -Overlay <id>.")
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
    require_installed(overlay_id)
    try:
        spec = OVERLAYS[overlay_id]
    except KeyError as exc:
        raise ValueError(f"unknown overlay: {overlay_id}") from exc
    module = importlib.import_module(spec.module)
    factory = cast(OverlayFactory, getattr(module, spec.factory))

    def finish(runner: OverlayRunner) -> OverlayRunner:
        if launcher_managed and overlay_id != "bolttagu-2d":
            enable = getattr(runner, "enable_launcher_management", None)
            if not callable(enable):
                raise ValueError(f"launcher-managed presentation is unavailable for {overlay_id}")
            enable()
        return runner

    if overlay_id in {"robot-arm-3d-v2", "robot-arm-3d-v3"}:
        return finish(factory(transport, mode, eye_emission=eye_emission))
    if eye_emission:
        raise ValueError("eye emission is only supported by robot-arm-3d-v2 and robot-arm-3d-v3")
    if overlay_id == "bolttagu-2d":
        return finish(factory(
            transport, mode, face_pointer=face_pointer, scale=scale, launcher_managed=launcher_managed
        ))
    if not face_pointer:
        raise ValueError("pointer facing is only supported by bolttagu-2d")
    if scale != 1.0:
        raise ValueError("scale is only supported by bolttagu-2d")
    return finish(factory(transport, mode))
