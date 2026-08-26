"""UV-textured low-poly industrial robot arm with a 3D expression plane."""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..scene3d import Camera, Face3D, ProjectedPoint, Vec3, box_faces, lit_face_color, point_along, sphere_faces, tapered_prism_faces
from ..software_uv import TexturedFace3D, UVTextureAtlas, rasterize_texture_quad, rasterize_textured_face, textured_prism_faces
from .robot_arm import eyelid_polygon_points
from .robot_arm_3d import RobotArm3DView, cable_hardware_faces, first_link_accessory_faces, visible_eyelid_offsets

PLAIN_CABLE = "#0c0d0f"
PLAIN_TECH = "#34302b"
PLAIN_JOINT = "#25282c"

ExpressionQuad = tuple[Vec3, Vec3, Vec3, Vec3]


@dataclass(frozen=True)
class ExpressionPlaneLayers:
    """Rear-to-front planes that give the mechanical eye physical depth."""

    sclera: ExpressionQuad
    iris: ExpressionQuad
    pupil: ExpressionQuad
    eyelid: ExpressionQuad

    def ordered(self) -> tuple[ExpressionQuad, ...]:
        return self.sclera, self.iris, self.pupil, self.eyelid


def pod_axis(camera: Camera, eye: Vec3, wrist: Vec3) -> Vec3:
    """Keep the aperture mostly forward-facing while retaining a readable 3/4 body."""
    link_rear = (wrist - eye).normalized()
    camera_depth = camera.world_space(Vec3(0.0, 0.0, 1.0)).normalized()
    return (link_rear * 0.42 + camera_depth * 0.90).normalized(camera_depth)


def pod_faces_and_expression_plane(
    camera: Camera,
    eye: Vec3,
    wrist: Vec3,
) -> tuple[list[TexturedFace3D], ExpressionPlaneLayers]:
    """Build an open-front octagonal pod and a layered mechanical eye."""
    axis = pod_axis(camera, eye, wrist)
    camera_right = camera.world_space(Vec3(1.0, 0.0, 0.0)).normalized()
    side = (camera_right - axis * camera_right.dot(axis)).normalized(Vec3(1.0, 0.0, 0.0))
    up = axis.cross(side).normalized(Vec3(0.0, -1.0, 0.0))
    middle = eye + axis * 38.0
    rear = eye + axis * 94.0
    faces = textured_prism_faces(
        eye,
        middle,
        start_radius=36.0,
        end_radius=33.0,
        sides=8,
        side_cells=((0, 1), (1, 1), (2, 1), (3, 1)),
        cap_cells=((0, 3), (1, 3)),
        color="#d8d3c8",
        side=side,
        depth=up,
        include_start_cap=False,
        include_end_cap=False,
    )
    faces.extend(
        textured_prism_faces(
            middle,
            rear,
            start_radius=33.0,
            end_radius=17.0,
            sides=8,
            side_cells=((0, 2), (1, 2), (2, 2), (3, 2)),
            cap_cells=((1, 3), (2, 3)),
            color="#1b1e22",
            side=side,
            depth=up,
            include_start_cap=False,
            include_end_cap=True,
        )
    )
    radius = 29.0

    def plane_at(depth: float) -> ExpressionQuad:
        plane_center = eye + axis * depth
        return (
            plane_center - side * radius - up * radius,
            plane_center + side * radius - up * radius,
            plane_center + side * radius + up * radius,
            plane_center - side * radius + up * radius,
        )

    planes = ExpressionPlaneLayers(
        sclera=plane_at(2.8),
        iris=plane_at(1.0),
        pupil=plane_at(-0.6),
        eyelid=plane_at(-2.2),
    )
    return faces, planes


