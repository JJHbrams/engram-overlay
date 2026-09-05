"""Bolttagu sprite overlay driven by the bolttagu sprite pack.

The upstream pack is a set of full-canvas 1254x1254 PNGs.  ``scripts/build-bolttagu-assets.py``
crops them to a shared rectangle and packs them into the horizontal sheets bundled here, so every
pose and frame stays aligned on the same feet anchor.

Frames are described as recipes -- an ordered tuple of ``(sheet, cell)`` layers composited bottom
up -- because idle is two independent loops at once: a random eye blink and the 24-frame steam
rising off the mug.  Recipe selection is pure clock arithmetic over an injectable random source,
so all of it is tested without a window.
"""

from __future__ import annotations

import json
import random
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import TOOL_CATEGORIES, JsonlTransport
from .spritemap import MAPPING_FILE, Layer, Option, Row, Section, SpriteMap
from .spritemap import installed_mapping_path as _installed_mapping_path
from .spritemap import resolve as _resolve
from .spritemap import single as _single
from ..state import OverlayState

TRANSPARENT = "#010203"
ASSET_DIR = Path(__file__).parent / "assets" / "bolttagu_2d"

Recipe = tuple[tuple[str, int], ...]

# Frame timings are the pack's own, from sprites.json. Every event set is three frames.
ENTER_DURATIONS_MS = (200, 300, 220)
EXIT_DURATIONS_MS = (220, 220, 260)
EVENT_DURATIONS_MS: dict[str, tuple[int, int, int]] = {
    "wondering": (320, 260, 320),
    "searching": (650, 500, 650),
    "writing": (320, 320, 420),
    "speaking": (220, 220, 260),
    "listening": (420, 420, 420),
    "waiting": (800, 800, 800),
    "success": (280, 360, 360),
    "error": (260, 300, 420),
}
LOOPING_EVENTS = ("wondering", "searching", "writing", "speaking", "listening", "waiting", "error")

# idle: steam is a 24-frame 10 fps loop, blink is a fixed 210 ms sequence that
# re-arms itself 2.5-6 s after it finishes.
STEAM_FRAME_MS = 100
STEAM_CELLS = 24
EYE_CELLS = {"open": 0, "half": 1, "closed": 2}
BLINK_SEQUENCE = (("half", 50), ("closed", 90), ("half", 70))
BLINK_INTERVAL_MS = (2500, 6000)

# The artwork is drawn with the long cheek and the mug toward the viewer's left,
# so the sprite already looks left and is mirrored only to turn right.
POINTER_DEADZONE_PX = 24

SCALE_RANGE = (0.2, 4.0)


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


def _event_clip(state: str, *, loop: bool) -> Clip:
    return Clip(sheet=state, cells=(0, 1, 2), durations_ms=EVENT_DURATIONS_MS[state], loop=loop)


CLIPS: dict[str, Clip] = {
    "alert": Clip(sheet="alert", cells=(0,), durations_ms=(1000,), loop=True),
    "enter": Clip(sheet="enter", cells=(0, 1, 2), durations_ms=ENTER_DURATIONS_MS, loop=False),
    # The rear-view farewell, played when Engram's launcher collapses the character.
    "exit": Clip(sheet="exit", cells=(0, 1, 2), durations_ms=EXIT_DURATIONS_MS, loop=False),
    # The pack's only one-shot event: play once, then settle back to idle.
    "success": _event_clip("success", loop=False),
    **{state: _event_clip(state, loop=True) for state in LOOPING_EVENTS},
}

# "idle" is the layered blink+steam pose; the rest name a looping clip above.
# The mapping follows the intent the pack states in its own event-map.json.
IDLE_POSE = "idle"
STATE_POSES: dict[str, str] = {
    "default": IDLE_POSE,
    "idle": IDLE_POSE,
    # The success one-shot plays over this pose and settles back into it.
    "success": IDLE_POSE,
    "hover": "alert",
    "click": "alert",
    "input": "listening",
    "generating": "speaking",
    "thought": "wondering",
    "search": "searching",
    # Consulting stored notes reads the same as consulting documents.
    "memory": "searching",
    "error": "error",
    "provider_error": "error",
}

