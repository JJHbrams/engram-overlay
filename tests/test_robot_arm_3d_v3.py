import unittest

from PIL import Image, ImageDraw

from engram_overlay.__main__ import build_parser
from engram_overlay.overlays.robot_arm_3d_v3 import (
    Cover,
    RobotArm3DV3View,
    TinyWanderer,
    advance_wanderer,
    draw_ground_and_covers,
    draw_wanderer,
    point_in_gaze_cone,
)
from engram_overlay.registry import OVERLAYS, overlay_ids


class RobotArm3DV3Tests(unittest.TestCase):
    def test_registry_exposes_v3_as_independent_overlay(self) -> None:
        self.assertIn("robot-arm-3d-v3", overlay_ids())
        self.assertEqual(OVERLAYS["robot-arm-3d-v3"].backend, "tk-textured-software-3d")
        args = build_parser().parse_args(("--overlay", "robot-arm-3d-v3", "--eye-emission"))
        self.assertTrue(args.eye_emission)

    def test_gaze_cone_is_directional_and_finite(self) -> None:
        self.assertTrue(point_in_gaze_cone((50.0, 12.0), (0.0, 0.0), (100.0, 0.0), half_angle_degrees=15.0))
        self.assertFalse(point_in_gaze_cone((50.0, 30.0), (0.0, 0.0), (100.0, 0.0), half_angle_degrees=15.0))
        self.assertFalse(point_in_gaze_cone((-20.0, 0.0), (0.0, 0.0), (100.0, 0.0)))
        self.assertFalse(point_in_gaze_cone((130.0, 0.0), (0.0, 0.0), (100.0, 0.0)))

    def test_seen_wanderer_evades_toward_nearest_cover_then_hides(self) -> None:
        covers = (Cover(50.0, 100.0, 20.0), Cover(180.0, 100.0, 20.0))
        traveler = TinyWanderer(100.0, 100.0, speed=20.0)
        advance_wanderer(traveler, seen=True, covers=covers, dt=0.5)
        self.assertEqual(traveler.state, "evade")
        self.assertLess(traveler.x, 100.0)
        for _ in range(10):
            advance_wanderer(traveler, seen=True, covers=covers, dt=0.2)
        self.assertEqual(traveler.state, "hide")

    def test_hidden_wanderer_peeks_then_resumes_patrol(self) -> None:
        traveler = TinyWanderer(50.0, 100.0, state="hide")
        advance_wanderer(traveler, seen=False, dt=1.2)
        self.assertEqual(traveler.state, "peek")
        advance_wanderer(traveler, seen=False, dt=0.7)
        self.assertEqual(traveler.state, "walk")

    def test_screen_space_scene_paints_compact_silhouettes(self) -> None:
        target = Image.new("RGBA", (220, 140), (0, 0, 0, 0))
        cover = Cover(80.0, 120.0, 20.0)
        draw_ground_and_covers(target, (cover,))
        draw_wanderer(ImageDraw.Draw(target), TinyWanderer(130.0, 118.0))
        self.assertIsNotNone(target.getbbox())
        self.assertGreater(sum(1 for pixel in target.get_flattened_data() if pixel[3]), 100)

    def test_v3_uses_more_vertical_space_and_starts_with_a_small_party(self) -> None:
        view = RobotArm3DV3View()
        self.assertGreater(view.height, 430)
        self.assertEqual(len(view.wanderers), 3)
        self.assertFalse(view.eye_emission_enabled)


if __name__ == "__main__":
    unittest.main()
