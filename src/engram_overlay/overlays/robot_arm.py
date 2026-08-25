"""Three-link 2D robot arm with a Z-biased inverse-kinematics pose."""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from collections.abc import Sequence
from dataclasses import dataclass

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState

Point = tuple[float, float]
TRANSPARENT = "#010203"


@dataclass(frozen=True)
class EyeExpression:
    name: str
    color: str
    upper_y: float
    lower_y: float
    upper_tilt: float
    lower_tilt: float
    upper_peak: float
    lower_peak: float
    gaze: Point
    pulse_speed: float
    pupil_size: Point
    pupil_outline_width: float


EXPRESSIONS = (
    EyeExpression("idle", "#fbbf24", -27.0, 27.0, 0.0, 0.0, 0.0, 0.0, (0.0, 0.0), 0.7, (15.0, 15.0), 4.0),
    EyeExpression("boring", "#fbbf24", -6.0, 27.0, 0.0, 0.0, 0.0, 0.0, (0.0, 2.0), 0.5, (15.0, 13.0), 4.5),
    EyeExpression("giggle", "#facc15", -27.0, 8.0, 0.0, 0.0, 0.0, 0.0, (0.0, -2.0), 1.5, (16.0, 13.0), 3.5),
    EyeExpression("curious", "#eaff00", -22.0, 16.0, 0.0, -9.0, 0.0, 0.0, (4.0, -2.0), 1.2, (14.0, 17.0), 3.5),
    EyeExpression("hesitant", "#cbd5e1", -12.0, 20.0, 0.0, -9.0, 0.0, 0.0, (-3.0, 1.0), 0.8, (14.0, 15.0), 4.0),
    EyeExpression("skeptical", "#cbd5e1", -7.0, 7.0, 0.0, 0.0, 0.0, 0.0, (2.0, 0.0), 0.6, (16.0, 9.0), 5.0),
    EyeExpression("tempered", "#ef4444", -11.0, 23.0, 0.0, -5.0, 12.0, 0.0, (0.0, 2.0), 2.3, (15.0, 16.0), 4.5),
    EyeExpression("angry", "#ef4444", -12.0, 9.0, 0.0, 0.0, 15.0, 0.0, (0.0, 2.0), 2.8, (17.0, 14.0), 5.5),
    EyeExpression("depressed", "#0ea5e9", -8.0, 27.0, 0.0, 0.0, -10.0, 0.0, (0.0, 4.0), 0.5, (15.0, 14.0), 3.5),
    EyeExpression("sad", "#0ea5e9", -8.0, 10.0, 0.0, 0.0, -11.0, 0.0, (0.0, 4.0), 0.45, (14.0, 16.0), 4.0),
)
ALARM_EXPRESSION = EyeExpression(
    "alarm", "#ef4444", -12.0, 8.0, 0.0, 0.0, 16.0, 0.0, (0.0, 1.0), 3.4, (17.0, 15.0), 6.0
)


def _distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _point_at(origin: Point, direction: Point, distance: float) -> Point:
    return origin[0] + direction[0] * distance, origin[1] + direction[1] * distance


def _unit(a: Point, b: Point, fallback: Point = (0.0, -1.0)) -> Point:
    distance = _distance(a, b)
    if distance <= 1e-9:
        return fallback
    return (b[0] - a[0]) / distance, (b[1] - a[1]) / distance


def z_seed(base: Point, target: Point, lengths: Sequence[float], *, bend_side: int = 1) -> list[Point]:
    """Build an alternating Z seed aligned with the base-to-target direction."""
    direction = _unit(base, target)
    perpendicular = (-direction[1], direction[0])
    forward = 0.58
    sideways = math.sqrt(1.0 - forward * forward)
    points = [base]
    for index, length in enumerate(lengths):
        side = (sideways if index % 2 == 0 else -sideways) * bend_side
        segment = (
            direction[0] * forward + perpendicular[0] * side,
            direction[1] * forward + perpendicular[1] * side,
        )
        points.append(_point_at(points[-1], segment, length))
    return points


