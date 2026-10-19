"""Put the gallery's variants of each card next to the QGIS render of its kit.

    python tools/compare.py gallery_out/ kits_out/ compare/

``gallery_out`` is the output of ``extract_gallery.py``, ``kits_out`` that of
``run_kits.py``. Writes ``compare/<card>.png``.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw


def _tile(path: Path, caption: str, width: int = 330) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image = image.resize((width, max(1, round(image.height * width / image.width))))
    lines = textwrap.wrap(caption, 44)[:3] or [""]
    tile = Image.new("RGB", (width + 10, image.height + 16 * len(lines) + 12), "white")
    tile.paste(image, (5, 5))
    draw = ImageDraw.Draw(tile)
    for i, line in enumerate(lines):
        draw.text((5, image.height + 8 + 16 * i), line, fill="black")
    return tile


def main(gallery: Path, kits: Path, out: Path) -> None:
    """Write one comparison sheet per card that has a kit."""
    cards = json.loads((gallery / "cards.json").read_text())
    summary = json.loads((kits / "summary.json").read_text())
    out.mkdir(parents=True, exist_ok=True)
    for key, card in cards.items():
        if key not in summary:
            continue
        theirs = [_tile(gallery / f["image"], "draft renderer: " + f["caption"]) for f in card["figures"]]
        mine = [_tile(kits / e["image"], f"QGIS: {style}") for style, e in summary[key].items() if "error" not in e]
        tiles = theirs + mine
        sheet = Image.new("RGB", (sum(t.width for t in tiles), max(t.height for t in tiles)), "white")
        x = 0
        for tile in tiles:
            sheet.paste(tile, (x, 0))
            x += tile.width
        sheet.save(out / f"{key}.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
