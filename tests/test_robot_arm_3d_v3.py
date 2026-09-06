import unittest
import random
from pathlib import Path

from PIL import Image, ImageDraw

from engram_overlay.__main__ import build_parser
from engram_overlay.overlays.robot_arm_3d_v3 import (
    Cover,
    RobotArm3DV3View,
    WandererParty,
    absolute_tk_geometry,
    atlas_frames,
    advance_party,
    draw_ground_and_covers,
    draw_party,
    point_in_gaze_cone,
    opposite_corner_origin,
    scene_layout,
    terrain_ridge_points,
    v3_exploration_target,
    walking_limb_pose,
)
from engram_overlay.registry import OVERLAYS, overlay_ids


class RobotArm3DV3Tests(unittest.TestCase):
    def test_registry_exposes_v3_as_independent_overlay(self) -> None:
        self.assertIn("robot-arm-3d-v3", overlay_ids())
        self.assertEqual(OVERLAYS["robot-arm-3d-v3"].backend, "tk-textured-software-3d")
        args = build_parser().parse_args(("--overlay", "robot-arm-3d-v3", "--eye-emission"))
        self.assertTrue(args.eye_emission)
        self.assertEqual(OVERLAYS["robot-arm-3d-v3"].name, "CCTV")

    def test_gaze_cone_is_directional_and_finite(self) -> None:
        self.assertTrue(point_in_gaze_cone((50.0, 12.0), (0.0, 0.0), (100.0, 0.0), half_angle_degrees=15.0))
        self.assertFalse(point_in_gaze_cone((50.0, 30.0), (0.0, 0.0), (100.0, 0.0), half_angle_degrees=15.0))
        self.assertFalse(point_in_gaze_cone((-20.0, 0.0), (0.0, 0.0), (100.0, 0.0)))
        self.assertFalse(point_in_gaze_cone((130.0, 0.0), (0.0, 0.0), (100.0, 0.0)))

    def test_scene_uses_opposite_corner_with_negative_monitor_coordinates(self) -> None:
        self.assertEqual(opposite_corner_origin(-420.0, -2560.0, 0.0, 640.0), ("left", -2560.0))
        self.assertEqual(opposite_corner_origin(-2200.0, -2560.0, 0.0, 640.0), ("right", -640.0))
        self.assertEqual(absolute_tk_geometry(640, 96, -2560, 2277), "640x96+-2560+2277")

    def test_walking_pose_moves_opposite_limbs_through_two_segments(self) -> None:
        first = walking_limb_pose(50.0, 80.0, 1.0, 0.0)
        quarter = walking_limb_pose(50.0, 80.0, 1.0, 1.57)
        self.assertEqual(len(first.left_arm), 3)
        self.assertEqual(len(first.left_leg), 3)
        self.assertNotEqual(first.left_leg[-1], quarter.left_leg[-1])
        self.assertLess(quarter.left_arm[-1][0], quarter.right_arm[-1][0])

    def test_v3_idle_exploration_uses_more_of_the_canvas(self) -> None:
        points = [v3_exploration_target(random.Random(seed), 420.0) for seed in range(100)]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        self.assertLess(min(xs), 58.0)
        self.assertGreater(max(xs), 362.0)
        self.assertLess(min(ys), 230.0)
        self.assertGreater(max(ys), 322.0)

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

    def test_terrain_is_one_low_continuous_ridge(self) -> None:
        ridge = terrain_ridge_points(640.0)
        self.assertEqual(ridge[0][0], 0.0)
        self.assertEqual(ridge[11][0], 640.0)
        self.assertTrue(all(77.0 <= y <= 83.0 for _x, y in ridge[:12]))
        self.assertEqual(ridge[-2:], ((640.0, 96), (0.0, 96)))

    def test_v3_keeps_arm_height_and_scales_party_to_companion_strip(self) -> None:
        view = RobotArm3DV3View()
        covers, party = scene_layout(640.0)
        self.assertEqual(view.height, 430)
        self.assertEqual(len(covers), 3)
        self.assertAlmostEqual(covers[-1].x, 640.0 * 0.84)
        self.assertAlmostEqual(party.x, 640.0 * 0.31)
        self.assertEqual(covers[0].kind, "tower")
        self.assertIsNone(view.wanderer_display)
        self.assertFalse(view.party_tracking_active)
        self.assertFalse(view.eye_emission_enabled)

    def test_generated_silhouette_texture_atlases_are_packaged(self) -> None:
        asset_dir = Path(__file__).parents[1] / "src" / "engram_overlay" / "overlays" / "assets" / "robot_arm_3d_v3"
        travelers = Image.open(asset_dir / "traveler-walk-atlas.png").convert("RGBA")
        covers = Image.open(asset_dir / "terrain-cover-atlas.png").convert("RGBA")
        ridge = Image.open(asset_dir / "terrain-ridge.png").convert("RGBA")
        frames = atlas_frames(travelers, 4, 3)
        self.assertEqual((len(frames), len(frames[0])), (3, 4))
        self.assertTrue(all(frame.getbbox() is not None for row in frames for frame in row))
        self.assertIsNotNone(covers.getbbox())
        self.assertIsNotNone(ridge.getbbox())

    def test_party_detection_forces_alarm_tracking_then_restores_idle(self) -> None:
        class FakeDisplay:
            origin_x = 100.0
            origin_y = 700.0
            party = WandererParty(200.0, 82.0)

        view = RobotArm3DV3View()
        view.wanderer_display = FakeDisplay()  # type: ignore[assignment]
        view.party_tracking_active = True
        view.tick(0, 0, 100, 100)
        self.assertEqual(view.expression.name, "alarm")
        self.assertFalse(view.random_expressions_enabled)
        self.assertTrue(view.was_party_tracking)

        view.party_tracking_active = False
        view.tick(0, 0, 100, 100)
        self.assertTrue(view.random_expressions_enabled)
        self.assertFalse(view.was_party_tracking)


if __name__ == "__main__":
    unittest.main()
