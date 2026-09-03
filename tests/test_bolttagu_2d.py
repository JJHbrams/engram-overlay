import json
import unittest

from engram_overlay.overlays import bolttagu_2d
from engram_overlay.overlays.bolttagu_2d import (
    ASSET_DIR,
    CLIPS,
    HINT_ONESHOTS,
    STATE_CLIPS,
    BolttaguAnimator,
    Clip,
    clip_cell,
    load_atlas,
)
from engram_overlay.protocol import DISPLAY_HINTS
from engram_overlay.registry import OVERLAYS, overlay_ids


class ClipTests(unittest.TestCase):
    def test_rejects_mismatched_durations(self) -> None:
        with self.assertRaises(ValueError):
            Clip(sheet="stills", cells=(0, 1), durations_ms=(100,), loop=True)

    def test_rejects_empty_clip(self) -> None:
        with self.assertRaises(ValueError):
            Clip(sheet="stills", cells=(), durations_ms=(), loop=True)

    def test_rejects_non_positive_duration(self) -> None:
        with self.assertRaises(ValueError):
            Clip(sheet="enter", cells=(0,), durations_ms=(0,), loop=False)


class ClipCellTests(unittest.TestCase):
    def test_wondering_advances_at_ten_fps_and_wraps(self) -> None:
        clip = CLIPS["wondering"]
        self.assertEqual(clip.total_ms, 800)
        self.assertEqual(clip_cell(clip, 0), 0)
        self.assertEqual(clip_cell(clip, 99), 0)
        self.assertEqual(clip_cell(clip, 100), 1)
        self.assertEqual(clip_cell(clip, 750), 7)
        self.assertEqual(clip_cell(clip, 800), 0)

    def test_enter_uses_pack_durations_then_retires(self) -> None:
        clip = CLIPS["enter"]
        self.assertEqual(clip.durations_ms, (200, 300, 220))
        self.assertEqual(clip_cell(clip, 0), 0)
        self.assertEqual(clip_cell(clip, 200), 1)
        self.assertEqual(clip_cell(clip, 500), 2)
        self.assertIsNone(clip_cell(clip, 720))

    def test_negative_elapsed_clamps_to_first_cell(self) -> None:
        self.assertEqual(clip_cell(CLIPS["enter"], -50), 0)


class StateMappingTests(unittest.TestCase):
    def test_every_display_hint_is_mapped(self) -> None:
        self.assertEqual(set(STATE_CLIPS), set(DISPLAY_HINTS))

    def test_hints_only_resolve_to_looping_clips(self) -> None:
        for hint, name in STATE_CLIPS.items():
            with self.subTest(hint=hint):
                self.assertTrue(CLIPS[name].loop)

    def test_oneshot_targets_are_non_looping_clips(self) -> None:
        for hint, name in HINT_ONESHOTS.items():
            with self.subTest(hint=hint):
                self.assertIn(hint, STATE_CLIPS)
                self.assertFalse(CLIPS[name].loop)


class AnimatorTests(unittest.TestCase):
    def test_intro_plays_once_then_falls_back_to_idle(self) -> None:
        animator = BolttaguAnimator(started_ms=1_000)
        self.assertEqual(animator.resolve(1_000), ("enter", 0))
        self.assertEqual(animator.resolve(1_250), ("enter", 1))
        self.assertEqual(animator.resolve(1_800), ("stills", 0))
        self.assertIsNone(animator.oneshot)

    def test_thinking_hints_run_the_wondering_loop(self) -> None:
        animator = BolttaguAnimator(started_ms=0, intro=None)
        animator.apply_hint("thought", 5_000)
        self.assertEqual(animator.resolve(5_000), ("wondering", 0))
        self.assertEqual(animator.resolve(5_300), ("wondering", 3))
        self.assertEqual(animator.resolve(5_800), ("wondering", 0))

    def test_hint_restart_is_ignored_while_unchanged(self) -> None:
        animator = BolttaguAnimator(started_ms=0, intro=None)
        animator.apply_hint("search", 1_000)
        animator.apply_hint("search", 1_400)
        self.assertEqual(animator.state_started_ms, 1_000)
        self.assertEqual(animator.resolve(1_400), ("wondering", 4))

    def test_unknown_hint_falls_back_to_idle(self) -> None:
        animator = BolttaguAnimator(started_ms=0, intro=None)
        animator.apply_hint("teleporting", 100)
        self.assertEqual(animator.display_hint, "idle")
        self.assertEqual(animator.resolve(100), ("stills", 0))

    def test_provider_error_plays_the_exit_wave_then_holds_alert(self) -> None:
        animator = BolttaguAnimator(started_ms=0, intro=None)
        animator.apply_hint("provider_error", 2_000)
        self.assertEqual(animator.resolve(2_000), ("exit", 0))
        self.assertEqual(animator.resolve(2_450), ("exit", 2))
        self.assertEqual(animator.resolve(2_700), ("stills", 1))

    def test_hover_and_click_use_the_alert_pose(self) -> None:
        animator = BolttaguAnimator(started_ms=0, intro=None)
        animator.apply_hint("hover", 0)
        self.assertEqual(animator.resolve(10), ("stills", 1))
        animator.apply_hint("click", 20)
        self.assertEqual(animator.resolve(30), ("stills", 1))


