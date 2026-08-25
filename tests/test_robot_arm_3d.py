import math
import unittest

from engram_overlay.overlays.robot_arm_3d import (
    RobotArm3DView,
    cable_decoration_paths,
    cable_hardware_faces,
    constrain_target_reach,
    depth_at_phase,
    quadratic_curve,
    solve_three_link_3d,
    solve_z_posture_3d,
    target_from_pointer,
)
from engram_overlay.registry import OVERLAYS, overlay_ids
from engram_overlay.scene3d import Camera, Vec3
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

    def test_pointer_mapping_preserves_screen_position_at_independent_depths(self) -> None:
        camera = Camera(180.0, 190.0, yaw=-0.38, pitch=-0.10, focal_length=650.0)
        near = target_from_pointer(240.0, 325.0, 360.0, 430.0, camera=camera, depth=-55.0)
        far = target_from_pointer(240.0, 325.0, 360.0, 430.0, camera=camera, depth=55.0)
        projected_near = camera.project(near)
        projected_far = camera.project(far)
        self.assertAlmostEqual(projected_near.x, projected_far.x)
        self.assertAlmostEqual(projected_near.y, projected_far.y)
        self.assertAlmostEqual(projected_near.depth, -55.0)
        self.assertAlmostEqual(projected_far.depth, 55.0)
        self.assertGreater((far - near).length, 100.0)
        self.assertGreater(projected_near.scale, projected_far.scale)

    def test_camera_stays_fixed_while_arm_moves_in_xyz(self) -> None:
        view = RobotArm3DView()
        camera = view.camera
        view.tick(110, 310, 0, 0)
        view.tick(250, 330, 0, 0)
        self.assertEqual(view.camera, camera)
        self.assertNotEqual(view.target_depth, 0.0)
        self.assertNotEqual(depth_at_phase(math.pi * 0.5), depth_at_phase(math.pi * 1.5))

    def test_workspace_allows_wider_root_and_elbow_motion(self) -> None:
        camera = Camera(180.0, 190.0, yaw=-0.38, pitch=-0.10, focal_length=650.0)
        left = camera.project(target_from_pointer(-100.0, 300.0, 360.0, 430.0, camera=camera, depth=0.0))
        right = camera.project(target_from_pointer(500.0, 300.0, 360.0, 430.0, camera=camera, depth=0.0))
        self.assertAlmostEqual(left.x, 55.0)
        self.assertAlmostEqual(right.x, 305.0)
        sampled_depths = [depth_at_phase(index * math.tau / 100.0) for index in range(100)]
        self.assertLessEqual(max(abs(depth) for depth in sampled_depths), 30.0)
        near_scale = camera.project(camera.unproject(180.0, 300.0, -30.0)).scale
        far_scale = camera.project(camera.unproject(180.0, 300.0, 30.0)).scale
        self.assertLess(near_scale / far_scale, 1.11)

    def test_reach_constraint_avoids_a_fully_straight_configuration(self) -> None:
        view = RobotArm3DView()
        requested = target_from_pointer(500.0, 500.0, 360.0, 430.0, camera=view.camera, depth=30.0)
        constrained = constrain_target_reach(view.base, requested, view.lengths)
        self.assertAlmostEqual((constrained - view.base).length, sum(view.lengths) * 0.90)
        points = solve_three_link_3d(view.base, constrained, view.lengths)
        turns = []
        for index in (1, 2):
            parent = (points[index] - points[index - 1]).normalized()
            child = (points[index + 1] - points[index]).normalized()
            turns.append(math.degrees(math.acos(max(-1.0, min(1.0, parent.dot(child))))))
        self.assertGreater(min(turns), 15.0)

    def test_z_posture_solver_alternates_bends_and_preserves_chain(self) -> None:
        base = Vec3(0.0, -145.0, 0.0)
        target = Vec3(0.0, 135.0, 20.0)
        lengths = (120.0, 105.0, 95.0)
        points = solve_z_posture_3d(base, target, lengths, bend_side=1)
        self.assertGreater(points[1].x, 0.0)
        self.assertLess(points[2].x, 0.0)
        self.assertEqual(points[-1], target)
        for start, end, expected in zip(points[:-1], points[1:], lengths, strict=True):
            self.assertAlmostEqual((end - start).length, expected, places=6)

        mirrored = solve_z_posture_3d(base, target, lengths, bend_side=-1)
        self.assertLess(mirrored[1].x, 0.0)
        self.assertGreater(mirrored[2].x, 0.0)

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

    def test_cable_bundle_has_curved_paths_and_low_poly_hardware(self) -> None:
        start = Vec3(0.0, 0.0, 0.0)
        end = Vec3(80.0, 70.0, 25.0)
        curve = quadratic_curve(start, Vec3(35.0, 55.0, 30.0), end)
        self.assertEqual(curve[0], start)
        self.assertEqual(curve[-1], end)
        self.assertGreater((curve[3] - (start + end) * 0.5).length, 5.0)
        main_path, warm_path, cool_path = cable_decoration_paths(start, end, index=0)
        self.assertEqual(len(main_path), 7)
        self.assertEqual(len(warm_path), 7)
        self.assertEqual(len(cool_path), 7)
        self.assertTrue(all((warm - cool).length > 12.0 for warm, cool in zip(warm_path, cool_path, strict=True)))
        faces = cable_hardware_faces(start, end, index=0)
        self.assertEqual(len(faces), 24)
        self.assertTrue(any(face.color == "#475569" for face in faces))
        self.assertTrue(any(face.color == "#334155" for face in faces))

if __name__ == "__main__":
    unittest.main()
