import json
import random
import unittest

from engram_overlay.overlays import bolttagu_2d
from engram_overlay.overlays.bolttagu_2d import (
    ASSET_DIR,
    BLINK_INTERVAL_MS,
    CLIPS,
    EYE_CELLS,
    HINT_ONESHOTS,
    IDLE_POSE,
    STATE_POSES,
    SCALE_RANGE,
    STEAM_CELLS,
    BlinkTimeline,
    BolttaguAnimator,
    Clip,
    clip_cell,
    facing_mirrored,
    load_atlas,
    scaled_cell,
    steam_cell,
)
from engram_overlay.protocol import DISPLAY_HINTS
from engram_overlay.registry import OVERLAYS, create_overlay, overlay_ids
from engram_overlay.state import OverlayState


class FixedIntervalRandom(random.Random):
    """Random source whose blink gaps are predictable but still range-checked."""

    def __init__(self, interval: int) -> None:
        super().__init__(0)
        self.interval = interval
        self.calls = 0

    def randint(self, a: int, b: int) -> int:  # type: ignore[override]
        assert (a, b) == BLINK_INTERVAL_MS
        self.calls += 1
        return self.interval


class ClipTests(unittest.TestCase):
    def test_rejects_mismatched_durations(self) -> None:
        with self.assertRaises(ValueError):
            Clip(sheet="alert", cells=(0, 1), durations_ms=(100,), loop=True)

    def test_rejects_empty_clip(self) -> None:
        with self.assertRaises(ValueError):
            Clip(sheet="alert", cells=(), durations_ms=(), loop=True)

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


class SteamTests(unittest.TestCase):
    def test_steam_runs_a_24_frame_ten_fps_loop(self) -> None:
        self.assertEqual(steam_cell(0), 0)
        self.assertEqual(steam_cell(99), 0)
        self.assertEqual(steam_cell(100), 1)
        self.assertEqual(steam_cell(2_300), 23)
        self.assertEqual(steam_cell(2_400), 0)

    def test_negative_elapsed_clamps(self) -> None:
        self.assertEqual(steam_cell(-500), 0)


class BlinkTests(unittest.TestCase):
    def test_eyes_stay_open_until_the_scheduled_blink(self) -> None:
        blink = BlinkTimeline(rng=FixedIntervalRandom(3_000), started_ms=0)
        self.assertEqual(blink.eye(0), "open")
        self.assertEqual(blink.eye(2_999), "open")

    def test_blink_runs_half_closed_half_then_reopens(self) -> None:
        blink = BlinkTimeline(rng=FixedIntervalRandom(3_000), started_ms=0)
        self.assertEqual(blink.eye(3_000), "half")
        self.assertEqual(blink.eye(3_049), "half")
        self.assertEqual(blink.eye(3_050), "closed")
        self.assertEqual(blink.eye(3_139), "closed")
        self.assertEqual(blink.eye(3_140), "half")
        self.assertEqual(blink.eye(3_209), "half")
        self.assertEqual(blink.eye(3_210), "open")

    def test_next_blink_is_rescheduled_after_completion(self) -> None:
        rng = FixedIntervalRandom(3_000)
        blink = BlinkTimeline(rng=rng, started_ms=0)
        self.assertEqual(rng.calls, 1)
        blink.eye(3_210)
        self.assertEqual(rng.calls, 2)
        self.assertEqual(blink.eye(6_209), "open")
        self.assertEqual(blink.eye(6_210), "half")

    def test_a_long_stall_does_not_stretch_the_blink(self) -> None:
        blink = BlinkTimeline(rng=FixedIntervalRandom(3_000), started_ms=0)
        # One tick arrives well past the whole blink; it must already be over.
        self.assertEqual(blink.eye(30_000), "open")

    def test_reset_rearms_from_the_given_instant(self) -> None:
        blink = BlinkTimeline(rng=FixedIntervalRandom(2_500), started_ms=0)
        blink.reset(10_000)
        self.assertEqual(blink.eye(12_499), "open")
        self.assertEqual(blink.eye(12_500), "half")

    def test_default_random_source_stays_inside_the_pack_interval(self) -> None:
        blink = BlinkTimeline(rng=random.Random(7), started_ms=0)
        low, high = BLINK_INTERVAL_MS
        for _ in range(50):
            blink.reset(0)
            self.assertGreaterEqual(blink._next_blink_ms, low)
            self.assertLessEqual(blink._next_blink_ms, high)


