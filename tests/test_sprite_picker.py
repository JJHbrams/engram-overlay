"""Every sprite overlay must describe itself well enough for the shared picker."""

import importlib
import json
import random
import tempfile
import unittest
from pathlib import Path

from engram_overlay.overlays.spritemap import (
    Layer, Option, Rotation, Row, Section, SpriteMap, cell_at, finished, frames_at, resolve, single,
)
from engram_overlay.registry import overlay_catalog

REPO_ROOT = Path(__file__).resolve().parents[1]


def sprite_maps() -> list[SpriteMap]:
    found = []
    for spec in overlay_catalog():
        factory = getattr(importlib.import_module(spec.module), "sprite_map", None)
        if callable(factory):
            found.append(factory())
    return found


class DescriptorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.maps = sprite_maps()

    def test_both_sprite_overlays_describe_themselves(self) -> None:
        self.assertEqual({m.overlay_id for m in self.maps}, {"bolttagu-2d", "rabbit-2d"})

    def test_every_referenced_sheet_exists_and_holds_its_cells(self) -> None:
        for sprite_map in self.maps:
            for name, (file_name, count, columns) in sprite_map.sheets.items():
                with self.subTest(overlay=sprite_map.overlay_id, sheet=name):
                    self.assertTrue((sprite_map.asset_dir / file_name).is_file())
                    self.assertGreaterEqual(columns, 1)
                    self.assertLessEqual(columns, count)

    def test_every_layer_draws_a_cell_the_sheet_has(self) -> None:
        for sprite_map in self.maps:
            for key, option in sprite_map.options.items():
                for layer in option.layers:
                    with self.subTest(overlay=sprite_map.overlay_id, option=key):
                        self.assertIn(layer.sheet, sprite_map.sheets)
                        self.assertLess(max(layer.cells), sprite_map.sheets[layer.sheet][1])

    def test_every_offered_option_is_drawable(self) -> None:
        for sprite_map in self.maps:
            for section in sprite_map.sections:
                for key in section.options:
                    with self.subTest(overlay=sprite_map.overlay_id, option=key):
                        self.assertIn(key, sprite_map.options)

    def test_every_default_is_offered_by_its_own_section(self) -> None:
        """A default the picker cannot show would silently drop on first save."""
        for sprite_map in self.maps:
            for section in sprite_map.sections:
                for row in section.rows:
                    with self.subTest(overlay=sprite_map.overlay_id, row=row.key):
                        for value in row.default:
                            self.assertIn(value, section.options)
                        if not section.allow_empty:
                            self.assertTrue(row.default)
                        if not section.multi:
                            self.assertLessEqual(len(row.default), 1)

    def test_signals_are_unique_within_a_section(self) -> None:
        for sprite_map in self.maps:
            for section in sprite_map.sections:
                keys = [row.key for row in section.rows]
                with self.subTest(overlay=sprite_map.overlay_id, section=section.key):
                    self.assertEqual(len(keys), len(set(keys)))

    def test_refused_keys_are_not_also_offered(self) -> None:
        for sprite_map in self.maps:
            for section in sprite_map.sections:
                for key in section.refused:
                    with self.subTest(overlay=sprite_map.overlay_id, key=key):
                        self.assertNotIn(key, section.by_key)


