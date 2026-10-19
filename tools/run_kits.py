"""Render every kit of a draft-check ``gallery/kit`` folder, with every style it holds.

    python tools/run_kits.py path/to/gallery/kit out/

Writes ``out/<kit>/<style>.png`` and ``out/summary.json`` (what was assumed,
what could not be carried over, and any error, per kit and style).
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from cartosym_qgis.kit import render_kit
from cartosym_qgis.render import qgis_app
from cartosym_qgis.symbols import Options


def main(root: Path, out: Path) -> None:
    """Render all kits under *root* into *out*."""
    summary: dict[str, dict] = {}
    with qgis_app():
        for view in sorted(root.glob("*/view.json")):
            kit = view.parent
            for style in sorted(kit.glob("style*.cs.json")):
                target = out / kit.name / f"{style.name.removesuffix('.cs.json')}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                entry: dict = {"image": str(target.relative_to(out))}
                try:
                    report = render_kit(kit, style, target, Options(base_dir=kit))
                    entry.update(assumed=report.assumed, dropped=report.dropped)
                except Exception as exc:  # one kit failing must not stop the others
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    entry["trace"] = traceback.format_exc(limit=3)
                summary.setdefault(kit.name, {})[style.name] = entry
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    failed = sum("error" in e for k in summary.values() for e in k.values())
    print(f"{sum(len(k) for k in summary.values())} renders, {failed} failed")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
