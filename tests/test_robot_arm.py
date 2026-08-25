import unittest

from engram_overlay.overlays.robot_arm import solve_three_link_z, upper_workspace_target
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

    def test_unreachable_target_extends_to_total_length(self) -> None:
        points = solve_three_link_z((0.0, 0.0), (0.0, -1000.0), (10.0, 20.0, 30.0))
        self.assertAlmostEqual(distance(points[0], points[-1]), 60.0)
        self.assertEqual(points[-1], (0.0, -60.0))

    def test_endpoint_is_clamped_to_upper_workspace(self) -> None:
        self.assertEqual(upper_workspace_target(-100, 999, 360), (95.0, 145.0))
        self.assertEqual(upper_workspace_target(200, -5, 360), (200, 65.0))


if __name__ == "__main__":
    unittest.main()
