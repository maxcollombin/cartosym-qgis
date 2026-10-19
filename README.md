# cartosym-qgis

Builds a QGIS rule-based renderer (and a `.qml` style) from a CartoSym style,
and renders it headless, on top of [pycartosym](https://github.com/maxcollombin/pycartosym).
The aim is an independent renderer to check how the CartoSym requirements read
in practice. QML has no standard mapping: every mapping here is a choice of this
project, not of the OGC specification.

PyQGIS is not on PyPI: use the system Python that provides it, in a venv with
system site packages.

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
.venv/bin/cartosym-qgis qml style.cscss --geometry polygon --layer Landuse -o landuse.qml
.venv/bin/cartosym-qgis render style.cscss data/landuse.geojson --layer Landuse --scale 5000 -o out.png
```

Whatever QGIS cannot express is listed on stderr (`--strict` makes it an error),
never dropped silently.

## How rules map

CartoSym merges every matching rule in document order; QGIS rules do not. The
conditions are split into cells (one state per property tested with `=`, one per
`viz.sd` interval, one per other condition) and each cell gets one QGIS rule
carrying the merged symbolizer. `viz.sd` becomes the rule's scale range.

## Readings of open requirements

Where the draft leaves a behaviour open, the choice is an option:
`--casing-width total|extra` (is the casing width the whole band, or the part
beyond each side of the stroke) and `--casing-pass all-first|with-feature`
(every casing before any stroke, or each feature's casing with its own stroke).
`--hatch-angle clockwise|counter-clockwise`, `--dash-units px|stroke-width`,
`--outline-unit px|pt` and `--outline-extent outward|centered` (QGIS draws a font
outline as a stroke centred on the glyph contour, so `outward` doubles the size).
Other assumptions are listed on stderr as `assumed:`.

## Supported so far

Polygon fill and stroke (colour, opacity, width, join), line stroke (cap, join,
dash), casing and centre line, hatches, dot patterns, stipples, `Text` labels with font outline (`label.elements`), `Dot` markers, `viz.sd`, property comparisons, `like`, `in`, `between`,
`px`/`mm`/`cm`/`pt`/`in`/`m`/`ft`.

Not yet: pattern fills and strokes, Image markers, `Text` position and alignment, coverages, `viz.pass`, time conditions.

Dots of a dot pattern or stipple are 1 px squares in the fill colour (the draft
leaves their size and colour open). A stipple scatters `ratio * area` dots at
random with a fixed seed, so at high ratios dots overlap and the covered share
stays below `ratio`.