class ResolveTests(unittest.TestCase):
    def map(self) -> SpriteMap:
        return SpriteMap(
            overlay_id="demo",
            name="Demo",
            cell=(10, 10),
            asset_dir=Path(tempfile.mkdtemp()),
            sheets={"s": ("s.png", 3, 3)},
            options={n: Option(n, (Layer("s", (i,), (100,)),)) for i, n in enumerate("abc")},
            sections=(
                Section("one", "One", (Row("x", default=("a",)),), ("a", "b"),
                        refused={"gone": "moved elsewhere"}),
                Section("many", "Many", (Row("y", default=("a", "b")),), ("a", "b", "c"),
                        multi=True, allow_empty=True),
            ),
        )

    def load(self, document: object):
        path = Path(tempfile.mkdtemp()) / "mapping.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        notes: list[str] = []
        return resolve(self.map(), path, log=notes.append), notes

    def test_defaults_when_no_file(self) -> None:
        missing = Path(tempfile.mkdtemp()) / "nope.json"
        self.assertEqual(resolve(self.map(), missing), {"one": {"x": ("a",)}, "many": {"y": ("a", "b")}})

    def test_single_section_refuses_a_list(self) -> None:
        resolved, notes = self.load({"one": {"x": ["a", "b"]}})
        self.assertEqual(resolved["one"]["x"], ("a",))
        self.assertIn("takes one value", notes[0])

    def test_multi_section_accepts_a_list(self) -> None:
        resolved, notes = self.load({"many": {"y": ["c"]}})
        self.assertEqual(resolved["many"]["y"], ("c",))
        self.assertEqual(notes, [])

    def test_empty_is_refused_unless_allowed(self) -> None:
        resolved, notes = self.load({"one": {"x": None}})
        self.assertEqual(resolved["one"]["x"], ("a",))
        self.assertIn("cannot be empty", notes[0])

    def test_empty_is_kept_where_allowed(self) -> None:
        resolved, notes = self.load({"many": {"y": []}})
        self.assertEqual(resolved["many"]["y"], ())
        self.assertEqual(notes, [])

    def test_a_refused_key_explains_itself(self) -> None:
        _, notes = self.load({"one": {"gone": "a"}})
        self.assertIn("moved elsewhere", notes[0])

    def test_unknown_section_and_signal_are_reported(self) -> None:
        _, notes = self.load({"nope": {"x": "a"}, "one": {"zzz": "a"}})
        self.assertEqual(len(notes), 2)

    def test_a_value_outside_the_section_is_refused(self) -> None:
        resolved, notes = self.load({"one": {"x": "c"}})
        self.assertEqual(resolved["one"]["x"], ("a",))
        self.assertIn("cannot draw", notes[0])

    def test_broken_file_never_raises(self) -> None:
        path = Path(tempfile.mkdtemp()) / "mapping.json"
        path.write_text("{ not json", encoding="utf-8")
        notes: list[str] = []
        self.assertEqual(resolve(self.map(), path, log=notes.append)["one"]["x"], ("a",))
        self.assertTrue(notes)

    def test_single_flattens_and_drops_empties(self) -> None:
        resolved, _ = self.load({"many": {"y": []}})
        self.assertEqual(single(resolved, "one"), {"x": "a"})
        self.assertEqual(single(resolved, "many"), {})


class GeneratorTests(unittest.TestCase):
    def test_the_generator_is_overlay_agnostic(self) -> None:
        """It must find overlays through the registry, not by name."""
        source = (REPO_ROOT / "scripts" / "build-sprite-preview.py").read_text(encoding="utf-8")
        self.assertIn("overlay_catalog", source)
        self.assertIn("sprite_map", source)
        for overlay_id in ("bolttagu", "rabbit"):
            self.assertNotIn(f'"{overlay_id}', source)


if __name__ == "__main__":
    unittest.main()


class HiddenSectionTests(unittest.TestCase):
    """A section can be loadable without being offered in the picker."""

    def test_bolttagu_keeps_its_flourish_out_of_the_picker(self) -> None:
        sprite_map = next(m for m in sprite_maps() if m.overlay_id == "bolttagu-2d")
        hidden = [s for s in sprite_map.sections if s.hidden]
        self.assertEqual([s.key for s in hidden], ["oneshots"])

    def test_a_hidden_section_still_resolves(self) -> None:
        from engram_overlay.overlays.bolttagu_2d import HINT_ONESHOTS, load_mapping

        missing = Path(tempfile.mkdtemp()) / "none.json"
        self.assertEqual(load_mapping(missing).oneshots, HINT_ONESHOTS)

    def test_a_hidden_section_is_still_accepted_from_the_file(self) -> None:
        from engram_overlay.overlays.bolttagu_2d import load_mapping

        path = Path(tempfile.mkdtemp()) / "mapping.json"
        path.write_text(json.dumps({"version": 1, "oneshots": {"click": "success"}}), encoding="utf-8")
        notes: list[str] = []
        self.assertEqual(load_mapping(path, log=notes.append).oneshots["click"], "success")
        self.assertEqual(notes, [])


