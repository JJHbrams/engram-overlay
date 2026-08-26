"""V2 robot arm watching tiny screen-space wanderers below it."""

from __future__ import annotations

import math
import sys
import tkinter as tk
import ctypes
import time
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from .robot_arm import ALARM_EXPRESSION, expression_for_hint
from .robot_arm_3d import RobotArm3DView
from .robot_arm_3d_v2 import (
    RobotArm3DV2View,
    TRANSPARENT,
    display_work_area_for_window,
    enable_per_monitor_dpi_awareness,
    eye_emission_projection,
    physical_canvas_transform,
    physical_window_bounds,
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


@dataclass(frozen=True)
class ArticulatedPose:
    left_arm: tuple[tuple[float, float], ...]
    right_arm: tuple[tuple[float, float], ...]
    left_leg: tuple[tuple[float, float], ...]
    right_leg: tuple[tuple[float, float], ...]


def walking_limb_pose(x: float, ground: float, direction: float, phase: float, crouch: float = 0.0) -> ArticulatedPose:
    """Return two-segment arm and leg joints for a readable silhouette walk."""
    hip = (x, ground - 10.0 + crouch * 0.55)
    shoulder = (x + direction * 0.5, ground - 24.0 + crouch)
    swing = math.sin(phase)
    lift = max(0.0, math.cos(phase)) * 1.6

    def leg(sign: float) -> tuple[tuple[float, float], ...]:
        knee = (hip[0] + direction * swing * 4.2 * sign, hip[1] + 5.2 - lift * sign)
        foot = (knee[0] + direction * swing * 4.0 * sign, ground - lift * sign)
        return hip, knee, foot

    def arm(sign: float) -> tuple[tuple[float, float], ...]:
        elbow = (shoulder[0] - direction * swing * 3.5 * sign, shoulder[1] + 5.0)
        hand = (elbow[0] - direction * swing * 3.0 * sign, elbow[1] + 5.0)
        return shoulder, elbow, hand

    return ArticulatedPose(left_arm=arm(1.0), right_arm=arm(-1.0), left_leg=leg(1.0), right_leg=leg(-1.0))


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


def absolute_tk_geometry(width: int, height: int, x: int, y: int) -> str:
    """Encode signed virtual-desktop coordinates as absolute Tk offsets."""
    return f"{width}x{height}+{x}+{y}"


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
    crouch = 6.0 if state == "hide" else 2.5 if state == "peek" else 0.0
    phase = stride + role * 0.72
    bob = 0.0 if crouch else math.sin(phase * 2.0) * 0.8
    height = (34.0, 31.0, 36.0)[role]
    head_y = ground - height + crouch + bob
    facing = direction
    pose = walking_limb_pose(x, ground, facing, phase, crouch)
    limb_color = "#111216"
    for limb in (pose.left_leg, pose.right_leg, pose.left_arm, pose.right_arm):
        draw.line(limb, fill="#51483e", width=4, joint="curve")
        draw.line(limb, fill=limb_color, width=3, joint="curve")

    shoulder_y = head_y + 5.0
    hip_y = ground - 10.0 + crouch * 0.55
    draw.polygon(
        [(x - 4.2, shoulder_y), (x + 4.2, shoulder_y), (x + 3.1, hip_y), (x - 3.1, hip_y)],
        fill="#111216",
        outline="#51483e",
    )
    # A short wind-swept cape keeps the traveler silhouette without turning
    # the entire body into a triangular icon.
    cape_back = x - facing * (7.5 + role)
    draw.polygon(
        [(x - facing * 3.2, shoulder_y + 1.0), (cape_back, hip_y - 1.0), (x - facing * 2.2, hip_y + 1.0)],
        fill="#17171a",
        outline="#494139",
    )
    draw.ellipse((x - 2.8, head_y - 2.8, x + 2.8, head_y + 2.8), fill="#141518", outline="#665b4e")
    draw.polygon(
        [(x - 3.4, head_y), (x + 3.4, head_y), (x + facing * 1.0, head_y - 4.5)],
        fill="#17171a",
        outline="#665b4e",
    )
    if role == 0:
        hand_x, hand_y = pose.left_arm[-1]
        staff_x = hand_x + facing * 1.5
        draw.line((staff_x, head_y - 1.0, staff_x + facing * 2.0, ground + 1.0), fill="#806e59", width=2)
    elif role == 1:
        pack_x = x - facing * 5.0
        draw.ellipse((pack_x - 3.0, head_y + 4.0, pack_x + 3.0, head_y + 11.0), fill="#242124")
        ember_x = x + facing * 6.0
        draw.ellipse((ember_x - 1.5, head_y + 6.0, ember_x + 1.5, head_y + 9.0), fill="#d27a2e")
    else:
        draw.ellipse((x - facing * 9.0 - 3.0, head_y + 5.0, x - facing * 9.0 + 3.0, head_y + 13.0), fill="#242124")


def draw_party(draw: ImageDraw.ImageDraw, party: WandererParty) -> None:
    """Draw a tight three-person procession that keeps formation."""
    offsets = (-20.0, 0.0, 20.0)
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


def terrain_ridge_points(width: float) -> tuple[tuple[float, float], ...]:
    """Return a restrained continuous foreground ridge beneath the procession."""
    ridge = (
        (0.00, 0.0),
        (0.07, -2.0),
        (0.14, 1.0),
        (0.23, -1.5),
        (0.31, 0.5),
        (0.40, -3.0),
        (0.50, 0.0),
        (0.61, -1.0),
        (0.70, 1.0),
        (0.80, -2.5),
        (0.91, 0.0),
        (1.00, -1.0),
    )
    top = tuple((width * ratio, GROUND_Y + offset) for ratio, offset in ridge)
    return (*top, (width, STRIP_HEIGHT), (0.0, STRIP_HEIGHT))


def draw_ground_and_covers(target: Image.Image, covers: tuple[Cover, ...]) -> None:
    draw = ImageDraw.Draw(target)
    ridge = terrain_ridge_points(target.width)
    draw.polygon(ridge, fill="#111215")
    draw.line(ridge[:12], fill="#51483f", width=1, joint="curve")
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
        self.window.title("Engram V3 Wanderer Strip")
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
        root_bounds = physical_window_bounds(self.root)
        root_center = (
            (root_bounds[0] + root_bounds[2]) * 0.5
            if root_bounds is not None
            else self.root.winfo_rootx() + self.root.winfo_width() * 0.5
        )
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
            # Tk's bare negative offset means "from the right/bottom edge".
            # Prefix both coordinates with '+' so negative values remain
            # absolute virtual-desktop coordinates (e.g. '+-2560+981').
            self.window.geometry(absolute_tk_geometry(self.width, STRIP_HEIGHT, self.origin_x, self.origin_y))
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
    ) -> str:
        self._place()
        (source_x, source_y), (scale_x, scale_y) = physical_canvas_transform(source_canvas)
        start = (
            source_x + gaze_start[0] * scale_x - self.origin_x,
            source_y + gaze_start[1] * scale_y - self.origin_y,
        )
        direction_x = (gaze_end[0] - gaze_start[0]) * scale_x
        direction_y = (gaze_end[1] - gaze_start[1]) * scale_y
        length = max(math.hypot(direction_x, direction_y), 1.0)
        reach = math.hypot(self.width, self.bounds[3] - self.bounds[1]) * 2.0
        end = start[0] + direction_x / length * reach, start[1] + direction_y / length * reach

        # A secondary Windows color-key Toplevel can discard an RGBA
        # PhotoImage as fully transparent. Paint an opaque key-color RGB frame
        # instead; Tk removes only #010203 and keeps every silhouette pixel.
        target = Image.new("RGB", (self.width, STRIP_HEIGHT), TRANSPARENT)
        draw = ImageDraw.Draw(target)
        member_points = tuple((self.party.x + offset * self.party.direction, self.party.y - 15.0) for offset in (-20.0, 0.0, 20.0))
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
        return self.party.state


