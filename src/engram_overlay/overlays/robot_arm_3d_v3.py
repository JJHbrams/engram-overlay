"""V2 robot arm watching tiny screen-space wanderers below it."""

from __future__ import annotations

import math
import sys
import tkinter as tk
import ctypes
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from .robot_arm_3d_v2 import (
    RobotArm3DV2View,
    TRANSPARENT,
    display_work_area_for_window,
    enable_per_monitor_dpi_awareness,
    eye_emission_projection,
)

STRIP_HEIGHT = 78
GROUND_Y = 64.0


@dataclass(frozen=True)
class Cover:
    x: float
    y: float
    radius: float


@dataclass
class TinyWanderer:
    """Small autonomous traveler with a deliberately simple behavior state."""

    x: float
    y: float
    direction: float = 1.0
    speed: float = 12.0
    state: str = "walk"
    state_time: float = 0.0
    stride: float = 0.0
    accent: str = "#d89135"


def scene_layout(width: float) -> tuple[tuple[Cover, ...], list[TinyWanderer]]:
    """Scale the miniature scene across the active monitor work area."""
    covers = (
        Cover(width * 0.16, GROUND_Y, 23.0),
        Cover(width * 0.49, GROUND_Y, 20.0),
        Cover(width * 0.84, GROUND_Y, 27.0),
    )
    wanderers = [
        TinyWanderer(width * 0.27, GROUND_Y, direction=1.0, speed=28.0, accent="#d89135"),
        TinyWanderer(width * 0.40, GROUND_Y, direction=-1.0, speed=23.0, accent=""),
        TinyWanderer(width * 0.69, GROUND_Y, direction=1.0, speed=30.0, accent="#7f9a73"),
    ]
    return covers, wanderers


DEFAULT_COVERS, _DEFAULT_WANDERERS = scene_layout(420.0)


def point_in_gaze_cone(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    half_angle_degrees: float = 15.0,
) -> bool:
    """Return whether a screen point lies in the finite eye-to-target cone."""
    ray_x, ray_y = end[0] - start[0], end[1] - start[1]
    point_x, point_y = point[0] - start[0], point[1] - start[1]
    ray_length = math.hypot(ray_x, ray_y)
    point_length = math.hypot(point_x, point_y)
    if ray_length < 1e-6 or point_length < 1e-6 or point_length > ray_length * 1.08:
        return False
    cosine = (ray_x * point_x + ray_y * point_y) / (ray_length * point_length)
    return cosine >= math.cos(math.radians(half_angle_degrees))


def advance_wanderer(
    wanderer: TinyWanderer,
    *,
    seen: bool,
    covers: tuple[Cover, ...] = DEFAULT_COVERS,
    dt: float = 1.0 / 60.0,
    bounds: tuple[float, float] = (18.0, 402.0),
) -> None:
    """Advance one traveler: evade the gaze, hide, peek, then resume patrol."""
    wanderer.state_time += dt
    wanderer.stride += dt * (12.0 if wanderer.state in {"evade", "walk"} else 4.0)
    nearest = min(covers, key=lambda cover: abs(cover.x - wanderer.x))
    safe_distance = nearest.radius * 0.62

    if seen and wanderer.state != "hide":
        wanderer.state = "evade"
        wanderer.state_time = 0.0
    if wanderer.state == "evade":
        delta = nearest.x - wanderer.x
        if abs(delta) <= safe_distance:
            wanderer.state = "hide"
            wanderer.state_time = 0.0
        else:
            wanderer.direction = 1.0 if delta > 0.0 else -1.0
            wanderer.x += wanderer.direction * wanderer.speed * 2.8 * dt
    elif wanderer.state == "hide":
        if seen:
            wanderer.state_time = 0.0
        elif wanderer.state_time > 1.1:
            wanderer.state = "peek"
            wanderer.state_time = 0.0
    elif wanderer.state == "peek":
        if seen:
            wanderer.state = "hide"
            wanderer.state_time = 0.0
        elif wanderer.state_time > 0.65:
            wanderer.state = "walk"
            wanderer.state_time = 0.0
            wanderer.direction *= -1.0
    else:
        wanderer.x += wanderer.direction * wanderer.speed * dt

    if wanderer.x <= bounds[0] or wanderer.x >= bounds[1]:
        wanderer.x = min(max(wanderer.x, bounds[0]), bounds[1])
        wanderer.direction *= -1.0


def draw_wanderer(draw: ImageDraw.ImageDraw, wanderer: TinyWanderer) -> None:
    """Paint a tiny original hooded silhouette without character-specific detail."""
    x, ground = wanderer.x, wanderer.y
    crouch = 4.0 if wanderer.state == "hide" else 2.0 if wanderer.state == "peek" else 0.0
    bob = 0.0 if crouch else math.sin(wanderer.stride) * 1.2
    head_y = ground - 17.0 + crouch + bob
    facing = wanderer.direction
    cloak = [(x - 6.0, ground - 2.0), (x + 6.0, ground - 2.0), (x + facing * 3.5, head_y + 5.0)]
    draw.polygon(cloak, fill="#17191d", outline="#4c4640")
    draw.ellipse((x - 4.2, head_y - 4.2, x + 4.2, head_y + 4.2), fill="#22242a", outline="#665d50")
    draw.polygon(
        [(x - 5.4, head_y), (x + 5.4, head_y), (x + facing * 1.5, head_y - 6.0)],
        fill="#302d31",
        outline="#71685b",
    )
    if wanderer.state != "hide":
        foot = math.sin(wanderer.stride) * 2.0
        draw.line((x - 2.0, ground - 2.0, x - 3.0 - foot, ground + 1.0), fill="#71685b", width=1)
        draw.line((x + 2.0, ground - 2.0, x + 3.0 + foot, ground + 1.0), fill="#71685b", width=1)
    # A restrained carried ember gives one readable story beat at this scale.
    if wanderer.accent and wanderer.state != "hide":
        hand_x = x + facing * 6.0
        draw.ellipse((hand_x - 1.5, head_y + 4.0, hand_x + 1.5, head_y + 7.0), fill=wanderer.accent)


