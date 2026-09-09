"""Build the core wheel and local verified component payload archives."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "engram_overlay"
PAYLOADS = {
    "overlay.bolttagu-2d": (["overlays/bolttagu_2d.py", "overlays/assets/bolttagu_2d"], []),
    "overlay.rabbit-2d": (["overlays/rabbit_2d.py", "overlays/assets/rabbit_2d"], []),
    "resource.robot-arm-base": (["overlays/robot_arm.py"], []),
    "resource.robot-arm-3d-base": (["overlays/robot_arm_3d.py"], ["resource.robot-arm-base"]),
    "resource.robot-arm-3d-v2": (["overlays/robot_arm_3d_v2.py", "overlays/assets/robot_arm_3d_v2"], ["resource.robot-arm-3d-base"]),
    "overlay.robot-arm-3d-v3": (["overlays/robot_arm_3d_v3.py", "overlays/assets/robot_arm_3d_v3"], ["resource.robot-arm-3d-v2"]),
    "overlay.xeyes": (["overlays/xeyes.py"], []),
}
COMPONENTS = (("bolttagu-2d", "Bolttagu", "2D", "overlay.bolttagu-2d"), ("rabbit-2d", "Rabbit", "2D", "overlay.rabbit-2d"), ("robot-arm", "Engram 3-Link Robot Arm", "2D", "resource.robot-arm-base"), ("xeyes", "Engram XEyes", "2D", "overlay.xeyes"), ("robot-arm-3d", "Engram 3D Robot Arm", "3D", "resource.robot-arm-3d-base"), ("robot-arm-3d-v2", "Engram Textured 3D Robot Arm V2", "3D", "resource.robot-arm-3d-v2"), ("robot-arm-3d-v3", "CCTV", "3D", "overlay.robot-arm-3d-v3"))

def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def files(items: list[str]) -> list[Path]:
    result: list[Path] = []
    for item in items:
        source = SOURCE / item
        result += sorted(path for path in source.rglob("*") if path.is_file()) if source.is_dir() else [source]
    return result

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "components")
    parser.add_argument("--build", type=int, default=None)
    args = parser.parse_args(argv)
    build = args.build or int(subprocess.check_output(("git", "-C", str(ROOT), "rev-list", "--count", "HEAD"), text=True))
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engram-overlay-core-") as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        for name in ("pyproject.toml", "VERSION", "README.md"):
            shutil.copy2(ROOT / name, stage / name)
        shutil.copytree(SOURCE, stage / "src" / "engram_overlay", ignore=shutil.ignore_patterns("__pycache__"))
        stage_source = stage / "src" / "engram_overlay"
        for item_list, _ in PAYLOADS.values():
            for item in item_list:
                target = stage_source / item
                shutil.rmtree(target) if target.is_dir() else target.unlink()
        env = os.environ | {"SEMVER4_BUILD": str(build)}
        subprocess.run((sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(output), str(stage)), check=True, env=env)
    wheel, = output.glob("engram_custom_overlay-*.whl")
    version = wheel.name.removeprefix("engram_custom_overlay-").removesuffix("-py3-none-any.whl")
    payload_records = []
    for identifier, (item_list, requires) in PAYLOADS.items():
        relative = Path("payloads") / f"{identifier}.zip"
        archive = output / relative
        archive.parent.mkdir(exist_ok=True)
        records = []
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for source in files(item_list):
                name = source.relative_to(SOURCE).as_posix()
                zip_file.write(source, name)
                records.append({"path": name, "sha256": digest(source), "size": source.stat().st_size})
        payload_records.append({"id": identifier, "file": relative.as_posix(), "sha256": digest(archive), "requires": requires, "files": records})
    sdk = output / f"engram-overlay-sdk-{version}.zip"
    with zipfile.ZipFile(sdk, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for name in ("docs/llm-overlay-authoring.md", "docs/event-api-v2.md", "docs/architecture.md", "README.md", "examples/minimal-v2-client.py"):
            zip_file.write(ROOT / name, name)
    manifest = {"schema": 1, "package_version": version, "registry_revision": "external-overlay-components-v1", "common": {"file": wheel.name, "sha256": digest(wheel)}, "sdk": {"file": sdk.name, "sha256": digest(sdk)}, "components": [{"id": identifier, "display_name": name, "group": group, "payloads": [payload], "requires": []} for identifier, name, group, payload in COMPONENTS], "payloads": payload_records}
    path = output / "engram-overlay-components.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0
if __name__ == "__main__": raise SystemExit(main())
