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


OverlayFactory = Callable[[JsonlTransport, str], OverlayRunner]


@dataclass(frozen=True)
class OverlaySpec:
    id: str
    backend: str
    module: str
    factory: str


OVERLAYS: dict[str, OverlaySpec] = {
    "robot-arm": OverlaySpec("robot-arm", "tk", "engram_overlay.overlays.robot_arm", "create_robot_arm"),
    "robot-arm-3d": OverlaySpec(
        "robot-arm-3d", "tk-software-3d", "engram_overlay.overlays.robot_arm_3d", "create_robot_arm_3d"
    ),
    "xeyes": OverlaySpec("xeyes", "tk", "engram_overlay.overlays.xeyes", "create_xeyes"),
}


def overlay_ids() -> tuple[str, ...]:
    return tuple(sorted(OVERLAYS))


def create_overlay(overlay_id: str, transport: JsonlTransport, mode: str) -> OverlayRunner:
    try:
        spec = OVERLAYS[overlay_id]
    except KeyError as exc:
        raise ValueError(f"unknown overlay: {overlay_id}") from exc
    module = importlib.import_module(spec.module)
    factory = cast(OverlayFactory, getattr(module, spec.factory))
    return factory(transport, mode)
