"""Three-link 2D robot arm with a Z-biased inverse-kinematics pose."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Sequence

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..state import OverlayState

Point = tuple[float, float]
TRANSPARENT = "#010203"


def _distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _point_at(origin: Point, direction: Point, distance: float) -> Point:
    return origin[0] + direction[0] * distance, origin[1] + direction[1] * distance


def _unit(a: Point, b: Point, fallback: Point = (0.0, -1.0)) -> Point:
    distance = _distance(a, b)
    if distance <= 1e-9:
        return fallback
    return (b[0] - a[0]) / distance, (b[1] - a[1]) / distance


def z_seed(base: Point, target: Point, lengths: Sequence[float]) -> list[Point]:
    """Build an alternating Z seed aligned with the base-to-target direction."""
    direction = _unit(base, target)
    perpendicular = (-direction[1], direction[0])
    forward = 0.58
    sideways = math.sqrt(1.0 - forward * forward)
    points = [base]
    for index, length in enumerate(lengths):
        side = sideways if index % 2 == 0 else -sideways
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
    iterations: int = 24,
    tolerance: float = 0.15,
) -> list[Point]:
    """Solve a fixed-base three-link chain while retaining its Z bend branch."""
    if len(lengths) != 3 or any(length <= 0 for length in lengths):
        raise ValueError("three positive link lengths are required")

    total = sum(lengths)
    target_distance = _distance(base, target)
    if target_distance >= total:
        direction = _unit(base, target)
        points = [base]
        for length in lengths:
            points.append(_point_at(points[-1], direction, length))
        return points

    # Hold the tool at a shallow up-right angle, then solve the first two
    # circles for the right-handed elbow. This makes the preferred branch a
    # clear /\/ silhouette instead of letting an unconstrained solver relax
    # the final link toward vertical.
    tool_angle = math.radians(28.0)
    tool_direction = (math.sin(tool_angle), -math.cos(tool_angle))
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
        if seed is not None and len(seed) == 4:
            elbow = min(elbows, key=lambda point: _distance(point, seed[1]))
        else:
            elbow = max(elbows, key=lambda point: point[0])
        return [base, elbow, wrist, target]

    points = list(seed) if seed is not None and len(seed) == 4 else z_seed(base, target, lengths)
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


def upper_workspace_target(pointer_x: float, pointer_y: float, width: float) -> Point:
    """Keep the end effector inside the upper workspace while tracking the pointer."""
    return min(max(pointer_x, 95.0), width - 95.0), min(max(pointer_y, 65.0), 145.0)


class RobotArmView:
    width = 360
    height = 410
    background = TRANSPARENT
    transparent_color = TRANSPARENT
    base: Point = (180.0, 374.0)
    lengths = (132.0, 122.0, 116.0)

    def __init__(self) -> None:
        self.canvas: tk.Canvas | None = None
        self.target: Point = (180.0, 72.0)
        self.joints = solve_three_link_z(self.base, self.target, self.lengths)
        self.link_ids: list[int] = []
        self.joint_ids: list[int] = []
        self.target_id: int | None = None
        self.gripper_ids: list[int] = []
        self.status_id: int | None = None
        self.accent = "#86a8e7"

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        canvas.create_text(20, 25, text="3-LINK / Z-IK", fill="#64748b", anchor="w", font=("Segoe UI", 9, "bold"))
        self.status_id = canvas.create_oval(326, 17, 340, 31, fill=self.accent, outline="")
        self.target_id = canvas.create_oval(0, 0, 0, 0, outline=self.accent, width=2, dash=(3, 3))
        for width in (18, 16, 14):
            self.link_ids.append(canvas.create_line(0, 0, 0, 0, fill="#334155", width=width, capstyle=tk.ROUND))
        for _ in range(4):
            self.joint_ids.append(canvas.create_oval(0, 0, 0, 0, fill="#e2e8f0", outline=self.accent, width=4))
        self.gripper_ids = [
            canvas.create_line(0, 0, 0, 0, fill=self.accent, width=5, capstyle=tk.ROUND),
            canvas.create_line(0, 0, 0, 0, fill=self.accent, width=5, capstyle=tk.ROUND),
        ]
        canvas.create_polygon(154, 390, 206, 390, 218, 404, 142, 404, fill="#1e293b", outline=self.accent, width=3)
        self._draw()

    def apply_state(self, state: OverlayState) -> None:
        self.accent, _ = state.appearance
        if self.canvas is None:
            return
        if self.target_id is not None:
            self.canvas.itemconfigure(self.target_id, outline=self.accent)
        if self.status_id is not None:
            self.canvas.itemconfigure(self.status_id, fill=self.accent)
        for joint_id in self.joint_ids:
            self.canvas.itemconfigure(joint_id, outline=self.accent)
        for gripper_id in self.gripper_ids:
            self.canvas.itemconfigure(gripper_id, fill=self.accent)

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        local_target = upper_workspace_target(pointer_x - window_x, pointer_y - window_y, self.width)
        smoothing = 0.14
        self.target = (
            self.target[0] + (local_target[0] - self.target[0]) * smoothing,
            self.target[1] + (local_target[1] - self.target[1]) * smoothing,
        )
        self.joints = solve_three_link_z(self.base, self.target, self.lengths, seed=self.joints)
        self._draw()

    def _draw(self) -> None:
        if self.canvas is None:
            return
        for link_id, start, end in zip(self.link_ids, self.joints, self.joints[1:], strict=True):
            self.canvas.coords(link_id, *start, *end)
        for index, (joint_id, point) in enumerate(zip(self.joint_ids, self.joints, strict=True)):
            radius = 13 if index in (0, 3) else 11
            self.canvas.coords(joint_id, point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius)
        if self.target_id is not None:
            self.canvas.coords(self.target_id, self.target[0] - 19, self.target[1] - 19, self.target[0] + 19, self.target[1] + 19)
        end = self.joints[-1]
        previous = self.joints[-2]
        direction = _unit(previous, end)
        normal = (-direction[1], direction[0])
        wrist = _point_at(end, direction, 9)
        left = (wrist[0] + normal[0] * 13, wrist[1] + normal[1] * 13)
        right = (wrist[0] - normal[0] * 13, wrist[1] - normal[1] * 13)
        left_tip = _point_at(left, direction, 16)
        right_tip = _point_at(right, direction, 16)
        self.canvas.coords(self.gripper_ids[0], *wrist, *left, *left_tip)
        self.canvas.coords(self.gripper_ids[1], *wrist, *right, *right_tip)


def create_robot_arm(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, RobotArmView(), mode=mode, title="Engram 3-Link Robot Arm")
