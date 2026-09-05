"""Hand-drawn rabbit sprite overlay with Engram-style random state rotation."""

from __future__ import annotations

import random
import time
import tkinter as tk
from pathlib import Path
from typing import Callable

from PIL import Image, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState
from .spritemap import Layer, Option, Row, Section, SpriteMap
from .spritemap import installed_mapping_path as _installed_mapping_path
from .spritemap import Rotation
from .spritemap import resolve as _resolve

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

OVERLAY_ID = "rabbit-2d"
ASSET_DIR = Path(__file__).parent / "assets" / "rabbit_2d"

# The five drawn poses, in atlas order.
POSE_NAMES = ("졸림", "놀람", "울먹임", "궁금함", "화남")
HINT_NOTES = {
    "idle": "유휴", "default": "기본", "input": "사용자 입력 제출",
    "generating": "응답 생성 · 도구 실행", "thought": "생각 중", "search": "검색 도구",
    "memory": "기억 도구", "success": "턴 완료", "hover": "포인터 올림",
    "click": "클릭", "error": "도구 실패", "provider_error": "provider 실패",
}
HINT_ORDER = (
    "idle", "default", "input", "generating", "thought",
    "search", "memory", "success", "hover", "click", "error", "provider_error",
)
PREVIEW_FRAME_MS = 900


def installed_mapping_path() -> Path:
    return _installed_mapping_path(OVERLAY_ID)


def sprite_map() -> SpriteMap:
    """Declarative description for the shared picker and loader.

    Unlike a sheet overlay, a hint here holds several stills and one is drawn per
    time bucket, so its section is multi-select.
    """
    options = {
        name: Option(name, (Layer("states", (index,), (PREVIEW_FRAME_MS,)),))
        for index, name in enumerate(POSE_NAMES)
    }
    return SpriteMap(
        overlay_id=OVERLAY_ID,
        name="Rabbit",
        cell=FRAME_SIZE,
        asset_dir=ASSET_DIR,
        sheets={"states": ("rabbit-states.png", len(POSE_NAMES), ATLAS_COLUMNS)},
        options=options,
        sections=(
            Section(
                "hints", "display hint",
                tuple(
                    Row(key, HINT_NOTES.get(key, ""),
                        tuple(POSE_NAMES[i] for i in STATE_FRAMES[key]))
                    for key in HINT_ORDER
                ),
                tuple(POSE_NAMES),
                note="여러 장을 고르면 시간 구간마다 하나씩 무작위로 뽑는다. 직전 장은 피한다.",
                multi=True,
            ),
        ),
    )


def load_frames(
    path: Path | None = None, *, log: Callable[[str], None] | None = None
) -> dict[str, tuple[int, ...]]:
    """Resolve hint -> candidate frame indices through the shared loader."""
    resolved = _resolve(sprite_map(), path, log=log)["hints"]
    lookup = {name: index for index, name in enumerate(POSE_NAMES)}
    return {key: tuple(lookup[name] for name in names) for key, names in resolved.items() if names}


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
    rotation: Rotation,
    frames_by_hint: dict[str, tuple[int, ...]] | None = None,
) -> int:
    """Choose once per state bucket and avoid immediate repeats when possible.

    The rotation itself is shared: any overlay whose signal offers several
    options picks between them the same way.
    """
    table = frames_by_hint if frames_by_hint is not None else STATE_FRAMES
    hint = display_hint if display_hint in table else "idle"
    names = tuple(POSE_NAMES[index] for index in table[hint])
    chosen = rotation.pick(hint, names, bucket)
    return POSE_NAMES.index(chosen) if chosen is not None else table[hint][0]


class Rabbit2DView:
    width, height = DISPLAY_SIZE
    background = TRANSPARENT
    transparent_color = TRANSPARENT

    def __init__(
        self,
        *,
        rng: random.Random | None = None,
        mapping_path: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.frames_by_hint = load_frames(mapping_path, log=log)
        asset = ASSET_DIR / "rabbit-states.png"
        atlas = Image.open(asset).convert("RGBA")
        self.frames = tuple(
            frame.resize(DISPLAY_SIZE, Image.Resampling.LANCZOS)
            for frame in atlas_frames(atlas)[:5]
        )
        self.rotation = Rotation(rng or random.Random())
        self.canvas: tk.Canvas | None = None
        self.image_id: int | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.display_hint = "idle"
        self.state_started_at = time.monotonic()

        self.current_frame = -1

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.photo = ImageTk.PhotoImage(self.frames[0], master=canvas)
        self.image_id = canvas.create_image(0, 0, image=self.photo, anchor="nw")

    def apply_state(self, state: OverlayState) -> None:
        hint = state.display_hint if state.display_hint in self.frames_by_hint else "idle"
        if hint != self.display_hint:
            self.display_hint = hint
            self.state_started_at = time.monotonic()
            self.rotation.clear()

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        del pointer_x, pointer_y, window_x, window_y
        if self.canvas is None or self.image_id is None:
            return
        elapsed_ms = max(0.0, (time.monotonic() - self.state_started_at) * 1000)
        bucket = int(elapsed_ms // STATE_FRAME_MS[self.display_hint])
        frame = choose_frame(self.display_hint, bucket, self.rotation, self.frames_by_hint)
        if frame == self.current_frame:
            return
        self.current_frame = frame
        self.photo = ImageTk.PhotoImage(self.frames[frame], master=self.canvas)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        if len(self.choices) > 12:
            self.choices = {key: value for key, value in self.choices.items() if key[1] >= bucket - 1}


def create_rabbit_2d(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, Rabbit2DView(), mode=mode, title="Engram Rabbit")
