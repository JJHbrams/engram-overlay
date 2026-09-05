import random
import unittest
from pathlib import Path

from PIL import Image

from engram_overlay.overlays.rabbit_2d import STATE_FRAMES, atlas_frames, choose_frame
from engram_overlay.overlays.spritemap import Rotation
from engram_overlay.registry import OVERLAYS, overlay_ids


class Rabbit2DTests(unittest.TestCase):
    def test_registry_exposes_rabbit(self) -> None:
        self.assertIn("rabbit-2d", overlay_ids())
        self.assertEqual(OVERLAYS["rabbit-2d"].backend, "tk-sprite-grid")

    def test_random_choice_is_stable_per_bucket_and_avoids_repeat(self) -> None:
        rotation = Rotation(random.Random(7))
        first = choose_frame("idle", 0, rotation)
        self.assertEqual(first, choose_frame("idle", 0, rotation))
        second = choose_frame("idle", 1, rotation)
        self.assertNotEqual(first, second)

    def test_unknown_hint_uses_idle_rotation(self) -> None:
        frame = choose_frame("future-state", 0, Rotation(random.Random(2)))
        self.assertIn(frame, STATE_FRAMES["idle"])

    def test_a_single_candidate_hint_never_varies(self) -> None:
        rotation = Rotation(random.Random(3))
        chosen = {choose_frame("input", bucket, rotation) for bucket in range(6)}
        self.assertEqual(chosen, set(STATE_FRAMES["input"]))

    def test_packaged_atlas_has_five_states_and_empty_spare_cell(self) -> None:
        asset = Path(__file__).parents[1] / "src" / "engram_overlay" / "overlays" / "assets" / "rabbit_2d" / "rabbit-states.png"
        image = Image.open(asset).convert("RGBA")
        frames = atlas_frames(image)
        self.assertTrue(all(frame.getbbox() is not None for frame in frames[:5]))
        self.assertIsNone(frames[5].getbbox())
        self.assertLess(image.getextrema()[3][0], image.getextrema()[3][1])


if __name__ == "__main__":
    unittest.main()
