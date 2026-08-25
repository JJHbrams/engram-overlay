"""Texture-mapped industrial variant of the ceiling-mounted 3D robot arm."""

from __future__ import annotations

import math
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..scene3d import Face3D, Vec3, box_faces, face_normal, point_along, sphere_faces, tapered_prism_faces
from .robot_arm_3d import (
    RobotArm3DView,
    cable_hardware_faces,
    first_link_accessory_faces,
)

MATERIAL_BLACK = "#181a1d"
MATERIAL_WHITE = "#d8d3c8"
MATERIAL_CABLE = "#111316"
MATERIAL_TECH = "#292622"
PLAIN_CABLE = "#0c0d0f"
PLAIN_TECH = "#34302b"
PLAIN_JOINT = "#25282c"


@dataclass(frozen=True)
class AtlasRegion:
    left: float
    top: float
    right: float
    bottom: float


ATLAS_REGIONS = {
    MATERIAL_BLACK: AtlasRegion(0.0, 0.0, 0.5, 0.5),
    MATERIAL_WHITE: AtlasRegion(0.5, 0.0, 1.0, 0.5),
    MATERIAL_CABLE: AtlasRegion(0.0, 0.5, 0.5, 1.0),
    MATERIAL_TECH: AtlasRegion(0.5, 0.5, 1.0, 1.0),
}


