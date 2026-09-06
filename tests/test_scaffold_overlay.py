import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ScaffoldOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = self.root / "src" / "engram_overlay" / "registry.py"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(
            "OVERLAYS: dict[str, OverlaySpec] = {\n}\n\n\ndef overlay_ids() -> tuple[str, ...]:\n    return tuple()\n",
            encoding="utf-8",
        )
        self.roster = self.root / "tests" / "roster.json"
        self.roster.parent.mkdir(parents=True)
        self.roster.write_text("{}\n", encoding="utf-8")
        self.script = Path(__file__).parents[1] / "scripts" / "scaffold-overlay.py"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_scaffold(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (sys.executable, str(self.script), "clock-face", "--name", "Clock Face", "--root", str(self.root), *arguments),
            check=False,
            capture_output=True,
            text=True,
        )

    def test_dry_run_reports_files_without_writing(self) -> None:
        result = self.run_scaffold("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("roster.json", result.stdout)
        self.assertFalse((self.root / "src" / "engram_overlay" / "overlays" / "clock_face.py").exists())

    def test_scaffold_creates_module_test_registry_and_roster_entries(self) -> None:
        result = self.run_scaffold()
        self.assertEqual(result.returncode, 0, result.stderr)
        module = self.root / "src" / "engram_overlay" / "overlays" / "clock_face.py"
        test = self.root / "tests" / "test_clock_face.py"
        self.assertTrue(module.is_file())
        self.assertTrue(test.is_file())
        self.assertIn('"clock-face": OverlaySpec(', self.registry.read_text(encoding="utf-8"))
        self.assertIn("def create_clock_face", module.read_text(encoding="utf-8"))
        compile(module.read_text(encoding="utf-8"), str(module), "exec")
        compile(test.read_text(encoding="utf-8"), str(test), "exec")
        self.assertEqual(
            json.loads(self.roster.read_text(encoding="utf-8")),
            {"clock-face": {"name": "Clock Face", "renderer_id": "engram.clock-face"}},
        )

    def test_scaffold_refuses_to_overwrite_existing_overlay(self) -> None:
        self.assertEqual(self.run_scaffold().returncode, 0)
        result = self.run_scaffold()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite", result.stderr)

    def test_scaffold_rejects_non_kebab_case_id(self) -> None:
        result = subprocess.run(
            (sys.executable, str(self.script), "Clock_Face", "--root", str(self.root)),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lowercase kebab-case", result.stderr)


if __name__ == "__main__":
    unittest.main()
