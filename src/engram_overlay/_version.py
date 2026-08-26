"""Resolve the four-part release version for package builds."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _base_version() -> str:
    version_file = _repository_root() / "VERSION"
    if not version_file.is_file():
        return "0.0.0"
    value = version_file.read_text(encoding="utf-8").strip()
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"VERSION must contain Major.Minor.Patch, got {value!r}")
    return value


def _build_number() -> int:
    for variable in ("SEMVER4_BUILD", "GITHUB_RUN_NUMBER", "CI_PIPELINE_IID", "BUILD_NUMBER"):
        value = os.environ.get(variable)
        if value:
            return min(max(int(value), 0), 65534)
    try:
        result = subprocess.run(
            ("git", "rev-list", "--count", "HEAD"),
            cwd=_repository_root(),
            check=True,
            capture_output=True,
            text=True,
        )
        return min(max(int(result.stdout.strip()), 0), 65534)
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        return 0


__version__ = f"{_base_version()}.{_build_number()}"
