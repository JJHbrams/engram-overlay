"""V2 robot arm watching tiny screen-space wanderers below it."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

from ..backends.tk import TkOverlayHost
from ..protocol import JsonlTransport
from .robot_arm_3d_v2 import (
    RobotArm3DV2View,
    enable_per_monitor_dpi_awareness,
    eye_emission_projection,
    ray_to_display_edge,
)

GROUND_Y = 484.0


@dataclass(frozen=True)
class Cover:
    x: float
    y: float
    radius: float


@dataclass
class TinyWanderer:
    """Small autonomous traveler with a deliberately simple behavior state."""

    x: float
    y: float
    direction: float = 1.0
    speed: float = 12.0
    state: str = "walk"
    state_time: float = 0.0
    stride: float = 0.0
    accent: str = "#d89135"


DEFAULT_COVERS = (
    Cover(66.0, GROUND_Y, 23.0),
    Cover(205.0, GROUND_Y, 20.0),
    Cover(350.0, GROUND_Y, 27.0),
)


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


def advance_wanderer(
    wanderer: TinyWanderer,
    *,
    seen: bool,
    covers: tuple[Cover, ...] = DEFAULT_COVERS,
    dt: float = 1.0 / 60.0,
    bounds: tuple[float, float] = (18.0, 402.0),
) -> None:
    """Advance one traveler: evade the gaze, hide, peek, then resume patrol."""
    wanderer.state_time += dt
    wanderer.stride += dt * (12.0 if wanderer.state in {"evade", "walk"} else 4.0)
    nearest = min(covers, key=lambda cover: abs(cover.x - wanderer.x))
    safe_distance = nearest.radius * 0.62

    if seen and wanderer.state != "hide":
        wanderer.state = "evade"
        wanderer.state_time = 0.0
    if wanderer.state == "evade":
        delta = nearest.x - wanderer.x
        if abs(delta) <= safe_distance:
            wanderer.state = "hide"
            wanderer.state_time = 0.0
        else:
            wanderer.direction = 1.0 if delta > 0.0 else -1.0
            wanderer.x += wanderer.direction * wanderer.speed * 2.8 * dt
    elif wanderer.state == "hide":
        if seen:
            wanderer.state_time = 0.0
        elif wanderer.state_time > 1.1:
            wanderer.state = "peek"
            wanderer.state_time = 0.0
    elif wanderer.state == "peek":
        if seen:
            wanderer.state = "hide"
            wanderer.state_time = 0.0
        elif wanderer.state_time > 0.65:
            wanderer.state = "walk"
            wanderer.state_time = 0.0
            wanderer.direction *= -1.0
    else:
        wanderer.x += wanderer.direction * wanderer.speed * dt

    if wanderer.x <= bounds[0] or wanderer.x >= bounds[1]:
        wanderer.x = min(max(wanderer.x, bounds[0]), bounds[1])
        wanderer.direction *= -1.0


def draw_wanderer(draw: ImageDraw.ImageDraw, wanderer: TinyWanderer) -> None:
    """Paint a tiny original hooded silhouette without character-specific detail."""
    x, ground = wanderer.x, wanderer.y
    crouch = 4.0 if wanderer.state == "hide" else 2.0 if wanderer.state == "peek" else 0.0
    bob = 0.0 if crouch else math.sin(wanderer.stride) * 1.2
    head_y = ground - 17.0 + crouch + bob
    facing = wanderer.direction
    cloak = [(x - 6.0, ground - 2.0), (x + 6.0, ground - 2.0), (x + facing * 3.5, head_y + 5.0)]
    draw.polygon(cloak, fill="#17191d", outline="#4c4640")
    draw.ellipse((x - 4.2, head_y - 4.2, x + 4.2, head_y + 4.2), fill="#22242a", outline="#665d50")
    draw.polygon(
        [(x - 5.4, head_y), (x + 5.4, head_y), (x + facing * 1.5, head_y - 6.0)],
        fill="#302d31",
        outline="#71685b",
    )
    if wanderer.state != "hide":
        foot = math.sin(wanderer.stride) * 2.0
        draw.line((x - 2.0, ground - 2.0, x - 3.0 - foot, ground + 1.0), fill="#71685b", width=1)
        draw.line((x + 2.0, ground - 2.0, x + 3.0 + foot, ground + 1.0), fill="#71685b", width=1)
    # A restrained carried ember gives one readable story beat at this scale.
    if wanderer.accent and wanderer.state != "hide":
        hand_x = x + facing * 6.0
        draw.ellipse((hand_x - 1.5, head_y + 4.0, hand_x + 1.5, head_y + 7.0), fill=wanderer.accent)


def draw_ground_and_covers(target: Image.Image, covers: tuple[Cover, ...]) -> None:
    draw = ImageDraw.Draw(target)
    draw.line((10, GROUND_Y + 2, target.width - 10, GROUND_Y + 2), fill="#34312f", width=2)
    for index, cover in enumerate(covers):
        shade = "#26272a" if index % 2 else "#302e2d"
        draw.polygon(
            [
                (cover.x - cover.radius, cover.y + 2),
                (cover.x - cover.radius * 0.72, cover.y - cover.radius * 0.55),
                (cover.x - cover.radius * 0.16, cover.y - cover.radius),
                (cover.x + cover.radius * 0.62, cover.y - cover.radius * 0.68),
                (cover.x + cover.radius, cover.y + 2),
            ],
            fill=shade,
            outline="#5a5148",
        )
        draw.line(
            (cover.x - cover.radius * 0.55, cover.y - cover.radius * 0.48, cover.x + cover.radius * 0.45, cover.y - cover.radius * 0.62),
            fill="#71665a",
            width=1,
        )


class RobotArm3DV3View(RobotArm3DV2View):
    """Textured arm plus reactive miniature travelers in its surveillance field."""

    width = 420
    height = 520

    def __init__(self, *, eye_emission_enabled: bool = False) -> None:
        super().__init__(eye_emission_enabled=eye_emission_enabled)
        self.covers = DEFAULT_COVERS
        self.wanderers = [
            TinyWanderer(112.0, GROUND_Y, direction=1.0, speed=10.0, accent="#d89135"),
            TinyWanderer(165.0, GROUND_Y, direction=-1.0, speed=8.5, accent=""),
            TinyWanderer(286.0, GROUND_Y, direction=1.0, speed=11.0, accent="#7f9a73"),
        ]

    def _draw_surface_overlays(self) -> None:
        if self.surface_image is None:
            return
        gaze: tuple[tuple[float, float], tuple[float, float]] | None = None
        if self.expression_plane is not None:
            start, end = eye_emission_projection(self, self.expression_plane, self.camera)
            gaze_start = (start.x, start.y)
            gaze_end = ray_to_display_edge(
                gaze_start,
                (end.x - start.x, end.y - start.y),
                self.width,
                self.height,
            )
            gaze = gaze_start, gaze_end
        draw = ImageDraw.Draw(self.surface_image)
        for wanderer in self.wanderers:
            seen = gaze is not None and point_in_gaze_cone((wanderer.x, wanderer.y - 10.0), *gaze)
            advance_wanderer(wanderer, seen=seen, covers=self.covers)
            draw_wanderer(draw, wanderer)
        # Covers are foreground masks, so a crouched traveler is actually hidden.
        draw_ground_and_covers(self.surface_image, self.covers)


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
