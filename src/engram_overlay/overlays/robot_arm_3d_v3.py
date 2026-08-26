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

STRIP_HEIGHT = 96
MAX_SCENE_WIDTH = 640
GROUND_Y = 82.0


@dataclass(frozen=True)
class Cover:
    x: float
    y: float
    radius: float
    kind: str = "rock"


@dataclass
class WandererParty:
    """Three travelers moving and reacting as one small procession."""

    x: float
    y: float
    direction: float = 1.0
    speed: float = 27.0
    state: str = "walk"
    state_time: float = 0.0
    stride: float = 0.0


def scene_layout(width: float) -> tuple[tuple[Cover, ...], WandererParty]:
    """Scale the miniature scene across the active monitor work area."""
    covers = (
        Cover(width * 0.16, GROUND_Y, 39.0, "tower"),
        Cover(width * 0.49, GROUND_Y, 34.0, "rock"),
        Cover(width * 0.84, GROUND_Y, 42.0, "ruin"),
    )
    return covers, WandererParty(width * 0.31, GROUND_Y)


def opposite_corner_origin(root_center_x: float, work_left: float, work_right: float, scene_width: float) -> tuple[str, float]:
    """Place the scene in the work-area corner farthest from the robot."""
    midpoint = work_left + (work_right - work_left) * 0.5
    if root_center_x >= midpoint:
        return "left", work_left
    return "right", work_right - scene_width


DEFAULT_COVERS, _DEFAULT_PARTY = scene_layout(420.0)


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


def advance_party(
    party: WandererParty,
    *,
    seen: bool,
    covers: tuple[Cover, ...] = DEFAULT_COVERS,
    dt: float = 1.0 / 60.0,
    bounds: tuple[float, float] = (18.0, 402.0),
) -> None:
    """Advance the procession: evade together, hide, peek, then march on."""
    party.state_time += dt
    party.stride += dt * (13.0 if party.state in {"evade", "walk"} else 3.5)
    nearest = min(covers, key=lambda cover: abs(cover.x - party.x))
    safe_distance = nearest.radius * 0.18

    if seen and party.state != "hide":
        party.state = "evade"
        party.state_time = 0.0
    if party.state == "evade":
        delta = nearest.x - party.x
        if abs(delta) <= safe_distance:
            party.state = "hide"
            party.state_time = 0.0
        else:
            party.direction = 1.0 if delta > 0.0 else -1.0
            party.x += party.direction * party.speed * 2.6 * dt
    elif party.state == "hide":
        if seen:
            party.state_time = 0.0
        elif party.state_time > 1.35:
            party.state = "peek"
            party.state_time = 0.0
    elif party.state == "peek":
        if seen:
            party.state = "hide"
            party.state_time = 0.0
        elif party.state_time > 0.7:
            party.state = "walk"
            party.state_time = 0.0
            party.direction *= -1.0
    else:
        party.x += party.direction * party.speed * dt

    margin = 25.0
    if party.x <= bounds[0] + margin or party.x >= bounds[1] - margin:
        party.x = min(max(party.x, bounds[0] + margin), bounds[1] - margin)
        party.direction *= -1.0


def draw_wanderer(
    draw: ImageDraw.ImageDraw,
    *,
    x: float,
    ground: float,
    direction: float,
    stride: float,
    state: str,
    role: int,
) -> None:
    """Paint an original hooded carrier silhouette with role-specific gear."""
    crouch = 5.0 if state == "hide" else 2.0 if state == "peek" else 0.0
    bob = 0.0 if crouch else math.sin(stride + role * 1.7) * 1.2
    height = (22.0, 18.0, 24.0)[role]
    head_y = ground - height + crouch + bob
    facing = direction
    cloak_width = (6.5, 6.0, 7.0)[role]
    cloak = [(x - cloak_width, ground - 2.0), (x + cloak_width, ground - 2.0), (x + facing * 3.0, head_y + 5.0)]
    draw.polygon(cloak, fill="#101114", outline="#494139")
    draw.ellipse((x - 3.7, head_y - 3.7, x + 3.7, head_y + 3.7), fill="#141518", outline="#5f5549")
    draw.polygon(
        [(x - 5.0, head_y), (x + 5.0, head_y), (x + facing * 1.5, head_y - 6.5)],
        fill="#17171a",
        outline="#665b4e",
    )
    if role == 0:
        staff_x = x + facing * 7.0
        draw.line((staff_x, head_y + 2.0, staff_x + facing * 1.5, ground + 1.0), fill="#736452", width=2)
    elif role == 1:
        pack_x = x - facing * 5.0
        draw.ellipse((pack_x - 3.0, head_y + 4.0, pack_x + 3.0, head_y + 11.0), fill="#242124")
        ember_x = x + facing * 6.0
        draw.ellipse((ember_x - 1.5, head_y + 6.0, ember_x + 1.5, head_y + 9.0), fill="#d27a2e")
    else:
        draw.line((x - facing * 4.0, head_y + 5.0, x - facing * 8.0, head_y + 11.0), fill="#5b5045", width=2)
    if state != "hide":
        foot = math.sin(stride + role * 1.7) * 2.2
        draw.line((x - 2.0, ground - 2.0, x - 3.0 - foot, ground + 1.0), fill="#71685b", width=1)
        draw.line((x + 2.0, ground - 2.0, x + 3.0 + foot, ground + 1.0), fill="#71685b", width=1)


