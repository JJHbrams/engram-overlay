import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from engram_overlay import components


def marker(version: str, selected: list[str]) -> dict[str, object]:
    payloads = sorted(components._closure(components.COMPONENT_PAYLOADS[item] for item in selected))
    return {"schema": 1, "package_version": version, "registry_revision": components.REGISTRY_REVISION, "manifest_sha256": "a" * 64, "ownership": {"owner": "engram", "layout": "generation-venv"}, "installed_components": selected, "installed_payloads": payloads}


class ComponentMarkerTests(unittest.TestCase):
    def test_valid_marker_limits_catalog_without_exposing_cctv_dependency(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(components, "package_version", return_value="1.1.2.154"):
            path = Path(temporary) / components.MARKER_NAME
            path.write_text(json.dumps(marker("1.1.2.154", ["robot-arm-3d-v3"])), encoding="utf-8")
            self.assertEqual(components.read_installed_components(path), frozenset({"robot-arm-3d-v3"}))

    def test_invalid_marker_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / components.MARKER_NAME
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(components.read_installed_components(path), frozenset())

    def test_install_rejects_unknown_selection_before_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                components.install_components(manifest, root, ["unknown"], root / components.MARKER_NAME)

    def test_payload_member_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("../outside.py", b"bad")
            with self.assertRaises(ValueError):
                components._extract_payload("overlay.xeyes", archive, Path(temporary) / "target", [{"path": "../outside.py", "sha256": hashlib.sha256(b"bad").hexdigest(), "size": 3}])