class GeneratorPayloadTests(unittest.TestCase):
    """The page is seeded from what is installed, and hidden sections stay out."""

    def setUp(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gen", REPO_ROOT / "scripts" / "build-sprite-preview.py"
        )
        self.gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gen)

    def test_hidden_sections_are_not_described(self) -> None:
        sprite_map = next(m for m in sprite_maps() if m.overlay_id == "bolttagu-2d")
        described = {s["key"] for s in self.gen.describe(sprite_map)["sections"]}
        self.assertNotIn("oneshots", described)
        self.assertIn("hints", described)

    def test_every_row_carries_both_default_and_current(self) -> None:
        for sprite_map in sprite_maps():
            payload = self.gen.describe(sprite_map)
            for section in payload["sections"]:
                for row in section["rows"]:
                    with self.subTest(overlay=sprite_map.overlay_id, row=row["key"]):
                        self.assertIn("default", row)
                        self.assertIn("current", row)

    def test_current_follows_an_installed_mapping(self) -> None:
        """Reopening the picker must show the choices in force, not the defaults."""
        sprite_map = next(m for m in sprite_maps() if m.overlay_id == "bolttagu-2d")
        chosen = Path(tempfile.mkdtemp()) / "mapping.json"
        chosen.write_text(json.dumps({"version": 1, "hints": {"thought": "waiting"}}), encoding="utf-8")
        payload = self.gen.describe(sprite_map, chosen)
        hints = next(s for s in payload["sections"] if s["key"] == "hints")
        row = next(r for r in hints["rows"] if r["key"] == "thought")
        self.assertEqual(row["default"], ["wondering"])
        self.assertEqual(row["current"], ["waiting"])
        self.assertTrue(payload["hasMapping"])

    def test_no_installed_mapping_leaves_current_at_the_defaults(self) -> None:
        sprite_map = sprite_maps()[0]
        payload = self.gen.describe(sprite_map, Path(tempfile.mkdtemp()) / "none.json")
        self.assertFalse(payload["hasMapping"])
        for section in payload["sections"]:
            for row in section["rows"]:
                self.assertEqual(row["current"], row["default"])


class RuntimeTests(unittest.TestCase):
    """The timeline both renderers draw from."""

    def layer(self, **kwargs):
        base = {"sheet": "s", "cells": (0, 1, 2), "durations_ms": (100, 100, 100)}
        return Layer(**{**base, **kwargs})

    def test_a_loop_wraps(self) -> None:
        layer = self.layer()
        self.assertEqual([cell_at(layer, t) for t in (0, 100, 250, 300, 350)], [0, 1, 2, 0, 0])

    def test_a_one_shot_holds_its_last_cell(self) -> None:
        layer = self.layer(loop=False)
        self.assertEqual(cell_at(layer, 299), 2)
        self.assertEqual(cell_at(layer, 10_000), 2)

    def test_negative_time_clamps(self) -> None:
        self.assertEqual(cell_at(self.layer(), -500), 0)

    def test_a_held_first_cell_waits_inside_its_range(self) -> None:
        layer = self.layer(durations_ms=(0, 50, 90), hold_ms=(2_500, 6_000))
        first_action = next(t for t in range(0, 20_000, 10) if cell_at(layer, t) != 0)
        self.assertGreaterEqual(first_action, 2_500)
        self.assertLessEqual(first_action, 6_000)

    def test_a_held_cell_is_reproducible_and_seed_dependent(self) -> None:
        layer = self.layer(durations_ms=(0, 50, 90), hold_ms=(2_500, 6_000))
        run = lambda seed: [cell_at(layer, t, seed) for t in range(0, 30_000, 25)]
        self.assertEqual(run(1), run(1))
        self.assertNotEqual(run(1), run(4))

    def test_a_hold_range_must_be_usable(self) -> None:
        for bad in ((0, 100), (500, 100)):
            with self.subTest(hold=bad), self.assertRaises(ValueError):
                self.layer(durations_ms=(0, 50, 90), hold_ms=bad)

    def test_frames_at_returns_every_layer_bottom_first(self) -> None:
        option = Option("x", (self.layer(sheet="a"), self.layer(sheet="b", cells=(5,), durations_ms=(10,))))
        self.assertEqual([sheet for sheet, _ in frames_at(option, 0)], ["a", "b"])

    def test_finished_only_applies_to_a_one_shot(self) -> None:
        self.assertFalse(finished(Option("l", (self.layer(),)), 10_000))
        once = Option("o", (self.layer(loop=False),))
        self.assertFalse(finished(once, 299))
        self.assertTrue(finished(once, 300))

    def test_rotation_holds_a_bucket_and_avoids_an_immediate_repeat(self) -> None:
        rotation = Rotation(random.Random(11))
        first = rotation.pick("k", ("a", "b", "c"), 0)
        self.assertEqual(first, rotation.pick("k", ("a", "b", "c"), 0))
        self.assertNotEqual(first, rotation.pick("k", ("a", "b", "c"), 1))

    def test_rotation_passes_a_lone_candidate_through(self) -> None:
        rotation = Rotation(random.Random(0))
        self.assertEqual({rotation.pick("k", ("a",), b) for b in range(5)}, {"a"})

    def test_rotation_returns_nothing_for_an_empty_choice(self) -> None:
        self.assertIsNone(Rotation(random.Random(0)).pick("k", (), 0))
