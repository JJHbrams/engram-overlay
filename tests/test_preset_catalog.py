"""The bundled preset roster, and the listing built from it.

The registry is the single source of truth for a preset's display name: the CLI
listing and both install scripts read it from there instead of keeping their own
copy. These tests guard that roster and its agreement with the reference
manifests under manifests/.
"""

import contextlib
import io
import re
import unittest
from pathlib import Path

from engram_overlay.__main__ import main
from engram_overlay.registry import OVERLAYS, format_catalog, overlay_catalog, overlay_ids

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "manifests"


def manifest_field(path: Path, field: str) -> str:
    """Read one top-level scalar without requiring PyYAML in the test environment."""
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^{field}:\s*(.+?)\s*$", line)
        if match:
            return match.group(1).strip().strip('"').strip("'")
    raise AssertionError(f"{path} has no {field}")


class CatalogTests(unittest.TestCase):
    def test_catalog_is_ordered_by_id_and_covers_every_overlay(self) -> None:
        catalog = overlay_catalog()
        self.assertEqual(tuple(spec.id for spec in catalog), overlay_ids())
        self.assertEqual(len(catalog), len(OVERLAYS))

    def test_every_preset_has_a_name_and_a_summary(self) -> None:
        for spec in overlay_catalog():
            with self.subTest(overlay=spec.id):
                self.assertTrue(spec.name.strip(), "display name must not be empty")
                self.assertTrue(spec.summary.strip(), "summary must not be empty")
                self.assertNotEqual(spec.name, spec.id, "name should be a label, not the id")

    def test_display_names_are_unique(self) -> None:
        names = [spec.name for spec in overlay_catalog()]
        self.assertEqual(len(names), len(set(names)))

    def test_registry_names_match_the_reference_manifests(self) -> None:
        """A new preset must not leave manifests/ and the packaged roster disagreeing."""
        for spec in overlay_catalog():
            manifest = MANIFEST_DIR / spec.id / "manifest.yaml"
            with self.subTest(overlay=spec.id):
                self.assertTrue(manifest.is_file(), f"missing {manifest}")
                self.assertEqual(manifest_field(manifest, "id"), spec.id)
                self.assertEqual(manifest_field(manifest, "name"), spec.name)

    def test_every_reference_manifest_has_a_registry_entry(self) -> None:
        on_disk = {path.parent.name for path in MANIFEST_DIR.glob("*/manifest.yaml")}
        self.assertEqual(on_disk, set(overlay_ids()))


class FormatCatalogTests(unittest.TestCase):
    def test_listing_names_every_preset(self) -> None:
        rendered = format_catalog()
        for spec in overlay_catalog():
            with self.subTest(overlay=spec.id):
                self.assertIn(spec.id, rendered)
                self.assertIn(spec.name, rendered)
                self.assertIn(spec.backend, rendered)

    def test_listing_reports_the_preset_count(self) -> None:
        self.assertIn(f"({len(overlay_ids())})", format_catalog())

    def test_ids_are_column_aligned(self) -> None:
        lines = [line for line in format_catalog().splitlines() if line.startswith("  bolttagu-2d")]
        self.assertEqual(len(lines), 1)
        width = max(len(spec.id) for spec in overlay_catalog())
        self.assertTrue(lines[0].startswith("  " + "bolttagu-2d".ljust(width) + "  "))


class ListOverlaysCliTests(unittest.TestCase):
    def test_flag_prints_the_catalog_and_exits_cleanly(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["--list-overlays"])
        self.assertEqual(code, 0)
        self.assertIn("Bundled overlay presets", stream.getvalue())

    def test_flag_emits_no_handshake(self) -> None:
        """It exits before a transport exists, so no JSONL may reach stdout."""
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            main(["--list-overlays"])
        self.assertNotIn("overlay.hello", stream.getvalue())
        self.assertNotIn("schema_version", stream.getvalue())

    def test_flag_ignores_an_overlay_selection(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["--overlay", "xeyes", "--list-overlays"])
        self.assertEqual(code, 0)
        self.assertIn("bolttagu-2d", stream.getvalue())


class InstallScriptTests(unittest.TestCase):
    """Neither script may carry its own copy of the roster."""

    def setUp(self) -> None:
        scripts = REPO_ROOT / "scripts"
        self.dev = (scripts / "install-dev.ps1").read_text(encoding="utf-8")
        self.runtime = (scripts / "install-runtime.ps1").read_text(encoding="utf-8")

    def scripts(self):
        return (("dev", self.dev), ("runtime", self.runtime))

    def test_both_scripts_read_the_registry_instead_of_hardcoding_ids(self) -> None:
        for name, source in self.scripts():
            with self.subTest(script=name):
                self.assertIn("overlay_catalog", source)
                # A ValidateSet over overlay ids is exactly the copy that used to drift.
                self.assertNotIn('ValidateSet("xeyes"', source)

    def test_both_scripts_can_install_the_presentation_flag(self) -> None:
        """Without this there is no supported way to opt into Engram's launcher."""
        for name, source in self.scripts():
            with self.subTest(script=name):
                self.assertRegex(source, r"\[switch\]\$Presentation")
                self.assertIn('"--presentation"', source)

    def test_neither_script_writes_a_v1_manifest(self) -> None:
        """v2 never spawns a renderer, so a spawn manifest is a dead file that
        still names whichever checkout wrote it."""
        for name, source in self.scripts():
            with self.subTest(script=name):
                self.assertNotIn("schema_version: 1", source)

    def test_the_runtime_install_does_not_link_the_checkout(self) -> None:
        """An editable install would leave the runtime broken the moment this
        repository is moved or deleted."""
        self.assertNotRegex(self.runtime, r"pip install.*\s-e\s")

    def test_the_runtime_install_offers_autostart_both_ways(self) -> None:
        self.assertRegex(self.runtime, r"\[switch\]\$Autostart")
        self.assertRegex(self.runtime, r"\[switch\]\$RemoveAutostart")

    def test_the_legacy_cleanup_removes_manifests_and_nothing_else(self) -> None:
        """mapping.json next to a manifest is hand-built state, not litter."""
        self.assertRegex(self.runtime, r"\[switch\]\$RemoveLegacyManifests")
        self.assertIn("Remove-Item -LiteralPath $manifest -Force", self.runtime)
        self.assertNotRegex(self.runtime, r"Remove-Item.*-Recurse")


if __name__ == "__main__":
    unittest.main()
