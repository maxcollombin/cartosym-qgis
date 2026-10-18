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
Other assumptions are listed on stderr as `assumed:`.

## Supported so far

Polygon fill and stroke (colour, opacity, width, join), line stroke (cap, join,
dash), casing and centre line, `Dot` markers, `viz.sd`, property comparisons, `like`, `in`, `between`,
`px`/`mm`/`cm`/`pt`/`in`/`m`/`ft`.

Not yet: hatches, stipples, dot patterns, pattern fills and
strokes, Text and Image markers, labels, coverages, `viz.pass`, time conditions.
