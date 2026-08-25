"""A tiny xeyes-style overlay that follows the global mouse pointer."""

from __future__ import annotations

import math
import tkinter as tk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState

TRANSPARENT = "#010203"


def pupil_center(
    eye_x: float,
    eye_y: float,
    target_x: float,
    target_y: float,
    *,
    limit_x: float = 24.0,
    limit_y: float = 31.0,
) -> tuple[float, float]:
    """Clamp a target direction to an elliptical pupil travel boundary."""
    delta_x = target_x - eye_x
    delta_y = target_y - eye_y
    normalized = (delta_x / limit_x) ** 2 + (delta_y / limit_y) ** 2
    if normalized > 1.0:
        scale = 1.0 / math.sqrt(normalized)
        delta_x *= scale
        delta_y *= scale
    return eye_x + delta_x, eye_y + delta_y


class XEyesView:
    width = 250
    height = 140
    background = TRANSPARENT
    transparent_color = TRANSPARENT
    eye_centers = ((72.0, 70.0), (178.0, 70.0))
    eye_radii = (51.0, 61.0)
    pupil_radii = (17.0, 22.0)

    def __init__(self) -> None:
        self.canvas: tk.Canvas | None = None
        self.eye_ids: list[int] = []
        self.pupil_ids: list[int] = []
        self.status_id: int | None = None

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        radius_x, radius_y = self.eye_radii
        pupil_x, pupil_y = self.pupil_radii
        for center_x, center_y in self.eye_centers:
            self.eye_ids.append(
                canvas.create_oval(
                    center_x - radius_x,
                    center_y - radius_y,
                    center_x + radius_x,
                    center_y + radius_y,
                    fill="#f8fafc",
                    outline="#86a8e7",
                    width=5,
                )
            )
            self.pupil_ids.append(
                canvas.create_oval(
                    center_x - pupil_x,
                    center_y - pupil_y,
                    center_x + pupil_x,
                    center_y + pupil_y,
                    fill="#111827",
                    outline="#020617",
                    width=2,
                )
            )
        self.status_id = canvas.create_oval(119, 5, 131, 17, fill="#86a8e7", outline="")

    def apply_state(self, state: OverlayState) -> None:
        if self.canvas is None:
            return
        color, _ = state.appearance
        for eye_id in self.eye_ids:
            self.canvas.itemconfigure(eye_id, outline=color)
        if self.status_id is not None:
            self.canvas.itemconfigure(self.status_id, fill=color)

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        if self.canvas is None:
            return
        pupil_x, pupil_y = self.pupil_radii
        for pupil_id, (local_x, local_y) in zip(self.pupil_ids, self.eye_centers, strict=True):
            screen_eye_x = window_x + local_x
            screen_eye_y = window_y + local_y
            screen_pupil_x, screen_pupil_y = pupil_center(
                screen_eye_x,
                screen_eye_y,
                pointer_x,
                pointer_y,
            )
            center_x = screen_pupil_x - window_x
            center_y = screen_pupil_y - window_y
            self.canvas.coords(
                pupil_id,
                center_x - pupil_x,
                center_y - pupil_y,
                center_x + pupil_x,
                center_y + pupil_y,
            )


def create_xeyes(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, XEyesView(), mode=mode, title="Engram XEyes")

