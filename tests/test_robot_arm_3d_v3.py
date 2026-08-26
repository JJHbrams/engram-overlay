import unittest

from PIL import Image, ImageDraw

from engram_overlay.__main__ import build_parser
from engram_overlay.overlays.robot_arm_3d_v3 import (
    Cover,
    RobotArm3DV3View,
    WandererParty,
    advance_party,
    draw_ground_and_covers,
    draw_party,
    point_in_gaze_cone,
    scene_layout,
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

    def test_seen_party_evades_toward_nearest_cover_then_hides(self) -> None:
        covers = (Cover(50.0, 100.0, 20.0), Cover(180.0, 100.0, 20.0))
        party = WandererParty(100.0, 100.0, speed=20.0)
        advance_party(party, seen=True, covers=covers, dt=0.5)
        self.assertEqual(party.state, "evade")
        self.assertLess(party.x, 100.0)
        for _ in range(10):
            advance_party(party, seen=True, covers=covers, dt=0.2)
        self.assertEqual(party.state, "hide")

    def test_hidden_party_peeks_then_resumes_patrol(self) -> None:
        party = WandererParty(50.0, 100.0, state="hide")
        advance_party(party, seen=False, dt=1.4)
        self.assertEqual(party.state, "peek")
        advance_party(party, seen=False, dt=0.8)
        self.assertEqual(party.state, "walk")

    def test_screen_space_scene_paints_compact_silhouettes(self) -> None:
        target = Image.new("RGBA", (220, 140), (0, 0, 0, 0))
        cover = Cover(80.0, 120.0, 20.0, "rock")
        draw_ground_and_covers(target, (cover,))
        draw_party(ImageDraw.Draw(target), WandererParty(130.0, 118.0))
        self.assertIsNotNone(target.getbbox())
        self.assertGreater(sum(1 for pixel in target.get_flattened_data() if pixel[3]), 100)

    def test_v3_keeps_arm_height_and_scales_party_to_companion_strip(self) -> None:
        view = RobotArm3DV3View()
        covers, party = scene_layout(640.0)
        self.assertEqual(view.height, 430)
        self.assertEqual(len(covers), 3)
        self.assertAlmostEqual(covers[-1].x, 640.0 * 0.84)
        self.assertAlmostEqual(party.x, 640.0 * 0.31)
        self.assertEqual(covers[0].kind, "tower")
        self.assertIsNone(view.wanderer_display)
        self.assertFalse(view.eye_emission_enabled)


if __name__ == "__main__":
    unittest.main()
