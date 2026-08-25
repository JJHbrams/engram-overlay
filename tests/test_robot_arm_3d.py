import math
import random
import unittest

from engram_overlay.overlays.robot_arm_3d import (
    RobotArm3DView,
    aperture_segments,
    cable_decoration_paths,
    cable_hardware_faces,
    constrain_target_reach,
    continuous_posture_hints,
    depth_at_phase,
    eye_shading_from_link,
    eased_exploration_point,
    exploration_waypoint,
    first_link_accessory_faces,
    first_link_back_loops,
    first_link_hub_center,
    first_link_service_path,
    quadratic_curve,
    solve_three_link_3d,
    solve_z_posture_3d,
    target_from_pointer,
    visible_eyelid_offsets,
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
        self.assertAlmostEqual((constrained - view.base).length, sum(view.lengths) * 0.95)
        points = solve_z_posture_3d(
            view.base,
            constrained,
            view.lengths,
            elbow_hint=continuous_posture_hints(500.0, 360.0, view.camera)[0],
            wrist_hint=continuous_posture_hints(500.0, 360.0, view.camera)[1],
        )
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
        points = solve_z_posture_3d(base, target, lengths, elbow_hint=Vec3(1.0, 0.0, 0.0))
        self.assertGreater(points[1].x, 0.0)
        self.assertLess(points[2].x, 0.0)
        self.assertEqual(points[-1], target)
        for start, end, expected in zip(points[:-1], points[1:], lengths, strict=True):
            self.assertAlmostEqual((end - start).length, expected, places=6)

        mirrored = solve_z_posture_3d(base, target, lengths, elbow_hint=Vec3(-1.0, 0.0, 0.0))
        self.assertLess(mirrored[1].x, 0.0)
        self.assertGreater(mirrored[2].x, 0.0)

    def test_pole_crosses_center_through_depth_without_a_branch_jump(self) -> None:
        camera = Camera(180.0, 190.0, yaw=-0.38, pitch=-0.10, focal_length=650.0)
        left_elbow, left_wrist = continuous_posture_hints(179.0, 360.0, camera)
        center_elbow, center_wrist = continuous_posture_hints(180.0, 360.0, camera)
        right_elbow, right_wrist = continuous_posture_hints(181.0, 360.0, camera)
        self.assertGreater(left_elbow.dot(center_elbow), 0.999)
        self.assertGreater(center_elbow.dot(right_elbow), 0.999)
        self.assertGreater(left_wrist.dot(center_wrist), 0.999)
        self.assertGreater(center_wrist.dot(right_wrist), 0.999)
        camera_forward = camera.world_space(Vec3(0.0, 0.0, -1.0)).normalized()
        self.assertGreater(center_elbow.dot(camera_forward), 0.999)
        self.assertGreater(center_wrist.dot(camera_forward), 0.999)

        base = Vec3(0.0, -145.0, 0.0)
        target = Vec3(0.0, 135.0, 20.0)
        lengths = (120.0, 105.0, 95.0)
        left_pose = solve_z_posture_3d(base, target, lengths, elbow_hint=left_elbow, wrist_hint=left_wrist)
        right_pose = solve_z_posture_3d(base, target, lengths, elbow_hint=right_elbow, wrist_hint=right_wrist)
        self.assertLess((left_pose[1] - right_pose[1]).length, 2.0)
        self.assertLess((left_pose[2] - right_pose[2]).length, 2.0)

        center_pose = solve_z_posture_3d(
            base,
            target,
            lengths,
            elbow_hint=center_elbow,
            wrist_hint=center_wrist,
        )
        endpoint_depth = min(camera.camera_space(base).z, camera.camera_space(target).z)
        self.assertLess(camera.camera_space(center_pose[1]).z, endpoint_depth)
        self.assertLess(camera.camera_space(center_pose[2]).z, endpoint_depth)

    def test_full_pointer_sweep_keeps_joint_motion_continuous(self) -> None:
        view = RobotArm3DView()
        for _ in range(90):
            view.tick(55, 310, 0, 0)
        previous = view.joints
        maximum_step = 0.0
        for pointer_x in range(55, 306):
            view.tick(pointer_x, 310, 0, 0)
            maximum_step = max(
                maximum_step,
                max((current - prior).length for prior, current in zip(previous, view.joints, strict=True)),
            )
            previous = view.joints
        self.assertLess(maximum_step, 2.5)

    def test_eye_shading_tracks_projected_link_direction_and_depth(self) -> None:
        shade_x, shade_y, angle, strength = eye_shading_from_link(Vec3(4.0, -3.0, 0.0))
        self.assertGreater(shade_x, 0.0)
        self.assertLess(shade_y, 0.0)
        self.assertAlmostEqual(strength, 3.2)
        self.assertAlmostEqual(angle, math.degrees(math.atan2(3.0, 4.0)))
        _, _, _, depth_strength = eye_shading_from_link(Vec3(1.0, 0.0, 4.0))
        self.assertGreater(depth_strength, strength)

    def test_mechanical_iris_seams_are_subtle_and_three_way(self) -> None:
        segments = aperture_segments((10.0, 20.0), 8.0, 6.0, 0.0)
        self.assertEqual(len(segments), 3)
        self.assertGreater(segments[0][0], 10.0)
        self.assertGreater(segments[0][2], segments[0][0])
        self.assertEqual(visible_eyelid_offsets(-27.0, 27.0), (-22.0, 22.0))
        self.assertEqual(visible_eyelid_offsets(-8.0, 10.0), (-8.0, 10.0))

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

    def test_first_link_accessories_add_module_hardware_and_service_line(self) -> None:
        start = Vec3(0.0, -145.0, 0.0)
        end = Vec3(55.0, -45.0, 25.0)
        faces = first_link_accessory_faces(start, end)
        path = first_link_service_path(start, end)
        loops = first_link_back_loops(start, end)
        hub = first_link_hub_center(start, end)
        self.assertGreater(len(faces), 45)
        self.assertEqual(len(path), 8)
        self.assertTrue(all(len(loop) == 10 for loop in loops))
        self.assertGreater((hub - start).length, 20.0)
        self.assertTrue(any(face.color == "#64748b" for face in faces))

    def test_exploration_waypoint_stays_restrained(self) -> None:
        waypoint = exploration_waypoint(random.Random(7))
        self.assertGreaterEqual(waypoint[0], -92.0)
        self.assertLessEqual(waypoint[0], 92.0)
        self.assertGreaterEqual(waypoint[1], -50.0)
        self.assertLessEqual(waypoint[1], 50.0)
        elliptical_radius = math.hypot(waypoint[0] / 92.0, waypoint[1] / 50.0)
        self.assertGreaterEqual(elliptical_radius, 0.65)
        self.assertLessEqual(elliptical_radius, 1.0)

    def test_idle_explorer_uses_a_smooth_virtual_pointer_and_yields_to_mouse(self) -> None:
        self.assertEqual(eased_exploration_point((0.0, 0.0), (10.0, -4.0), 0.0), (0.0, 0.0))
        self.assertEqual(eased_exploration_point((0.0, 0.0), (10.0, -4.0), 1.0), (10.0, -4.0))
        midpoint = eased_exploration_point((0.0, 0.0), (10.0, -4.0), 0.5)
        self.assertEqual(midpoint, (5.0, -2.0))

        view = RobotArm3DView(rng=random.Random(7))
        view.last_pointer = (180.0, 310.0)
        view.last_pointer_motion_at = 0.0
        view.explore_started_at = 0.0
        view.explore_hold_until = 0.0
        view.tick(180, 310, 0, 0)
        self.assertTrue(view.explorer_active)
        self.assertNotEqual(view.explore_to, (0.0, 0.0))
        view.tick(230, 310, 0, 0)
        self.assertFalse(view.explorer_active)

if __name__ == "__main__":
    unittest.main()