# payload.category refines "generating", which is Engram's catch-all for every tool
# that is neither a search nor a memory lookup. Without this, editing a file and
# streaming an answer look identical.
# Engram publishes "search" and "memory" as display hints of their own, so those
# two categories never arrive alongside "generating" and can never reach the
# refinement below. Only the rest are configurable here; the hint table owns the
# other two. See event_api.event_for_bubble.
UNREACHABLE_CATEGORIES = frozenset({"search", "memory"})
REFINABLE_CATEGORIES = frozenset(TOOL_CATEGORIES) - UNREACHABLE_CATEGORIES

CATEGORY_POSES: dict[str, str] = {
    "write": "writing",     # code, docs, artifacts: write/edit/patch/delete tools
    "execute": "waiting",   # shell, build, test, run: work to wait on
    "read": "searching",    # opening a document
}

# A hint that warrants a one-shot the moment the renderer enters it.
HINT_ONESHOTS: dict[str, str] = {"success": "success"}

# Engram's launcher plays these for overlay.show and overlay.hide. A hint may use
# them too: a lifecycle transition is a one-shot override, so it still wins while
# it runs. Nothing here is off limits -- every bundled clip can be chosen.
LIFECYCLE_CLIPS = ("enter", "exit")

# What the launcher's own transitions play. overlay.show and overlay.hide are
# events in their own right, so which clip each one runs is chosen here rather
# than hardcoded at the call site.
LIFECYCLE_TRANSITIONS: dict[str, str] = {"show": "enter", "hide": "exit"}


def selectable_poses() -> list[str]:
    """Every pose a state can rest in.

    A clip that does not loop holds its last frame for as long as the state lasts.
    """
    return [IDLE_POSE] + sorted(CLIPS)


def selectable_oneshots() -> list[str]:
    """Every clip a hint may play once on arrival before settling into its pose."""
    return sorted(name for name, clip in CLIPS.items() if not clip.loop)


OVERLAY_ID = "bolttagu-2d"


def installed_mapping_path() -> Path:
    return _installed_mapping_path(OVERLAY_ID)


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
CATEGORY_NOTES = {
    "write": "write · edit · patch · delete",
    "execute": "shell · exec · build · test · run",
    "read": "read · open",
    "communication": "mail · message · discord",
    "other": "그 외",
}
# A fixed blink cycle stands in for the runtime's random one; over a preview the
# difference is not visible and it keeps the description declarative.
PREVIEW_BLINK_MS = 3_000


def sprite_map() -> SpriteMap:
    """Declarative description of this overlay for the shared picker and loader."""
    metadata = json.loads((ASSET_DIR / "atlas.json").read_text(encoding="utf-8"))
    sheets = {
        Path(name).stem.removeprefix("bolttagu-"): (name, len(frames), len(frames))
        for name, frames in metadata["sheets"].items()
    }
    options = {
        IDLE_POSE: Option(
            IDLE_POSE,
            (
                Layer("idle", tuple(EYE_CELLS[n] for n in ("open", "half", "closed", "half")),
                      (PREVIEW_BLINK_MS,) + tuple(ms for _, ms in BLINK_SEQUENCE)),
                Layer("steam", tuple(range(STEAM_CELLS)), (STEAM_FRAME_MS,) * STEAM_CELLS),
            ),
            note="눈깜빡임 + 커피 김",
        )
    }
    for name, clip in CLIPS.items():
        options[name] = Option(name, (Layer(clip.sheet, clip.cells, clip.durations_ms, clip.loop),))

    poses = tuple(selectable_poses())
    return SpriteMap(
        overlay_id=OVERLAY_ID,
        name="Bolttagu",
        cell=tuple(metadata["cell"]),
        asset_dir=ASSET_DIR,
        sheets=sheets,
        options=options,
        sections=(
            Section(
                "hints", "display hint",
                tuple(Row(k, HINT_NOTES.get(k, ""), (STATE_POSES[k],)) for k in HINT_ORDER),
                poses,
                note="그 상태에 머무는 동안 반복되는 동작. 반복하지 않는 클립은 마지막 프레임에서 멈춘다.",
            ),
            Section(
                "oneshots", "1회 재생",
                tuple(Row(k, HINT_NOTES.get(k, ""),
                          (HINT_ONESHOTS[k],) if k in HINT_ONESHOTS else ())
                      for k in HINT_ORDER),
                tuple(selectable_oneshots()),
                note="신호에 진입할 때 지속 동작 위로 한 번 얹힌 뒤 가라앉는다.",
                allow_empty=True,
            ),
            Section(
                "categories", "도구 범주 — generating 세분",
                tuple(Row(k, CATEGORY_NOTES.get(k, ""),
                          (CATEGORY_POSES[k],) if k in CATEGORY_POSES else ())
                      for k in ("write", "execute", "read", "communication", "other")
                      if k in REFINABLE_CATEGORIES),
                poses,
                note="검색·기억 도구는 자기 display hint로 오므로 여기 없다. 비우면 generating 설정을 따른다.",
                allow_empty=True,
            ),
            Section(
                "lifecycle", "런처 전환",
                (Row("show", "overlay.show · 런처로 펼칠 때", (LIFECYCLE_TRANSITIONS["show"],)),
                 Row("hide", "overlay.hide · 런처로 접을 때", (LIFECYCLE_TRANSITIONS["hide"],))),
                tuple(sorted(CLIPS)),
                note="display hint와 무관하게 항상 우선한다.",
            ),
        ),
    )


