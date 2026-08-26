"""Normalize generated V3 silhouette art into transparent runtime atlases."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def remove_light_background(source: Image.Image) -> Image.Image:
    rgb = source.convert("RGB")
    result = Image.new("RGBA", rgb.size)
    output = []
    for red, green, blue in rgb.get_flattened_data():
        luminance = (red * 299 + green * 587 + blue * 114) // 1000
        alpha = max(0, min(255, (220 - luminance) * 7))
        output.append((red, green, blue, alpha))
    result.putdata(output)
    return result


def normalized_cell(image: Image.Image, bounds: tuple[int, int, int, int], size: int = 256) -> Image.Image:
    crop = image.crop(bounds)
    content = crop.getbbox()
    target = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if content is None:
        return target
    crop = crop.crop(content)
    scale = min((size - 18) / crop.width, (size - 12) / crop.height)
    resized = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
    target.alpha_composite(resized, ((size - resized.width) // 2, size - resized.height))
    return target


def build(character_source: Path, terrain_source: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    characters = remove_light_background(Image.open(character_source))
    characters.save(output_dir / "traveler-walk-atlas.png", optimize=True)

    terrain = remove_light_background(Image.open(terrain_source))
    width, height = terrain.size
    thirds = (
        (0, 0, width // 3, height),
        (width // 3, 0, width * 2 // 3, height),
        (width * 2 // 3, 0, width, height),
    )
    cover_atlas = Image.new("RGBA", (256 * 3, 256), (0, 0, 0, 0))
    for index, bounds in enumerate(thirds):
        cover_atlas.alpha_composite(normalized_cell(terrain, bounds), (index * 256, 0))
    cover_atlas.save(output_dir / "terrain-cover-atlas.png", optimize=True)

    content = terrain.getbbox()
    if content is None:
        raise RuntimeError("terrain source contains no silhouette pixels")
    ridge_top = max(content[1], content[3] - max(40, (content[3] - content[1]) // 8))
    ridge = terrain.crop((content[0], ridge_top, content[2], content[3]))
    ridge = ridge.resize((640, 18), Image.Resampling.LANCZOS)
    ridge.save(output_dir / "terrain-ridge.png", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--characters", type=Path, required=True)
    parser.add_argument("--terrain", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    build(args.characters, args.terrain, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
