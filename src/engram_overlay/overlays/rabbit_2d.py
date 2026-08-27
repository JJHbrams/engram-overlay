"""Hand-drawn rabbit sprite overlay with Engram-style random state rotation."""

from __future__ import annotations

import random
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState

TRANSPARENT = "#010203"
ATLAS_COLUMNS = 3
ATLAS_ROWS = 2
FRAME_SIZE = (512, 384)
DISPLAY_SIZE = (320, 240)

STATE_FRAMES: dict[str, tuple[int, ...]] = {
    "default": (0, 1, 2, 3, 4),
    "idle": (0, 1, 2, 3, 4),
    "hover": (1,),
    "click": (1, 4),
    "input": (3,),
    "generating": (0, 3),
    "search": (1, 3),
    "thought": (2, 3),
    "memory": (0, 2),
    "success": (1,),
    "provider_error": (2, 4),
    "error": (4,),
}

STATE_FRAME_MS = {
    "default": 5200,
    "idle": 5200,
    "hover": 900,
    "click": 750,
    "input": 1500,
    "generating": 1900,
    "search": 1450,
    "thought": 1700,
    "memory": 1900,
    "success": 2200,
    "provider_error": 1300,
    "error": 1300,
}


def atlas_frames(atlas: Image.Image) -> tuple[Image.Image, ...]:
    expected = (FRAME_SIZE[0] * ATLAS_COLUMNS, FRAME_SIZE[1] * ATLAS_ROWS)
    if atlas.size != expected:
        raise ValueError(f"rabbit atlas must be {expected[0]}x{expected[1]}")
    frames = []
    for row in range(ATLAS_ROWS):
        for column in range(ATLAS_COLUMNS):
            frames.append(
                atlas.crop(
                    (
                        column * FRAME_SIZE[0],
                        row * FRAME_SIZE[1],
                        (column + 1) * FRAME_SIZE[0],
                        (row + 1) * FRAME_SIZE[1],
                    )
                )
            )
    return tuple(frames)


def choose_frame(
    display_hint: str,
    bucket: int,
    choices: dict[tuple[str, int], int],
    rng: random.Random,
) -> int:
    """Choose once per state bucket and avoid immediate repeats when possible."""
    hint = display_hint if display_hint in STATE_FRAMES else "idle"
    key = (hint, max(0, bucket))
    if key in choices:
        return choices[key]
    frames = STATE_FRAMES[hint]
    previous = choices.get((hint, key[1] - 1))
    candidates = tuple(frame for frame in frames if frame != previous) or frames
    choices[key] = rng.choice(candidates)
    return choices[key]


class Rabbit2DView:
    width, height = DISPLAY_SIZE
    background = TRANSPARENT
    transparent_color = TRANSPARENT

    def __init__(self, *, rng: random.Random | None = None) -> None:
        asset = Path(__file__).parent / "assets" / "rabbit_2d" / "rabbit-states.png"
        atlas = Image.open(asset).convert("RGBA")
        self.frames = tuple(
            frame.resize(DISPLAY_SIZE, Image.Resampling.LANCZOS)
            for frame in atlas_frames(atlas)[:5]
        )
        self.rng = rng or random.Random()
        self.canvas: tk.Canvas | None = None
        self.image_id: int | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.display_hint = "idle"
        self.state_started_at = time.monotonic()
        self.choices: dict[tuple[str, int], int] = {}
        self.current_frame = -1

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.photo = ImageTk.PhotoImage(self.frames[0], master=canvas)
        self.image_id = canvas.create_image(0, 0, image=self.photo, anchor="nw")

    def apply_state(self, state: OverlayState) -> None:
        hint = state.display_hint if state.display_hint in STATE_FRAMES else "idle"
        if hint != self.display_hint:
            self.display_hint = hint
            self.state_started_at = time.monotonic()
            self.choices.clear()

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        del pointer_x, pointer_y, window_x, window_y
        if self.canvas is None or self.image_id is None:
            return
        elapsed_ms = max(0.0, (time.monotonic() - self.state_started_at) * 1000)
        bucket = int(elapsed_ms // STATE_FRAME_MS[self.display_hint])
        frame = choose_frame(self.display_hint, bucket, self.choices, self.rng)
        if frame == self.current_frame:
            return
        self.current_frame = frame
        self.photo = ImageTk.PhotoImage(self.frames[frame], master=self.canvas)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        if len(self.choices) > 12:
            self.choices = {key: value for key, value in self.choices.items() if key[1] >= bucket - 1}


def create_rabbit_2d(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, Rabbit2DView(), mode=mode, title="Engram Rabbit")