class ScaleTests(unittest.TestCase):
    def test_identity_scale_returns_the_cell_untouched(self) -> None:
        self.assertEqual(scaled_cell((270, 302), 1.0), (270, 302))

    def test_scaling_rounds_both_axes(self) -> None:
        self.assertEqual(scaled_cell((270, 302), 2.0), (540, 604))
        self.assertEqual(scaled_cell((270, 302), 0.5), (135, 151))
        self.assertEqual(scaled_cell((270, 302), 1.5), (405, 453))

    def test_out_of_range_scales_are_rejected(self) -> None:
        low, high = SCALE_RANGE
        for bad in (0.0, -1.0, low - 0.01, high + 0.01):
            with self.subTest(scale=bad), self.assertRaises(ValueError):
                scaled_cell((270, 302), bad)

    def test_range_bounds_themselves_are_allowed(self) -> None:
        for good in SCALE_RANGE:
            with self.subTest(scale=good):
                self.assertGreater(scaled_cell((270, 302), good)[0], 0)


class FacingTests(unittest.TestCase):
    def test_pointer_on_the_right_mirrors_the_sprite(self) -> None:
        self.assertTrue(facing_mirrored(500, 100, 270, current=False))

    def test_pointer_on_the_left_keeps_the_native_orientation(self) -> None:
        self.assertFalse(facing_mirrored(0, 100, 270, current=True))

    def test_deadzone_around_the_centre_holds_the_current_side(self) -> None:
        centre = 100 + 270 // 2
        self.assertTrue(facing_mirrored(centre + 10, 100, 270, current=True))
        self.assertFalse(facing_mirrored(centre + 10, 100, 270, current=False))
        self.assertTrue(facing_mirrored(centre - 10, 100, 270, current=True))

    def test_window_position_is_taken_into_account(self) -> None:
        # Same pointer, window moved past it: the sprite must turn around.
        self.assertTrue(facing_mirrored(700, 400, 270, current=False))
        self.assertFalse(facing_mirrored(700, 900, 270, current=True))


class StateMappingTests(unittest.TestCase):
    def test_every_display_hint_is_mapped(self) -> None:
        self.assertEqual(set(STATE_POSES), set(DISPLAY_HINTS))

    def test_hints_only_resolve_to_idle_or_a_looping_clip(self) -> None:
        for hint, pose in STATE_POSES.items():
            with self.subTest(hint=hint):
                if pose != IDLE_POSE:
                    self.assertTrue(CLIPS[pose].loop)

    def test_oneshot_targets_are_non_looping_clips(self) -> None:
        for hint, name in HINT_ONESHOTS.items():
            with self.subTest(hint=hint):
                self.assertIn(hint, STATE_POSES)
                self.assertFalse(CLIPS[name].loop)


