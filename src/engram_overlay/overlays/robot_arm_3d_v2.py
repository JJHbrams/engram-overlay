"""UV-textured low-poly industrial robot arm with a 3D expression plane."""

from __future__ import annotations

import ctypes
import math
import sys
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from ..scene3d import Camera, Face3D, ProjectedPoint, Vec3, box_faces, lit_face_color, point_along, sphere_faces, tapered_prism_faces
from ..software_uv import TexturedFace3D, UVTextureAtlas, atlas_cell_uv, rasterize_texture_quad, rasterize_textured_face, textured_prism_faces
from .robot_arm import eyelid_polygon_points
from .robot_arm_3d import TRANSPARENT, RobotArm3DView, cable_hardware_faces, first_link_accessory_faces, visible_eyelid_offsets

PLAIN_CABLE = "#0c0d0f"
PLAIN_TECH = "#34302b"
PLAIN_JOINT = "#25282c"
POD_MIDDLE_DEPTH = 38.0
POD_REAR_DEPTH = 94.0
EYE_BASE_DEPTH = 0.0
EYE_IRIS_DEPTH = 2.4
EYE_PUPIL_DEPTH = -2.2

ExpressionQuad = tuple[Vec3, Vec3, Vec3, Vec3]


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    )


def _push_physical_dpi_context() -> int | None:
    if sys.platform != "win32":
        return None
    setter = getattr(ctypes.windll.user32, "SetThreadDpiAwarenessContext", None)
    if setter is None:
        return None
    setter.argtypes = (ctypes.c_void_p,)
    setter.restype = ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))
    return int(previous) if previous else None


def _pop_dpi_context(previous: int | None) -> None:
    if previous is None or sys.platform != "win32":
        return
    setter = ctypes.windll.user32.SetThreadDpiAwarenessContext
    setter(ctypes.c_void_p(previous))


def enable_per_monitor_dpi_awareness() -> bool:
    """Use one physical-pixel coordinate space across mixed-DPI displays."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    thread_setter = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if thread_setter is not None:
        thread_setter.argtypes = (ctypes.c_void_p,)
        thread_setter.restype = ctypes.c_void_p
        if thread_setter(ctypes.c_void_p(-4)):
            return True
    process_setter = getattr(user32, "SetProcessDpiAwarenessContext", None)
    if process_setter is None:
        return False
    process_setter.argtypes = (ctypes.c_void_p,)
    process_setter.restype = wintypes.BOOL
    return bool(process_setter(ctypes.c_void_p(-4)))


@dataclass(frozen=True)
class ExpressionPlaneLayers:
    """Render planes that give the iris and pupil restrained physical depth."""

    sclera: ExpressionQuad
    iris: ExpressionQuad
    pupil: ExpressionQuad
    eyelid: ExpressionQuad

    def ordered(self) -> tuple[ExpressionQuad, ...]:
        return self.iris, self.sclera, self.pupil, self.eyelid


def pod_axis(camera: Camera, eye: Vec3, wrist: Vec3) -> Vec3:
    """Keep the aperture mostly forward-facing while retaining a readable 3/4 body."""
    link_rear = (wrist - eye).normalized()
    camera_depth = camera.world_space(Vec3(0.0, 0.0, 1.0)).normalized()
    return (link_rear * 0.42 + camera_depth * 0.90).normalized(camera_depth)


def pod_attachment_point(camera: Camera, eye: Vec3, wrist: Vec3) -> Vec3:
    """Return the rear mechanical socket; the aperture remains at ``eye``."""
    return eye + pod_axis(camera, eye, wrist) * POD_REAR_DEPTH


def visual_link_joints(joints: list[Vec3], camera: Camera) -> list[Vec3]:
    """Route only the rendered terminal link into the pod's rear socket."""
    rendered = list(joints)
    rendered[-1] = pod_attachment_point(camera, joints[-1], joints[-2])
    return rendered


