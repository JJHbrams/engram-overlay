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
    # A range the first cell's duration is drawn from anew each cycle. Lets a
    # resting pose wait an unpredictable while before its brief action -- a blink,
    # say -- without the timeline stopping being a pure function of the clock.
    hold_ms: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if not self.cells:
            raise ValueError(f"layer on {self.sheet} has no cells")
        if len(self.cells) != len(self.durations_ms):
            raise ValueError(f"layer on {self.sheet} has mismatched cells and durations")
        rest = self.durations_ms[1:] if self.hold_ms else self.durations_ms
        if rest and min(rest) <= 0:
            raise ValueError(f"layer on {self.sheet} has a non-positive duration")
        if self.hold_ms:
            low, high = self.hold_ms
            if low <= 0 or high < low:
                raise ValueError(f"layer on {self.sheet} has an unusable hold range")

    @property
    def total_ms(self) -> int:
        """Nominal length, using the midpoint of a random hold."""
        if not self.hold_ms:
            return sum(self.durations_ms)
        low, high = self.hold_ms
        return (low + high) // 2 + sum(self.durations_ms[1:])


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


def _hold_at(layer: Layer, cycle: int, seed: int) -> int:
    """The first cell's duration for one cycle: reproducible, not memorised.

    A plain LCG keeps this identical in the preview page, so what is previewed is
    what is drawn rather than an approximation of it.
    """
    assert layer.hold_ms is not None
    low, high = layer.hold_ms
    noise = ((cycle * 9301 + seed * 49297 + 233280) % 233280) / 233280
    return low + int(noise * (high - low))


def cell_at(layer: Layer, elapsed_ms: int, seed: int = 0) -> int:
    """Which cell of this layer is showing, given the clock."""
    time = max(0, elapsed_ms)
    if layer.hold_ms is None:
        total = sum(layer.durations_ms)
        if layer.loop:
            time %= total
        elif time >= total:
            return layer.cells[-1]
        cursor = 0
        for cell, duration in zip(layer.cells, layer.durations_ms):
            cursor += duration
            if time < cursor:
                return cell
        return layer.cells[-1]

    # A held first cell makes each cycle a different length, so walk the cycles.
    tail = sum(layer.durations_ms[1:])
    cycle = 0
    while True:
        span = _hold_at(layer, cycle, seed) + tail
        if time < span or not layer.loop:
            break
        time -= span
        cycle += 1
    cursor = _hold_at(layer, cycle, seed)
    if time < cursor:
        return layer.cells[0]
    for cell, duration in zip(layer.cells[1:], layer.durations_ms[1:]):
        cursor += duration
        if time < cursor:
            return cell
    return layer.cells[-1] if not layer.loop else layer.cells[0]


def frames_at(option: Option, elapsed_ms: int, seed: int = 0) -> tuple[tuple[str, int], ...]:
    """Every (sheet, cell) this option draws right now, bottom layer first."""
    return tuple(
        (layer.sheet, cell_at(layer, elapsed_ms, seed + index))
        for index, layer in enumerate(option.layers)
    )


def finished(option: Option, elapsed_ms: int) -> bool:
    """Whether a non-looping option has run out. A looping one never has."""
    return not option.loops and elapsed_ms >= option.total_ms


class Rotation:
    """Pick one of several options per time bucket, avoiding an immediate repeat.

    A signal that offers several stills wants variety without flicker, so the
    choice is made once per bucket and remembered.
    """

    def __init__(self, rng: object) -> None:
        self.rng = rng
        self.picked: dict[tuple[str, int], str] = {}

    def clear(self) -> None:
        self.picked.clear()

    def pick(self, key: str, choice: Choice, bucket: int) -> str | None:
        if not choice:
            return None
        if len(choice) == 1:
            return choice[0]
        bucket = max(0, bucket)
        remembered = self.picked.get((key, bucket))
        if remembered is not None:
            return remembered
        previous = self.picked.get((key, bucket - 1))
        candidates = tuple(value for value in choice if value != previous) or choice
        self.picked[(key, bucket)] = self.rng.choice(candidates)  # type: ignore[attr-defined]
        return self.picked[(key, bucket)]


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