def solve_three_link_z(
    base: Point,
    target: Point,
    lengths: Sequence[float],
    *,
    seed: Sequence[Point] | None = None,
    bend_side: int = 1,
    iterations: int = 24,
    tolerance: float = 0.15,
) -> list[Point]:
    """Solve a fixed-base three-link chain while retaining its Z bend branch."""
    if len(lengths) != 3 or any(length <= 0 for length in lengths):
        raise ValueError("three positive link lengths are required")
    if bend_side not in {-1, 1}:
        raise ValueError("bend_side must be -1 or 1")

    total = sum(lengths)
    target_distance = _distance(base, target)
    if target_distance >= total:
        direction = _unit(base, target)
        points = [base]
        for length in lengths:
            points.append(_point_at(points[-1], direction, length))
        return points

    # Hold the tool at a shallow right-facing angle, then solve the first two
    # circles for the right-handed elbow. This makes the preferred branch a
    # clear /\/ silhouette instead of letting an unconstrained solver relax
    # the final link toward vertical.
    tool_angle = math.radians(28.0)
    vertical_sign = 1.0 if target[1] >= base[1] else -1.0
    tool_direction = (bend_side * math.sin(tool_angle), vertical_sign * math.cos(tool_angle))
    wrist = _point_at(target, tool_direction, -lengths[2])
    wrist_distance = _distance(base, wrist)
    if abs(lengths[0] - lengths[1]) <= wrist_distance <= lengths[0] + lengths[1]:
        axis = _unit(base, wrist)
        along = (lengths[0] ** 2 - lengths[1] ** 2 + wrist_distance**2) / (2.0 * wrist_distance)
        height = math.sqrt(max(lengths[0] ** 2 - along**2, 0.0))
        center = _point_at(base, axis, along)
        normal = (-axis[1], axis[0])
        elbows = (
            _point_at(center, normal, height),
            _point_at(center, normal, -height),
        )
        elbow = max(elbows, key=lambda point: point[0]) if bend_side > 0 else min(elbows, key=lambda point: point[0])
        return [base, elbow, wrist, target]

    points = z_seed(base, target, lengths, bend_side=bend_side)
    points[0] = base
    for _ in range(iterations):
        points[-1] = target
        for index in range(2, -1, -1):
            direction = _unit(points[index + 1], points[index])
            points[index] = _point_at(points[index + 1], direction, lengths[index])

        points[0] = base
        for index, length in enumerate(lengths):
            direction = _unit(points[index], points[index + 1])
            points[index + 1] = _point_at(points[index], direction, length)

        if _distance(points[-1], target) <= tolerance:
            break
    return points


def lower_workspace_target(pointer_x: float, pointer_y: float, width: float) -> Point:
    """Keep the hanging eye below its ceiling root while tracking the pointer."""
    return min(max(pointer_x, 95.0), width - 95.0), min(max(pointer_y, 285.0), 375.0)


def bend_side_for_target(current: int, target_x: float, center_x: float, *, deadband: float = 18.0) -> int:
    """Mirror the Z branch only after the endpoint clears the center deadband."""
    if target_x < center_x - deadband:
        return -1
    if target_x > center_x + deadband:
        return 1
    return current


def eyelid_polygon_points(
    center: Point,
    y_offset: float,
    tilt: float,
    peak: float,
    *,
    upper: bool,
) -> tuple[float, ...]:
    """Build a filled mechanical eyelid whose inner edge carries the expression."""
    edge_radius = 28.0
    rim_radius = 29.0
    inner = (
        (center[0] - edge_radius, center[1] + y_offset - tilt),
        (center[0], center[1] + y_offset + peak),
        (center[0] + edge_radius, center[1] + y_offset + tilt),
    )
    if upper:
        rim = (
            (center[0] + rim_radius, center[1] - 8.0),
            (center[0] + 20.0, center[1] - 25.0),
            (center[0], center[1] - rim_radius),
            (center[0] - 20.0, center[1] - 25.0),
            (center[0] - rim_radius, center[1] - 8.0),
        )
    else:
        rim = (
            (center[0] + rim_radius, center[1] + 8.0),
            (center[0] + 20.0, center[1] + 25.0),
            (center[0], center[1] + rim_radius),
            (center[0] - 20.0, center[1] + 25.0),
            (center[0] - rim_radius, center[1] + 8.0),
        )
    points = (*inner, *rim)
    return tuple(coordinate for point in points for coordinate in point)


