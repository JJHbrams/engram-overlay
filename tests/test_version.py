import os
import unittest
from unittest.mock import patch

from engram_overlay import _version


class VersionTests(unittest.TestCase):
    def test_version_uses_three_part_file_and_explicit_build(self) -> None:
        self.assertEqual(_version._base_version(), "1.0.0")
        with patch.dict(os.environ, {"SEMVER4_BUILD": "321"}):
            self.assertEqual(_version._build_number(), 321)

    def test_build_number_respects_file_version_limit(self) -> None:
        with patch.dict(os.environ, {"SEMVER4_BUILD": "99999"}):
            self.assertEqual(_version._build_number(), 65534)


if __name__ == "__main__":
    unittest.main()
