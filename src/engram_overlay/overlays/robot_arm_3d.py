"""Software-rendered 3D extension of the ceiling-mounted single-eye robot arm."""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from collections.abc import Sequence

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..scene3d import (
    Camera,
    Face3D,
    Vec3,
    box_faces,
    lit_face_color,
    point_along,
    sphere_faces,
    tapered_prism_faces,
)
from ..state import OverlayState
from .robot_arm import (
    EXPRESSIONS,
    EyeExpression,
    eyelid_polygon_points,
    expression_for_hint,
    tracked_gaze,
)

TRANSPARENT = "#010203"


def z_seed_3d(base: Vec3, target: Vec3, lengths: Sequence[float]) -> list[Vec3]:
    """Create an alternating depth-aware seed for the 3-link FABRIK solver."""
    forward = (target - base).normalized()
    side = forward.cross(Vec3(0.0, 0.0, 1.0)).normalized(Vec3(1.0, 0.0, 0.0))
    depth = side.cross(forward).normalized(Vec3(0.0, 0.0, 1.0))
    points = [base]
    for index, length in enumerate(lengths):
        direction = (
            forward * 0.66
            + side * (0.58 if index % 2 == 0 else -0.58)
            + depth * (0.28 if index != 1 else -0.28)
        ).normalized()
        points.append(points[-1] + direction * length)
    return points


def solve_three_link_3d(
    base: Vec3,
    target: Vec3,
    lengths: Sequence[float],
    *,
    seed: Sequence[Vec3] | None = None,
    iterations: int = 28,
    tolerance: float = 0.15,
) -> list[Vec3]:
    """Solve a fixed-base three-link chain in full XYZ space."""
    if len(lengths) != 3 or any(length <= 0.0 for length in lengths):
        raise ValueError("three positive link lengths are required")
    total_length = sum(lengths)
    target_distance = (target - base).length
    if target_distance >= total_length:
        direction = (target - base).normalized()
        points = [base]
        for length in lengths:
            points.append(points[-1] + direction * length)
        return points

    points = list(seed) if seed is not None and len(seed) == 4 else z_seed_3d(base, target, lengths)
    points[0] = base
    for _ in range(iterations):
        points[-1] = target
        for index in range(2, -1, -1):
            direction = (points[index] - points[index + 1]).normalized()
            points[index] = points[index + 1] + direction * lengths[index]

        points[0] = base
        for index, length in enumerate(lengths):
            direction = (points[index + 1] - points[index]).normalized()
            points[index + 1] = points[index] + direction * length

        if (points[-1] - target).length <= tolerance:
            break
    return points


def solve_z_posture_3d(
    base: Vec3,
    target: Vec3,
    lengths: Sequence[float],
    *,
    pole_hint: Vec3 = Vec3(1.0, 0.0, 0.0),
    tool_angle: float = math.radians(30.0),
) -> list[Vec3]:
    """Solve an exact 3D chain whose projected link bends alternate as a Z."""
    if len(lengths) != 3 or any(length <= 0.0 for length in lengths):
        raise ValueError("three positive link lengths are required")
    forward = (target - base).normalized()
    pole_axis = (pole_hint - forward * pole_hint.dot(forward)).normalized(Vec3(1.0, 0.0, 0.0))
    tool_direction = (forward * math.cos(tool_angle) + pole_axis * math.sin(tool_angle)).normalized()
    wrist = target - tool_direction * lengths[2]
    wrist_offset = wrist - base
    wrist_distance = wrist_offset.length
    minimum = abs(lengths[0] - lengths[1])
    maximum = lengths[0] + lengths[1]
    if not minimum < wrist_distance < maximum:
        return solve_three_link_3d(base, target, lengths)

    wrist_axis = wrist_offset.normalized()
    along = (lengths[0] ** 2 - lengths[1] ** 2 + wrist_distance**2) / (2.0 * wrist_distance)
    height = math.sqrt(max(lengths[0] ** 2 - along**2, 0.0))
    elbow_axis = (pole_axis - wrist_axis * pole_axis.dot(wrist_axis)).normalized(Vec3(0.0, 0.0, 1.0))
    elbow = base + wrist_axis * along + elbow_axis * height
    return [base, elbow, wrist, target]


