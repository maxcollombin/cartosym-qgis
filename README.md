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
# a render kit of github.com/henrik716/cartosym-draft-check (style, data and view.json)
.venv/bin/cartosym-qgis kit path/to/kit --style style-variant-4.cs.json -o out.png
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
dash), casing and centre line, hatches, dot patterns, stipples, `Image` and `Dot` markers (on points, at a polygon's centroid, at a line's vertices) with `hotSpot` and `position`, an `Image` as fill pattern or repeated along a stroke (`pattern`, `patternGap`, `patternInitialGap`), `Text` labels with font outline (`label.elements`), `Dot` markers, `viz.sd`, property comparisons, `like`, `in`, `between`,
`px`/`mm`/`cm`/`pt`/`in`/`m`/`ft`.

Coverages (`kit` command, bands as `<layer>.<band>.asc`): `singleChannel` (a band or an
expression over bands) with `colorMap`, `colorChannels`, `alphaChannel` with selectors on
band values (`[SCL=8]`), `opacity`, and `hillShading` (GDAL's hillshade, with its `colorMap`
and `opacityMap` on the 0..1 intensity). `colorMap` is interpolated linearly and clamped,
`colorChannels` values are stretched to their min/max, the sun azimuth is read clockwise
from north; all three are listed as `assumed`. `hillShading.factor` is not carried over: the
draft does not say what it scales.

Not yet: `Dot` and shapes as fill patterns, `tint`/`blackTint`/`alphaThreshold`, `Text` position and alignment, coverages, `viz.pass`, time conditions.

Dots of a dot pattern or stipple are 1 px squares in the fill colour (the draft
leaves their size and colour open). A stipple scatters `ratio * area` dots at
random with a fixed seed, so at high ratios dots overlap and the covered share
stays below `ratio`.

Relative image paths start in the style file's folder. An `Image` is drawn at its
own size; `pc` in a `hotSpot` is read as a percentage of the image.
