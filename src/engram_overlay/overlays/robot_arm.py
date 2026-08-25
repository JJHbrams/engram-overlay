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


EXPRESSIONS = (
    EyeExpression("idle", "#fbbf24", -27.0, 27.0, 0.0, 0.0, 0.0, 0.0, (0.0, 0.0), 0.7),
    EyeExpression("boring", "#fbbf24", -6.0, 27.0, 0.0, 0.0, 0.0, 0.0, (0.0, 2.0), 0.5),
    EyeExpression("giggle", "#facc15", -27.0, 8.0, 0.0, 0.0, 0.0, 0.0, (0.0, -2.0), 1.5),
    EyeExpression("curious", "#eaff00", -22.0, 16.0, 0.0, -9.0, 0.0, 0.0, (4.0, -2.0), 1.2),
    EyeExpression("well", "#cbd5e1", -12.0, 20.0, 0.0, -9.0, 0.0, 0.0, (-3.0, 1.0), 0.8),
    EyeExpression("hmm", "#cbd5e1", -7.0, 7.0, 0.0, 0.0, 0.0, 0.0, (2.0, 0.0), 0.6),
    EyeExpression("tempered", "#ef4444", -11.0, 23.0, 0.0, -5.0, 12.0, 0.0, (0.0, 2.0), 2.3),
    EyeExpression("angry", "#ef4444", -12.0, 9.0, 0.0, 0.0, 15.0, 0.0, (0.0, 2.0), 2.8),
    EyeExpression("depressed", "#0ea5e9", -8.0, 27.0, 0.0, 0.0, -10.0, 0.0, (0.0, 4.0), 0.5),
    EyeExpression("sad", "#0ea5e9", -8.0, 10.0, 0.0, 0.0, -11.0, 0.0, (0.0, 4.0), 0.45),
)
ALARM_EXPRESSION = EyeExpression("alarm", "#ef4444", -12.0, 8.0, 0.0, 0.0, 16.0, 0.0, (0.0, 1.0), 3.4)


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


def shutter_line_points(center: Point, y_offset: float, tilt: float, peak: float) -> tuple[float, ...]:
    """Return a single three-point shutter line clipped visually by the eye rim."""
    radius = 25.0
    return (
        center[0] - radius,
        center[1] + y_offset - tilt,
        center[0],
        center[1] + y_offset + peak,
        center[0] + radius,
        center[1] + y_offset + tilt,
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
        self.joint_ids: list[int] = []
        self.target_id: int | None = None
        self.ambient_ids: list[int] = []
        self.shutter_ids: list[int] = []
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
        self.pulse_phase = 0.0
        self.next_expression_at = time.monotonic() + self.rng.uniform(3.0, 5.5)

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        color = self.expression.color
        canvas.create_rectangle(116, 0, 244, 15, fill="#1e293b", outline="#64748b", width=2)
        canvas.create_line(138, 13, 160, 44, fill="#475569", width=7, capstyle=tk.ROUND)
        canvas.create_line(222, 13, 200, 44, fill="#475569", width=7, capstyle=tk.ROUND)
        canvas.create_text(18, 22, text="CEILING LINK / IRIS", fill="#64748b", anchor="w", font=("Segoe UI", 9, "bold"))
        self.status_id = canvas.create_oval(326, 15, 340, 29, fill=color, outline="")
        self.target_id = canvas.create_oval(0, 0, 0, 0, outline=color, width=2, dash=(3, 3))
        for dash in ((3, 6), (1, 8)):
            self.ambient_ids.append(canvas.create_oval(0, 0, 0, 0, outline=color, width=1, dash=dash))
        for width in (18, 16, 14):
            self.link_ids.append(canvas.create_line(0, 0, 0, 0, fill="#334155", width=width, capstyle=tk.ROUND))
        for _ in range(4):
            self.joint_ids.append(canvas.create_oval(0, 0, 0, 0, fill="#e2e8f0", outline=color, width=4))
        self.led_halo_id = canvas.create_oval(0, 0, 0, 0, fill=color, outline="", stipple="gray50")
        self.led_core_id = canvas.create_oval(0, 0, 0, 0, fill=color, outline="#082f49", width=4)
        for _ in range(2):
            self.shutter_ids.append(
                canvas.create_line(0, 0, 0, 0, fill="#475569", width=7, capstyle=tk.ROUND, joinstyle=tk.ROUND)
            )
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
        self.pulse_phase += 0.055 * self.expression.pulse_speed
        self._draw()

    def _set_expression(self, expression: EyeExpression, now: float) -> None:
        self.expression = expression
        self.next_expression_at = now + self.rng.uniform(3.0, 5.5)
        if self.canvas is None:
            return
        color = expression.color
        if self.target_id is not None:
            self.canvas.itemconfigure(self.target_id, outline=color)
        if self.status_id is not None:
            self.canvas.itemconfigure(self.status_id, fill=color)
        for item_id in (*self.joint_ids, *self.ambient_ids):
            self.canvas.itemconfigure(item_id, outline=color)
        if self.led_halo_id is not None:
            self.canvas.itemconfigure(self.led_halo_id, fill=color)
        if self.led_core_id is not None:
            self.canvas.itemconfigure(self.led_core_id, fill=color)

    def _draw(self) -> None:
        if self.canvas is None:
            return
        for link_id, start, end in zip(self.link_ids, self.joints[:-1], self.joints[1:], strict=True):
            self.canvas.coords(link_id, *start, *end)
        for index, (joint_id, point) in enumerate(zip(self.joint_ids, self.joints, strict=True)):
            radius = 31 if index == 3 else (14 if index == 0 else 11)
            self.canvas.coords(joint_id, point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius)
        if self.target_id is not None:
            self.canvas.coords(self.target_id, self.target[0] - 34, self.target[1] - 34, self.target[0] + 34, self.target[1] + 34)
        end = self.joints[-1]
        pulse = (math.sin(self.pulse_phase) + 1.0) * 0.5
        for index, ambient_id in enumerate(self.ambient_ids):
            radius = 40.0 + index * 9.0 + pulse * (2.0 + index)
            self.canvas.coords(ambient_id, end[0] - radius, end[1] - radius, end[0] + radius, end[1] + radius)
        pupil = (end[0] + self.gaze[0], end[1] + self.gaze[1])
        halo_radius = 12.0 + pulse * 3.0
        core_radius = 6.0 + pulse * 1.2
        if self.led_halo_id is not None:
            self.canvas.coords(
                self.led_halo_id,
                pupil[0] - halo_radius,
                pupil[1] - halo_radius,
                pupil[0] + halo_radius,
                pupil[1] + halo_radius,
            )
        if self.led_core_id is not None:
            self.canvas.coords(
                self.led_core_id,
                pupil[0] - core_radius,
                pupil[1] - core_radius,
                pupil[0] + core_radius,
                pupil[1] + core_radius,
            )
        if len(self.shutter_ids) == 2:
            self.canvas.coords(
                self.shutter_ids[0],
                *shutter_line_points(end, self.upper_y, self.upper_tilt, self.upper_peak),
            )
            self.canvas.coords(
                self.shutter_ids[1],
                *shutter_line_points(end, self.lower_y, self.lower_tilt, self.lower_peak),
            )


def create_robot_arm(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, RobotArmView(), mode=mode, title="Engram 3-Link Robot Arm")
