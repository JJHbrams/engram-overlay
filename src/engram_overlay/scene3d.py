"""Small dependency-free 3D scene primitives for transparent Tk overlays."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __truediv__(self, scalar: float) -> Vec3:
        if abs(scalar) <= 1e-12:
            raise ZeroDivisionError("cannot divide a Vec3 by zero")
        return self * (1.0 / scalar)

    def dot(self, other: Vec3) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    @property
    def length(self) -> float:
        return math.sqrt(self.dot(self))

    def normalized(self, fallback: Vec3 | None = None) -> Vec3:
        length = self.length
        if length <= 1e-9:
            return fallback or Vec3(0.0, 1.0, 0.0)
        return self / length


@dataclass(frozen=True)
class ProjectedPoint:
    x: float
    y: float
    depth: float
    scale: float


@dataclass(frozen=True)
class Face3D:
    vertices: tuple[Vec3, ...]
    color: str
    outline: str = "#263442"


@dataclass(frozen=True)
class Camera:
    center_x: float
    center_y: float
    yaw: float = -0.32
    pitch: float = -0.08
    focal_length: float = 650.0

    def camera_space(self, point: Vec3) -> Vec3:
        yaw_cos = math.cos(self.yaw)
        yaw_sin = math.sin(self.yaw)
        yaw_x = point.x * yaw_cos - point.z * yaw_sin
        yaw_z = point.x * yaw_sin + point.z * yaw_cos
        pitch_cos = math.cos(self.pitch)
        pitch_sin = math.sin(self.pitch)
        pitch_y = point.y * pitch_cos - yaw_z * pitch_sin
        pitch_z = point.y * pitch_sin + yaw_z * pitch_cos
        return Vec3(yaw_x, pitch_y, pitch_z)

    def world_space(self, point: Vec3) -> Vec3:
        """Transform a camera-space point back into world space."""
        pitch_cos = math.cos(self.pitch)
        pitch_sin = math.sin(self.pitch)
        world_y = point.y * pitch_cos + point.z * pitch_sin
        yaw_z = -point.y * pitch_sin + point.z * pitch_cos
        yaw_cos = math.cos(self.yaw)
        yaw_sin = math.sin(self.yaw)
        world_x = point.x * yaw_cos + yaw_z * yaw_sin
        world_z = -point.x * yaw_sin + yaw_z * yaw_cos
        return Vec3(world_x, world_y, world_z)

    def unproject(self, screen_x: float, screen_y: float, depth: float) -> Vec3:
        """Place a screen coordinate on a camera-space depth plane."""
        denominator = max(self.focal_length + depth, self.focal_length * 0.2)
        scale = self.focal_length / denominator
        camera_point = Vec3(
            (screen_x - self.center_x) / scale,
            (screen_y - self.center_y) / scale,
            depth,
        )
        return self.world_space(camera_point)

    def project(self, point: Vec3) -> ProjectedPoint:
        camera_point = self.camera_space(point)
        denominator = max(self.focal_length + camera_point.z, self.focal_length * 0.2)
        scale = self.focal_length / denominator
        return ProjectedPoint(
            self.center_x + camera_point.x * scale,
            self.center_y + camera_point.y * scale,
            camera_point.z,
            scale,
        )


def point_along(start: Vec3, end: Vec3, distance: float) -> Vec3:
    return start + (end - start).normalized() * distance


def _segment_frame(start: Vec3, end: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    axis = (end - start).normalized()
    reference = Vec3(0.0, 0.0, 1.0)
    if abs(axis.dot(reference)) > 0.92:
        reference = Vec3(1.0, 0.0, 0.0)
    side = axis.cross(reference).normalized(Vec3(1.0, 0.0, 0.0))
    depth = side.cross(axis).normalized(Vec3(0.0, 0.0, 1.0))
    return axis, side, depth


def tapered_prism_faces(
    start: Vec3,
    end: Vec3,
    *,
    start_radius: float,
    end_radius: float,
    color: str,
    outline: str = "#263442",
) -> list[Face3D]:
    """Create six quad faces for a box-like tapered link between two points."""
    _, side, depth = _segment_frame(start, end)
    starts = (
        start + side * start_radius + depth * start_radius,
        start - side * start_radius + depth * start_radius,
        start - side * start_radius - depth * start_radius,
        start + side * start_radius - depth * start_radius,
    )
    ends = (
        end + side * end_radius + depth * end_radius,
        end - side * end_radius + depth * end_radius,
        end - side * end_radius - depth * end_radius,
        end + side * end_radius - depth * end_radius,
    )
    faces = [Face3D(starts, color, outline), Face3D(tuple(reversed(ends)), color, outline)]
    for index in range(4):
        next_index = (index + 1) % 4
        faces.append(Face3D((starts[index], starts[next_index], ends[next_index], ends[index]), color, outline))
    return faces


def box_faces(center: Vec3, size: Vec3, *, color: str, outline: str = "#263442") -> list[Face3D]:
    """Create an axis-aligned box as six faces."""
    x, y, z = size.x * 0.5, size.y * 0.5, size.z * 0.5
    vertices = (
        Vec3(center.x - x, center.y - y, center.z - z),
        Vec3(center.x + x, center.y - y, center.z - z),
        Vec3(center.x + x, center.y + y, center.z - z),
        Vec3(center.x - x, center.y + y, center.z - z),
        Vec3(center.x - x, center.y - y, center.z + z),
        Vec3(center.x + x, center.y - y, center.z + z),
        Vec3(center.x + x, center.y + y, center.z + z),
        Vec3(center.x - x, center.y + y, center.z + z),
    )
    indices = ((0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7))
    return [Face3D(tuple(vertices[index] for index in face), color, outline) for face in indices]


def sphere_faces(
    center: Vec3,
    radius: float,
    *,
    color: str,
    rings: int = 5,
    segments: int = 10,
    z_scale: float = 1.0,
    outline: str = "#263442",
) -> list[Face3D]:
    """Create a low-poly UV sphere suitable for painter-sorted Canvas faces."""
    if rings < 3 or segments < 3:
        raise ValueError("sphere requires at least 3 rings and 3 segments")
    rows: list[list[Vec3]] = []
    for ring in range(rings + 1):
        latitude = -math.pi * 0.5 + math.pi * ring / rings
        row = []
        for segment in range(segments):
            longitude = 2.0 * math.pi * segment / segments
            row.append(
                Vec3(
                    center.x + radius * math.cos(latitude) * math.cos(longitude),
                    center.y + radius * math.sin(latitude),
                    center.z + radius * z_scale * math.cos(latitude) * math.sin(longitude),
                )
            )
        rows.append(row)
    faces: list[Face3D] = []
    for ring in range(rings):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append(
                Face3D(
                    (
                        rows[ring][segment],
                        rows[ring][next_segment],
                        rows[ring + 1][next_segment],
                        rows[ring + 1][segment],
                    ),
                    color,
                    outline,
                )
            )
    return faces


def face_normal(vertices: Sequence[Vec3]) -> Vec3:
    if len(vertices) < 3:
        return Vec3(0.0, 0.0, 1.0)
    return (vertices[1] - vertices[0]).cross(vertices[2] - vertices[0]).normalized(Vec3(0.0, 0.0, 1.0))


def shade_color(color: str, intensity: float) -> str:
    """Scale an RGB hex color without adding an external color dependency."""
    value = color.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB color, got {color!r}")
    intensity = min(max(intensity, 0.0), 1.4)
    channels = [min(int(round(int(value[index : index + 2], 16) * intensity)), 255) for index in (0, 2, 4)]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def lit_face_color(face: Face3D, light_direction: Vec3 = Vec3(-0.4, -0.7, -1.0)) -> str:
    normal = face_normal(face.vertices)
    light = light_direction.normalized()
    diffuse = abs(normal.dot(light))
    return shade_color(face.color, 0.48 + diffuse * 0.62)
