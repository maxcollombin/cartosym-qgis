# QGIS against the draft-check render kits

All 42 kits of [`henrik716/cartosym-draft-check`](https://github.com/henrik716/cartosym-draft-check)
(`gallery/kit`, 51 styles in all) rendered with `cartosym-qgis` 0.0.1 and QGIS 3.44.10:
51 renders, none failed. The images are in [`renders/`](renders/), what was assumed or not
carried over per render in [`kit-summary.json`](kit-summary.json).

```bash
python tools/run_kits.py path/to/gallery/kit docs/          # renders and kit-summary.json
python tools/extract_gallery.py path/to/gallery/index.html gallery_out/   # the draft renderer's variants
python tools/compare.py gallery_out/ docs/ compare/         # one sheet per card, side by side
```

The 23 cards of the gallery were compared by eye (the 19 `sample-*` kits only checked for
sanity). QGIS draws one reading of each open point, so a card is "matched" when that reading
is one of the variants of the draft renderer. Nothing here shows which reading the SWG should
pick; it shows where an independent renderer lands by default.

## Where QGIS agrees with the draft renderer's choice

| Card | QGIS |
|---|---|
| `casing-order` | casing beneath the stroke |
| `casing-width` | `width` is the whole band: a casing narrower than the stroke is hidden |
| `casing-crossing` | all casings first: crossings merge |
| `ndvi-division` | real-valued `/` (integer division would make every cell 0) |
| `sun-azimuth` | azimuth clockwise from north (GDAL's convention) |
| `color-channels` (`style.cs.json`) | bands divided by 2500 look the same as the draft renderer's |
| `gradient-angle` | angle read like CSS (0 towards the top, clockwise) |
| `gradient-frame` | gradient across each feature's bounding box |
| `dots` | 1 px dots in the fill colour |
| `font-outline` | outline beneath the glyphs, extending outward by `size` |
| `label-priority` | a higher value wins |
| `label-spacing` | repeated line labels, `minSpacing` apart, in px |
| `dash-units` | `dashPattern` values in px |
| `z-order` | a higher `zOrder` is drawn on top (across layers too) |
| `label-pass` | labels drawn above all features |

## Where it differs, or where QGIS has to choose

| Card | What happens | Reading |
|---|---|---|
| `color-channels` (`style-variant-2`, unscaled bands) | grey image: QGIS stretches each band between its min and max; the draft renderer clamps to 1 and draws white | the draft defines no mapping from band values to 0..1 |
| `hillshade-overlay`, `hillshade-factor`, `sun-azimuth` | `hillShading.factor` is not carried over; the overlay is GDAL's hillshade, multiplied | the draft does not say what `factor` scales. The examples' `factor: 56` is far beyond any usual exaggeration |
| `hillshade-overlay` (Example 9, intensity maps) | almost nothing is visible: with GDAL's hillshade 97.6 % of the cells have an intensity above 0.55, where the opacity map reaches 0 | confirms the draft-check finding by a second implementation |
| `gamma` | QGIS applies gamma to the colours and brightens, like the `c ^ (1 / gamma)` variant | `gamma` is not part of the draft's coverage model |
| `default-marker` | no marker is drawn; the draft's table has a default 10 px white `Dot` on every point, vertex and centroid | not implemented: the draft itself flags it as probably unintended |
| `casing-*` | line ends are flat (butt) where the draft renderer's are round | the draft sets no default `cap` |
| `opacity` | the darker band where stroke overlaps fill is drawn (the "separate" variant) | not investigated |
| `hatch-angle` | clockwise; the draft renderer's images of this card are blank in the extraction, so nothing to compare | the draft says clockwise |
| `sample-gradient-types-1` | all four fills are linear: a `type` given by a property is not carried over | QGIS gradient type is not data-driven here |
| `sample-vector-text-1` | `Text.alignment` is not carried over | |

## What the exercise changed in `cartosym-qgis`

Rendering the kits found real faults, now fixed: labels were not drawn when a rule drew nothing
else (QGIS only labels features a rule draws); a `Dot` given by its `stroke` was ignored;
`zOrder` was ignored; widths, priorities and offsets given as expressions or unit lists were not
read; `data:` images and CS-JSON properties unknown to pycartosym's model (`gamma`, `gradient`,
`dashOffset`, `colorChannels` as `{r, g, b}`) made a style fail. CS-JSON styles are now read as
they are, without validation.

## Limits of this comparison

- One reading per open point. The draft renderer's variants that QGIS does not take (casing
  band `extra`, counter-clockwise hatches, dash values as multiples of the width…) are not rendered.
- The comparison is by eye, on one machine, with one QGIS version.
- GDAL's hillshade and QGIS's colour handling are one more implementation, not a reference.