@dataclass(frozen=True)
class Mapping:
    """Which animation each signal draws, after any user override."""

    hints: dict[str, str]
    categories: dict[str, str]
    oneshots: dict[str, str]
    lifecycle: dict[str, str]


def _valid_pose(pose: object) -> bool:
    return isinstance(pose, str) and pose in selectable_poses()


def _valid_oneshot(clip: object) -> bool:
    return clip is None or (isinstance(clip, str) and clip in selectable_oneshots())


def load_mapping(
    path: Path | None = None, *, log: Callable[[str], None] | None = None
) -> Mapping:
    """Resolve this overlay's mapping through the shared loader."""
    resolved = _resolve(sprite_map(), path, log=log)
    return Mapping(
        hints=_single(resolved, "hints"),
        categories=_single(resolved, "categories"),
        oneshots=_single(resolved, "oneshots"),
        lifecycle=_single(resolved, "lifecycle"),
    )


def pose_for(
    hint: str,
    category: str | None,
    hints: dict[str, str] | None = None,
    categories: dict[str, str] | None = None,
) -> str:
    """Pose for one hint, refined by the tool category when Engram supplied one."""
    hints = STATE_POSES if hints is None else hints
    categories = CATEGORY_POSES if categories is None else categories
    resolved = hint if hint in hints else "idle"
    if resolved == "generating" and category in categories:
        return categories[category]
    return hints[resolved]


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


def scaled_cell(cell: tuple[int, int], scale: float) -> tuple[int, int]:
    """Window size for an atlas cell, or the cell itself at 1.0."""
    low, high = SCALE_RANGE
    if not low <= scale <= high:
        raise ValueError(f"scale must be between {low} and {high}, got {scale}")
    if scale == 1.0:
        return cell
    return (max(1, round(cell[0] * scale)), max(1, round(cell[1] * scale)))


