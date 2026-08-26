"""Small Pillow UV rasterizer for low-poly overlay meshes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageEnhance

from .scene3d import Face3D, ProjectedPoint, Vec3, face_normal


@dataclass(frozen=True)
class TexturedFace3D(Face3D):
    uvs: tuple[tuple[float, float], ...] = ()


def atlas_cell_uv(column: int, row: int, *, columns: int = 4, rows: int = 4) -> tuple[tuple[float, float], ...]:
    """Return a padded clockwise UV quad inside one atlas cell."""
    padding_u = 1.5 / (columns * 256.0)
    padding_v = 1.5 / (rows * 256.0)
    left = column / columns + padding_u
    right = (column + 1) / columns - padding_u
    top = row / rows + padding_v
    bottom = (row + 1) / rows - padding_v
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def _segment_frame(start: Vec3, end: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    axis = (end - start).normalized()
    reference = Vec3(0.0, 0.0, 1.0)
    if abs(axis.dot(reference)) > 0.92:
        reference = Vec3(1.0, 0.0, 0.0)
    side = axis.cross(reference).normalized(Vec3(1.0, 0.0, 0.0))
    depth = side.cross(axis).normalized(Vec3(0.0, 0.0, 1.0))
    return axis, side, depth


def textured_prism_faces(
    start: Vec3,
    end: Vec3,
    *,
    start_radius: float,
    end_radius: float,
    side_cells: tuple[tuple[int, int], ...],
    cap_cells: tuple[tuple[int, int], tuple[int, int]],
    sides: int = 4,
    color: str = "#30343a",
    outline: str = "#111827",
    side: Vec3 | None = None,
    depth: Vec3 | None = None,
    include_start_cap: bool = True,
    include_end_cap: bool = True,
) -> list[TexturedFace3D]:
    """Build a prism whose every face owns a stable UV island."""
    if sides < 3:
        raise ValueError("textured prism requires at least three sides")
    if not side or not depth:
        _, side, depth = _segment_frame(start, end)
    starts: list[Vec3] = []
    ends: list[Vec3] = []
    for index in range(sides):
        angle = math.tau * index / sides - math.pi * 0.25
        radial = side * math.cos(angle) + depth * math.sin(angle)
        starts.append(start + radial * start_radius)
        ends.append(end + radial * end_radius)

    faces: list[TexturedFace3D] = []
    for index in range(sides):
        next_index = (index + 1) % sides
        cell = side_cells[index % len(side_cells)]
        faces.append(
            TexturedFace3D(
                vertices=(starts[index], starts[next_index], ends[next_index], ends[index]),
                color=color,
                outline=outline,
                uvs=atlas_cell_uv(*cell),
            )
        )

    caps = []
    if include_start_cap:
        caps.append((starts, cap_cells[0], True))
    if include_end_cap:
        caps.append((ends, cap_cells[1], False))
    for ring, cell, reverse in caps:
        vertices = tuple(reversed(ring)) if reverse else tuple(ring)
        region = atlas_cell_uv(*cell)
        left, top = region[0]
        right, bottom = region[2]
        cap_uvs = []
        for vertex_index in range(sides):
            angle = math.tau * vertex_index / sides - math.pi * 0.25
            cap_uvs.append(
                (
                    (left + right) * 0.5 + math.cos(angle) * (right - left) * 0.48,
                    (top + bottom) * 0.5 + math.sin(angle) * (bottom - top) * 0.48,
                )
            )
        if reverse:
            cap_uvs.reverse()
        faces.append(TexturedFace3D(vertices=vertices, color=color, outline=outline, uvs=tuple(cap_uvs)))
    return faces


class UVTextureAtlas:
    def __init__(self, image: Image.Image, *, max_size: int = 256) -> None:
        atlas = image.convert("RGB")
        atlas.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        self.image = atlas
        self._shaded: dict[int, Image.Image] = {}

    def shaded(self, intensity: float) -> Image.Image:
        bucket = min(max(round(intensity * 16.0), 5), 22)
        cached = self._shaded.get(bucket)
        if cached is None:
            cached = ImageEnhance.Brightness(self.image).enhance(bucket / 16.0)
            self._shaded[bucket] = cached
        return cached


def rasterize_textured_face(
    target: Image.Image,
    atlas: UVTextureAtlas,
    face: TexturedFace3D,
    projected: tuple[ProjectedPoint, ...],
    *,
    light_direction: Vec3 = Vec3(-0.4, -0.7, -1.0),
) -> None:
    normal = face_normal(face.vertices)
    intensity = 0.48 + abs(normal.dot(light_direction.normalized())) * 0.62
    texture = atlas.shaded(intensity)
    if len(projected) == 4:
        source_points = tuple((uv[0] * (texture.width - 1), uv[1] * (texture.height - 1)) for uv in face.uvs)
        _warp_quad(target, texture, projected, source_points)
    else:
        center_u = sum(uv[0] for uv in face.uvs) / len(face.uvs)
        center_v = sum(uv[1] for uv in face.uvs) / len(face.uvs)
        fill = texture.getpixel((round(center_u * (texture.width - 1)), round(center_v * (texture.height - 1))))
        ImageDraw.Draw(target).polygon([(point.x, point.y) for point in projected], fill=fill + (255,))
    draw = ImageDraw.Draw(target)
    outline = [(round(point.x), round(point.y)) for point in projected]
    if outline:
        draw.line([*outline, outline[0]], fill=face.outline, width=1)


def rasterize_texture_quad(
    target: Image.Image,
    texture: Image.Image,
    projected: tuple[ProjectedPoint, ProjectedPoint, ProjectedPoint, ProjectedPoint],
) -> None:
    source_points = (
        (0.0, 0.0),
        (texture.width - 1.0, 0.0),
        (texture.width - 1.0, texture.height - 1.0),
        (0.0, texture.height - 1.0),
    )
    _warp_quad(target, texture, projected, source_points)


def _warp_quad(
    target: Image.Image,
    texture: Image.Image,
    points: tuple[ProjectedPoint, ProjectedPoint, ProjectedPoint, ProjectedPoint],
    source_points: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
) -> None:
    min_x = max(0, math.floor(min(point.x for point in points)))
    max_x = min(target.width, math.ceil(max(point.x for point in points)) + 1)
    min_y = max(0, math.floor(min(point.y for point in points)))
    max_y = min(target.height, math.ceil(max(point.y for point in points)) + 1)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 1 or height <= 1:
        return
    destination_points = tuple((point.x - min_x, point.y - min_y) for point in points)
    coefficients = _perspective_coefficients(destination_points, source_points)
    if coefficients is None:
        return
    warped = texture.transform(
        (width, height),
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BILINEAR,
    ).convert("RGBA")
    polygon_mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(polygon_mask).polygon(destination_points, fill=255)
    if texture.mode == "RGBA":
        polygon_mask = ImageChops.multiply(polygon_mask, warped.getchannel("A"))
    warped.putalpha(polygon_mask)
    target.alpha_composite(warped, dest=(min_x, min_y))


def _perspective_coefficients(
    destination: tuple[tuple[float, float], ...],
    source: tuple[tuple[float, float], ...],
) -> tuple[float, ...] | None:
    matrix: list[list[float]] = []
    for (x, y), (u, v) in zip(destination, source, strict=True):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, u])
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, v])
    for column in range(8):
        pivot = max(range(column, 8), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-9:
            return None
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(8):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [current - factor * pivot_value for current, pivot_value in zip(matrix[row], matrix[column], strict=True)]
    return tuple(matrix[row][8] for row in range(8))
