"""Every sprite overlay must describe itself well enough for the shared picker."""

import importlib
import json
import tempfile
import unittest
from pathlib import Path

from engram_overlay.overlays.spritemap import Layer, Option, Row, Section, SpriteMap, resolve, single
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
