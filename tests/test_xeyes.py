import math
import unittest

from engram_overlay.overlays.xeyes import pupil_center
from engram_overlay.registry import OVERLAYS, create_overlay, overlay_ids


class XEyesTests(unittest.TestCase):
    def test_registry_exposes_xeyes(self) -> None:
        self.assertIn("xeyes", overlay_ids())
        self.assertEqual(OVERLAYS["xeyes"].backend, "tk")

    def test_unknown_overlay_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_overlay("missing", None, "observer")  # type: ignore[arg-type]

    def test_pupil_stays_inside_elliptical_limit(self) -> None:
        pupil_x, pupil_y = pupil_center(0, 0, 1000, 1000, limit_x=24, limit_y=31)
        normalized = (pupil_x / 24) ** 2 + (pupil_y / 31) ** 2
        self.assertLessEqual(normalized, 1.0 + 1e-9)

    def test_pupil_tracks_target_direction(self) -> None:
        pupil_x, pupil_y = pupil_center(10, 20, -100, 200)
        self.assertLess(pupil_x, 10)
        self.assertGreater(pupil_y, 20)
        self.assertTrue(math.isfinite(pupil_x) and math.isfinite(pupil_y))

    def test_near_target_is_not_over_clamped(self) -> None:
        self.assertEqual(pupil_center(10, 20, 12, 23), (12, 23))


if __name__ == "__main__":
    unittest.main()
