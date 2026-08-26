"""Engram custom overlay renderer."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .protocol import SCHEMA_VERSION

if (Path(__file__).resolve().parents[2] / "VERSION").is_file():
    from ._version import __version__
else:
    try:
        __version__ = version("engram-custom-overlay")
    except PackageNotFoundError:
        from ._version import __version__

__all__ = ["SCHEMA_VERSION", "__version__"]

