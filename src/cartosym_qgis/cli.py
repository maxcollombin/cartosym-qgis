"""Command line: ``cartosym-qgis qml`` and ``cartosym-qgis render``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .renderer import build, load_style, to_qml
from .symbols import Options
from .kit import render_kit
from .render import qgis_app, render_png


def _report(report, strict: bool) -> int:
    for line in report.assumed:
        print(f"assumed: {line}", file=sys.stderr)
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
    k = sub.add_parser("kit", help="render a draft-check render kit to PNG")
    k.add_argument("directory")
    k.add_argument("--style", help="style file (default: style.cs.json in the kit)")
    k.add_argument("-o", "--output", required=True)
    for sp in (q, r, k):
        sp.add_argument("--strict", action="store_true", help="fail if anything is dropped")
        sp.add_argument("--casing-width", choices=["total", "extra"], default="total")
        sp.add_argument("--casing-pass", choices=["all-first", "with-feature"], default="all-first")
        sp.add_argument("--hatch-angle", choices=["clockwise", "counter-clockwise"], default="clockwise")
        sp.add_argument("--dash-units", choices=["px", "stroke-width"], default="px")
        sp.add_argument("--outline-unit", choices=["px", "pt"], default="px")
        sp.add_argument("--outline-extent", choices=["outward", "centered"], default="outward")
    args = p.parse_args(argv)

    if args.command == "kit":
        style_file = args.style or str(Path(args.directory) / "style.cs.json")
        args.style = style_file
    style = load_style(args.style) if args.command != "kit" else None
    options = Options(
        casing_width=args.casing_width,
        casing_pass=args.casing_pass,
        hatch_angle=args.hatch_angle,
        dash_units=args.dash_units,
        outline_unit=args.outline_unit,
        outline_extent=args.outline_extent,
        base_dir=Path(args.style).resolve().parent,
    )
    with qgis_app():
        if args.command == "kit":
            report = render_kit(args.directory, args.style, args.output, options)
        elif args.command == "qml":
            renderer, labeling, report = build(style, args.geometry, args.layer, options)
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(to_qml(renderer, args.geometry, labeling=labeling))
        else:
            report = render_png(
                style, args.data, args.output, args.layer, args.size, args.scale, options
            )
    return _report(report, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
