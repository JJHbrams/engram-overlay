import unittest

from engram_overlay.overlays.robot_arm_3d import RobotArm3DView, solve_three_link_3d, target_from_pointer
from engram_overlay.registry import OVERLAYS, overlay_ids
from engram_overlay.scene3d import Vec3
from engram_overlay.state import OverlayState


class RobotArm3DTests(unittest.TestCase):
    def test_registry_exposes_independent_3d_overlay(self) -> None:
        self.assertIn("robot-arm-3d", overlay_ids())
        self.assertEqual(OVERLAYS["robot-arm-3d"].backend, "tk-software-3d")

    def test_solver_reaches_xyz_target_and_preserves_lengths(self) -> None:
        lengths = (120.0, 105.0, 95.0)
        target = Vec3(45.0, 130.0, 28.0)
        points = solve_three_link_3d(Vec3(0.0, -145.0, 0.0), target, lengths)
        self.assertLess((points[-1] - target).length, 0.2)
        for start, end, expected in zip(points[:-1], points[1:], lengths, strict=True):
            self.assertAlmostEqual((end - start).length, expected, places=6)

    def test_unreachable_target_extends_in_three_dimensions(self) -> None:
        points = solve_three_link_3d(Vec3(0.0, 0.0, 0.0), Vec3(1000.0, 1000.0, 1000.0), (10.0, 20.0, 30.0))
        self.assertAlmostEqual((points[-1] - points[0]).length, 60.0)

    def test_pointer_mapping_adds_real_depth(self) -> None:
        left = target_from_pointer(95.0, 330.0, 360.0, 430.0)
        right = target_from_pointer(265.0, 330.0, 360.0, 430.0)
        self.assertLess(left.x, 0.0)
        self.assertLess(left.z, 0.0)
        self.assertAlmostEqual(left.x, -right.x)
        self.assertAlmostEqual(left.z, -right.z)

    def test_3d_view_reuses_event_expression_mapping(self) -> None:
        view = RobotArm3DView()
        view.apply_state(OverlayState(display_hint="generating"))
        self.assertFalse(view.random_expressions_enabled)
        self.assertEqual(view.expression.name, "skeptical")
        view.apply_state(OverlayState(display_hint="idle"))
        self.assertTrue(view.random_expressions_enabled)

    def test_scene_contains_volumetric_faces(self) -> None:
        view = RobotArm3DView()
        faces = view._scene_faces()
        self.assertGreater(len(faces), 100)
        self.assertTrue(all(len(face.vertices) >= 4 for face in faces))


if __name__ == "__main__":
    unittest.main()