def v2_surface_faces(
    base: Vec3,
    joints: list[Vec3],
    camera: Camera,
) -> tuple[list[Face3D], ExpressionPlaneLayers]:
    """Build UV-unwrapped link shells and a low-poly terminal pod."""
    faces: list[Face3D] = box_faces(Vec3(0.0, -169.0, 0.0), Vec3(138.0, 18.0, 62.0), color="#d8d3c8")
    faces.extend(box_faces(Vec3(0.0, -155.0, 0.0), Vec3(92.0, 16.0, 48.0), color="#292622"))
    for root_x in (-38.0, 38.0):
        faces.extend(tapered_prism_faces(Vec3(root_x, -157.0, 0.0), base, start_radius=8.0, end_radius=10.0, color=PLAIN_CABLE))

    shell_widths = ((27.0, 22.0), (25.0, 20.0), (22.0, 17.0))
    for index, (start, end) in enumerate(zip(joints[:-1], joints[1:], strict=True)):
        faces.extend(
            textured_prism_faces(
                start,
                end,
                start_radius=11.5,
                end_radius=9.5,
                sides=4,
                side_cells=((0, 2), (1, 2), (2, 2), (3, 2)),
                cap_cells=((0, 3), (1, 3)),
                color="#111316",
            )
        )
        shell_start = point_along(start, end, 10.0)
        shell_inset = 72.0 if index == 2 else 15.0
        shell_end = point_along(end, start, shell_inset)
        start_width, end_width = shell_widths[index]
        texture_row = 1 if index == 2 else 0
        shell_axis = shell_end - shell_start
        # Two separated armor blocks leave a machinery reveal in the middle,
        # so the atlas reads as actual cladding rather than a thin dark line.
        shell_sections = ((0.0, 0.46), (0.54, 1.0))
        for section_index, (section_start, section_end) in enumerate(shell_sections):
            section_cells = tuple(
                ((column + section_index + index) % 4, texture_row)
                for column in range(4)
            )
            faces.extend(
                textured_prism_faces(
                    shell_start + shell_axis * section_start,
                    shell_start + shell_axis * section_end,
                    start_radius=start_width + (end_width - start_width) * section_start,
                    end_radius=start_width + (end_width - start_width) * section_end,
                    sides=4,
                    side_cells=section_cells,
                    cap_cells=((0, 3), (2, 3)),
                    color="#d8d3c8" if index == 2 else "#181a1d",
                )
            )
        axis = (end - start).normalized()
        side = axis.cross(Vec3(0.0, 0.0, 1.0)).normalized(Vec3(1.0, 0.0, 0.0))
        depth = side.cross(axis).normalized(Vec3(0.0, 0.0, 1.0))
        for rail_sign in (-1.0, 1.0):
            rail_offset = side * (rail_sign * (start_width + 3.0)) + depth * 4.0
            faces.extend(
                tapered_prism_faces(
                    point_along(start, end, 18.0) + rail_offset,
                    point_along(end, start, max(25.0, shell_inset)) + rail_offset * 0.72,
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
    pod_faces, expression_plane = pod_faces_and_expression_plane(camera, joints[-1], joints[-2])
    faces.extend(pod_faces)
    return faces, expression_plane


def render_expression_layers(view: RobotArm3DView, size: int = 72) -> tuple[Image.Image, ...]:
    """Render sclera, iris, pupil, and eyelids as independent RGBA textures."""
    layers = tuple(Image.new("RGBA", (size, size), (0, 0, 0, 0)) for _ in range(4))
    sclera, iris, pupil, eyelid = layers
    margin = 3
    ImageDraw.Draw(sclera).ellipse(
        (margin, margin, size - margin, size - margin),
        fill="#e7edf0",
        outline="#0f172a",
        width=4,
    )
    center_x = size * 0.5 + (view.expression_gaze[0] + view.mouse_gaze[0]) * 0.9
    center_y = size * 0.5 + (view.expression_gaze[1] + view.mouse_gaze[1]) * 0.9
    pulse = (math.sin(view.pulse_phase) + 1.0) * 0.5
    iris_x = (view.pupil_size[0] + pulse * 0.8) * 0.92
    iris_y = (view.pupil_size[1] + pulse * 0.8) * 0.92
    halo = 5.0 + pulse * 1.5
    iris_draw = ImageDraw.Draw(iris)
    iris_draw.ellipse(
        (center_x - iris_x - halo, center_y - iris_y - halo, center_x + iris_x + halo, center_y + iris_y + halo),
        fill=view.expression.color + "58",
    )
    iris_draw.ellipse(
        (center_x - iris_x, center_y - iris_y, center_x + iris_x, center_y + iris_y),
        fill=view.expression.color,
        outline="#082f49",
        width=max(2, round(view.pupil_outline_width)),
    )
    pupil_radius = max(4.2, min(iris_x, iris_y) * 0.34)
    pupil_draw = ImageDraw.Draw(pupil)
    pupil_draw.ellipse(
        (center_x - pupil_radius, center_y - pupil_radius, center_x + pupil_radius, center_y + pupil_radius),
        fill="#071018",
        outline="#d7f5ff",
        width=1,
    )
    pupil_draw.ellipse(
        (center_x - pupil_radius * 0.35, center_y - pupil_radius * 0.45, center_x + pupil_radius * 0.05, center_y - pupil_radius * 0.05),
        fill="#ffffffb8",
    )
    upper_y, lower_y = visible_eyelid_offsets(view.upper_y, view.lower_y)
    eyelid_draw = ImageDraw.Draw(eyelid)
    for points in (
        eyelid_polygon_points((0.0, 0.0), upper_y, view.upper_tilt, view.upper_peak, upper=True),
        eyelid_polygon_points((0.0, 0.0), lower_y, view.lower_tilt, view.lower_peak, upper=False),
    ):
        polygon = [(size * 0.5 + points[index], size * 0.5 + points[index + 1]) for index in range(0, len(points), 2)]
        eyelid_draw.polygon(polygon, fill="#475569", outline="#0f172a")
    eyelid_draw.ellipse((margin, margin, size - margin, size - margin), outline="#0f172a", width=4)
    return layers


def render_expression_texture(view: RobotArm3DView, size: int = 72) -> Image.Image:
    """Return a flattened preview while runtime rendering keeps the layers apart."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for layer in render_expression_layers(view, size):
        image.alpha_composite(layer)
    return image


class RobotArm3DV2View(RobotArm3DView):
    """V1 behavior rendered through a real low-poly UV pipeline."""

    DRAW_VECTOR_EYE = False

    def __init__(self) -> None:
        super().__init__()
        self.uv_atlas: UVTextureAtlas | None = None
        self.surface_image: Image.Image | None = None
        self.surface_photo: ImageTk.PhotoImage | None = None
        self.expression_plane: ExpressionPlaneLayers | None = None

    def mount(self, canvas: tk.Canvas) -> None:
        atlas_path = Path(__file__).parent / "assets" / "robot_arm_3d_v2" / "robot-uv-atlas-v2.png"
        self.uv_atlas = UVTextureAtlas(Image.open(atlas_path))
        super().mount(canvas)

    def _scene_faces(self) -> list[Face3D]:
        faces, self.expression_plane = v2_surface_faces(self.base, self.joints, self.camera)
        return faces

    def _begin_surface_frame(self) -> None:
        self.surface_image = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))

    def _draw_projected_face(self, face: Face3D, coordinates: tuple[float, ...], projected: tuple[object, ...] | None = None) -> None:
        if self.surface_image is None:
            return
        projected_points = tuple(point for point in (projected or ()) if isinstance(point, ProjectedPoint))
        if isinstance(face, TexturedFace3D) and self.uv_atlas is not None and len(projected_points) == len(face.vertices):
            rasterize_textured_face(self.surface_image, self.uv_atlas, face, projected_points)
            return
        points = [(coordinates[index], coordinates[index + 1]) for index in range(0, len(coordinates), 2)]
        ImageDraw.Draw(self.surface_image).polygon(points, fill=lit_face_color(face), outline=face.outline)

    def _end_surface_frame(self) -> None:
        if self.canvas is None or self.surface_image is None:
            return
        if self.expression_plane is not None:
            for plane, texture in zip(self.expression_plane.ordered(), render_expression_layers(self), strict=True):
                projected = tuple(self.camera.project(vertex) for vertex in plane)
                rasterize_texture_quad(self.surface_image, texture, projected)
        self.surface_photo = ImageTk.PhotoImage(self.surface_image, master=self.canvas)
        self.canvas.create_image(0, 0, image=self.surface_photo, anchor=tk.NW, tags=("scene3d",))


def create_robot_arm_3d_v2(transport: JsonlTransport, mode: str) -> TkOverlayHost:
    return TkOverlayHost(transport, RobotArm3DV2View(), mode=mode, title="Engram 3D Robot Arm V2")