class RobotArm3DV3View(RobotArm3DV2View):
    """Textured arm plus reactive miniature travelers in its surveillance field."""

    width = 420
    height = 430

    def __init__(self, *, eye_emission_enabled: bool = False) -> None:
        super().__init__(eye_emission_enabled=eye_emission_enabled)
        self.wanderer_display: TinyWandererDisplay | None = None
        self.party_tracking_active = False
        self.was_party_tracking = False

    def mount(self, canvas: tk.Canvas) -> None:
        super().mount(canvas)
        self.wanderer_display = TinyWandererDisplay(canvas.winfo_toplevel())

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        """Let an alarmed arm pursue the party until it reaches cover."""
        now = time.monotonic()
        display = self.wanderer_display
        if self.party_tracking_active and display is not None:
            self.random_expressions_enabled = False
            self.explorer_active = False
            self.last_pointer_motion_at = now
            if self.expression.name != ALARM_EXPRESSION.name:
                self._set_expression(ALARM_EXPRESSION, now)
            party_screen_x = display.origin_x + display.party.x
            party_screen_y = display.origin_y + display.party.y - 15.0
            if self.canvas is not None:
                (canvas_x, canvas_y), (scale_x, scale_y) = physical_canvas_transform(self.canvas)
                local_x = (party_screen_x - canvas_x) / max(scale_x, 1e-6)
                local_y = (party_screen_y - canvas_y) / max(scale_y, 1e-6)
                RobotArm3DView.tick(self, round(window_x + local_x), round(window_y + local_y), window_x, window_y)
            else:
                RobotArm3DView.tick(self, round(party_screen_x), round(party_screen_y), window_x, window_y)
            self.was_party_tracking = True
            return

        if self.was_party_tracking:
            restored = expression_for_hint(self.active_hint)
            self.random_expressions_enabled = restored is None
            self.explorer_active = False
            self.last_pointer_motion_at = now
            if restored is not None:
                self._set_expression(restored, now)
            else:
                self.next_expression_at = now
                self.explore_hold_until = now + 0.35
            self.was_party_tracking = False
        super().tick(pointer_x, pointer_y, window_x, window_y)

    def _draw_surface_overlays(self) -> None:
        if self.surface_image is None or self.canvas is None or self.wanderer_display is None:
            return
        if self.expression_plane is not None:
            start, end = eye_emission_projection(self, self.expression_plane, self.camera)
            party_state = self.wanderer_display.update(self.canvas, (start.x, start.y), (end.x, end.y))
            self.party_tracking_active = party_state == "evade"


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