def atlas_sample_coordinate(
    material: str,
    u: float,
    v: float,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Map local UV coordinates into one material quadrant without crossing its seam."""
    region = ATLAS_REGIONS[material]
    u = min(max(u, 0.0), 1.0)
    v = min(max(v, 0.0), 1.0)
    left = int(region.left * width)
    top = int(region.top * height)
    right = max(left, int(region.right * width) - 1)
    bottom = max(top, int(region.bottom * height) - 1)
    return round(left + (right - left) * u), round(top + (bottom - top) * v)


def is_chroma_green(pixel: tuple[int, int, int] | tuple[int, int, int, int]) -> bool:
    """Recognize the generated compositing green without touching amber details."""
    red, green, blue = pixel[:3]
    return green >= 135 and green > red * 1.35 and green > blue * 1.35


def rotation_frame_index(screen_angle: float, frame_count: int = 24) -> int:
    """Choose the nearest cached pod orientation for a screen-space link angle."""
    normalized = (screen_angle + 180.0) % 360.0
    return round(normalized / (360.0 / frame_count)) % frame_count


def prepare_end_effector_pod(source_path: Path, output_size: int = 144) -> Image.Image:
    """Chroma-key and recenter a generated 3/4 pod around its enclosed aperture."""
    source = Image.open(source_path).convert("RGBA")
    source.thumbnail((256, 256), Image.Resampling.LANCZOS)
    width, height = source.size
    pixels = source.load()
    chroma = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            if is_chroma_green(pixels[x, y]):
                chroma[y * width + x] = 1

    visited = bytearray(width * height)
    enclosed_components: list[tuple[int, float, float]] = []
    for start_index, is_green in enumerate(chroma):
        if not is_green or visited[start_index]:
            continue
        pending = deque([start_index])
        visited[start_index] = 1
        count = 0
        sum_x = 0.0
        sum_y = 0.0
        touches_edge = False
        while pending:
            index = pending.popleft()
            x = index % width
            y = index // width
            count += 1
            sum_x += x
            sum_y += y
            touches_edge = touches_edge or x in (0, width - 1) or y in (0, height - 1)
            for neighbor_x, neighbor_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not (0 <= neighbor_x < width and 0 <= neighbor_y < height):
                    continue
                neighbor = neighbor_y * width + neighbor_x
                if chroma[neighbor] and not visited[neighbor]:
                    visited[neighbor] = 1
                    pending.append(neighbor)
        if not touches_edge and count >= 24:
            enclosed_components.append((count, sum_x / count, sum_y / count))

    if enclosed_components:
        _, pivot_x, pivot_y = max(enclosed_components)
    else:
        pivot_x, pivot_y = width * 0.5, height * 0.62

    for y in range(height):
        for x in range(width):
            if chroma[y * width + x]:
                red, green, blue, _ = pixels[x, y]
                pixels[x, y] = red, green, blue, 0

    centered = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    offset = (round(width * 0.5 - pivot_x), round(height * 0.5 - pivot_y))
    centered.alpha_composite(source, dest=offset)
    return centered.resize((output_size, output_size), Image.Resampling.LANCZOS)


def v2_surface_faces(base: Vec3, joints: list[Vec3]) -> list[Face3D]:
    """Build the heavier layered body while retaining the v1 kinematic skeleton."""
    faces = box_faces(Vec3(0.0, -169.0, 0.0), Vec3(138.0, 18.0, 62.0), color=MATERIAL_WHITE)
    faces.extend(box_faces(Vec3(0.0, -155.0, 0.0), Vec3(92.0, 16.0, 48.0), color=MATERIAL_TECH))
    for root_x in (-38.0, 38.0):
        faces.extend(
            tapered_prism_faces(
                Vec3(root_x, -157.0, 0.0),
                base,
                start_radius=8.0,
                end_radius=10.0,
                color=PLAIN_CABLE,
            )
        )

    shell_widths = ((23.0, 18.0), (21.0, 16.0), (18.0, 13.0))
    for index, (start, end) in enumerate(zip(joints[:-1], joints[1:], strict=True)):
        axis = (end - start).normalized()
        side = axis.cross(Vec3(0.0, 0.0, 1.0)).normalized(Vec3(1.0, 0.0, 0.0))
        depth = side.cross(axis).normalized(Vec3(0.0, 0.0, 1.0))

        faces.extend(
            tapered_prism_faces(
                start,
                end,
                start_radius=10.0,
                end_radius=8.0,
                color=MATERIAL_CABLE,
            )
        )
        shell_start = point_along(start, end, 13.0)
        shell_end = point_along(end, start, 18.0)
        start_width, end_width = shell_widths[index]
        shell_material = MATERIAL_WHITE if index == 2 else MATERIAL_BLACK
        faces.extend(
            tapered_prism_faces(
                shell_start,
                shell_end,
                start_radius=start_width,
                end_radius=end_width,
                color=shell_material,
            )
        )

        # Two offset structural rails make the link read as a layered machine,
        # rather than one smooth low-poly bar.
        for rail_sign in (-1.0, 1.0):
            rail_offset = side * (rail_sign * (start_width + 3.0)) + depth * 4.0
            faces.extend(
                tapered_prism_faces(
                    point_along(start, end, 18.0) + rail_offset,
                    point_along(end, start, 25.0) + rail_offset * 0.72,
                    start_radius=3.4,
                    end_radius=2.8,
                    color=PLAIN_TECH,
                )
            )

        faces.extend(cable_hardware_faces(start, end, index=index))
        if index == 0:
            faces.extend(first_link_accessory_faces(start, end))

    for index, joint in enumerate(joints[:-1]):
        faces.extend(sphere_faces(joint, 16.0, color=PLAIN_JOINT, rings=4, segments=10, z_scale=0.82))
        if index > 0:
            faces.extend(sphere_faces(joint + Vec3(0.0, 0.0, -1.5), 7.0, color="#7f1d1d", rings=3, segments=8))
    return faces


class TextureAtlas:
    def __init__(self, image: tk.PhotoImage) -> None:
        self.image = image
        self.width = image.width()
        self.height = image.height()
        self._cache: dict[tuple[str, int, int, int], str] = {}

    def color(self, material: str, u: float, v: float, intensity: float) -> str:
        quantized = (material, round(u * 24.0), round(v * 24.0), round(intensity * 20.0))
        cached = self._cache.get(quantized)
        if cached is not None:
            return cached
        x, y = atlas_sample_coordinate(material, u, v, self.width, self.height)
        pixel = self.image.get(x, y)
        if isinstance(pixel, str):
            value = pixel.removeprefix("#")
            red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
        else:
            red, green, blue = pixel[:3]
        channels = (red, green, blue)
        color = "#" + "".join(f"{min(max(round(channel * intensity), 0), 255):02x}" for channel in channels)
        self._cache[quantized] = color
        return color


class RobotArm3DV2View(RobotArm3DView):
    """V1 behavior with stable sampled materials and a textured eye-head sprite."""

    EYE_VISUAL_SCALE = 0.68
    POD_FRAME_COUNT = 24

    def __init__(self) -> None:
        super().__init__()
        self.texture_atlas: TextureAtlas | None = None
        self.pod_frames: list[ImageTk.PhotoImage] = []

    def mount(self, canvas: tk.Canvas) -> None:
        atlas_path = Path(__file__).parent / "assets" / "robot_arm_3d_v2" / "industrial-material-atlas.png"
        self.texture_atlas = TextureAtlas(tk.PhotoImage(master=canvas, file=str(atlas_path)))
        pod_path = Path(__file__).parent / "assets" / "robot_arm_3d_v2" / "end-effector-pod-v2.png"
        centered_pod = prepare_end_effector_pod(pod_path)
        self.pod_frames = []
        for index in range(self.POD_FRAME_COUNT):
            screen_angle = -180.0 + index * (360.0 / self.POD_FRAME_COUNT)
            # The source pod points toward 12 o'clock. Pillow's positive
            # rotation is counter-clockwise, opposite the screen-angle sign.
            rotation = -screen_angle - 90.0
            rotated = centered_pod.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=False)
            self.pod_frames.append(ImageTk.PhotoImage(rotated, master=canvas))
        super().mount(canvas)

    def _scene_faces(self) -> list[Face3D]:
        return v2_surface_faces(self.base, self.joints)

    def _draw_projected_face(self, face: Face3D, coordinates: tuple[float, ...]) -> None:
        if self.canvas is None or self.texture_atlas is None or face.color not in ATLAS_REGIONS:
            super()._draw_projected_face(face, coordinates)
            return
        normal = face_normal(face.vertices)
        light = Vec3(-0.4, -0.7, -1.0).normalized()
        intensity = 0.48 + abs(normal.dot(light)) * 0.62
        centroid = sum(vertex.x * 0.017 + vertex.y * 0.011 + vertex.z * 0.023 for vertex in face.vertices)
        phase = abs(math.sin(centroid))
        # One stable atlas sample per face avoids the pseudo-UV mosaic that
        # crawled and split at every low-poly face boundary.
        sample_u = 0.16 + phase * 0.68
        sample_v = 0.18 + abs(math.cos(centroid * 0.73)) * 0.64
        fill = self.texture_atlas.color(face.color, sample_u, sample_v, intensity)
        self.canvas.create_polygon(
            *coordinates,
            fill=fill,
            outline=face.outline,
            width=1,
            tags=("scene3d",),
        )

    def _draw(self) -> None:
        super()._draw()
        if self.canvas is None or not self.pod_frames:
            return
        eye = self.camera.project(self.joints[-1])
        rear = self.camera.project(self.joints[-2])
        screen_angle = math.degrees(math.atan2(rear.y - eye.y, rear.x - eye.x))
        pod_frame = self.pod_frames[rotation_frame_index(screen_angle, self.POD_FRAME_COUNT)]
        self.canvas.create_image(
            eye.x,
            eye.y,
            image=pod_frame,
            anchor=tk.CENTER,
            tags=("scene3d",),
        )
        self.canvas.tag_lower("scene3d")


def create_robot_arm_3d_v2(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, RobotArm3DV2View(), mode=mode, title="Engram 3D Robot Arm V2")
