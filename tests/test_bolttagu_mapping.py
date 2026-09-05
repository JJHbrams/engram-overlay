import json, tempfile, unittest
from pathlib import Path

from engram_overlay.overlays.bolttagu_2d import (
    CATEGORY_POSES,
    CLIPS,
    HINT_ONESHOTS,
    IDLE_POSE,
    LIFECYCLE_TRANSITIONS,
    REFINABLE_CATEGORIES,
    STATE_POSES,
    BolttaguAnimator,
    load_mapping,
    pose_for,
)


class MappingOverrideTests(unittest.TestCase):
    """A user-chosen mapping must be honoured, and a bad one must never bite."""

    def write(self, document: object) -> Path:
        path = Path(tempfile.mkdtemp()) / "mapping.json"
        path.write_text(
            document if isinstance(document, str) else json.dumps(document), encoding="utf-8"
        )
        return path

    def load(self, document: object):
        notes: list[str] = []
        mapping = load_mapping(self.write(document), log=notes.append)
        self.oneshots = mapping.oneshots
        self.lifecycle = mapping.lifecycle
        return mapping.hints, mapping.categories, notes

    def test_absent_file_keeps_the_defaults(self) -> None:
        mapping = load_mapping(Path(tempfile.mkdtemp()) / "nope.json")
        self.assertEqual(mapping.hints, STATE_POSES)
        self.assertEqual(mapping.categories, CATEGORY_POSES)
        self.assertEqual(mapping.oneshots, HINT_ONESHOTS)
        self.assertEqual(mapping.lifecycle, LIFECYCLE_TRANSITIONS)

    def test_the_launcher_transitions_are_choosable(self) -> None:
        """overlay.show and overlay.hide are events too; what each plays is a choice."""
        self.load({"lifecycle": {"show": "success", "hide": "waiting"}})
        self.assertEqual(self.lifecycle, {"show": "success", "hide": "waiting"})

    def test_an_unknown_transition_is_refused(self) -> None:
        _, _, notes = self.load({"lifecycle": {"teleport": "enter"}})
        self.assertEqual(self.lifecycle, LIFECYCLE_TRANSITIONS)
        self.assertTrue(notes)

    def test_a_transition_needs_a_real_clip(self) -> None:
        """idle is layered, not a clip, so it cannot be a transition."""
        for clip in ("idle", "nonsense", None):
            with self.subTest(clip=clip):
                _, _, notes = self.load({"lifecycle": {"show": clip}})
                self.assertEqual(self.lifecycle, LIFECYCLE_TRANSITIONS)
                self.assertTrue(notes)

    def test_the_view_plays_the_chosen_transitions(self) -> None:
        from engram_overlay.overlays import bolttagu_2d

        path = self.write({"lifecycle": {"show": "success", "hide": "waiting"}})
        view = bolttagu_2d.Bolttagu2dView(launcher_managed=True, mapping_path=path)
        self.assertEqual(view.begin_enter(), CLIPS["success"].total_ms)
        self.assertEqual(view.animator.oneshot, "success")
        self.assertEqual(view.begin_exit(), CLIPS["waiting"].total_ms)
        self.assertEqual(view.animator.oneshot, "waiting")

    def test_success_keeps_its_flourish_by_default(self) -> None:
        """The success sprite is a one-shot layered over the settle pose."""
        self.assertEqual(HINT_ONESHOTS["success"], "success")
        self.assertEqual(STATE_POSES["success"], IDLE_POSE)

    def test_a_flourish_can_be_moved_to_another_hint(self) -> None:
        self.load({"oneshots": {"click": "success"}})
        self.assertEqual(self.oneshots["click"], "success")
        self.assertEqual(self.oneshots["success"], "success")

    def test_a_flourish_can_be_turned_off(self) -> None:
        _, _, notes = self.load({"oneshots": {"success": None}})
        self.assertNotIn("success", self.oneshots)
        self.assertEqual(notes, [])

    def test_a_looping_clip_cannot_be_a_flourish(self) -> None:
        _, _, notes = self.load({"oneshots": {"success": "wondering"}})
        self.assertEqual(self.oneshots, HINT_ONESHOTS)
        self.assertTrue(notes)

    def test_lifecycle_clips_may_also_be_a_flourish(self) -> None:
        """The launcher's own transition still overrides while it runs, so reusing
        the clip on a hint cannot fight overlay.show/hide."""
        for clip in ("enter", "exit"):
            with self.subTest(clip=clip):
                _, _, notes = self.load({"oneshots": {"idle": clip}})
                self.assertEqual(self.oneshots["idle"], clip)
                self.assertEqual(notes, [])

    def test_a_looping_clip_is_still_refused_as_a_flourish(self) -> None:
        _, _, notes = self.load({"oneshots": {"idle": "wondering"}})
        self.assertNotIn("idle", self.oneshots)
        self.assertTrue(notes)

    def test_a_flourish_plays_once_then_settles(self) -> None:
        hints, categories, _ = self.load({"oneshots": {"click": "success"}})
        animator = BolttaguAnimator(
            started_ms=0, intro=None, hints=hints, categories=categories, oneshots=self.oneshots
        )
        animator.apply_hint("click", 0)
        self.assertEqual(animator.resolve(0), (("success", 0),))
        self.assertEqual(animator.resolve(1_200), (("alert", 0),))

    def test_a_chosen_hint_wins(self) -> None:
        hints, _, notes = self.load({"hints": {"input": "wondering"}})
        self.assertEqual(hints["input"], "wondering")
        self.assertEqual(notes, [])

    def test_untouched_entries_keep_their_default(self) -> None:
        hints, categories, _ = self.load({"hints": {"input": "wondering"}})
        self.assertEqual(hints["search"], STATE_POSES["search"])
        self.assertEqual(categories, CATEGORY_POSES)

    def test_unreachable_categories_are_refused_with_a_pointer(self) -> None:
        """search and memory arrive as their own hints, never alongside generating,
        so a category entry for them could never fire."""
        for key in ("search", "memory"):
            with self.subTest(category=key):
                _, categories, notes = self.load({"categories": {key: "waiting"}})
                self.assertNotIn(key, categories)
                self.assertEqual(len(notes), 1)
                self.assertIn("hint instead", notes[0])

    def test_every_refinable_category_is_accepted(self) -> None:
        for key in REFINABLE_CATEGORIES:
            with self.subTest(category=key):
                _, categories, notes = self.load({"categories": {key: "waiting"}})
                self.assertEqual(categories[key], "waiting")
                self.assertEqual(notes, [])

    def test_the_hint_decides_for_search_and_memory(self) -> None:
        """Setting the hint is the only thing that moves those two."""
        hints, categories, _ = self.load({"hints": {"search": "waiting"}})
        animator = BolttaguAnimator(started_ms=0, intro=None, hints=hints, categories=categories)
        animator.apply_hint("search", 0, "search")
        self.assertEqual(animator.resolve(0), (("waiting", 0),))

    def test_a_chosen_category_wins(self) -> None:
        _, categories, notes = self.load({"categories": {"read": "waiting"}})
        self.assertEqual(categories["read"], "waiting")
        self.assertEqual(notes, [])

    def test_idle_is_a_selectable_pose(self) -> None:
        hints, _, notes = self.load({"hints": {"error": "idle"}})
        self.assertEqual(hints["error"], "idle")
        self.assertEqual(notes, [])

    def test_a_one_shot_can_back_a_hint_and_holds_its_last_frame(self) -> None:
        """Every bundled clip is selectable; a non-looping one just stands still
        on its final frame for as long as the state lasts."""
        for pose in ("enter", "exit", "success"):
            with self.subTest(pose=pose):
                hints, categories, notes = self.load({"hints": {"click": pose}})
                self.assertEqual(hints["click"], pose)
                self.assertEqual(notes, [])
                animator = BolttaguAnimator(
                    started_ms=0, intro=None, hints=hints, categories=categories
                )
                animator.apply_hint("click", 0)
                self.assertEqual(animator.resolve(0), ((pose, 0),))
                self.assertEqual(animator.resolve(60_000), ((pose, 2),))

    def test_unknown_names_are_reported_and_dropped(self) -> None:
        hints, categories, notes = self.load(
            {"hints": {"teleporting": "idle", "idle": "nonsense"}, "categories": {"bogus": "idle"}}
        )
        self.assertEqual(hints, STATE_POSES)
        self.assertEqual(categories, CATEGORY_POSES)
        self.assertEqual(len(notes), 3)

    def test_broken_json_falls_back_without_raising(self) -> None:
        hints, categories, notes = self.load("{ not json")
        self.assertEqual(hints, STATE_POSES)
        self.assertEqual(categories, CATEGORY_POSES)
        self.assertTrue(notes)

    def test_wrong_shapes_fall_back(self) -> None:
        for document in ([1, 2], {"hints": "listening"}):
            with self.subTest(document=document):
                hints, _, notes = self.load(document)
                self.assertEqual(hints, STATE_POSES)
                self.assertTrue(notes)

    def test_the_animator_draws_the_chosen_pose(self) -> None:
        hints, categories, _ = self.load(
            {"hints": {"input": "wondering"}, "categories": {"write": "searching"}}
        )
        animator = BolttaguAnimator(started_ms=0, intro=None, hints=hints, categories=categories)
        animator.apply_hint("input", 0)
        self.assertEqual(animator.resolve(0), (("wondering", 0),))
        animator.apply_hint("generating", 0, "write")
        self.assertEqual(animator.resolve(0), (("searching", 0),))

    def test_every_pose_the_picker_offers_is_accepted(self) -> None:
        """The preview page lists idle plus the looping clips; all must load."""
        offered = [IDLE_POSE] + [name for name, clip in CLIPS.items() if clip.loop]
        hints, _, notes = self.load({"hints": {"idle": pose} for pose in offered[:1]})
        self.assertEqual(notes, [])
        for pose in offered:
            with self.subTest(pose=pose):
                hints, _, notes = self.load({"hints": {"thought": pose}})
                self.assertEqual(hints["thought"], pose)
                self.assertEqual(notes, [])

    def test_pose_for_defaults_to_the_built_in_tables(self) -> None:
        self.assertEqual(pose_for("search", None), STATE_POSES["search"])


if __name__ == "__main__":
    unittest.main()
