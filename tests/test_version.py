import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engram_overlay import _version


class VersionTests(unittest.TestCase):
    def test_version_uses_three_part_file_and_explicit_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "VERSION").write_text("2.3.4\n", encoding="utf-8")
            with patch.object(_version, "_repository_root", return_value=Path(temp_dir)):
                self.assertEqual(_version._base_version(), "2.3.4")
        with patch.dict(os.environ, {"SEMVER4_BUILD": "321"}):
            self.assertEqual(_version._build_number(), 321)

    def test_build_number_respects_file_version_limit(self) -> None:
        with patch.dict(os.environ, {"SEMVER4_BUILD": "99999"}):
            self.assertEqual(_version._build_number(), 65534)


if __name__ == "__main__":
    unittest.main()