class AtlasTests(unittest.TestCase):
    def test_metadata_matches_bundled_sheet_sizes(self) -> None:
        sheets, cell = load_atlas()
        self.assertEqual(cell, (270, 302))
        self.assertEqual(len(sheets["wondering"]), 8)
        self.assertEqual(len(sheets["enter"]), 3)
        self.assertEqual(len(sheets["exit"]), 3)
        self.assertEqual(len(sheets["stills"]), 3)
        self.assertEqual(len(sheets["floor"]), 2)
        for name, frames in sheets.items():
            with self.subTest(sheet=name):
                for frame in frames:
                    self.assertEqual(frame.size, cell)
                    self.assertEqual(frame.mode, "RGBA")

    def test_every_clip_cell_exists_in_its_sheet(self) -> None:
        sheets, _ = load_atlas()
        for name, clip in CLIPS.items():
            with self.subTest(clip=name):
                self.assertIn(clip.sheet, sheets)
                self.assertLess(max(clip.cells), len(sheets[clip.sheet]))

    def test_atlas_records_the_downscale_provenance(self) -> None:
        metadata = json.loads((ASSET_DIR / "atlas.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["source"], "sprite-pack-v7")
        self.assertEqual(metadata["sourceCanvas"], [1254, 1254])
        self.assertEqual(metadata["scale"], 0.25)
        self.assertEqual(metadata["feetAnchor"], [166, 267])

    def test_bundled_assets_stay_small(self) -> None:
        total = sum(path.stat().st_size for path in ASSET_DIR.glob("*.png"))
        self.assertLess(total, 1_500_000)


class ViewTests(unittest.TestCase):
    def test_canvas_size_matches_the_atlas_cell(self) -> None:
        view = bolttagu_2d.Bolttagu2dView()
        self.assertEqual((view.width, view.height), (270, 302))
        self.assertIsNone(view.drawn)

    def test_floor_option_composites_without_changing_geometry(self) -> None:
        view = bolttagu_2d.Bolttagu2dView(show_floor=True)
        self.assertEqual((view.width, view.height), (270, 302))
        plain = bolttagu_2d.Bolttagu2dView()
        self.assertNotEqual(
            view.sheets["stills"][0].tobytes(),
            plain.sheets["stills"][0].tobytes(),
        )

    def test_apply_state_is_safe_before_mount(self) -> None:
        from engram_overlay.state import OverlayState

        view = bolttagu_2d.Bolttagu2dView()
        state = OverlayState()
        state.display_hint = "memory"
        view.apply_state(state)
        view.tick(0, 0, 0, 0)
        self.assertEqual(view.animator.display_hint, "memory")


class RegistrationTests(unittest.TestCase):
    def test_registry_exposes_overlay(self) -> None:
        self.assertIn("bolttagu-2d", overlay_ids())
        self.assertEqual(OVERLAYS["bolttagu-2d"].backend, "tk-sprite-sheet")
        self.assertEqual(OVERLAYS["bolttagu-2d"].factory, "create_bolttagu_2d")


if __name__ == "__main__":
    unittest.main()
