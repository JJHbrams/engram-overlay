"""Verified selectable-component installation and runtime availability guard.

The marker deliberately lives beside a generation's venv, never in user
configuration.  Its presence changes the catalog from a legacy full package to
the explicitly installed component set; an invalid marker is fail-closed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

MARKER_NAME = "engram-overlay-components.json"
SCHEMA_VERSION = 1
REGISTRY_REVISION = "external-overlay-components-v1"
VISIBLE_IDS = (
    "bolttagu-2d", "rabbit-2d", "robot-arm", "robot-arm-3d", "robot-arm-3d-v2", "robot-arm-3d-v3", "xeyes",
)
COMPONENT_PAYLOADS = {
    "bolttagu-2d": "overlay.bolttagu-2d", "rabbit-2d": "overlay.rabbit-2d", "robot-arm": "resource.robot-arm-base",
    "robot-arm-3d": "resource.robot-arm-3d-base", "robot-arm-3d-v2": "resource.robot-arm-3d-v2",
    "robot-arm-3d-v3": "overlay.robot-arm-3d-v3", "xeyes": "overlay.xeyes",
}
PAYLOAD_REQUIRES = {
    "overlay.bolttagu-2d": (), "overlay.rabbit-2d": (), "resource.robot-arm-base": (),
    "resource.robot-arm-3d-base": ("resource.robot-arm-base",),
    "resource.robot-arm-3d-v2": ("resource.robot-arm-3d-base",),
    "overlay.robot-arm-3d-v3": ("resource.robot-arm-3d-v2",), "overlay.xeyes": (),
}
PAYLOAD_PATHS = {
    "overlay.bolttagu-2d": ("overlays/bolttagu_2d.py", "overlays/assets/bolttagu_2d/"), "overlay.rabbit-2d": ("overlays/rabbit_2d.py", "overlays/assets/rabbit_2d/"), "resource.robot-arm-base": ("overlays/robot_arm.py",), "resource.robot-arm-3d-base": ("overlays/robot_arm_3d.py",), "resource.robot-arm-3d-v2": ("overlays/robot_arm_3d_v2.py", "overlays/assets/robot_arm_3d_v2/"), "overlay.robot-arm-3d-v3": ("overlays/robot_arm_3d_v3.py", "overlays/assets/robot_arm_3d_v3/"), "overlay.xeyes": ("overlays/xeyes.py",),
}


def marker_path() -> Path:
    return Path(sys.prefix).parent / MARKER_NAME


def package_version() -> str:
    try:
        return importlib.metadata.version("engram-custom-overlay")
    except importlib.metadata.PackageNotFoundError:
        from ._version import __version__
        return __version__


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _closure(payloads: Iterable[str]) -> set[str]:
    resolved: set[str] = set()
    pending = list(payloads)
    while pending:
        payload = pending.pop()
        if payload in resolved:
            continue
        if payload not in PAYLOAD_REQUIRES:
            raise ValueError(f"unknown payload: {payload}")
        resolved.add(payload)
        pending.extend(PAYLOAD_REQUIRES[payload])
    return resolved


def _full_package_present() -> bool:
    base = Path(__file__).parent / "overlays"
    required = [base / "xeyes.py", base / "bolttagu_2d.py", base / "rabbit_2d.py", base / "robot_arm.py", base / "robot_arm_3d.py", base / "robot_arm_3d_v2.py", base / "robot_arm_3d_v3.py", base / "assets/bolttagu_2d/atlas.json", base / "assets/rabbit_2d/rabbit-states.png", base / "assets/robot_arm_3d_v2/robot-uv-atlas-v2.png", base / "assets/robot_arm_3d_v3/terrain-cover-atlas.png", base / "assets/robot_arm_3d_v3/terrain-ridge.png", base / "assets/robot_arm_3d_v3/traveler-walk-atlas.png"]
    return all(path.is_file() for path in required)


def read_installed_components(path: Path | None = None) -> frozenset[str] | None:
    """Return selected IDs; ``None`` is valid legacy/source full-package mode."""
    path = path or marker_path()
    if not path.exists():
        return None if _full_package_present() else frozenset()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        allowed = {"schema", "package_version", "registry_revision", "manifest_sha256", "ownership", "installed_components", "installed_payloads"}
        if not isinstance(value, dict) or set(value) != allowed:
            raise ValueError("marker fields")
        ownership = value["ownership"]
        if value["schema"] != SCHEMA_VERSION or value["package_version"] != package_version() or value["registry_revision"] != REGISTRY_REVISION:
            raise ValueError("marker identity")
        if not isinstance(value["manifest_sha256"], str) or len(value["manifest_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in value["manifest_sha256"]):
            raise ValueError("marker digest")
        if ownership != {"owner": "engram", "layout": "generation-venv"}:
            raise ValueError("marker ownership")
        components = value["installed_components"]
        payloads = value["installed_payloads"]
        if not isinstance(components, list) or not isinstance(payloads, list) or components != sorted(set(components)) or payloads != sorted(set(payloads)):
            raise ValueError("marker ordering")
        if not all(isinstance(item, str) and item in VISIBLE_IDS for item in components):
            raise ValueError("marker components")
        expected = _closure(COMPONENT_PAYLOADS[item] for item in components)
        if payloads != sorted(expected):
            raise ValueError("marker payload closure")
        return frozenset(components)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return frozenset()


def available_overlay_ids() -> tuple[str, ...]:
    installed = read_installed_components()
    return tuple(sorted(VISIBLE_IDS if installed is None else installed))


def require_installed(overlay_id: str) -> None:
    if overlay_id not in available_overlay_ids():
        raise ValueError(f"overlay is not installed in this runtime: {overlay_id}")


def _safe_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        return None
    return path


def _is_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.stat(), "st_file_attributes", 0) & 0x400)


def _extract_payload(payload_id: str, zip_path: Path, destination: Path, files: list[dict[str, Any]]) -> None:
    expected = {item["path"]: item for item in files}
    allowed = PAYLOAD_PATHS[payload_id]
    if not expected or any(not isinstance(name, str) or not name.startswith("overlays/") or not any(name == prefix or name.startswith(prefix) for prefix in allowed) for name in expected):
        raise ValueError("payload destination is outside its declared package scope")
    package_root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        raw_names = [info.filename for info in infos]
        if len(raw_names) != len(set(raw_names)) or len(raw_names) != len({name.casefold() for name in raw_names}) or any(info.is_dir() for info in infos):
            raise ValueError("unsafe duplicate, case-colliding, or directory payload member")
        names = set(raw_names)
        if names != set(expected):
            raise ValueError(f"payload file set mismatch: {zip_path.name}")
        for info in infos:
            if info.is_dir():
                continue
            relative = _safe_member(info.filename)
            metadata = expected[info.filename]
            if relative is None or info.is_dir() or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("unsafe payload member")
            if info.file_size != metadata["size"]:
                raise ValueError("payload size mismatch")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            if any(_is_reparse(parent) for parent in (target.parent, *target.parent.parents) if parent != package_root.parent):
                raise ValueError("payload destination crosses a reparse point")
            if package_root not in target.resolve(strict=False).parents:
                raise ValueError("payload destination escapes package root")
            if target.exists():
                if _is_reparse(target) or _sha256(target) != metadata["sha256"]:
                    raise ValueError("payload would overwrite an unexpected file")
                continue
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            if _sha256(target) != metadata["sha256"]:
                raise ValueError("payload hash mismatch")


def install_components(manifest_path: Path, payload_root: Path, component_ids: Iterable[str], installed_marker: Path) -> None:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    requested = tuple(sorted(set(component_ids)))
    if not requested or any(item not in VISIBLE_IDS for item in requested):
        raise ValueError("components must be one or more known IDs")
    if manifest.get("schema") != SCHEMA_VERSION or manifest.get("package_version") != package_version() or manifest.get("registry_revision") != REGISTRY_REVISION:
        raise ValueError("manifest does not match installed core wheel")
    components = {item["id"]: item for item in manifest.get("components", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    payloads = {item["id"]: item for item in manifest.get("payloads", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if set(components) != set(VISIBLE_IDS) or any(components[item].get("payloads") != [COMPONENT_PAYLOADS[item]] for item in VISIBLE_IDS):
        raise ValueError("manifest component mapping")
    selected_payloads = _closure(COMPONENT_PAYLOADS[item] for item in requested)
    if not selected_payloads <= set(payloads):
        raise ValueError("manifest payload mapping")
    for payload_id in sorted(selected_payloads):
        payload = payloads[payload_id]
        if payload.get("requires") != list(PAYLOAD_REQUIRES[payload_id]):
            raise ValueError("manifest payload dependencies")
        zip_path = (payload_root / payload["file"]).resolve()
        if payload_root.resolve() not in zip_path.parents or _sha256(zip_path) != payload.get("sha256"):
            raise ValueError("payload archive hash")
        _extract_payload(payload_id, zip_path, Path(__file__).parent, payload.get("files", []))
    marker = {"schema": SCHEMA_VERSION, "package_version": package_version(), "registry_revision": REGISTRY_REVISION, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "ownership": {"owner": "engram", "layout": "generation-venv"}, "installed_components": list(requested), "installed_payloads": sorted(selected_payloads)}
    installed_marker.write_text(json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="install verified Engram overlay component payloads")
    parser.add_argument("install", nargs="?")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--components", required=True)
    parser.add_argument("--installed-marker", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.install != "install":
        parser.error("only the install command is supported")
    install_components(args.manifest, args.payload_root, args.components.split(","), args.installed_marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