def target_from_pointer(
    pointer_x: float,
    pointer_y: float,
    width: float,
    height: float,
    *,
    camera: Camera,
    depth: float,
) -> Vec3:
    """Unproject a pointer onto an independently selected camera-depth plane."""
    clamped_x = min(max(pointer_x, 55.0), width - 55.0)
    clamped_y = min(max(pointer_y, 250.0), min(height - 80.0, 350.0))
    return camera.unproject(clamped_x, clamped_y, depth)


def continuous_pole_hint(pointer_x: float, width: float, camera: Camera) -> Vec3:
    """Move the Z-posture pole through depth when crossing the screen center."""
    half_span = max(width * 0.5 - 55.0, 1.0)
    horizontal = min(max((pointer_x - width * 0.5) / half_span, -1.0), 1.0)
    depth = math.sqrt(max(1.0 - horizontal * horizontal, 0.0))
    camera_right = camera.world_space(Vec3(1.0, 0.0, 0.0)).normalized()
    camera_depth = camera.world_space(Vec3(0.0, 0.0, 1.0)).normalized()
    return (camera_right * horizontal + camera_depth * depth).normalized(camera_depth)


def depth_at_phase(phase: float) -> float:
    """Return a subtle non-rhythmic camera-depth drift rather than a scale pulse."""
    primary = math.sin(phase) * 0.72
    secondary = math.sin(phase * 0.43 + 1.1) * 0.28
    return (primary + secondary) * 30.0


def constrain_target_reach(base: Vec3, target: Vec3, lengths: Sequence[float], *, ratio: float = 0.90) -> Vec3:
    """Keep enough reach in reserve to avoid a fully extended singular chain."""
    if not 0.0 < ratio <= 1.0:
        raise ValueError("reach ratio must be in (0, 1]")
    offset = target - base
    maximum_distance = sum(lengths) * ratio
    if offset.length <= maximum_distance:
        return target
    return base + offset.normalized() * maximum_distance


def quadratic_curve(start: Vec3, control: Vec3, end: Vec3, *, steps: int = 6) -> list[Vec3]:
    """Sample a short service-loop curve for a cable section."""
    if steps < 2:
        raise ValueError("curve requires at least 2 steps")
    points: list[Vec3] = []
    for index in range(steps + 1):
        t = index / steps
        inverse = 1.0 - t
        points.append(start * (inverse * inverse) + control * (2.0 * inverse * t) + end * (t * t))
    return points


def _link_surface_frame(start: Vec3, end: Vec3) -> tuple[Vec3, Vec3]:
    axis = (end - start).normalized()
    surface = (Vec3(0.0, 0.0, 1.0) - axis * axis.dot(Vec3(0.0, 0.0, 1.0))).normalized(Vec3(1.0, 0.0, 0.0))
    lateral = axis.cross(surface).normalized(Vec3(1.0, 0.0, 0.0))
    return surface, lateral


def cable_decoration_paths(start: Vec3, end: Vec3, *, index: int) -> tuple[list[Vec3], list[Vec3], list[Vec3]]:
    """Build camera-projectable cable paths with a small service loop."""
    surface, lateral = _link_surface_frame(start, end)
    anchor_start = point_along(start, end, 15.0) + surface * 18.0
    anchor_end = point_along(end, start, 17.0) + surface * 17.0
    midpoint = (anchor_start + anchor_end) * 0.5
    control = midpoint + surface * (25.0 + index * 3.0) + lateral * (9.0 if index % 2 == 0 else -9.0)
    main_path = quadratic_curve(anchor_start, control, anchor_end, steps=6)
    signal_offset = lateral * 6.5
    warm_path = quadratic_curve(anchor_start + signal_offset, control + signal_offset, anchor_end + signal_offset, steps=6)
    cool_path = quadratic_curve(anchor_start - signal_offset, control - signal_offset, anchor_end - signal_offset, steps=6)
    return main_path, warm_path, cool_path


def cable_hardware_faces(start: Vec3, end: Vec3, *, index: int) -> list[Face3D]:
    """Build low-poly clamps and connectors for a projected cable bundle."""
    main_path, _, _ = cable_decoration_paths(start, end, index=index)
    faces: list[Face3D] = []
    for fraction in (0.22, 0.78):
        clamp_center = start + (end - start) * fraction
        clamp_half_length = 3.2
        axis = (end - start).normalized()
        faces.extend(
            tapered_prism_faces(
                clamp_center - axis * clamp_half_length,
                clamp_center + axis * clamp_half_length,
                start_radius=18.5,
                end_radius=18.5,
                color="#475569",
                outline="#0f172a",
            )
        )
    for connector in (main_path[0], main_path[-1]):
        faces.extend(box_faces(connector, Vec3(9.0, 8.0, 7.0), color="#334155", outline="#0f172a"))
    return faces


