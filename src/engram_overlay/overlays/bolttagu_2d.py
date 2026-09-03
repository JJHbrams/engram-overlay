"""Bolttagu sprite overlay driven by the sprite-pack-v7 animation set.

The upstream pack is a set of full-canvas 1254x1254 PNGs.  ``scripts/build-bolttagu-assets.py``
crops them to a shared rectangle and packs them into the horizontal sheets bundled here, so every
pose and frame stays aligned on the same feet anchor.  Frame selection is pure clock arithmetic so
it can be tested without a window.
"""

from __future__ import annotations

import json
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState

TRANSPARENT = "#010203"
ASSET_DIR = Path(__file__).parent / "assets" / "bolttagu_2d"

WONDERING_FRAME_MS = 100  # sprites.json declares 10 fps for the 8-frame loop
ENTER_DURATIONS_MS = (200, 300, 220)
EXIT_DURATIONS_MS = (220, 220, 260)


@dataclass(frozen=True)
class Clip:
    """One animation drawn from a single horizontal sheet."""

    sheet: str
    cells: tuple[int, ...]
    durations_ms: tuple[int, ...]
    loop: bool

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValueError(f"clip {self.sheet} has no cells")
        if len(self.cells) != len(self.durations_ms):
            raise ValueError(f"clip {self.sheet} cell and duration counts differ")
        if min(self.durations_ms) <= 0:
            raise ValueError(f"clip {self.sheet} has a non-positive duration")

    @property
    def total_ms(self) -> int:
        return sum(self.durations_ms)


def _still(sheet: str, cell: int) -> Clip:
    return Clip(sheet=sheet, cells=(cell,), durations_ms=(1000,), loop=True)


CLIPS: dict[str, Clip] = {
    "idle": _still("stills", 0),
    "alert": _still("stills", 1),
    "wondering": Clip(
        sheet="wondering",
        cells=tuple(range(8)),
        durations_ms=(WONDERING_FRAME_MS,) * 8,
        loop=True,
    ),
    "enter": Clip(sheet="enter", cells=(0, 1, 2), durations_ms=ENTER_DURATIONS_MS, loop=False),
    "exit": Clip(sheet="exit", cells=(0, 1, 2), durations_ms=EXIT_DURATIONS_MS, loop=False),
}

# Only looping clips may back a display hint; one-shots are played as overrides.
STATE_CLIPS: dict[str, str] = {
    "default": "idle",
    "idle": "idle",
    "input": "idle",
    "success": "idle",
    "hover": "alert",
    "click": "alert",
    "error": "alert",
    "provider_error": "alert",
    "generating": "wondering",
    "search": "wondering",
    "thought": "wondering",
    "memory": "wondering",
}

# A hint that warrants a one-shot the moment the renderer enters it.
HINT_ONESHOTS: dict[str, str] = {"provider_error": "exit"}


def clip_cell(clip: Clip, elapsed_ms: int) -> int | None:
    """Sheet cell for ``elapsed_ms`` into ``clip``, or None once a one-shot has finished."""
    if elapsed_ms < 0:
        elapsed_ms = 0
    if clip.loop:
        elapsed_ms %= clip.total_ms
    elif elapsed_ms >= clip.total_ms:
        return None
    cursor = 0
    for index, duration in enumerate(clip.durations_ms):
        cursor += duration
        if elapsed_ms < cursor:
            return clip.cells[index]
    return clip.cells[-1]


class BolttaguAnimator:
    """Track the active hint and any one-shot override on a millisecond clock."""

    def __init__(self, *, started_ms: int = 0, intro: str | None = "enter") -> None:
        self.display_hint = "idle"
        self.state_started_ms = started_ms
        self.oneshot: str | None = intro if intro in CLIPS or intro is None else None
        self.oneshot_started_ms = started_ms

    def apply_hint(self, hint: str, now_ms: int) -> None:
        resolved = hint if hint in STATE_CLIPS else "idle"
        if resolved == self.display_hint:
            return
        self.display_hint = resolved
        self.state_started_ms = now_ms
        oneshot = HINT_ONESHOTS.get(resolved)
        if oneshot is not None:
            self.oneshot = oneshot
            self.oneshot_started_ms = now_ms

    def resolve(self, now_ms: int) -> tuple[str, int]:
        """Return the (sheet, cell) to draw, retiring a finished one-shot on the way."""
        if self.oneshot is not None:
            clip = CLIPS[self.oneshot]
            cell = clip_cell(clip, now_ms - self.oneshot_started_ms)
            if cell is not None:
                return clip.sheet, cell
            self.oneshot = None
        clip = CLIPS[STATE_CLIPS[self.display_hint]]
        cell = clip_cell(clip, now_ms - self.state_started_ms)
        assert cell is not None  # looping clips never retire
        return clip.sheet, cell


def load_atlas() -> tuple[dict[str, tuple[Image.Image, ...]], tuple[int, int]]:
    """Slice the bundled sheets into per-cell RGBA frames."""
    metadata = json.loads((ASSET_DIR / "atlas.json").read_text(encoding="utf-8"))
    cell_width, cell_height = (int(value) for value in metadata["cell"])
    sheets: dict[str, tuple[Image.Image, ...]] = {}
    for file_name, frames in metadata["sheets"].items():
        key = Path(file_name).stem.removeprefix("bolttagu-")
        sheet = Image.open(ASSET_DIR / file_name).convert("RGBA")
        expected = (cell_width * len(frames), cell_height)
        if sheet.size != expected:
            raise ValueError(f"{file_name} must be {expected[0]}x{expected[1]}, got {sheet.size}")
        sheets[key] = tuple(
            sheet.crop((index * cell_width, 0, (index + 1) * cell_width, cell_height))
            for index in range(len(frames))
        )
    return sheets, (cell_width, cell_height)


class Bolttagu2dView:
    background = TRANSPARENT
    transparent_color = TRANSPARENT

    def __init__(self, *, show_floor: bool = False, coffee: bool = True) -> None:
        sheets, cell = load_atlas()
        self.width, self.height = cell
        if show_floor:
            floor = sheets["floor"][1 if coffee else 0]
            sheets = {
                name: tuple(Image.alpha_composite(floor, frame) for frame in frames)
                for name, frames in sheets.items()
                if name != "floor"
            } | {"floor": sheets["floor"]}
        self.sheets = sheets
        self.animator = BolttaguAnimator(started_ms=self._now_ms())
        self.canvas: tk.Canvas | None = None
        self.image_id: int | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.drawn: tuple[str, int] | None = None

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        sheet, cell = self.animator.resolve(self._now_ms())
        self.photo = ImageTk.PhotoImage(self.sheets[sheet][cell], master=canvas)
        self.image_id = canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.drawn = (sheet, cell)

    def apply_state(self, state: OverlayState) -> None:
        self.animator.apply_hint(state.display_hint, self._now_ms())

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        self._redraw(self.animator.resolve(self._now_ms()))

    def _redraw(self, target: tuple[str, int]) -> None:
        if self.canvas is None or self.image_id is None or target == self.drawn:
            return
        sheet, cell = target
        self.photo = ImageTk.PhotoImage(self.sheets[sheet][cell], master=self.canvas)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        self.drawn = target

    @staticmethod
    def _now_ms() -> int:
        return int(time.monotonic() * 1000)


def create_bolttagu_2d(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, Bolttagu2dView(), mode=mode, title="Bolttagu")
