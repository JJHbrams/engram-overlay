"""Pack the 1254x1254 bolttagu sprite pack into small aligned overlay atlases.

The upstream pack ships one full-canvas PNG per frame (~26 MB for v8), which is far
too large to commit.  Every frame shares the same canvas and feet anchor, so a
single crop rectangle keeps all poses aligned while removing the empty margin.
The crop is the union of every shipped frame's alpha bounding box, downscaled by
a fixed factor and written as horizontal sheets.

The idle pose is layered rather than baked: the three blink frames are the base and
the 24 steam frames composite over them at runtime, so blink and steam stay
independent loops the way ``idle-animation.js`` describes.

Usage:
    python scripts/build-bolttagu-assets.py --pack <sprite-pack-v8 directory>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

SCALE = 0.25
SOURCE_CANVAS = (1254, 1254)
SOURCE_FEET_ANCHOR = (750, 1080)
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "src" / "engram_overlay" / "overlays" / "assets" / "bolttagu_2d"

# Cell order inside each generated sheet.  The overlay indexes these by name.
# idle holds the pre-composited blink states; the pack's own states/idle.png is
# skipped because it bakes in the static steam that v8 split out.
IDLE = ("animations/idle_blink/open.png", "animations/idle_blink/half.png", "animations/idle_blink/closed.png")
STEAM = tuple(f"animations/idle_steam/{index:02d}.png" for index in range(1, 25))
ALERT = ("states/alert_aha.png",)
WONDERING = tuple(f"animations/wondering/{index:02d}.png" for index in range(1, 9))
ENTER = tuple(f"animations/enter/{index:02d}.png" for index in range(1, 4))
EXIT = tuple(f"animations/exit/{index:02d}.png" for index in range(1, 4))
FLOOR = ("layers/floor_base.png", "layers/floor_with_coffee.png")

SHEETS = {
    "bolttagu-idle.png": IDLE,
    "bolttagu-steam.png": STEAM,
    "bolttagu-alert.png": ALERT,
    "bolttagu-wondering.png": WONDERING,
    "bolttagu-enter.png": ENTER,
    "bolttagu-exit.png": EXIT,
    "bolttagu-floor.png": FLOOR,
}


def source_images(pack: Path) -> dict[str, Image.Image]:
    images: dict[str, Image.Image] = {}
    for frames in SHEETS.values():
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


def build(pack: Path) -> dict[str, object]:
    images = source_images(pack)
    crop = union_bbox(images)
    cell = cell_size(crop)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    written: dict[str, int] = {}
    for sheet_name, frames in SHEETS.items():
        sheet = Image.new("RGBA", (cell[0] * len(frames), cell[1]), (0, 0, 0, 0))
        for index, frame_name in enumerate(frames):
            resized = images[frame_name].crop(crop).resize(cell, Image.Resampling.LANCZOS)
            sheet.paste(resized, (index * cell[0], 0))
        target = OUTPUT_DIR / sheet_name
        sheet.save(target, optimize=True)
        written[sheet_name] = target.stat().st_size

    anchor_x, anchor_y = SOURCE_FEET_ANCHOR
    metadata = {
        "source": pack.name,
        "sourceCanvas": list(SOURCE_CANVAS),
        "crop": list(crop),
        "scale": SCALE,
        "cell": list(cell),
        "feetAnchor": [
            round((anchor_x - crop[0]) * SCALE),
            round((anchor_y - crop[1]) * SCALE),
        ],
        "sheets": {name: list(frames) for name, frames in SHEETS.items()},
    }
    (OUTPUT_DIR / "atlas.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"cell": cell, "crop": crop, "bytes": written}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path, help="sprite-pack-v8 directory")
    arguments = parser.parse_args()
    result = build(arguments.pack.expanduser())
    written: dict[str, int] = result["bytes"]  # type: ignore[assignment]
    print(f"crop={result['crop']} cell={result['cell']}")
    for name, size in written.items():
        print(f"  {name}: {size / 1024:.0f} KiB")
    print(f"total: {sum(written.values()) / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