class AnimatorTests(unittest.TestCase):
    def animator(self, *, intro: str | None = None, interval: int = 3_000) -> BolttaguAnimator:
        return BolttaguAnimator(started_ms=0, intro=intro, rng=FixedIntervalRandom(interval))

    def test_rejects_an_unknown_intro(self) -> None:
        with self.assertRaises(ValueError):
            BolttaguAnimator(intro="pirouette")

    def test_idle_layers_blink_over_steam(self) -> None:
        animator = self.animator()
        self.assertEqual(
            animator.resolve(0),
            (("idle", EYE_CELLS["open"]), ("steam", 0)),
        )
        self.assertEqual(
            animator.resolve(3_050),
            (("idle", EYE_CELLS["closed"]), ("steam", steam_cell(3_050))),
        )

    def test_steam_and_blink_advance_independently(self) -> None:
        animator = self.animator()
        eyes = {animator.resolve(t)[0][1] for t in range(0, 2_400, 100)}
        steams = {animator.resolve(t)[1][1] for t in range(0, 2_400, 100)}
        self.assertEqual(eyes, {EYE_CELLS["open"]})  # no blink scheduled yet
        self.assertEqual(len(steams), STEAM_CELLS)

    def test_intro_plays_once_then_falls_back_to_idle(self) -> None:
        animator = self.animator(intro="enter")
        self.assertEqual(animator.resolve(0), (("enter", 0),))
        self.assertEqual(animator.resolve(250), (("enter", 1),))
        recipe = animator.resolve(800)
        self.assertEqual(recipe[0][0], "idle")
        self.assertIsNone(animator.oneshot)

    def test_intro_rearms_the_blink_when_it_retires(self) -> None:
        rng = FixedIntervalRandom(3_000)
        animator = BolttaguAnimator(started_ms=0, intro="enter", rng=rng)
        self.assertEqual(rng.calls, 1)
        animator.resolve(800)
        self.assertEqual(rng.calls, 2)

    def test_thinking_hints_run_the_wondering_loop(self) -> None:
        animator = self.animator()
        animator.apply_hint("thought", 5_000)
        self.assertEqual(animator.resolve(5_000), (("wondering", 0),))
        self.assertEqual(animator.resolve(5_300), (("wondering", 3),))
        self.assertEqual(animator.resolve(5_800), (("wondering", 0),))

    def test_hint_restart_is_ignored_while_unchanged(self) -> None:
        animator = self.animator()
        animator.apply_hint("search", 1_000)
        animator.apply_hint("search", 1_400)
        self.assertEqual(animator.state_started_ms, 1_000)
        self.assertEqual(animator.resolve(1_400), (("wondering", 4),))

    def test_unknown_hint_falls_back_to_idle(self) -> None:
        animator = self.animator()
        animator.apply_hint("teleporting", 100)
        self.assertEqual(animator.display_hint, "idle")
        self.assertEqual(animator.pose, IDLE_POSE)

    def test_returning_to_idle_rearms_the_blink(self) -> None:
        rng = FixedIntervalRandom(3_000)
        animator = BolttaguAnimator(started_ms=0, intro=None, rng=rng)
        animator.apply_hint("thought", 1_000)
        self.assertEqual(rng.calls, 1)
        animator.apply_hint("idle", 2_000)
        self.assertEqual(rng.calls, 2)
        self.assertEqual(animator.resolve(4_999)[0][1], EYE_CELLS["open"])
        self.assertEqual(animator.resolve(5_000)[0][1], EYE_CELLS["half"])

    def test_moving_between_two_idle_hints_does_not_rearm_the_blink(self) -> None:
        rng = FixedIntervalRandom(3_000)
        animator = BolttaguAnimator(started_ms=0, intro=None, rng=rng)
        animator.apply_hint("success", 1_000)
        self.assertEqual(animator.pose, IDLE_POSE)
        self.assertEqual(rng.calls, 1)

    def test_provider_error_plays_the_exit_wave_then_holds_alert(self) -> None:
        animator = self.animator()
        animator.apply_hint("provider_error", 2_000)
        self.assertEqual(animator.resolve(2_000), (("exit", 0),))
        self.assertEqual(animator.resolve(2_450), (("exit", 2),))
        self.assertEqual(animator.resolve(2_700), (("alert", 0),))

    def test_hover_and_click_use_the_alert_pose(self) -> None:
        animator = self.animator()
        animator.apply_hint("hover", 0)
        self.assertEqual(animator.resolve(10), (("alert", 0),))
        animator.apply_hint("click", 20)
        self.assertEqual(animator.resolve(30), (("alert", 0),))


class AtlasTests(unittest.TestCase):
    def test_metadata_matches_bundled_sheet_sizes(self) -> None:
        sheets, cell = load_atlas()
        self.assertEqual(cell, (270, 302))
        self.assertEqual(len(sheets["idle"]), len(EYE_CELLS))
        self.assertEqual(len(sheets["steam"]), STEAM_CELLS)
        self.assertEqual(len(sheets["alert"]), 1)
        self.assertEqual(len(sheets["wondering"]), 8)
        self.assertEqual(len(sheets["enter"]), 3)
        self.assertEqual(len(sheets["exit"]), 3)
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
        self.assertEqual(metadata["source"], "sprite-pack-v8")
        self.assertEqual(metadata["sourceCanvas"], [1254, 1254])
        self.assertEqual(metadata["scale"], 0.25)
        self.assertEqual(metadata["crop"], [87, 13, 1167, 1219])
        self.assertEqual(metadata["feetAnchor"], [166, 267])

    def test_bundled_assets_stay_small(self) -> None:
        total = sum(path.stat().st_size for path in ASSET_DIR.glob("*.png"))
        self.assertLess(total, 1_500_000)


