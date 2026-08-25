import unittest
from unittest.mock import Mock

from engram_overlay.overlays.robot_arm import (
    EXPRESSIONS,
    RobotArmView,
    bend_side_for_target,
    eyelid_polygon_points,
    lower_workspace_target,
    solve_three_link_z,
    tracked_gaze,
)
from engram_overlay.registry import OVERLAYS, overlay_ids


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5


def cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    first = (b[0] - a[0], b[1] - a[1])
    second = (c[0] - b[0], c[1] - b[1])
    return first[0] * second[1] - first[1] * second[0]


class RobotArmTests(unittest.TestCase):
    def test_registry_exposes_robot_arm(self) -> None:
        self.assertIn("robot-arm", overlay_ids())
        self.assertEqual(OVERLAYS["robot-arm"].backend, "tk")

    def test_solver_reaches_target_and_preserves_link_lengths(self) -> None:
        lengths = (132.0, 122.0, 116.0)
        points = solve_three_link_z((180.0, 374.0), (210.0, 72.0), lengths)

        self.assertLess(distance(points[-1], (210.0, 72.0)), 0.2)
        for start, end, expected in zip(points[:-1], points[1:], lengths, strict=True):
            self.assertAlmostEqual(distance(start, end), expected, places=6)

    def test_default_solution_uses_alternating_z_bends(self) -> None:
        points = solve_three_link_z((180.0, 374.0), (180.0, 72.0), (132.0, 122.0, 116.0))
        first_turn = cross(points[0], points[1], points[2])
        second_turn = cross(points[1], points[2], points[3])
        self.assertLess(first_turn * second_turn, 0.0)
        self.assertGreater(points[1][0], points[0][0])
        self.assertLess(points[2][0], points[3][0])

    def test_hanging_solution_descends_from_ceiling_in_z_shape(self) -> None:
        points = solve_three_link_z((180.0, 48.0), (180.0, 350.0), (132.0, 122.0, 116.0))
        self.assertGreater(points[-1][1], points[0][1])
        self.assertGreater(points[1][0], points[0][0])
        self.assertLess(points[2][0], points[3][0])
        self.assertLess(cross(points[0], points[1], points[2]) * cross(points[1], points[2], points[3]), 0.0)

    def test_hanging_solution_mirrors_around_center(self) -> None:
        lengths = (132.0, 122.0, 116.0)
        right = solve_three_link_z((180.0, 48.0), (230.0, 350.0), lengths, bend_side=1)
        left = solve_three_link_z((180.0, 48.0), (130.0, 350.0), lengths, bend_side=-1)
        for right_point, left_point in zip(right, left, strict=True):
            self.assertAlmostEqual(left_point[0], 360.0 - right_point[0], places=6)
            self.assertAlmostEqual(left_point[1], right_point[1], places=6)

    def test_bend_side_uses_center_deadband(self) -> None:
        self.assertEqual(bend_side_for_target(1, 150.0, 180.0), -1)
        self.assertEqual(bend_side_for_target(-1, 210.0, 180.0), 1)
        self.assertEqual(bend_side_for_target(-1, 175.0, 180.0), -1)
        self.assertEqual(bend_side_for_target(1, 185.0, 180.0), 1)

    def test_unreachable_target_extends_to_total_length(self) -> None:
        points = solve_three_link_z((0.0, 0.0), (0.0, -1000.0), (10.0, 20.0, 30.0))
        self.assertAlmostEqual(distance(points[0], points[-1]), 60.0)
        self.assertEqual(points[-1], (0.0, -60.0))

    def test_endpoint_is_clamped_below_ceiling_root(self) -> None:
        self.assertEqual(lower_workspace_target(-100, 999, 360), (95.0, 375.0))
        self.assertEqual(lower_workspace_target(200, -5, 360), (200, 285.0))

    def test_two_eyelid_profiles_cover_reference_expressions(self) -> None:
        names = {expression.name for expression in EXPRESSIONS}
        self.assertEqual(
            names,
            {
                "idle",
                "boring",
                "giggle",
                "curious",
                "hesitant",
                "skeptical",
                "tempered",
                "angry",
                "depressed",
                "sad",
            },
        )
        upper = eyelid_polygon_points((10.0, 20.0), -5.0, 2.0, 3.0, upper=True)
        lower = eyelid_polygon_points((10.0, 20.0), 5.0, 2.0, 3.0, upper=False)
        self.assertEqual(upper[:6], (-18.0, 13.0, 10.0, 18.0, 38.0, 17.0))
        self.assertEqual(lower[:6], (-18.0, 23.0, 10.0, 28.0, 38.0, 27.0))

    def test_mouse_gaze_is_soft_and_elliptically_bounded(self) -> None:
        self.assertEqual(tracked_gaze((10.0, 0.0), (0.0, 0.0)), (2.0 / 3.0, 0.0))
        far_gaze = tracked_gaze((1000.0, 1000.0), (0.0, 0.0), (3.0, 2.0))
        self.assertLessEqual((far_gaze[0] / 8.0) ** 2 + (far_gaze[1] / 6.0) ** 2, 1.0 + 1e-9)

    def test_draw_maps_three_links_to_four_joint_points(self) -> None:
        view = RobotArmView()
        view.canvas = Mock()
        view.link_ids = [1, 2, 3]
        view.joint_ids = [4, 5, 6, 7]
        view.target_id = 8
        view.ambient_ids = [9, 10]
        view.led_halo_id = 11
        view.led_core_id = 12
        view.eyelid_ids = [13, 14]
        view.eye_rim_id = 15

        view._draw()

        self.assertEqual(view.canvas.coords.call_count, 15)


if __name__ == "__main__":
    unittest.main()
