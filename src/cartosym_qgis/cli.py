"""Command line: ``cartosym-qgis qml`` and ``cartosym-qgis render``."""

from __future__ import annotations

import argparse
import sys

from .renderer import build_renderer, load_style, to_qml
from .render import qgis_app, render_png


def _report(report, strict: bool) -> int:
    for line in report.dropped:
        print(f"not carried over: {line}", file=sys.stderr)
    return 1 if strict and report.dropped else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    p = argparse.ArgumentParser(prog="cartosym-qgis")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("qml", help="write a QML style")
    q.add_argument("style")
    q.add_argument("--geometry", choices=["point", "line", "polygon"], required=True)
    q.add_argument("--layer")
    q.add_argument("-o", "--output", required=True)
    r = sub.add_parser("render", help="render a vector layer to PNG")
    r.add_argument("style")
    r.add_argument("data")
    r.add_argument("--layer")
    r.add_argument("--size", type=int, default=600)
    r.add_argument("--scale", type=float, help="scale denominator")
    r.add_argument("-o", "--output", required=True)
    for sp in (q, r):
        sp.add_argument("--strict", action="store_true", help="fail if anything is dropped")
    args = p.parse_args(argv)

    style = load_style(args.style)
    with qgis_app():
        if args.command == "qml":
            renderer, report = build_renderer(style, args.geometry, args.layer)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(to_qml(renderer, args.geometry))
        else:
            report = render_png(
                style, args.data, args.output, args.layer, args.size, args.scale
            )
    return _report(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