class ViewTests(unittest.TestCase):
    def view(self, **kwargs: object) -> bolttagu_2d.Bolttagu2dView:
        kwargs.setdefault("rng", FixedIntervalRandom(3_000))
        return bolttagu_2d.Bolttagu2dView(**kwargs)  # type: ignore[arg-type]

    def test_canvas_size_matches_the_atlas_cell(self) -> None:
        view = self.view()
        self.assertEqual((view.width, view.height), (270, 302))
        self.assertIsNone(view.drawn)

    def test_idle_frame_composites_steam_over_the_blink_layer(self) -> None:
        view = self.view()
        recipe = (("idle", EYE_CELLS["open"]), ("steam", 5))
        composed = view.compose(recipe, False)
        self.assertEqual(composed.size, (270, 302))
        self.assertNotEqual(composed.tobytes(), view.sheets["idle"][0].tobytes())

    def test_mirrored_frame_is_the_horizontal_flip(self) -> None:
        view = self.view()
        recipe = (("wondering", 0),)
        plain = view.compose(recipe, False)
        mirrored = view.compose(recipe, True)
        self.assertEqual(plain.size, mirrored.size)
        self.assertNotEqual(plain.tobytes(), mirrored.tobytes())
        self.assertEqual(
            mirrored.transpose(bolttagu_2d.Image.Transpose.FLIP_LEFT_RIGHT).tobytes(),
            plain.tobytes(),
        )

    def test_compose_does_not_mutate_the_source_cells(self) -> None:
        view = self.view()
        before = view.sheets["idle"][0].tobytes()
        view.compose((("idle", 0), ("steam", 3)), True)
        self.assertEqual(view.sheets["idle"][0].tobytes(), before)

    def test_floor_option_composites_without_changing_geometry(self) -> None:
        floored = self.view(show_floor=True)
        plain = self.view()
        self.assertEqual((floored.width, floored.height), (270, 302))
        self.assertIsNotNone(floored.floor)
        self.assertIsNone(plain.floor)
        recipe = (("alert", 0),)
        self.assertNotEqual(
            floored.compose(recipe, False).tobytes(),
            plain.compose(recipe, False).tobytes(),
        )

    def test_tick_turns_the_sprite_toward_the_pointer(self) -> None:
        view = self.view()
        view.tick(10_000, 0, 0, 0)
        self.assertTrue(view.mirrored)
        view.tick(-10_000, 0, 0, 0)
        self.assertFalse(view.mirrored)

    def test_face_pointer_can_be_disabled(self) -> None:
        view = self.view(face_pointer=False)
        view.tick(10_000, 0, 0, 0)
        self.assertFalse(view.mirrored)

    def test_scale_changes_the_window_and_the_composed_frame(self) -> None:
        view = self.view(scale=2.0)
        self.assertEqual((view.width, view.height), (540, 604))
        self.assertEqual(view.cell, (270, 302))
        self.assertEqual(view.compose((("alert", 0),), False).size, (540, 604))

    def test_scale_does_not_resize_the_cached_cells(self) -> None:
        # Only the finished frame is resized, so memory does not grow with scale.
        view = self.view(scale=3.0)
        self.assertEqual(view.sheets["alert"][0].size, (270, 302))

    def test_default_scale_leaves_the_frame_at_native_size(self) -> None:
        view = self.view()
        self.assertEqual((view.width, view.height), (270, 302))
        self.assertEqual(view.compose((("alert", 0),), False).size, (270, 302))

    def test_scale_and_mirroring_compose_together(self) -> None:
        view = self.view(scale=0.5)
        frame = view.compose((("wondering", 0),), True)
        self.assertEqual(frame.size, (135, 151))

    def test_invalid_scale_is_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            self.view(scale=99.0)

    def test_apply_state_is_safe_before_mount(self) -> None:
        view = self.view()
        state = OverlayState()
        state.display_hint = "memory"
        view.apply_state(state)
        view.tick(0, 0, 0, 0)
        self.assertEqual(view.animator.display_hint, "memory")
        self.assertIsNone(view.drawn)


class RegistrationTests(unittest.TestCase):
    def test_registry_exposes_overlay(self) -> None:
        self.assertIn("bolttagu-2d", overlay_ids())
        self.assertEqual(OVERLAYS["bolttagu-2d"].backend, "tk-sprite-sheet")
        self.assertEqual(OVERLAYS["bolttagu-2d"].factory, "create_bolttagu_2d")

    def test_face_pointer_is_rejected_for_other_overlays(self) -> None:
        with self.assertRaises(ValueError):
            create_overlay("xeyes", None, "observer", face_pointer=False)  # type: ignore[arg-type]

    def test_scale_is_rejected_for_other_overlays(self) -> None:
        with self.assertRaises(ValueError):
            create_overlay("xeyes", None, "observer", scale=2.0)  # type: ignore[arg-type]

    def test_cli_rejects_scale_for_other_overlays(self) -> None:
        import contextlib
        import io

        from engram_overlay.__main__ import main

        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--overlay", "xeyes", "--scale", "2.0"])

    def test_cli_rejects_no_face_pointer_for_other_overlays(self) -> None:
        import contextlib
        import io

        from engram_overlay.__main__ import main

        # argparse writes its usage banner to stderr; keep it out of the test log.
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--overlay", "xeyes", "--no-face-pointer"])


if __name__ == "__main__":
    unittest.main()
