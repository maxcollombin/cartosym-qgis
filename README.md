# cartosym-qgis

Draws a [CartoSym](https://github.com/opengeospatial/cartographic-symbology) style with
QGIS, headless, on top of [pycartosym](https://github.com/maxcollombin/pycartosym).
It writes a QGIS style (`.qml`) or a PNG.

Its purpose is to be an independent renderer: it shows how the draft requirements read when
another implementation has to pick a meaning. QGIS has no standard mapping for CartoSym, so
every mapping here is this project's choice, not the OGC's.

## Install

PyQGIS is not on PyPI. Use the Python that comes with QGIS (the system Python on Linux), in a
virtual environment that can see it:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
```

## Use

```bash
# a QGIS style for one layer
cartosym-qgis qml style.cscss --geometry polygon --layer Landuse -o landuse.qml

# a PNG of a vector layer, at a scale
cartosym-qgis render style.cscss data.geojson --layer Landuse --scale 5000 -o out.png

# a render kit of cartosym-draft-check: style, data and view.json in one folder
cartosym-qgis kit path/to/kit [--style style-variant-2.cs.json] -o out.png
```

Anything QGIS cannot express is printed on stderr as `not carried over:` (`--strict` turns it
into an error). A choice made where the draft is open is printed as `assumed:`.

## What it draws

| | |
|---|---|
| Vector | fill, stroke (width, cap, join, dashes, `dashOffset`), casing, centre line, `opacity`, `zOrder`, widths given as expressions |
| Fills | hatches, dot patterns, stipples, gradients (linear, radial, conical), an `Image` as a pattern |
| Strokes | an `Image` repeated along the line (`pattern`, `patternGap`) |
| Markers | `Dot` and `Image` (with `hotSpot`, `position`) on points, at a polygon's centroid, at a line's vertices |
| Labels | `Text` with font, outline, offset, priority, repeat distance; a marker's `Text` is a label that is never left out |
| Selectors | property comparisons, `like`, `in`, `between`, scale (`viz.sd`) |
| Coverages | `singleChannel` (a band or an expression over bands), `colorMap`, `colorChannels`, `alphaChannel` with selectors on band values, hill shading with its `colorMap` and `opacityMap` |

CS-JSON is read as it is, without validation, so draft proposals that pycartosym does not know
yet (`gamma`, `gradient`, …) still render.

**Not yet:** a gradient `type` given by a property, `Text.alignment`, the default marker, a
`Dot` or shape as a fill pattern, `tint` / `blackTint` / `alphaThreshold`,
`hillShading.factor` (the draft does not say what it scales), `viz.pass`, time conditions.

## Choices where the draft is open

| Point | Reading |
|---|---|
| casing `width` | the whole band; casings are drawn beneath, all before any stroke |
| hatch `angle` | clockwise from the x axis |
| `dashPattern`, font outline `size` | pixels; the outline extends outward by `size` |
| dots of a dot pattern or stipple | 1 px squares in the fill colour |
| `colorMap` | interpolated linearly, clamped beyond its ends |
| `colorChannels` as bands | stretched between their minimum and maximum |
| hill shading sun | azimuth clockwise from north |
| `pc` in a `hotSpot` | percentage of the image |
| `position`, `Text.position` | `y` points down |
| `Label.placement.minSpacing` | distance between repeated line labels |

## How a style becomes rules

CartoSym merges every matching rule in document order; QGIS rules do not. The selectors are
split into cells (one state per property tested with `=`, one per scale interval, one per other
condition) and each cell gets one QGIS rule with the merged symbolizer.

## Comparison with cartosym-draft-check

`tools/` renders all kits of
[cartosym-draft-check](https://github.com/henrik716/cartosym-draft-check) and puts them next to
that project's own variants. What it showed is in [`docs/kit-comparison.md`](docs/kit-comparison.md).

## Tests

```bash
.venv/bin/python -m pytest
```

MIT licence.