class RobotArm3DView:
    width = 360
    height = 430
    background = TRANSPARENT
    transparent_color = TRANSPARENT
    base = Vec3(0.0, -145.0, 0.0)
    lengths = (120.0, 105.0, 95.0)

    def __init__(self, *, rng: random.Random | None = None) -> None:
        self.canvas: tk.Canvas | None = None
        self.rng = rng or random.Random()
        self.camera = Camera(self.width * 0.5, 190.0, yaw=-0.38, pitch=-0.10, focal_length=650.0)
        self.depth_phase = 0.0
        self.target_depth = depth_at_phase(self.depth_phase)
        self.target = constrain_target_reach(
            self.base,
            target_from_pointer(
                self.width * 0.5,
                320.0,
                self.width,
                self.height,
                camera=self.camera,
                depth=self.target_depth,
            ),
            self.lengths,
        )
        self.posture_pole = continuous_pole_hint(self.width * 0.5, self.width, self.camera)
        self.joints = solve_z_posture_3d(
            self.base,
            self.target,
            self.lengths,
            pole_hint=self.posture_pole,
        )
        self.status_id: int | None = None
        self.expression = EXPRESSIONS[0]
        self.active_hint = "idle"
        self.random_expressions_enabled = True
        self.upper_y = self.expression.upper_y
        self.lower_y = self.expression.lower_y
        self.upper_tilt = self.expression.upper_tilt
        self.lower_tilt = self.expression.lower_tilt
        self.upper_peak = self.expression.upper_peak
        self.lower_peak = self.expression.lower_peak
        self.expression_gaze = self.expression.gaze
        self.mouse_gaze = (0.0, 0.0)
        self.pupil_size = self.expression.pupil_size
        self.pupil_outline_width = self.expression.pupil_outline_width
        self.pulse_phase = 0.0
        self.next_expression_at = time.monotonic() + self.rng.uniform(3.0, 5.5)

    def mount(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        canvas.create_text(18, 22, text="CEILING LINK / 3D", fill="#64748b", anchor="w", font=("Segoe UI", 9, "bold"))
        self.status_id = canvas.create_oval(326, 15, 340, 29, fill=self.expression.color, outline="")
        self._draw()

    def apply_state(self, state: OverlayState) -> None:
        hint = state.display_hint
        if hint == self.active_hint:
            return
        self.active_hint = hint
        expression = expression_for_hint(hint)
        now = time.monotonic()
        if expression is None:
            self.random_expressions_enabled = True
            self.next_expression_at = now
            return
        self.random_expressions_enabled = False
        self._set_expression(expression, now)

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        local_pointer = (pointer_x - window_x, pointer_y - window_y)
        self.depth_phase = (self.depth_phase + 0.009) % math.tau
        desired_depth = depth_at_phase(self.depth_phase)
        self.target_depth += (desired_depth - self.target_depth) * 0.08
        desired_target = constrain_target_reach(
            self.base,
            target_from_pointer(
                *local_pointer,
                self.width,
                self.height,
                camera=self.camera,
                depth=self.target_depth,
            ),
            self.lengths,
        )
        target_smoothing = 0.11
        self.target = self.target + (desired_target - self.target) * target_smoothing
        desired_pole = continuous_pole_hint(local_pointer[0], self.width, self.camera)
        self.posture_pole = (self.posture_pole * 0.86 + desired_pole * 0.14).normalized(desired_pole)
        self.joints = solve_z_posture_3d(
            self.base,
            self.target,
            self.lengths,
            pole_hint=self.posture_pole,
        )

        projected_eye = self.camera.project(self.joints[-1])
        desired_mouse_gaze = tracked_gaze(local_pointer, (projected_eye.x, projected_eye.y), max_x=7.0, max_y=5.0)
        gaze_smoothing = 0.16
        self.mouse_gaze = (
            self.mouse_gaze[0] + (desired_mouse_gaze[0] - self.mouse_gaze[0]) * gaze_smoothing,
            self.mouse_gaze[1] + (desired_mouse_gaze[1] - self.mouse_gaze[1]) * gaze_smoothing,
        )

        now = time.monotonic()
        if self.random_expressions_enabled and now >= self.next_expression_at:
            choices = tuple(expression for expression in EXPRESSIONS if expression.name != self.expression.name)
            self._set_expression(self.rng.choice(choices), now)
        smoothing = 0.1
        for attribute in ("upper_y", "lower_y", "upper_tilt", "lower_tilt", "upper_peak", "lower_peak"):
            current = getattr(self, attribute)
            setattr(self, attribute, current + (getattr(self.expression, attribute) - current) * smoothing)
        self.expression_gaze = (
            self.expression_gaze[0] + (self.expression.gaze[0] - self.expression_gaze[0]) * smoothing,
            self.expression_gaze[1] + (self.expression.gaze[1] - self.expression_gaze[1]) * smoothing,
        )
        self.pupil_size = (
            self.pupil_size[0] + (self.expression.pupil_size[0] - self.pupil_size[0]) * smoothing,
            self.pupil_size[1] + (self.expression.pupil_size[1] - self.pupil_size[1]) * smoothing,
        )
        self.pupil_outline_width += (self.expression.pupil_outline_width - self.pupil_outline_width) * smoothing
        self.pulse_phase += 0.055 * self.expression.pulse_speed
        self._draw()

    def _set_expression(self, expression: EyeExpression, now: float) -> None:
        self.expression = expression
        self.next_expression_at = now + self.rng.uniform(3.0, 5.5)
        if self.canvas is not None and self.status_id is not None:
            self.canvas.itemconfigure(self.status_id, fill=expression.color)

    def _scene_faces(self) -> list[Face3D]:
        faces = box_faces(Vec3(0.0, -169.0, 0.0), Vec3(132.0, 18.0, 58.0), color="#e7e5df")
        faces.extend(
            tapered_prism_faces(
                Vec3(-38.0, -160.0, -12.0), self.base, start_radius=6.0, end_radius=8.0, color="#475569"
            )
        )
        faces.extend(
            tapered_prism_faces(
                Vec3(38.0, -160.0, 12.0), self.base, start_radius=6.0, end_radius=8.0, color="#475569"
            )
        )
        shell_widths = ((17.0, 13.0), (16.0, 12.0), (15.0, 11.0))
        for index, (start, end) in enumerate(zip(self.joints[:-1], self.joints[1:], strict=True)):
            faces.extend(tapered_prism_faces(start, end, start_radius=8.0, end_radius=7.0, color="#273444"))
            shell_start = point_along(start, end, 16.0)
            shell_end = point_along(end, start, 21.0)
            start_width, end_width = shell_widths[index]
            faces.extend(
                tapered_prism_faces(
                    shell_start,
                    shell_end,
                    start_radius=start_width,
                    end_radius=end_width,
                    color="#e7e5df",
                )
            )
            faces.extend(cable_hardware_faces(start, end, index=index))
        for joint in self.joints[:-1]:
            faces.extend(sphere_faces(joint, 13.0, color="#64748b", rings=4, segments=8, z_scale=0.88))
        faces.extend(sphere_faces(self.joints[-1], 34.0, color="#d8d6cf", rings=5, segments=10, z_scale=0.72))
        return faces

    @staticmethod
    def _scaled_polygon(points: Sequence[float], center: tuple[float, float], scale: float) -> tuple[float, ...]:
        scaled: list[float] = []
        for index in range(0, len(points), 2):
            scaled.extend((center[0] + points[index] * scale, center[1] + points[index + 1] * scale))
        return tuple(scaled)

    def _draw(self) -> None:
        if self.canvas is None:
            return
        self.canvas.delete("scene3d")
        projected_faces: list[tuple[float, Face3D, tuple[float, ...]]] = []
        for face in self._scene_faces():
            projected = tuple(self.camera.project(vertex) for vertex in face.vertices)
            coordinates = tuple(coordinate for point in projected for coordinate in (point.x, point.y))
            depth = sum(point.depth for point in projected) / len(projected)
            projected_faces.append((depth, face, coordinates))
        for _, face, coordinates in sorted(projected_faces, key=lambda item: item[0], reverse=True):
            self.canvas.create_polygon(
                *coordinates,
                fill=lit_face_color(face),
                outline=face.outline,
                width=1,
                tags=("scene3d",),
            )

        for index, (start, end) in enumerate(zip(self.joints[:-1], self.joints[1:], strict=True)):
            main_path, warm_path, cool_path = cable_decoration_paths(start, end, index=index)
            for path, color, base_width in (
                (main_path, "#020617", 9.0),
                (main_path, "#475569", 5.4),
                (warm_path, "#f59e0b", 2.8),
                (cool_path, "#22d3ee", 2.4),
            ):
                projected_path = tuple(self.camera.project(point) for point in path)
                coordinates = tuple(coordinate for point in projected_path for coordinate in (point.x, point.y))
                average_scale = sum(point.scale for point in projected_path) / len(projected_path)
                self.canvas.create_line(
                    *coordinates,
                    fill=color,
                    width=max(1.5, base_width * average_scale),
                    smooth=True,
                    splinesteps=12,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    tags=("scene3d",),
                )
            for path, color in ((warm_path, "#f59e0b"), (cool_path, "#22d3ee")):
                for endpoint in (path[0], path[-1]):
                    projected_endpoint = self.camera.project(endpoint)
                    radius = max(2.0, 2.6 * projected_endpoint.scale)
                    self.canvas.create_oval(
                        projected_endpoint.x - radius,
                        projected_endpoint.y - radius,
                        projected_endpoint.x + radius,
                        projected_endpoint.y + radius,
                        fill=color,
                        outline="#0f172a",
                        width=1,
                        tags=("scene3d",),
                    )

        eye = self.camera.project(self.joints[-1])
        center = (eye.x, eye.y)
        scale = eye.scale
        radius = 30.0 * scale
        self.canvas.create_oval(
            center[0] - radius,
            center[1] - radius,
            center[0] + radius,
            center[1] + radius,
            fill="#f8fafc",
            outline="#0f172a",
            width=max(2.0, 4.0 * scale),
            tags=("scene3d",),
        )
        pupil = (
            center[0] + (self.expression_gaze[0] + self.mouse_gaze[0]) * scale,
            center[1] + (self.expression_gaze[1] + self.mouse_gaze[1]) * scale,
        )
        pulse = (math.sin(self.pulse_phase) + 1.0) * 0.5
        pupil_x = (self.pupil_size[0] + pulse * 0.8) * scale
        pupil_y = (self.pupil_size[1] + pulse * 0.8) * scale
        halo_x = pupil_x + (5.0 + pulse * 1.5) * scale
        halo_y = pupil_y + (5.0 + pulse * 1.5) * scale
        self.canvas.create_oval(
            pupil[0] - halo_x,
            pupil[1] - halo_y,
            pupil[0] + halo_x,
            pupil[1] + halo_y,
            fill=self.expression.color,
            outline="",
            stipple="gray50",
            tags=("scene3d",),
        )
        self.canvas.create_oval(
            pupil[0] - pupil_x,
            pupil[1] - pupil_y,
            pupil[0] + pupil_x,
            pupil[1] + pupil_y,
            fill=self.expression.color,
            outline="#082f49",
            width=max(2.0, self.pupil_outline_width * scale),
            tags=("scene3d",),
        )
        iris_base = max(pupil_x, pupil_y)
        for index, dash in enumerate(((3, 3), (3, 6), (1, 8))):
            ring_radius = iris_base + (2.0 + index * 3.0 + pulse * (0.35 + index * 0.2)) * scale
            self.canvas.create_oval(
                pupil[0] - ring_radius,
                pupil[1] - ring_radius,
                pupil[0] + ring_radius,
                pupil[1] + ring_radius,
                outline=self.expression.color,
                width=2 if index == 0 else 1,
                dash=dash,
                tags=("scene3d",),
            )
        upper = eyelid_polygon_points((0.0, 0.0), self.upper_y, self.upper_tilt, self.upper_peak, upper=True)
        lower = eyelid_polygon_points((0.0, 0.0), self.lower_y, self.lower_tilt, self.lower_peak, upper=False)
        for points in (upper, lower):
            self.canvas.create_polygon(
                *self._scaled_polygon(points, center, scale),
                fill="#64748b",
                outline="#0f172a",
                width=max(2.0, 3.0 * scale),
                joinstyle=tk.ROUND,
                tags=("scene3d",),
            )
        self.canvas.create_oval(
            center[0] - radius,
            center[1] - radius,
            center[0] + radius,
            center[1] + radius,
            fill="",
            outline="#0f172a",
            width=max(2.0, 4.0 * scale),
            tags=("scene3d",),
        )

        self.canvas.tag_lower("scene3d")


def create_robot_arm_3d(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, RobotArm3DView(), mode=mode, title="Engram 3D Robot Arm")