def draw_party(draw: ImageDraw.ImageDraw, party: WandererParty) -> None:
    """Draw a tight three-person procession that keeps formation."""
    offsets = (-15.0, 0.0, 15.0)
    for role, offset in enumerate(offsets):
        draw_wanderer(
            draw,
            x=party.x + offset * party.direction,
            ground=party.y,
            direction=party.direction,
            stride=party.stride,
            state=party.state,
            role=role,
        )


def draw_ground_and_covers(target: Image.Image, covers: tuple[Cover, ...]) -> None:
    draw = ImageDraw.Draw(target)
    draw.line((10, GROUND_Y + 2, target.width - 10, GROUND_Y + 2), fill="#34312f", width=2)
    for index, cover in enumerate(covers):
        shade = "#26272a" if index % 2 else "#302e2d"
        if cover.kind == "tower":
            draw.polygon(
                [
                    (cover.x - 18.0, cover.y + 2.0),
                    (cover.x - 12.0, cover.y - 47.0),
                    (cover.x - 7.0, cover.y - cover.radius * 1.75),
                    (cover.x, cover.y - cover.radius * 2.05),
                    (cover.x + 7.0, cover.y - cover.radius * 1.75),
                    (cover.x + 12.0, cover.y - 47.0),
                    (cover.x + 18.0, cover.y + 2.0),
                ],
                fill="#111215",
                outline="#51483f",
            )
            eye_y = cover.y - cover.radius * 1.63
            draw.ellipse((cover.x - 5.0, eye_y - 2.5, cover.x + 5.0, eye_y + 2.5), fill="#b9582c")
        else:
            crown = 1.15 if cover.kind == "ruin" else 1.0
            draw.polygon(
                [
                    (cover.x - cover.radius, cover.y + 2),
                    (cover.x - cover.radius * 0.72, cover.y - cover.radius * 0.55),
                    (cover.x - cover.radius * 0.16, cover.y - cover.radius * crown),
                    (cover.x + cover.radius * 0.18, cover.y - cover.radius * 0.72),
                    (cover.x + cover.radius * 0.62, cover.y - cover.radius * 0.88),
                    (cover.x + cover.radius, cover.y + 2),
                ],
                fill=shade,
                outline="#5a5148",
            )
            if cover.kind == "ruin":
                draw.rectangle(
                    (cover.x + cover.radius * 0.25, cover.y - cover.radius * 1.25, cover.x + cover.radius * 0.57, cover.y - 8.0),
                    fill="#1a1b1e",
                    outline="#51483f",
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
        self.width = min(MAX_SCENE_WIDTH, self.bounds[2])
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
        self.corner = "left"
        self.covers, self.party = scene_layout(self.width)
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
        self.origin_y = work[3] - STRIP_HEIGHT
        work_width = work[2] - work[0]
        new_width = min(MAX_SCENE_WIDTH, work_width)
        root_center = self.root.winfo_rootx() + self.root.winfo_width() * 0.5
        new_corner, new_origin_x = opposite_corner_origin(root_center, work[0], work[2], new_width)
        size_changed = new_width != self.width
        if changed or size_changed:
            self.width = new_width
            self.covers, self.party = scene_layout(self.width)
            self.canvas.configure(width=self.width, height=STRIP_HEIGHT)
        corner_changed = new_corner != self.corner or new_origin_x != self.origin_x
        self.corner = new_corner
        self.origin_x = new_origin_x
        if changed or size_changed or corner_changed or not self._positioned:
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
        member_points = tuple((self.party.x + offset * self.party.direction, self.party.y - 12.0) for offset in (-15.0, 0.0, 15.0))
        seen = any(point_in_gaze_cone(point, start, end) for point in member_points)
        advance_party(
            self.party,
            seen=seen,
            covers=self.covers,
            bounds=(18.0, self.width - 18.0),
        )
        draw_party(draw, self.party)
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
