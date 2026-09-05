"""Shared vocabulary for sprite overlays that let their mapping be chosen.

A sprite overlay decides which artwork each semantic signal draws. Which artwork
that should be is a visual judgement, so it belongs in a picker rather than in a
table of literals -- and every sprite overlay wants the same picker.

An overlay describes itself with a :class:`SpriteMap`: the sheets it draws from,
the options a signal may take, and the sections those choices are grouped into.
``resolve`` merges a user's ``mapping.json`` over the declared defaults and drops
anything that cannot be drawn, so a hand-edited file can never stop a renderer.

The description is deliberately declarative: ``scripts/build-sprite-preview.py``
renders every overlay from it without knowing anything about any of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MAPPING_FILE = "mapping.json"

Choice = tuple[str, ...]
Resolved = dict[str, dict[str, Choice]]


def installed_mapping_path(overlay_id: str) -> Path:
    """Where Engram's installed manifest for this overlay lives."""
    return Path.home() / ".engram" / "overlays" / overlay_id / MAPPING_FILE


@dataclass(frozen=True)
class Layer:
    """Cells from one sheet on their own timeline, drawn in declaration order."""

    sheet: str
    cells: tuple[int, ...]
    durations_ms: tuple[int, ...]
    loop: bool = True

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValueError(f"layer on {self.sheet} has no cells")
        if len(self.cells) != len(self.durations_ms):
            raise ValueError(f"layer on {self.sheet} has mismatched cells and durations")
        if min(self.durations_ms) <= 0:
            raise ValueError(f"layer on {self.sheet} has a non-positive duration")

    @property
    def total_ms(self) -> int:
        return sum(self.durations_ms)


@dataclass(frozen=True)
class Option:
    """One choosable value and how it is drawn."""

    key: str
    layers: tuple[Layer, ...]
    note: str = ""

    @property
    def total_ms(self) -> int:
        return max(layer.total_ms for layer in self.layers)

    @property
    def loops(self) -> bool:
        return all(layer.loop for layer in self.layers)


@dataclass(frozen=True)
class Row:
    """One signal the overlay reacts to."""

    key: str
    note: str = ""
    default: Choice = ()


@dataclass(frozen=True)
class Section:
    """A group of signals that share a pool of options."""

    key: str
    title: str
    rows: tuple[Row, ...]
    options: tuple[str, ...]
    note: str = ""
    multi: bool = False
    allow_empty: bool = False
    # Keys the overlay recognises but deliberately does not offer, each with the
    # reason. Without this a deliberate omission is indistinguishable from a typo.
    refused: dict[str, str] = field(default_factory=dict)
    # Resolved and loadable, but not offered in the picker. For a choice that is
    # real but too narrow to be worth a column.
    hidden: bool = False

    @property
    def by_key(self) -> dict[str, Row]:
        return {row.key: row for row in self.rows}


@dataclass(frozen=True)
class SpriteMap:
    """Everything the picker and the loader need to know about one overlay."""

    overlay_id: str
    name: str
    cell: tuple[int, int]
    asset_dir: Path
    # name -> (file name, cell count, columns). A horizontal strip has
    # columns == count; a grid atlas wraps after that many cells.
    sheets: dict[str, tuple[str, int, int]]
    options: dict[str, Option]
    sections: tuple[Section, ...] = field(default_factory=tuple)

    @property
    def mapping_path(self) -> Path:
        return installed_mapping_path(self.overlay_id)

    def defaults(self) -> Resolved:
        return {s.key: {row.key: row.default for row in s.rows} for s in self.sections}


def _check(section: Section, row_key: str, value: object, options: set[str]) -> tuple[Choice, str]:
    """Return the accepted choice and an empty note, or the reason it was refused."""
    values: list[object] = list(value) if isinstance(value, (list, tuple)) else [value]
    if values == [None]:
        values = []
    if not section.multi and len(values) > 1:
        return (), f"{row_key!r} takes one value, got {len(values)}"
    if not values and not section.allow_empty:
        return (), f"{row_key!r} cannot be empty"
    for item in values:
        if not isinstance(item, str) or item not in options:
            return (), f"{row_key!r} cannot draw {item!r}"
    return tuple(values), ""  # type: ignore[arg-type]


def resolve(
    sprite_map: SpriteMap,
    path: Path | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> Resolved:
    """Merge a user mapping over the declared defaults, refusing what cannot be drawn."""
    resolved = sprite_map.defaults()
    path = sprite_map.mapping_path if path is None else path
    note = log or (lambda message: None)
    if not path.is_file():
        return resolved
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        note(f"{MAPPING_FILE} ignored: {exc}")
        return resolved
    if not isinstance(document, dict):
        note(f"{MAPPING_FILE} ignored: top level must be an object")
        return resolved

    sections = {section.key: section for section in sprite_map.sections}
    for key, entries in document.items():
        if key == "version":
            continue
        section = sections.get(key)
        if section is None:
            note(f"{MAPPING_FILE}: unknown section {key!r}")
            continue
        if not isinstance(entries, dict):
            note(f"{MAPPING_FILE}: {key} must be an object")
            continue
        rows, options = section.by_key, set(section.options)
        for row_key, value in entries.items():
            if row_key in section.refused:
                note(f"{MAPPING_FILE}: {key}: {section.refused[row_key]}")
                continue
            if row_key not in rows:
                note(f"{MAPPING_FILE}: {key}: unknown signal {row_key!r}")
                continue
            choice, refusal = _check(section, row_key, value, options)
            if refusal:
                note(f"{MAPPING_FILE}: {key}: {refusal}")
            else:
                resolved[key][row_key] = choice
    return resolved


def single(resolved: Resolved, section: str) -> dict[str, str]:
    """Flatten a single-select section, dropping rows left empty."""
    return {key: value[0] for key, value in resolved[section].items() if value}
