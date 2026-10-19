"""CartoSym coverage styling (``singleChannel``, ``colorChannels``, ``colorMap``,
``alphaChannel``, ``hillShading``) as QGIS raster layers.

QGIS cannot select by cell value, so what depends on the cells (an expression
over bands, and ``alphaChannel`` through selectors such as ``[SCL=8]``) is
computed here into a temporary GeoTIFF; QGIS then colours and draws it.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal
from qgis.core import (
    QgsColorRampShader,
    QgsContrastEnhancement,
    QgsMultiBandColorRenderer,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor, QPainter

from . import expressions
from .renderer import Report, _merge
from .units import Unsupported, color

gdal.UseExceptions()
NODATA = -9999.0


def read_band(path: Path) -> tuple[np.ndarray, tuple, str]:
    """``(array, geotransform, projection)`` of a one-band raster; no-data is NaN."""
    ds = gdal.Open(str(path))
    array = ds.GetRasterBand(1).ReadAsArray().astype("float64")
    array[array == NODATA] = np.nan
    return array, ds.GetGeoTransform(), ds.GetProjection()


def evaluate(node: Any, bands: dict[str, np.ndarray]):
    """Evaluate a numeric CQL2-JSON expression over band arrays (division is real)."""
    if isinstance(node, bool):
        raise Unsupported("boolean in a numeric expression")
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, dict) and "property" in node:
        if node["property"] not in bands:
            raise Unsupported(f"band {node['property']!r}")
        return bands[node["property"]]
    if isinstance(node, dict) and "op" in node:
        args = [evaluate(a, bands) for a in node["args"]]
        ops = {
            "+": lambda a, b: a + b,
            "-": lambda a, b: a - b,
            "*": lambda a, b: a * b,
            "/": lambda a, b: np.divide(a, b, out=np.full(np.shape(a), np.nan), where=np.asarray(b) != 0),
            "^": lambda a, b: np.power(a, b),
        }
        if node["op"] in ops and len(args) == 2:
            return ops[node["op"]](*args)
    raise Unsupported(f"expression {node!r}")


@dataclass
class _Node:
    sym: dict[str, Any]
    equals: set[tuple[str, Any]]
    min_scale: float
    max_scale: float


def _walk(rule, inherited, layer_id, scale, report, out) -> None:
    cond = expressions.analyse(rule.get("selector"))
    for dropped in cond.dropped:
        report.add("coverage", f"selector dropped ({dropped})")
    for flt in cond.filters:
        report.add("coverage", f"selector {flt} not carried over (only band = value is)")
    if layer_id and cond.layer_ids and layer_id not in cond.layer_ids:
        return
    chain = [*inherited, cond]
    min_scale = min((c.min_scale for c in chain if c.min_scale), default=float("inf"))
    max_scale = max(c.max_scale for c in chain)
    if scale is not None and not (max_scale <= scale < min_scale):
        return
    out.append(_Node(rule.get("symbolizer") or {}, {e for c in chain for e in c.equals}, min_scale, max_scale))
    for child in rule.get("nestedRules", []):
        if child.get("selector") is not None:
            _walk(child, chain, layer_id, scale, report, out)


def _states(nodes: list[_Node]):
    """Every combination of the band values the selectors test, with the merged symbolizer."""
    groups: dict[str, list[Any]] = {}
    for n in nodes:
        for prop, lit in n.equals:
            if lit not in groups.setdefault(prop, []):
                groups[prop].append(lit)
    props = list(groups)
    for states in product(*(range(len(groups[p]) + 1) for p in props)):
        chosen = {p: (groups[p][i] if i < len(groups[p]) else None) for p, i in zip(props, states)}
        merged: dict[str, Any] = {}
        for n in nodes:
            if all(chosen.get(p) == lit for p, lit in n.equals):
                merged = _merge(merged, n.sym)
        yield chosen, merged


def _interpolate(stops: list[tuple[float, Any]], x: float) -> np.ndarray:
    """Linear interpolation between ``(value, [components])`` stops, clamped at both ends."""
    xs = [s[0] for s in stops]
    return np.array([np.interp(x, xs, [s[1][i] for s in stops]) for i in range(len(stops[0][1]))])


def _ramp_items(color_map, opacity_map, notes):
    """Ramp items from a ``colorMap`` and/or ``opacityMap`` (value, colour/opacity pairs)."""
    colors = []
    for value, col in color_map or []:
        c = color(col)
        colors.append((float(value), [c.red(), c.green(), c.blue()]))
    opacities = [(float(v), [float(o)]) for v, o in (opacity_map or [])]
    xs = sorted({s[0] for s in colors} | {s[0] for s in opacities})
    items = []
    for x in xs:
        rgb = _interpolate(colors, x) if colors else np.array([0, 0, 0])
        alpha = _interpolate(opacities, x)[0] if opacities else 1.0
        qcolor = QColor(int(round(rgb[0])), int(round(rgb[1])), int(round(rgb[2])))
        qcolor.setAlphaF(float(alpha))
        items.append(QgsColorRampShader.ColorRampItem(x, qcolor, str(x)))
    return items


def _write_tiff(path: Path, arrays: list[np.ndarray], geotransform, projection) -> None:
    rows, cols = arrays[0].shape
    ds = gdal.GetDriverByName("GTiff").Create(str(path), cols, rows, len(arrays), gdal.GDT_Float32)
    ds.SetGeoTransform(geotransform)
    ds.SetProjection(projection)
    for i, array in enumerate(arrays, 1):
        band = ds.GetRasterBand(i)
        band.SetNoDataValue(NODATA)
        band.WriteArray(np.where(np.isnan(array), NODATA, array))
    ds.FlushCache()


def _pseudocolor(layer: QgsRasterLayer, items, alpha_band: int | None) -> None:
    shader = QgsColorRampShader()
    shader.setColorRampType(QgsColorRampShader.Interpolated)  # linear, clamped beyond the ends
    shader.setColorRampItemList(items)
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(shader)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, raster_shader)
    renderer.setClassificationMin(items[0].value)
    renderer.setClassificationMax(items[-1].value)
    if alpha_band:
        renderer.setAlphaBand(alpha_band)
    layer.setRenderer(renderer)


@dataclass
class Coverage:
    layers: list[QgsRasterLayer] = field(default_factory=list)
    workdir: Any = None  # keeps the temporary files alive


def build_coverage(
    style: dict[str, Any],
    layer_id: str,
    bands: dict[str, Path],
    scale: float | None,
    report: Report,
) -> Coverage:
    """QGIS raster layers (bottom first) drawing the coverage *layer_id* with *style*."""
    nodes: list[_Node] = []
    for rule in style.get("stylingRules", []):
        _walk(rule, [], layer_id, scale, report, nodes)
    states = list(_states(nodes))
    if not states or all(m.get("visibility", True) is False for _c, m in states):
        return Coverage()
    base = next(m for _c, m in states if m.get("visibility", True) is not False)

    arrays = {name: read_band(path) for name, path in bands.items()}
    values = {name: a[0] for name, a in arrays.items()}
    _first, geotransform, projection = next(iter(arrays.values()))
    shape = next(iter(values.values())).shape

    # alphaChannel, per cell: each state of the tested band values sets its own
    alpha = np.ones(shape)
    varies = False
    for chosen, merged in states:
        a = 0.0 if merged.get("visibility", True) is False else merged.get("alphaChannel", 1.0)
        if not isinstance(a, (int, float)):
            report.add("coverage", "alphaChannel expression not carried over")
            a = 1.0
        mask = np.ones(shape, dtype=bool)
        for prop, lit in chosen.items():
            if lit is None:  # none of the tested values
                tested = [e[1] for n in nodes for e in n.equals if e[0] == prop]
                mask &= ~np.isin(values[prop], tested)
            else:
                mask &= values[prop] == lit
        alpha[mask] = a
        varies |= a != 1.0
        for key in merged:
            if key not in ("alphaChannel", "visibility") and merged.get(key) != base.get(key):
                report.add("coverage", f"{key} varying with the cell values not carried over")

    # QGIS reads an alpha band as 0..255; none is written when every cell is opaque
    alpha_bands = [alpha * 255.0] if (alpha != 1.0).any() else []
    work = Path(tempfile.mkdtemp(prefix="cartosym-qgis-"))
    result = Coverage(workdir=work)
    opacity = base.get("opacity", 1.0) if isinstance(base.get("opacity", 1.0), (int, float)) else 1.0
    hill = base.get("hillShading")

    try:
        if base.get("colorChannels"):
            spec = base["colorChannels"]
            # {r, g, b}: components in 0..1 given by expressions; [a, b, c]: raw bands
            fixed = isinstance(spec, dict)
            names = [spec[k] for k in ("r", "g", "b")] if fixed else spec[:3]
            channels = [evaluate(c, values) for c in names]
            path = work / "color.tif"
            _write_tiff(path, [*channels, *alpha_bands], geotransform, projection)
            layer = QgsRasterLayer(str(path), f"{layer_id} colour")
            renderer = QgsMultiBandColorRenderer(layer.dataProvider(), 1, 2, 3)
            for setter in (renderer.setRedContrastEnhancement, renderer.setGreenContrastEnhancement, renderer.setBlueContrastEnhancement):
                enhancement = QgsContrastEnhancement(layer.dataProvider().dataType(1))
                enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
                if fixed:
                    enhancement.setMinimumValue(0.0)
                    enhancement.setMaximumValue(1.0)
                setter(enhancement)
            if alpha_bands:
                renderer.setAlphaBand(4)
            layer.setRenderer(renderer)
            layer.setOpacity(opacity)
            _gamma(layer, base, report)
            result.layers.append(layer)
            if not fixed:
                report.assumed.append("coverage: band values stretched to their min/max (the draft defines no mapping to 0..1)")
        elif base.get("singleChannel") is not None and base.get("colorMap"):
            single = evaluate(base["singleChannel"], values)
            path = work / "single.tif"
            _write_tiff(path, [single, *alpha_bands], geotransform, projection)
            layer = QgsRasterLayer(str(path), f"{layer_id} colour map")
            _pseudocolor(layer, _ramp_items(base["colorMap"], None, report), 2 if alpha_bands else None)
            layer.setOpacity(opacity)
            _gamma(layer, base, report)
            result.layers.append(layer)
            report.assumed.append("coverage: colorMap interpolated linearly, clamped beyond its ends (the draft leaves it open)")
        if hill and base.get("singleChannel") is not None:
            result.layers.append(_hillshade(base, hill, values, geotransform, projection, work, opacity, report, layer_id))
    except Unsupported as exc:
        report.add("coverage", str(exc))
    return result


def _gamma(layer: QgsRasterLayer, base: dict[str, Any], report: Report) -> None:
    """``gamma`` is not in the draft's coverage model (#86); QGIS applies it to the colours."""
    gamma = base.get("gamma")
    if gamma is None:
        return
    if not isinstance(gamma, (int, float)) or gamma <= 0:
        report.add("coverage", f"gamma {gamma!r} not carried over")
        return
    layer.brightnessFilter().setGamma(float(gamma))
    report.assumed.append("coverage: gamma applied to the colours (it is not part of the draft's coverage model)")


def _hillshade(base, hill, values, geotransform, projection, work, opacity, report, layer_id) -> QgsRasterLayer:
    elevation = evaluate(base["singleChannel"], values)
    dem = work / "dem.tif"
    _write_tiff(dem, [elevation], geotransform, projection)
    sun = hill.get("sun") or {}
    out = work / "hillshade.tif"
    gdal.DEMProcessing(
        str(out), str(dem), "hillshade",
        azimuth=float(sun.get("azimuth", 315)), altitude=float(sun.get("elevation", 45)),
        computeEdges=True,
    )
    layer = QgsRasterLayer(str(out), f"{layer_id} hill shading")
    if hill.get("colorMap") or hill.get("opacityMap"):
        # the maps are on the 0..1 shading intensity; GDAL's shade is 0..255
        items = _ramp_items(hill.get("colorMap"), hill.get("opacityMap"), report)
        for item in items:
            item.value *= 255.0
        _pseudocolor(layer, items, None)
    else:
        layer.setBlendMode(QPainter.CompositionMode_Multiply)
    layer.setOpacity(opacity)
    report.add("coverage", "hillShading.factor not carried over (the draft does not define its scale)")
    report.assumed.append("coverage: hillShading.sun.azimuth read clockwise from north")
    return layer