def steam_cell(elapsed_ms: int) -> int:
    if elapsed_ms < 0:
        elapsed_ms = 0
    return (elapsed_ms // STEAM_FRAME_MS) % STEAM_CELLS


def facing_mirrored(pointer_x: int, window_x: int, width: int, *, current: bool) -> bool:
    """Whether to mirror the sprite so it looks toward the pointer.

    A deadzone around the window centre keeps the sprite from flipping back and forth
    while the pointer hovers exactly on the seam.
    """
    offset = pointer_x - (window_x + width // 2)
    if abs(offset) <= POINTER_DEADZONE_PX:
        return current
    return offset > 0


class BlinkTimeline:
    """Random eye blink on a millisecond clock and an injectable random source."""

    def __init__(self, *, rng: random.Random, started_ms: int = 0) -> None:
        self.rng = rng
        self._blink_started_ms: int | None = None
        self._next_blink_ms = started_ms + self._interval()

    def _interval(self) -> int:
        return self.rng.randint(*BLINK_INTERVAL_MS)

    def reset(self, now_ms: int) -> None:
        """Re-arm from scratch, as the pack's controller does on idle re-entry."""
        self._blink_started_ms = None
        self._next_blink_ms = now_ms + self._interval()

    def eye(self, now_ms: int) -> str:
        if self._blink_started_ms is None:
            if now_ms < self._next_blink_ms:
                return "open"
            # Start from the scheduled instant, not from this tick, so a late
            # frame does not stretch the blink itself.
            self._blink_started_ms = self._next_blink_ms
        elapsed = now_ms - self._blink_started_ms
        cursor = 0
        for name, duration in BLINK_SEQUENCE:
            cursor += duration
            if elapsed < cursor:
                return name
        self.reset(now_ms)
        return "open"


class BolttaguAnimator:
    """Track the active hint, any one-shot override, and the idle sub-loops."""

    def __init__(
        self,
        *,
        started_ms: int = 0,
        intro: str | None = "enter",
        rng: random.Random | None = None,
        hints: dict[str, str] | None = None,
        categories: dict[str, str] | None = None,
        oneshots: dict[str, str] | None = None,
    ) -> None:
        if intro is not None and intro not in CLIPS:
            raise ValueError(f"unknown intro clip: {intro}")
        self.hints = STATE_POSES if hints is None else hints
        self.categories = CATEGORY_POSES if categories is None else categories
        self.oneshots = HINT_ONESHOTS if oneshots is None else oneshots
        self.display_hint = "idle"
        self.tool_category: str | None = None
        self.state_started_ms = started_ms
        self.oneshot = intro
        self.oneshot_started_ms = started_ms
        # A farewell is terminal: nothing follows it on screen, so it holds its
        # last frame instead of snapping back to idle before the window closes.
        self.oneshot_holds = False
        self.blink = BlinkTimeline(rng=rng or random.Random(), started_ms=started_ms)

    @property
    def pose(self) -> str:
        return pose_for(self.display_hint, self.tool_category, self.hints, self.categories)

    def play_lifecycle(self, clip: str, now_ms: int, *, hold_last: bool = False) -> int:
        """Start a show/hide transition, overriding any hint one-shot in flight."""
        if clip not in CLIPS:
            raise ValueError(f"unknown lifecycle clip: {clip}")
        self.oneshot = clip
        self.oneshot_started_ms = now_ms
        self.oneshot_holds = hold_last
        return CLIPS[clip].total_ms

    def apply_hint(self, hint: str, now_ms: int, category: str | None = None) -> None:
        resolved = hint if hint in self.hints else "idle"
        if (resolved, category) == (self.display_hint, self.tool_category):
            return
        was_idle = self.pose == IDLE_POSE
        self.display_hint = resolved
        self.tool_category = category
        self.state_started_ms = now_ms
        self.oneshot_holds = False
        if self.pose == IDLE_POSE and not was_idle:
            self.blink.reset(now_ms)
        oneshot = self.oneshots.get(resolved)
        if oneshot is not None:
            self.oneshot = oneshot
            self.oneshot_started_ms = now_ms

    def resolve(self, now_ms: int) -> Recipe:
        """Layers to draw for this instant, retiring a finished one-shot on the way."""
        if self.oneshot is not None:
            clip = CLIPS[self.oneshot]
            cell = clip_cell(clip, now_ms - self.oneshot_started_ms)
            if cell is not None:
                return ((clip.sheet, cell),)
            if self.oneshot_holds:
                return ((clip.sheet, clip.cells[-1]),)
            self.oneshot = None
            if self.pose == IDLE_POSE:
                self.blink.reset(now_ms)
        if self.pose == IDLE_POSE:
            return (
                ("idle", EYE_CELLS[self.blink.eye(now_ms)]),
                ("steam", steam_cell(now_ms - self.state_started_ms)),
            )
        clip = CLIPS[self.pose]
        cell = clip_cell(clip, now_ms - self.state_started_ms)
        if cell is None:
            # A one-shot chosen as a state pose: play it, then stand there.
            cell = clip.cells[-1]
        return ((clip.sheet, cell),)


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

    def __init__(
        self,
        *,
        scale: float = 1.0,
        face_pointer: bool = True,
        launcher_managed: bool = False,
        show_floor: bool = False,
        coffee: bool = True,
        rng: random.Random | None = None,
        mapping_path: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        mapping = load_mapping(mapping_path, log=log)
        self.mapping = mapping
        sheets, cell = load_atlas()
        self.cell = cell
        self.scale = scale
        # Resize the finished frame rather than every cell, so memory stays flat
        # at any scale and only the <=12 redraws per second pay for it.
        self.width, self.height = scaled_cell(cell, scale)
        self.floor = sheets["floor"][1 if coffee else 0] if show_floor else None
        self.sheets = sheets
        self.face_pointer = face_pointer
        # When Engram's launcher owns presentation, the arrival bow belongs to
        # overlay.show rather than to process start.
        self.animator = BolttaguAnimator(
            started_ms=self._now_ms(),
            intro=None if launcher_managed else "enter",
            rng=rng,
            hints=mapping.hints,
            categories=mapping.categories,
            oneshots=mapping.oneshots,
        )
        self.mirrored = False
        self._pointer_frozen = False
        self.canvas: tk.Canvas | None = None
        self.image_id: int | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.drawn: tuple[Recipe, bool] | None = None

    def compose(self, recipe: Recipe, mirrored: bool) -> Image.Image:
        """Flatten one recipe. Cheap enough to redo per visible frame change."""
        base = self.floor
        frame = self.sheets[recipe[0][0]][recipe[0][1]]
        image = Image.alpha_composite(base, frame) if base is not None else frame.copy()
        for sheet, cell in recipe[1:]:
            image = Image.alpha_composite(image, self.sheets[sheet][cell])
        if mirrored:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if (self.width, self.height) != self.cell:
            image = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        return image

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        target = (self.animator.resolve(self._now_ms()), self.mirrored)
        self.photo = ImageTk.PhotoImage(self.compose(*target), master=canvas)
        self.image_id = canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.drawn = target

    def apply_state(self, state: OverlayState) -> None:
        self.animator.apply_hint(state.display_hint, self._now_ms(), state.tool_category)

    def resize(self, requested_width: int, requested_height: int) -> tuple[int, int]:
        """Apply host physical height within the safe scale range without stretching art."""
        del requested_width
        scale = min(SCALE_RANGE[1], max(SCALE_RANGE[0], float(requested_height) / self.cell[1]))
        self.width, self.height = scaled_cell(self.cell, scale)
        self.drawn = None
        return self.width, self.height

    def begin_enter(self) -> int:
        self._pointer_frozen = False
        return self.animator.play_lifecycle(self.mapping.lifecycle["show"], self._now_ms())

    def begin_exit(self) -> int:
        now_ms = self._now_ms()
        # Freeze orientation before starting or drawing the farewell so a late
        # pointer sample cannot flip any of its frames.
        self._pointer_frozen = True
        # Holding the final frame keeps the character gone until the window closes.
        hold_ms = self.animator.play_lifecycle(
            self.mapping.lifecycle["hide"], now_ms, hold_last=True
        )
        self._redraw((self.animator.resolve(now_ms), self.mirrored))
        return hold_ms

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        if self.face_pointer and not self._pointer_frozen:
            self.mirrored = facing_mirrored(pointer_x, window_x, self.width, current=self.mirrored)
        self._redraw((self.animator.resolve(self._now_ms()), self.mirrored))

    def _redraw(self, target: tuple[Recipe, bool]) -> None:
        if self.canvas is None or self.image_id is None or target == self.drawn:
            return
        self.photo = ImageTk.PhotoImage(self.compose(*target), master=self.canvas)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        self.drawn = target

    @staticmethod
    def _now_ms() -> int:
        return int(time.monotonic() * 1000)


def create_bolttagu_2d(
    transport: JsonlTransport,
    mode: str,
    *,
    face_pointer: bool = True,
    scale: float = 1.0,
    launcher_managed: bool = False,
) -> TkOverlayHost:
    view = Bolttagu2dView(
        face_pointer=face_pointer,
        scale=scale,
        launcher_managed=launcher_managed,
        log=transport.log,
    )
    return TkOverlayHost(
        transport, view, mode=mode, title="Bolttagu", start_hidden=launcher_managed
    )
