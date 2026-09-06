"""Pack the 1254x1254 bolttagu sprite packs into small aligned overlay atlases.

An upstream pack ships one full-canvas PNG per frame (~27 MB), which is far
too large to commit.  Every frame shares the same canvas and feet anchor, so a
single crop rectangle keeps all poses aligned while removing the empty margin.
The crop is the union of every shipped frame's alpha bounding box **across every
pack**, downscaled by a fixed factor and written as horizontal sheets.  One crop
for all of them is what lets a mapping draw one set for one signal and another
set for the next without the feet moving between them.

Two sets ship.  The original pack owns the unprefixed sheet names; each retouch
of the same character prefixes its own, and may add states the original never
drew.  The floor and the spilled coffee are style-neutral -- both packs ship the
same pixels -- so only the original pack contributes them.

The idle pose is layered rather than baked: the three blink frames are the base and
the 24 steam frames composite over them at runtime, so blink and steam stay
independent loops the way ``idle-animation.js`` describes.

Usage:
    python scripts/build-bolttagu-assets.py --pack <v10 pack> --retouch <trickcal pack>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SCALE = 0.25
SOURCE_CANVAS = (1254, 1254)
SOURCE_FEET_ANCHOR = (750, 1080)
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "src" / "engram_overlay" / "overlays" / "assets" / "bolttagu_2d"

# Cell order inside each generated sheet.  The overlay indexes these by name.
# idle holds the pre-composited blink states; a pack's own states/idle.png is
# skipped because it bakes in the static steam the packs split out in v8.
IDLE = ("animations/idle_blink/open.png", "animations/idle_blink/half.png", "animations/idle_blink/closed.png")
STEAM = tuple(f"animations/idle_steam/{index:02d}.png" for index in range(1, 25))
ALERT = ("states/alert_aha.png",)
FLOOR = ("layers/floor_base.png",)
# The tipped mug and its puddle, drawn under the poses that have both hands up.
# It is a layer of those poses rather than part of the floor, so the spill shows
# whether or not the floor is drawn -- and only while she is not holding the mug.
SPILL = ("layers/coffee_spill.png",)

# Only states the overlay can actually reach are packed. Every state a pack
# ships is reachable now that Engram's launcher drives show and hide.
EVENTS = (
    "wondering", "enter", "exit", "searching", "writing",
    "speaking", "listening", "waiting", "success", "error",
)
# The trickcal retouch draws two activities the original v10 pack never had.
RETOUCH_EVENTS = ("executing", "tool_use")


def event_frames(state: str, count: int = 3) -> tuple[str, ...]:
    return tuple(f"animations/{state}/{index:02d}.png" for index in range(1, count + 1))


@dataclass(frozen=True)
class SpriteSet:
    """One art style, and which of its frames end up in the atlas."""

    key: str
    events: tuple[str, ...]
    # Ground props are drawn under any set, so they are packed once rather than
    # per style. Both packs ship them byte for byte identical.
    ground: bool

    @property
    def prefix(self) -> str:
        """Sheet-name prefix. The original set owns the bare names."""
        return "" if self.key == "origin" else f"{self.key}-"

    def sheets(self) -> dict[str, tuple[str, ...]]:
        sheets = {
            f"bolttagu-{self.prefix}idle.png": IDLE,
            f"bolttagu-{self.prefix}steam.png": STEAM,
            f"bolttagu-{self.prefix}alert.png": ALERT,
            **{
                f"bolttagu-{self.prefix}{state}.png": event_frames(state)
                for state in self.events
            },
        }
        if self.ground:
            sheets[f"bolttagu-{self.prefix}floor.png"] = FLOOR
            sheets[f"bolttagu-{self.prefix}spill.png"] = SPILL
        return sheets


SETS = (
    SpriteSet("origin", EVENTS, ground=True),
    SpriteSet("trickcal", EVENTS + RETOUCH_EVENTS, ground=False),
)


def source_images(pack: Path, sheets: dict[str, tuple[str, ...]]) -> dict[str, Image.Image]:
    images: dict[str, Image.Image] = {}
    for frames in sheets.values():
        for name in frames:
            path = pack / name
            if not path.is_file():
                raise SystemExit(f"missing source frame: {path}")
            image = Image.open(path).convert("RGBA")
            if image.size != SOURCE_CANVAS:
                raise SystemExit(f"{name} must be {SOURCE_CANVAS}, got {image.size}")
            images[name] = image
    return images


def union_bbox(images: dict[str, Image.Image]) -> tuple[int, int, int, int]:
    """Smallest rectangle that contains every frame's non-transparent pixels."""
    boxes = [image.getchannel("A").getbbox() for image in images.values()]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        raise SystemExit("every source frame is fully transparent")
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def cell_size(crop: tuple[int, int, int, int]) -> tuple[int, int]:
    return (
        max(1, round((crop[2] - crop[0]) * SCALE)),
        max(1, round((crop[3] - crop[1]) * SCALE)),
    )


def build(packs: dict[str, Path]) -> dict[str, object]:
    loaded = {
        sprite_set: (packs[sprite_set.key], sprite_set.sheets())
        for sprite_set in SETS
    }
    images = {
        sprite_set: source_images(pack, sheets)
        for sprite_set, (pack, sheets) in loaded.items()
    }
    # One crop for every set: a mapping may draw a different style per signal, so
    # the sets have to share a cell or the character would jump between them.
    crop = union_bbox({
        f"{sprite_set.key}/{name}": image
        for sprite_set, frames in images.items()
        for name, image in frames.items()
    })
    cell = cell_size(crop)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    packed: dict[str, list[str]] = {}
    for sprite_set, (_, sheets) in loaded.items():
        for sheet_name, frames in sheets.items():
            sheet = Image.new("RGBA", (cell[0] * len(frames), cell[1]), (0, 0, 0, 0))
            for index, frame_name in enumerate(frames):
                source = images[sprite_set][frame_name]
                resized = source.crop(crop).resize(cell, Image.Resampling.LANCZOS)
                sheet.paste(resized, (index * cell[0], 0))
            target = OUTPUT_DIR / sheet_name
            sheet.save(target, optimize=True)
            written[sheet_name] = target.stat().st_size
            packed[sheet_name] = list(frames)

    anchor_x, anchor_y = SOURCE_FEET_ANCHOR
    metadata = {
        "sources": {sprite_set.key: packs[sprite_set.key].name for sprite_set in SETS},
        "sourceCanvas": list(SOURCE_CANVAS),
        "crop": list(crop),
        "scale": SCALE,
        "cell": list(cell),
        "feetAnchor": [
            round((anchor_x - crop[0]) * SCALE),
            round((anchor_y - crop[1]) * SCALE),
        ],
        "sheets": packed,
    }
    (OUTPUT_DIR / "atlas.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"cell": cell, "crop": crop, "bytes": written}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path, help="original sprite-pack-vN directory")
    parser.add_argument(
        "--retouch", required=True, type=Path, help="trickcal-inspired retouch pack directory"
    )
    arguments = parser.parse_args()
    result = build({
        "origin": arguments.pack.expanduser(),
        "trickcal": arguments.retouch.expanduser(),
    })
    written: dict[str, int] = result["bytes"]  # type: ignore[assignment]
    print(f"crop={result['crop']} cell={result['cell']}")
    for name, size in written.items():
        print(f"  {name}: {size / 1024:.0f} KiB")
    print(f"total: {sum(written.values()) / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