def tracked_gaze(
    pointer: Point,
    center: Point,
    bias: Point = (0.0, 0.0),
    *,
    max_x: float = 8.0,
    max_y: float = 6.0,
    response_distance: float = 120.0,
) -> Point:
    """Return a softly bounded elliptical gaze toward the pointer."""
    dx = pointer[0] - center[0]
    dy = pointer[1] - center[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-9:
        mouse_x = mouse_y = 0.0
    else:
        strength = min(distance / response_distance, 1.0)
        mouse_x = dx / distance * max_x * strength
        mouse_y = dy / distance * max_y * strength
    gaze_x = bias[0] + mouse_x
    gaze_y = bias[1] + mouse_y
    ellipse_length = math.hypot(gaze_x / max_x, gaze_y / max_y)
    if ellipse_length > 1.0:
        gaze_x /= ellipse_length
        gaze_y /= ellipse_length
    return gaze_x, gaze_y


def oriented_polygon_points(center: Point, direction: Point, local_points: Sequence[Point]) -> tuple[float, ...]:
    """Transform side/forward local coordinates into a link-oriented polygon."""
    forward = _unit((0.0, 0.0), direction, fallback=(0.0, 1.0))
    side = (-forward[1], forward[0])
    points = (
        (
            center[0] + side[0] * local_side + forward[0] * local_forward,
            center[1] + side[1] * local_side + forward[1] * local_forward,
        )
        for local_side, local_forward in local_points
    )
    return tuple(coordinate for point in points for coordinate in point)


def link_shell_points(
    start: Point,
    end: Point,
    *,
    start_inset: float,
    end_inset: float,
    start_half_width: float,
    end_half_width: float,
    side_offset: float = 0.0,
) -> tuple[float, ...]:
    """Return a tapered armor plate over the middle of one skeletal link."""
    direction = _unit(start, end, fallback=(0.0, 1.0))
    side = (-direction[1], direction[0])
    shell_start = (
        start[0] + direction[0] * start_inset + side[0] * side_offset,
        start[1] + direction[1] * start_inset + side[1] * side_offset,
    )
    shell_end = (
        end[0] - direction[0] * end_inset + side[0] * side_offset,
        end[1] - direction[1] * end_inset + side[1] * side_offset,
    )
    points = (
        _point_at(shell_start, side, start_half_width),
        _point_at(shell_end, side, end_half_width),
        _point_at(shell_end, side, -end_half_width),
        _point_at(shell_start, side, -start_half_width),
    )
    return tuple(coordinate for point in points for coordinate in point)


def offset_link_points(start: Point, end: Point, *, side_offset: float, inset: float) -> tuple[float, ...]:
    """Return an exposed cable or highlight parallel to a moving link."""
    direction = _unit(start, end, fallback=(0.0, 1.0))
    side = (-direction[1], direction[0])
    cable_start = _point_at(_point_at(start, direction, inset), side, side_offset)
    cable_end = _point_at(_point_at(end, direction, -inset), side, side_offset)
    return *cable_start, *cable_end


EYE_POD_PROFILE: tuple[Point, ...] = (
    (-38.0, 12.0),
    (-43.0, -8.0),
    (-29.0, -33.0),
    (-7.0, -43.0),
    (22.0, -38.0),
    (39.0, -18.0),
    (42.0, 8.0),
    (27.0, 33.0),
    (-15.0, 38.0),
)


class RobotArmView:
    width = 360
    height = 430
    background = TRANSPARENT
    transparent_color = TRANSPARENT
    base: Point = (180.0, 48.0)
    lengths = (132.0, 122.0, 116.0)

    def __init__(self, *, rng: random.Random | None = None) -> None:
        self.canvas: tk.Canvas | None = None
        self.target: Point = (180.0, 350.0)
        self.bend_side = 1
        self.joints = solve_three_link_z(self.base, self.target, self.lengths, bend_side=self.bend_side)
        self.link_ids: list[int] = []
        self.link_shadow_ids: list[int] = []
        self.link_shell_ids: list[int] = []
        self.link_highlight_ids: list[int] = []
        self.cable_ids: list[int] = []
        self.pod_shell_ids: list[int] = []
        self.joint_ids: list[int] = []
        self.iris_ring_ids: list[int] = []
        self.eyelid_ids: list[int] = []
        self.eye_rim_id: int | None = None
        self.led_halo_id: int | None = None
        self.led_core_id: int | None = None
        self.status_id: int | None = None
        self.rng = rng or random.Random()
        self.expression = EXPRESSIONS[0]
        self.upper_y = self.expression.upper_y
        self.lower_y = self.expression.lower_y
        self.upper_tilt = self.expression.upper_tilt
        self.lower_tilt = self.expression.lower_tilt
        self.upper_peak = self.expression.upper_peak
        self.lower_peak = self.expression.lower_peak
        self.gaze: Point = self.expression.gaze
        self.mouse_gaze: Point = (0.0, 0.0)
        self.pupil_size: Point = self.expression.pupil_size
        self.pupil_outline_width = self.expression.pupil_outline_width
        self.pulse_phase = 0.0
        self.next_expression_at = time.monotonic() + self.rng.uniform(3.0, 5.5)

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        color = self.expression.color
        canvas.create_rectangle(110, 0, 250, 12, fill="#111827", outline="#0f172a", width=2)
        canvas.create_polygon(
            116,
            0,
            244,
            0,
            236,
            18,
            124,
            18,
            fill="#e7e5df",
            outline="#334155",
            width=2,
        )
        canvas.create_line(138, 13, 160, 44, fill="#475569", width=7, capstyle=tk.ROUND)
        canvas.create_line(222, 13, 200, 44, fill="#475569", width=7, capstyle=tk.ROUND)
        canvas.create_text(18, 22, text="CEILING LINK / IRIS", fill="#64748b", anchor="w", font=("Segoe UI", 9, "bold"))
        self.status_id = canvas.create_oval(326, 15, 340, 29, fill=color, outline="")
        for width in (18, 16, 14):
            self.link_ids.append(canvas.create_line(0, 0, 0, 0, fill="#334155", width=width, capstyle=tk.ROUND))
        for _ in range(3):
            self.link_shadow_ids.append(
                canvas.create_polygon(0, 0, 0, 0, fill="#64748b", outline="#1f2937", width=2, joinstyle=tk.ROUND)
            )
        for _ in range(3):
            self.link_shell_ids.append(
                canvas.create_polygon(0, 0, 0, 0, fill="#e7e5df", outline="#263442", width=2, joinstyle=tk.ROUND)
            )
        for _ in range(3):
            self.link_highlight_ids.append(
                canvas.create_line(0, 0, 0, 0, fill="#ffffff", width=2, capstyle=tk.ROUND)
            )
        for index in range(3):
            cable_color = "#d97706" if index == 2 else "#111827"
            self.cable_ids.append(canvas.create_line(0, 0, 0, 0, fill=cable_color, width=3, capstyle=tk.ROUND))
        self.pod_shell_ids.append(
            canvas.create_polygon(0, 0, 0, 0, fill="#334155", outline="#0f172a", width=3, joinstyle=tk.ROUND)
        )
        self.pod_shell_ids.append(
            canvas.create_polygon(0, 0, 0, 0, fill="#e7e5df", outline="#263442", width=3, joinstyle=tk.ROUND)
        )
        for _ in range(4):
            self.joint_ids.append(canvas.create_oval(0, 0, 0, 0, fill="#e2e8f0", outline=color, width=4))
        self.led_halo_id = canvas.create_oval(0, 0, 0, 0, fill=color, outline="", stipple="gray50")
        self.led_core_id = canvas.create_oval(0, 0, 0, 0, fill=color, outline="#082f49", width=4)
        for dash, width in (((3, 3), 2), ((3, 6), 1), ((1, 8), 1)):
            self.iris_ring_ids.append(canvas.create_oval(0, 0, 0, 0, outline=color, width=width, dash=dash))
        for _ in range(2):
            self.eyelid_ids.append(
                canvas.create_polygon(0, 0, 0, 0, fill="#64748b", outline="#0f172a", width=3, joinstyle=tk.ROUND)
            )
        self.eye_rim_id = canvas.create_oval(0, 0, 0, 0, fill="", outline="#0f172a", width=4)
        self._draw()

    def apply_state(self, state: OverlayState) -> None:
        if state.display_hint in {"error", "provider_error"}:
            self._set_expression(ALARM_EXPRESSION, time.monotonic())

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        local_target = lower_workspace_target(pointer_x - window_x, pointer_y - window_y, self.width)
        smoothing = 0.14
        self.target = (
            self.target[0] + (local_target[0] - self.target[0]) * smoothing,
            self.target[1] + (local_target[1] - self.target[1]) * smoothing,
        )
        self.bend_side = bend_side_for_target(self.bend_side, self.target[0], self.base[0])
        self.joints = solve_three_link_z(
            self.base,
            self.target,
            self.lengths,
            seed=self.joints,
            bend_side=self.bend_side,
        )
        desired_mouse_gaze = tracked_gaze(
            (pointer_x - window_x, pointer_y - window_y),
            self.joints[-1],
        )
        gaze_smoothing = 0.16
        self.mouse_gaze = (
            self.mouse_gaze[0] + (desired_mouse_gaze[0] - self.mouse_gaze[0]) * gaze_smoothing,
            self.mouse_gaze[1] + (desired_mouse_gaze[1] - self.mouse_gaze[1]) * gaze_smoothing,
        )
        now = time.monotonic()
        if now >= self.next_expression_at:
            choices = tuple(expression for expression in EXPRESSIONS if expression.name != self.expression.name)
            self._set_expression(self.rng.choice(choices), now)
        expression_smoothing = 0.1
        for attribute in ("upper_y", "lower_y", "upper_tilt", "lower_tilt", "upper_peak", "lower_peak"):
            current = getattr(self, attribute)
            setattr(self, attribute, current + (getattr(self.expression, attribute) - current) * expression_smoothing)
        self.gaze = (
            self.gaze[0] + (self.expression.gaze[0] - self.gaze[0]) * expression_smoothing,
            self.gaze[1] + (self.expression.gaze[1] - self.gaze[1]) * expression_smoothing,
        )
        self.pupil_size = (
            self.pupil_size[0] + (self.expression.pupil_size[0] - self.pupil_size[0]) * expression_smoothing,
            self.pupil_size[1] + (self.expression.pupil_size[1] - self.pupil_size[1]) * expression_smoothing,
        )
        self.pupil_outline_width += (
            self.expression.pupil_outline_width - self.pupil_outline_width
        ) * expression_smoothing
        self.pulse_phase += 0.055 * self.expression.pulse_speed
        self._draw()

    def _set_expression(self, expression: EyeExpression, now: float) -> None:
        self.expression = expression
        self.next_expression_at = now + self.rng.uniform(3.0, 5.5)
        if self.canvas is None:
            return
        color = expression.color
        if self.status_id is not None:
            self.canvas.itemconfigure(self.status_id, fill=color)
        for item_id in (*self.joint_ids, *self.iris_ring_ids):
            self.canvas.itemconfigure(item_id, outline=color)
        if self.led_halo_id is not None:
            self.canvas.itemconfigure(self.led_halo_id, fill=color)
        if self.led_core_id is not None:
            self.canvas.itemconfigure(self.led_core_id, fill=color, width=expression.pupil_outline_width)

    def _draw(self) -> None:
        if self.canvas is None:
            return
        for link_id, start, end in zip(self.link_ids, self.joints[:-1], self.joints[1:], strict=True):
            self.canvas.coords(link_id, *start, *end)
        shell_widths = ((18.0, 13.0), (17.0, 12.0), (16.0, 11.0))
        cable_offsets = (22.0, -20.0, 18.0)
        for index, (start, end) in enumerate(zip(self.joints[:-1], self.joints[1:], strict=True)):
            start_width, end_width = shell_widths[index]
            self.canvas.coords(
                self.link_shadow_ids[index],
                *link_shell_points(
                    start,
                    end,
                    start_inset=19.0,
                    end_inset=22.0,
                    start_half_width=start_width + 2.0,
                    end_half_width=end_width + 2.0,
                    side_offset=5.0,
                ),
            )
            self.canvas.coords(
                self.link_shell_ids[index],
                *link_shell_points(
                    start,
                    end,
                    start_inset=17.0,
                    end_inset=24.0,
                    start_half_width=start_width,
                    end_half_width=end_width,
                    side_offset=-2.0,
                ),
            )
            self.canvas.coords(
                self.link_highlight_ids[index],
                *offset_link_points(start, end, side_offset=-(end_width - 3.0), inset=31.0),
            )
            self.canvas.coords(
                self.cable_ids[index],
                *offset_link_points(start, end, side_offset=cable_offsets[index], inset=10.0),
            )
        wrist = self.joints[-2]
        end = self.joints[-1]
        pod_direction = (end[0] - wrist[0], end[1] - wrist[1])
        if len(self.pod_shell_ids) == 2:
            shadow_profile = tuple((side + 4.0, forward + 4.0) for side, forward in EYE_POD_PROFILE)
            self.canvas.coords(
                self.pod_shell_ids[0],
                *oriented_polygon_points(end, pod_direction, shadow_profile),
            )
            self.canvas.coords(
                self.pod_shell_ids[1],
                *oriented_polygon_points(end, pod_direction, EYE_POD_PROFILE),
            )
        for index, (joint_id, point) in enumerate(zip(self.joint_ids, self.joints, strict=True)):
            radius = 31 if index == 3 else (14 if index == 0 else 11)
            self.canvas.coords(joint_id, point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius)
        pulse = (math.sin(self.pulse_phase) + 1.0) * 0.5
        pupil = (
            end[0] + self.gaze[0] + self.mouse_gaze[0],
            end[1] + self.gaze[1] + self.mouse_gaze[1],
        )
        pupil_radius_x = self.pupil_size[0] + pulse * 0.8
        pupil_radius_y = self.pupil_size[1] + pulse * 0.8
        halo_radius_x = pupil_radius_x + 5.0 + pulse * 1.5
        halo_radius_y = pupil_radius_y + 5.0 + pulse * 1.5
        if self.led_halo_id is not None:
            self.canvas.coords(
                self.led_halo_id,
                pupil[0] - halo_radius_x,
                pupil[1] - halo_radius_y,
                pupil[0] + halo_radius_x,
                pupil[1] + halo_radius_y,
            )
        if self.led_core_id is not None:
            self.canvas.itemconfigure(self.led_core_id, width=self.pupil_outline_width)
            self.canvas.coords(
                self.led_core_id,
                pupil[0] - pupil_radius_x,
                pupil[1] - pupil_radius_y,
                pupil[0] + pupil_radius_x,
                pupil[1] + pupil_radius_y,
            )
        iris_base = max(pupil_radius_x, pupil_radius_y)
        for index, iris_ring_id in enumerate(self.iris_ring_ids):
            radius = iris_base + 2.0 + index * 3.0 + pulse * (0.35 + index * 0.2)
            self.canvas.coords(
                iris_ring_id,
                pupil[0] - radius,
                pupil[1] - radius,
                pupil[0] + radius,
                pupil[1] + radius,
            )
        if len(self.eyelid_ids) == 2:
            self.canvas.coords(
                self.eyelid_ids[0],
                *eyelid_polygon_points(end, self.upper_y, self.upper_tilt, self.upper_peak, upper=True),
            )
            self.canvas.coords(
                self.eyelid_ids[1],
                *eyelid_polygon_points(end, self.lower_y, self.lower_tilt, self.lower_peak, upper=False),
            )
        if self.eye_rim_id is not None:
            self.canvas.coords(self.eye_rim_id, end[0] - 31, end[1] - 31, end[0] + 31, end[1] + 31)


def create_robot_arm(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, RobotArmView(), mode=mode, title="Engram 3-Link Robot Arm")
