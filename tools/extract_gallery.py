"""Extract the rendered variants of each card of the draft-check gallery (``index.html``).

    python tools/extract_gallery.py path/to/gallery/index.html out/

Writes ``out/<card>/<n>.png`` and ``out/cards.json`` (caption and whether the
variant is the one the draft's text chooses, per card). Inline SVGs are drawn
with Qt; nothing from the page is executed.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(index: Path, out: Path) -> None:
    """Extract every figure of every card."""
    from qgis.PyQt.QtCore import QByteArray
    from qgis.PyQt.QtGui import QGuiApplication, QImage, QPainter
    from qgis.PyQt.QtSvg import QSvgRenderer

    app = QGuiApplication([])  # noqa: F841 (Qt needs one to paint)
    page = index.read_text(encoding="utf-8")
    cards: dict[str, list[dict]] = {}
    for match in re.finditer(r'<section class="card" id="([^"]+)">(.*?)</section>', page, re.S):
        key, body = match.groups()
        title = re.search(r"<h2>(.*?)</h2>", body, re.S)
        figures = []
        for n, fig in enumerate(re.findall(r"<figure>(.*?)</figure>", body, re.S)):
            target = out / key / f"{n}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            svg = re.search(r"<svg.*?</svg>", fig, re.S)
            png = re.search(r'(?:src|href)="data:image/png;base64,([^"]+)"', fig)
            if png:  # a picture; an inline <svg> beside it is only a legend swatch
                target.write_bytes(base64.b64decode(png.group(1)))
            elif svg:
                renderer = QSvgRenderer(QByteArray(svg.group(0).encode()))
                size = renderer.defaultSize()
                image = QImage(size, QImage.Format_ARGB32)
                image.fill(0xFFFFFFFF)
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
                image.save(str(target))
            else:
                continue
            caption = re.search(r"<figcaption>(.*?)</figcaption>", fig, re.S)
            text = html.unescape(re.sub(r"<[^>]+>", " ", caption.group(1))) if caption else ""
            figures.append({"image": str(target.relative_to(out)), "caption": " ".join(text.split()),
                            "draft": 'class="tag draft"' in fig or "<kbd>draft</kbd>" in fig})
        cards[key] = {"title": html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else key,
                      "figures": figures}
    out.mkdir(parents=True, exist_ok=True)
    (out / "cards.json").write_text(json.dumps(cards, indent=2, ensure_ascii=False))
    print(f"{len(cards)} cards, {sum(len(c['figures']) for c in cards.values())} images")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