def joint_point_texture_face(joint: Vec3, camera: Camera, *, index: int) -> TexturedFace3D:
    """Map a circular atlas mechanism onto the camera-facing joint cap."""
    camera_depth = camera.world_space(Vec3(0.0, 0.0, 1.0)).normalized()
    camera_right = camera.world_space(Vec3(1.0, 0.0, 0.0)).normalized()
    camera_up = camera.world_space(Vec3(0.0, 1.0, 0.0)).normalized()
    center = joint - camera_depth * 15.2
    radius = 14.2
    joint_cells = ((3, 1), (1, 1), (3, 1))
    return TexturedFace3D(
        vertices=(
            center - camera_right * radius - camera_up * radius,
            center + camera_right * radius - camera_up * radius,
            center + camera_right * radius + camera_up * radius,
            center - camera_right * radius + camera_up * radius,
        ),
        color="#26292d",
        outline="#111318",
        uvs=atlas_cell_uv(*joint_cells[index % len(joint_cells)]),
    )


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
    middle = eye + axis * POD_MIDDLE_DEPTH
    rear = pod_attachment_point(camera, eye, wrist)
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
        sclera=plane_at(EYE_BASE_DEPTH),
        iris=plane_at(EYE_IRIS_DEPTH),
        pupil=plane_at(EYE_PUPIL_DEPTH),
        eyelid=plane_at(EYE_BASE_DEPTH),
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
    rendered_joints = visual_link_joints(joints, camera)
    for index, (start, end) in enumerate(zip(rendered_joints[:-1], rendered_joints[1:], strict=True)):
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
        shell_inset = 12.0 if index == 2 else 15.0
        shell_end = point_along(end, start, shell_inset)
        start_width, end_width = shell_widths[index]
        texture_row = 1 if index == 2 else 0
        shell_axis = shell_end - shell_start
        # Two separated armor blocks leave a machinery reveal in the middle,
        # so the atlas reads as actual cladding rather than a thin dark line.
        shell_sections = ((0.0, 0.46), (0.54, 1.0))
        for section_index, (section_start, section_end) in enumerate(shell_sections):
            section_cells = []
            for column in range(4):
                point_panel = index < 2 and section_index == 1 and column % 2 == index % 2
                cell_row = 1 if point_panel else texture_row
                section_cells.append(((column + section_index + index) % 4, cell_row))
            faces.extend(
                textured_prism_faces(
                    shell_start + shell_axis * section_start,
                    shell_start + shell_axis * section_end,
                    start_radius=start_width + (end_width - start_width) * section_start,
                    end_radius=start_width + (end_width - start_width) * section_end,
                    sides=4,
                    side_cells=tuple(section_cells),
                    cap_cells=((0, 3), (2, 3)),
                    color="#d8d3c8" if index == 2 else "#181a1d",
                )
            )
        axis = (end - start).normalized()
        side = axis.cross(Vec3(0.0, 0.0, 1.0)).normalized(Vec3(1.0, 0.0, 0.0))
        depth = side.cross(axis).normalized(Vec3(0.0, 0.0, 1.0))
        for rail_sign in (-1.0, 1.0):
            rail_offset = side * (rail_sign * (start_width + 3.0)) + depth * 4.0
            rail_inset = 10.0 if index == 2 else max(25.0, shell_inset)
            faces.extend(
                tapered_prism_faces(
                    point_along(start, end, 18.0) + rail_offset,
                    point_along(end, start, rail_inset) + rail_offset * 0.72,
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
        faces.append(joint_point_texture_face(joint, camera, index=index))
    pod_faces, expression_plane = pod_faces_and_expression_plane(camera, joints[-1], joints[-2])
    faces.extend(pod_faces)
    return faces, expression_plane


def render_expression_layers(view: RobotArm3DView, size: int = 72) -> tuple[Image.Image, ...]:
    """Render backlight, annular base, camera lens, and eyelids back-to-front."""
    layers = tuple(Image.new("RGBA", (size, size), (0, 0, 0, 0)) for _ in range(4))
    sclera, iris, pupil, eyelid = layers
    margin = 3
    base_draw = ImageDraw.Draw(sclera)
    base_draw.ellipse(
        (margin, margin, size - margin, size - margin),
        fill="#e7edf0",
        outline="#0f172a",
        width=4,
    )
    aperture_radius = size * 0.32
    base_draw.ellipse(
        (size * 0.5 - aperture_radius, size * 0.5 - aperture_radius, size * 0.5 + aperture_radius, size * 0.5 + aperture_radius),
        fill=(0, 0, 0, 0),
        outline="#334155",
        width=3,
    )
    if getattr(view, "pointer_tracking_active", False):
        gaze_x, gaze_y = view.mouse_gaze
    else:
        gaze_x = view.expression_gaze[0] + view.mouse_gaze[0]
        gaze_y = view.expression_gaze[1] + view.mouse_gaze[1]
    center_x = size * 0.5 + gaze_x * 0.9
    center_y = size * 0.5 + gaze_y * 0.9
    pulse = (math.sin(view.pulse_phase) + 1.0) * 0.5
    iris_x = (view.pupil_size[0] + pulse * 0.8) * 0.92
    iris_y = (view.pupil_size[1] + pulse * 0.8) * 0.92
    halo = 5.0 + pulse * 1.5
    iris_draw = ImageDraw.Draw(iris)
    backing_radius = aperture_radius + 4.0
    iris_draw.ellipse(
        (size * 0.5 - backing_radius, size * 0.5 - backing_radius, size * 0.5 + backing_radius, size * 0.5 + backing_radius),
        fill="#071018",
        outline="#1e293b",
        width=2,
    )
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
    gaze_angle = math.atan2(gaze_y, gaze_x) if abs(gaze_x) + abs(gaze_y) > 0.05 else 0.0
    reticle_base = max(iris_x, iris_y)
    reticle_phase = math.degrees(gaze_angle * 0.18 + view.pulse_phase * 0.025)
    reticle_patterns = ((16.0, 12.0), (10.0, 17.0), (5.0, 22.0))
    for ring_index, (arc_length, gap_length) in enumerate(reticle_patterns):
        ring_radius = reticle_base + 2.0 + ring_index * 3.0 + pulse * (0.35 + ring_index * 0.2)
        step = arc_length + gap_length
        angle = reticle_phase + ring_index * 11.0
        while angle < reticle_phase + 360.0:
            iris_draw.arc(
                (center_x - ring_radius, center_y - ring_radius, center_x + ring_radius, center_y + ring_radius),
                start=angle,
                end=angle + arc_length,
                fill=view.expression.color + ("e0" if ring_index == 0 else "a8"),
                width=2 if ring_index == 0 else 1,
            )
            angle += step
    pupil_radius = max(4.2, min(iris_x, iris_y) * 0.34)
    pupil_draw = ImageDraw.Draw(pupil)
    pupil_draw.ellipse(
        (center_x - pupil_radius, center_y - pupil_radius, center_x + pupil_radius, center_y + pupil_radius),
        fill="#071018",
        outline="#d7f5ff",
        width=1,
    )
    lens_highlight_angle = gaze_angle * 0.12 - 2.25
    highlight_x = center_x + math.cos(lens_highlight_angle) * pupil_radius * 0.30
    highlight_y = center_y + math.sin(lens_highlight_angle) * pupil_radius * 0.30
    highlight_radius = pupil_radius * 0.24
    pupil_draw.ellipse(
        (highlight_x - highlight_radius, highlight_y - highlight_radius, highlight_x + highlight_radius, highlight_y + highlight_radius),
        fill="#ffffffc8",
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
    return iris, sclera, pupil, eyelid


def render_expression_texture(view: RobotArm3DView, size: int = 72) -> Image.Image:
    """Return a flattened preview while runtime rendering keeps the layers apart."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for layer in render_expression_layers(view, size):
        image.alpha_composite(layer)
    return image


def eye_emission_projection(
    view: RobotArm3DView,
    planes: ExpressionPlaneLayers,
    camera: Camera,
) -> tuple[ProjectedPoint, ProjectedPoint]:
    """Project the eye source and its gaze-biased forward ray."""
    aperture = planes.eyelid
    center = sum(aperture[1:], aperture[0]) * 0.25
    side = (aperture[1] - aperture[0]).normalized(Vec3(1.0, 0.0, 0.0))
    up = (aperture[3] - aperture[0]).normalized(Vec3(0.0, 1.0, 0.0))
    rear_normal = side.cross(up).normalized(Vec3(0.0, 0.0, 1.0))
    forward = rear_normal * -1.0
    if getattr(view, "pointer_tracking_active", False):
        gaze_x, gaze_y = view.mouse_gaze
    else:
        gaze_x = view.expression_gaze[0] + view.mouse_gaze[0]
        gaze_y = view.expression_gaze[1] + view.mouse_gaze[1]
    gaze_x = min(max(gaze_x, -7.0), 7.0)
    gaze_y = min(max(gaze_y, -5.0), 5.0)
    direction = (
        forward
        + side * (gaze_x / 7.0 * 0.38)
        + up * (gaze_y / 5.0 * 0.30)
    ).normalized(forward)
    return camera.project(center), camera.project(center + direction * 115.0)


def display_bounds_for_window(window: tk.Misc) -> tuple[int, int, int, int] | None:
    """Return the physical monitor containing a Tk top-level window."""
    if sys.platform != "win32":
        return None
    previous_context = _push_physical_dpi_context()
    try:
        user32 = ctypes.windll.user32
        window_id = window.winfo_id()
        root_hwnd = user32.GetParent(window_id) or window_id
        monitor = user32.MonitorFromWindow(root_hwnd, 2)
        if not monitor:
            return None
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcMonitor
        return rect.left, rect.top, rect.right, rect.bottom
    finally:
        _pop_dpi_context(previous_context)


def display_work_area_for_window(window: tk.Misc) -> tuple[int, int, int, int] | None:
    """Return the physical work area, excluding the monitor taskbar."""
    if sys.platform != "win32":
        return None
    previous_context = _push_physical_dpi_context()
    try:
        user32 = ctypes.windll.user32
        # Tk may expose an inner wrapper HWND whose owning monitor lags behind
        # after a cross-display drag. The physical window center is the stable
        # source of truth shared with our canvas pointer mapping.
        point = wintypes.POINT(
            round(window.winfo_rootx() + window.winfo_width() * 0.5),
            round(window.winfo_rooty() + window.winfo_height() * 0.5),
        )
        monitor_from_point = user32.MonitorFromPoint
        monitor_from_point.argtypes = (wintypes.POINT, wintypes.DWORD)
        monitor_from_point.restype = wintypes.HANDLE
        monitor = monitor_from_point(point, 2)
        if not monitor:
            return None
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcWork
        return rect.left, rect.top, rect.right, rect.bottom
    finally:
        _pop_dpi_context(previous_context)


def pointer_position_in_canvas(canvas: tk.Canvas) -> tuple[float, float]:
    """Read the physical cursor and map it into the canvas coordinate space."""
    if sys.platform != "win32":
        pointer_x, pointer_y = canvas.winfo_pointerxy()
        return pointer_x - canvas.winfo_rootx(), pointer_y - canvas.winfo_rooty()
    logical_width = max(canvas.winfo_width(), 1)
    logical_height = max(canvas.winfo_height(), 1)
    hwnd = canvas.winfo_id()
    point = wintypes.POINT()
    rect = wintypes.RECT()
    previous_context = _push_physical_dpi_context()
    try:
        user32 = ctypes.windll.user32
        if not user32.GetCursorPos(ctypes.byref(point)) or not user32.ScreenToClient(hwnd, ctypes.byref(point)):
            pointer_x, pointer_y = canvas.winfo_pointerxy()
            return pointer_x - canvas.winfo_rootx(), pointer_y - canvas.winfo_rooty()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return float(point.x), float(point.y)
        client_width = max(rect.right - rect.left, 1)
        client_height = max(rect.bottom - rect.top, 1)
        return point.x * logical_width / client_width, point.y * logical_height / client_height
    finally:
        _pop_dpi_context(previous_context)


def ray_to_display_edge(
    start: tuple[float, float],
    direction: tuple[float, float],
    width: float,
    height: float,
) -> tuple[float, float]:
    """Intersect a positive screen ray with the first display boundary."""
    start_x, start_y = start
    direction_x, direction_y = direction
    length = math.hypot(direction_x, direction_y)
    if length <= 1e-6:
        direction_x, direction_y, length = 0.0, 1.0, 1.0
    direction_x /= length
    direction_y /= length
    candidates: list[float] = []
    if direction_x > 1e-9:
        candidates.append((width - start_x) / direction_x)
    elif direction_x < -1e-9:
        candidates.append((0.0 - start_x) / direction_x)
    if direction_y > 1e-9:
        candidates.append((height - start_y) / direction_y)
    elif direction_y < -1e-9:
        candidates.append((0.0 - start_y) / direction_y)
    for distance in sorted(candidate for candidate in candidates if candidate >= 0.0):
        point = start_x + direction_x * distance, start_y + direction_y * distance
        if -1e-6 <= point[0] <= width + 1e-6 and -1e-6 <= point[1] <= height + 1e-6:
            return point
    return start


def emission_cone_polygons(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    pulse: float = 0.0,
) -> tuple[tuple[float, ...], ...]:
    """Build three nested field-of-view filters from the eye to screen edge."""
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    distance = max(math.hypot(delta_x, delta_y), 1.0)
    perpendicular_x = -delta_y / distance
    perpendicular_y = delta_x / distance
    direction_x = delta_x / distance
    direction_y = delta_y / distance
    far_width = min(max(distance * 0.22, 70.0), 420.0)
    near_width = 20.0 + pulse * 3.0
    polygons = []
    for scale in (1.0, 0.64, 0.34):
        scaled_near = near_width * scale
        scaled_far = far_width * scale
        cap_depth = min(scaled_far * 0.52, 120.0)
        far_arc: list[float] = []
        for index in range(9):
            t = -1.0 + index / 4.0
            inset = cap_depth * (1.0 - math.sqrt(max(0.0, 1.0 - t * t)))
            far_arc.extend(
                (
                    end[0] - direction_x * inset + perpendicular_x * scaled_far * t,
                    end[1] - direction_y * inset + perpendicular_y * scaled_far * t,
                )
            )
        polygons.append(
            (
                start[0] + perpendicular_x * scaled_near,
                start[1] + perpendicular_y * scaled_near,
                start[0] - perpendicular_x * scaled_near,
                start[1] - perpendicular_y * scaled_near,
                *far_arc,
            )
        )
    return tuple(polygons)


class EyeEmissionDisplay:
    """Click-through display-sized stipple filter behind the robot window."""

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.hwnd = 0
        self.origin_x = root.winfo_vrootx()
        self.origin_y = root.winfo_vrooty()
        self.width = root.winfo_vrootwidth() or root.winfo_screenwidth()
        self.height = root.winfo_vrootheight() or root.winfo_screenheight()
        self.bounds = (self.origin_x, self.origin_y, self.origin_x + self.width, self.origin_y + self.height)
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        try:
            self.window.attributes("-transparentcolor", TRANSPARENT)
            self.window.attributes("-alpha", 0.14)
        except tk.TclError:
            pass
        self.window.geometry(f"{self.width}x{self.height}{self.origin_x:+d}{self.origin_y:+d}")
        self.canvas = tk.Canvas(
            self.window,
            width=self.width,
            height=self.height,
            highlightthickness=0,
            borderwidth=0,
            bg=TRANSPARENT,
        )
        self.canvas.pack(fill="both", expand=True)
        self.window.deiconify()
        self.window.update_idletasks()
        self._make_click_through()
        self._position_display(restore_stack=True)

    def _position_display(self, *, restore_stack: bool = False) -> None:
        """Anchor the filter without churning the robot window's z-order."""
        if sys.platform == "win32" and self.hwnd:
            previous_context = _push_physical_dpi_context()
            try:
                user32 = ctypes.windll.user32
                user32.SetWindowPos(
                    self.hwnd,
                    -1 if restore_stack else 0,
                    round(self.origin_x),
                    round(self.origin_y),
                    round(self.width),
                    round(self.height),
                    0x0010 if restore_stack else 0x0010 | 0x0004,
                )
                if restore_stack:
                    root_id = self.root.winfo_id()
                    root_hwnd = user32.GetParent(root_id) or root_id
                    user32.SetWindowPos(root_hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            finally:
                _pop_dpi_context(previous_context)
            return
        if restore_stack:
            self.window.lift()
            self.root.lift()

    def _make_click_through(self) -> None:
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        window_id = self.window.winfo_id()
        parent_id = user32.GetParent(window_id)
        hwnd = parent_id or window_id
        self.hwnd = hwnd
        extended_style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, extended_style | 0x00000020 | 0x00000080 | 0x08000000)

    def update(
        self,
        source_canvas: tk.Canvas,
        source_point: tuple[float, float],
        direction_point: tuple[float, float],
        color: str,
        pulse: float,
    ) -> None:
        bounds = display_bounds_for_window(self.root)
        bounds_changed = bounds is not None and bounds != self.bounds
        if bounds_changed:
            self.bounds = bounds
            self.origin_x, self.origin_y = bounds[0], bounds[1]
            self.width, self.height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            self.window.geometry(f"{self.width}x{self.height}{self.origin_x:+d}{self.origin_y:+d}")
            self.canvas.configure(width=self.width, height=self.height)
        self._position_display(restore_stack=bounds_changed)
        if bounds_changed:
            self.window.update_idletasks()
        source_origin = source_canvas.winfo_rootx(), source_canvas.winfo_rooty()
        target_origin = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        start = (
            source_origin[0] + source_point[0] - target_origin[0],
            source_origin[1] + source_point[1] - target_origin[1],
        )
        mapped_end = (
            source_origin[0] + direction_point[0] - target_origin[0],
            source_origin[1] + direction_point[1] - target_origin[1],
        )
        direction = mapped_end[0] - start[0], mapped_end[1] - start[1]
        end = ray_to_display_edge(start, direction, self.width, self.height)
        polygons = emission_cone_polygons(start, end, pulse=pulse)
        red, green, blue = ImageColor.getrgb(color)
        colors = (
            color,
            "#" + "".join(f"{round(channel + (255 - channel) * 0.18):02x}" for channel in (red, green, blue)),
            "#" + "".join(f"{round(channel + (255 - channel) * 0.42):02x}" for channel in (red, green, blue)),
        )
        self.canvas.delete("eye-emission-field")
        for polygon, shade in zip(polygons, colors, strict=True):
            self.canvas.create_polygon(
                polygon,
                fill=shade,
                outline="",
                tags=("eye-emission-field",),
            )


def render_eye_emission(
    target: Image.Image,
    view: RobotArm3DView,
    planes: ExpressionPlaneLayers,
    camera: Camera,
) -> None:
    """Emit a soft mood-colored bloom along the 3D eye gaze direction."""
    start, end = eye_emission_projection(view, planes, camera)
    delta_x = end.x - start.x
    delta_y = end.y - start.y
    distance = math.hypot(delta_x, delta_y)
    if distance > 68.0:
        scale = 68.0 / distance
        delta_x *= scale
        delta_y *= scale
        distance = 68.0
    end_x = start.x + delta_x
    end_y = start.y + delta_y

    bloom_radius = 48.0
    left = max(0, math.floor(min(start.x, end_x) - bloom_radius))
    top = max(0, math.floor(min(start.y, end_y) - bloom_radius))
    right = min(target.width, math.ceil(max(start.x, end_x) + bloom_radius))
    bottom = min(target.height, math.ceil(max(start.y, end_y) + bloom_radius))
    if right <= left or bottom <= top:
        return

    local_size = (right - left, bottom - top)
    start_x = start.x - left
    start_y = start.y - top
    red, green, blue = ImageColor.getrgb(view.expression.color)
    mid = tuple(round(channel + (255 - channel) * 0.24) for channel in (red, green, blue))
    pulse = (math.sin(view.pulse_phase) + 1.0) * 0.5

    # Windows Tk color-key transparency turns ordinary semi-transparent blur
    # pixels black.  Blur an intensity mask, then dither it to binary alpha so
    # the bloom stays airy without ever emitting dark pixels.
    outer_mask = Image.new("L", local_size, 0)
    outer_draw = ImageDraw.Draw(outer_mask)
    for step in range(5, -1, -1):
        ratio = step / 5.0
        center_x = start_x + delta_x * ratio * 0.45
        center_y = start_y + delta_y * ratio * 0.45
        radius = 17.0 + ratio * 8.0 + pulse * 1.5
        strength = round(112.0 - ratio * 40.0 + pulse * 12.0)
        outer_draw.ellipse(
            (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
            fill=strength,
        )
    core_radius = 15.5 + pulse * 2.0
    outer_draw.ellipse(
        (start_x - core_radius, start_y - core_radius, start_x + core_radius, start_y + core_radius),
        fill=190,
    )
    outer_mask = outer_mask.filter(ImageFilter.GaussianBlur(6.5))
    outer_alpha = outer_mask.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    glow = Image.new("RGBA", local_size, mid + (255,))
    glow.putalpha(outer_alpha)
    target.alpha_composite(glow, dest=(left, top))


class RobotArm3DV2View(RobotArm3DView):
    """V1 behavior rendered through a real low-poly UV pipeline."""

    DRAW_VECTOR_EYE = False

    def __init__(self, *, eye_emission_enabled: bool = False) -> None:
        super().__init__()
        self.eye_emission_enabled = eye_emission_enabled
        self.uv_atlas: UVTextureAtlas | None = None
        self.surface_image: Image.Image | None = None
        self.surface_photo: ImageTk.PhotoImage | None = None
        self.expression_plane: ExpressionPlaneLayers | None = None
        self.emission_display: EyeEmissionDisplay | None = None
        self.pointer_tracking_active = False

    def mount(self, canvas: tk.Canvas) -> None:
        atlas_path = Path(__file__).parent / "assets" / "robot_arm_3d_v2" / "robot-uv-atlas-v2.png"
        self.uv_atlas = UVTextureAtlas(Image.open(atlas_path))
        super().mount(canvas)
        if self.eye_emission_enabled:
            self.emission_display = EyeEmissionDisplay(canvas.winfo_toplevel())

    def tick(self, pointer_x: int, pointer_y: int, window_x: int, window_y: int) -> None:
        """Feed the IK controller one DPI-consistent pointer coordinate."""
        if self.canvas is not None:
            local_pointer = pointer_position_in_canvas(self.canvas)
            pointer_x = round(window_x + local_pointer[0])
            pointer_y = round(window_y + local_pointer[1])
        super().tick(pointer_x, pointer_y, window_x, window_y)

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
            self.pointer_tracking_active = not self.explorer_active
            start, end = eye_emission_projection(self, self.expression_plane, self.camera)
            if self.eye_emission_enabled:
                render_eye_emission(self.surface_image, self, self.expression_plane, self.camera)
                if self.emission_display is not None:
                    self.emission_display.update(
                        self.canvas,
                        (start.x, start.y),
                        (end.x, end.y),
                        self.expression.color,
                        (math.sin(self.pulse_phase) + 1.0) * 0.5,
                    )
            for plane, texture in zip(self.expression_plane.ordered(), render_expression_layers(self), strict=True):
                projected = tuple(self.camera.project(vertex) for vertex in plane)
                rasterize_texture_quad(self.surface_image, texture, projected)
        self._draw_surface_overlays()
        self.surface_photo = ImageTk.PhotoImage(self.surface_image, master=self.canvas)
        self.canvas.create_image(0, 0, image=self.surface_photo, anchor=tk.NW, tags=("scene3d",))

    def _draw_surface_overlays(self) -> None:
        """Allow variants to add cheap screen-space layers before Tk upload."""


def create_robot_arm_3d_v2(
    transport: JsonlTransport,
    mode: str,
    *,
    eye_emission: bool = False,
) -> TkOverlayHost:
    enable_per_monitor_dpi_awareness()
    return TkOverlayHost(
        transport,
        RobotArm3DV2View(eye_emission_enabled=eye_emission),
        mode=mode,
        title="Engram 3D Robot Arm V2",
    )
