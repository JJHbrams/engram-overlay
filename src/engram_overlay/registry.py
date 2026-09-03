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
    id: str
    backend: str
    module: str
    factory: str


OVERLAYS: dict[str, OverlaySpec] = {
    "bolttagu-2d": OverlaySpec(
        "bolttagu-2d", "tk-sprite-sheet", "engram_overlay.overlays.bolttagu_2d", "create_bolttagu_2d"
    ),
    "rabbit-2d": OverlaySpec("rabbit-2d", "tk-sprite-grid", "engram_overlay.overlays.rabbit_2d", "create_rabbit_2d"),
    "robot-arm": OverlaySpec("robot-arm", "tk", "engram_overlay.overlays.robot_arm", "create_robot_arm"),
    "robot-arm-3d": OverlaySpec(
        "robot-arm-3d", "tk-software-3d", "engram_overlay.overlays.robot_arm_3d", "create_robot_arm_3d"
    ),
    "robot-arm-3d-v2": OverlaySpec(
        "robot-arm-3d-v2",
        "tk-textured-software-3d",
        "engram_overlay.overlays.robot_arm_3d_v2",
        "create_robot_arm_3d_v2",
    ),
    "robot-arm-3d-v3": OverlaySpec(
        "robot-arm-3d-v3",
        "tk-textured-software-3d",
        "engram_overlay.overlays.robot_arm_3d_v3",
        "create_robot_arm_3d_v3",
    ),
    "xeyes": OverlaySpec("xeyes", "tk", "engram_overlay.overlays.xeyes", "create_xeyes"),
}


def overlay_ids() -> tuple[str, ...]:
    return tuple(sorted(OVERLAYS))


def create_overlay(
    overlay_id: str,
    transport: JsonlTransport,
    mode: str,
    *,
    eye_emission: bool = False,
    face_pointer: bool = True,
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
        return factory(transport, mode, face_pointer=face_pointer)
    if not face_pointer:
        raise ValueError("pointer facing is only supported by bolttagu-2d")
    return factory(transport, mode)