def draw_ground_and_covers(target: Image.Image, covers: tuple[Cover, ...]) -> None:
    draw = ImageDraw.Draw(target)
    draw.line((10, GROUND_Y + 2, target.width - 10, GROUND_Y + 2), fill="#34312f", width=2)
    for index, cover in enumerate(covers):
        shade = "#26272a" if index % 2 else "#302e2d"
        draw.polygon(
            [
                (cover.x - cover.radius, cover.y + 2),
                (cover.x - cover.radius * 0.72, cover.y - cover.radius * 0.55),
                (cover.x - cover.radius * 0.16, cover.y - cover.radius),
                (cover.x + cover.radius * 0.62, cover.y - cover.radius * 0.68),
                (cover.x + cover.radius, cover.y + 2),
            ],
            fill=shade,
            outline="#5a5148",
        )
        draw.line(
            (cover.x - cover.radius * 0.55, cover.y - cover.radius * 0.48, cover.x + cover.radius * 0.45, cover.y - cover.radius * 0.62),
            fill="#71665a",
            width=1,
        )


class TinyWandererDisplay:
    """Independent taskbar-anchored strip that receives gaze in screen space."""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.bounds = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
        self.origin_x = 0
        self.origin_y = self.bounds[3] - STRIP_HEIGHT
        self.width = self.bounds[2]
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        try:
            self.window.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(
            self.window,
            width=self.width,
            height=STRIP_HEIGHT,
            highlightthickness=0,
            borderwidth=0,
            bg=TRANSPARENT,
        )
        self.canvas.pack(fill="both", expand=True)
        self.photo: ImageTk.PhotoImage | None = None
        self._positioned = False
        self.covers, self.wanderers = scene_layout(self.width)
        self._place()
        self.window.deiconify()
        self.window.update_idletasks()
        self._make_click_through()

    def _place(self) -> None:
        work = display_work_area_for_window(self.root)
        if work is None:
            work = (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        changed = work != self.bounds
        self.bounds = work
        self.origin_x = work[0]
        self.origin_y = work[3] - STRIP_HEIGHT
        new_width = work[2] - work[0]
        size_changed = new_width != self.width
        if changed or size_changed:
            self.width = new_width
            self.covers, self.wanderers = scene_layout(self.width)
            self.canvas.configure(width=self.width, height=STRIP_HEIGHT)
        if changed or size_changed or not self._positioned:
            self.window.geometry(f"{self.width}x{STRIP_HEIGHT}{self.origin_x:+d}{self.origin_y:+d}")
            self._positioned = True

    def _make_click_through(self) -> None:
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        window_id = self.window.winfo_id()
        hwnd = user32.GetParent(window_id) or window_id
        extended_style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, extended_style | 0x00000020 | 0x00000080 | 0x08000000)

    def update(
        self,
        source_canvas: tk.Canvas,
        gaze_start: tuple[float, float],
        gaze_end: tuple[float, float],
    ) -> None:
        self._place()
        source_x, source_y = source_canvas.winfo_rootx(), source_canvas.winfo_rooty()
        start = source_x + gaze_start[0] - self.origin_x, source_y + gaze_start[1] - self.origin_y
        direction_x, direction_y = gaze_end[0] - gaze_start[0], gaze_end[1] - gaze_start[1]
        length = max(math.hypot(direction_x, direction_y), 1.0)
        reach = math.hypot(self.width, self.bounds[3] - self.bounds[1]) * 2.0
        end = start[0] + direction_x / length * reach, start[1] + direction_y / length * reach

        target = Image.new("RGBA", (self.width, STRIP_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(target)
        for wanderer in self.wanderers:
            seen = point_in_gaze_cone((wanderer.x, wanderer.y - 10.0), start, end)
            advance_wanderer(
                wanderer,
                seen=seen,
                covers=self.covers,
                bounds=(18.0, self.width - 18.0),
            )
            draw_wanderer(draw, wanderer)
        draw_ground_and_covers(target, self.covers)
        self.photo = ImageTk.PhotoImage(target, master=self.canvas)
        self.canvas.delete("wanderers")
        self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW, tags=("wanderers",))


class RobotArm3DV3View(RobotArm3DV2View):
    """Textured arm plus reactive miniature travelers in its surveillance field."""

    width = 420
    height = 430

    def __init__(self, *, eye_emission_enabled: bool = False) -> None:
        super().__init__(eye_emission_enabled=eye_emission_enabled)
        self.wanderer_display: TinyWandererDisplay | None = None

    def mount(self, canvas: tk.Canvas) -> None:
        super().mount(canvas)
        self.wanderer_display = TinyWandererDisplay(canvas.winfo_toplevel())

    def _draw_surface_overlays(self) -> None:
        if self.surface_image is None or self.canvas is None or self.wanderer_display is None:
            return
        if self.expression_plane is not None:
            start, end = eye_emission_projection(self, self.expression_plane, self.camera)
            self.wanderer_display.update(self.canvas, (start.x, start.y), (end.x, end.y))


def create_robot_arm_3d_v3(
    transport: JsonlTransport,
    mode: str,
    *,
    eye_emission: bool = False,
) -> TkOverlayHost:
    enable_per_monitor_dpi_awareness()
    return TkOverlayHost(
        transport,
        RobotArm3DV3View(eye_emission_enabled=eye_emission),
        mode=mode,
        title="Engram 3D Robot Arm V3",
    )
