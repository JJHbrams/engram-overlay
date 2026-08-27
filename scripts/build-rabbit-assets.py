"""Normalize generated rabbit artwork into a transparent 3x2 runtime atlas."""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image


COLUMNS = 3
ROWS = 2
SOURCE_CELL = 512
OUTPUT_CELL = (512, 384)
SOURCE_REGIONS = (
    (0, 0, 560, 512),
    (560, 0, 1070, 512),
    (1070, 0, 1536, 512),
    (0, 512, 560, 1024),
    (560, 512, 1100, 1024),
)


def is_connected_background(pixel: tuple[int, int, int]) -> bool:
    """Match the neutral light checker while preserving the rabbit's warm fill."""
    red, green, blue = pixel
    return min(pixel) >= 225 and max(pixel) - min(pixel) <= 4


def remove_connected_background(source: Image.Image) -> Image.Image:
    rgb = source.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    background = bytearray(width * height)
    pending: deque[tuple[int, int]] = deque()

    for x in range(width):
        pending.append((x, 0))
        pending.append((x, height - 1))
    for y in range(1, height - 1):
        pending.append((0, y))
        pending.append((width - 1, y))

    while pending:
        x, y = pending.popleft()
        index = y * width + x
        if background[index] or not is_connected_background(pixels[x, y]):
            continue
        background[index] = 1
        if x:
            pending.append((x - 1, y))
        if x + 1 < width:
            pending.append((x + 1, y))
        if y:
            pending.append((x, y - 1))
        if y + 1 < height:
            pending.append((x, y + 1))

    rgba = rgb.convert("RGBA")
    output = list(rgba.get_flattened_data())
    for index, is_background in enumerate(background):
        if is_background:
            red, green, blue, _alpha = output[index]
            output[index] = (red, green, blue, 0)
    rgba.putdata(output)
    return rgba


def normalize_atlas(source: Image.Image) -> Image.Image:
    if source.size != (SOURCE_CELL * COLUMNS, SOURCE_CELL * ROWS):
        raise ValueError("rabbit source must be an exact 1536x1024 3x2 atlas")

    transparent = remove_connected_background(source)
    frames = [transparent.crop(bounds) for bounds in SOURCE_REGIONS]

    content_bounds = [frame.getbbox() for frame in frames]
    if any(bounds is None for bounds in content_bounds):
        raise ValueError("all five rabbit cells must contain artwork")
    max_width = max(bounds[2] - bounds[0] for bounds in content_bounds if bounds is not None)
    max_height = max(bounds[3] - bounds[1] for bounds in content_bounds if bounds is not None)
    scale = min((OUTPUT_CELL[0] - 24) / max_width, (OUTPUT_CELL[1] - 16) / max_height)

    atlas = Image.new("RGBA", (OUTPUT_CELL[0] * COLUMNS, OUTPUT_CELL[1] * ROWS), (0, 0, 0, 0))
    for index, (frame, bounds) in enumerate(zip(frames, content_bounds, strict=True)):
        assert bounds is not None
        crop = frame.crop(bounds)
        resized = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
        cell = Image.new("RGBA", OUTPUT_CELL, (0, 0, 0, 0))
        cell.alpha_composite(resized, ((OUTPUT_CELL[0] - resized.width) // 2, OUTPUT_CELL[1] - resized.height - 8))
        x = index % COLUMNS * OUTPUT_CELL[0]
        y = index // COLUMNS * OUTPUT_CELL[1]
        atlas.alpha_composite(cell, (x, y))
    return atlas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = normalize_atlas(Image.open(args.source))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.output, optimize=True)


if __name__ == "__main__":
    main()
