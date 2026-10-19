"""Merged CartoSym symbolizers as QGIS symbols."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qgis.core import (
    Qgis,
    QgsFillSymbol,
    QgsCentroidFillSymbolLayer,
    QgsLinePatternFillSymbolLayer,
    QgsMarkerLineSymbolLayer,
    QgsPointPatternFillSymbolLayer,
    QgsRandomMarkerFillSymbolLayer,
    QgsRasterFillSymbolLayer,
    QgsSVGFillSymbolLayer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleMarkerSymbolLayerBase,
    QgsSymbol,
)
from qgis.PyQt.QtCore import Qt

from .markers import graphic_layer, marker_symbol, native_size, resolve
from .units import Unsupported, color, length

POLYGON, LINE, POINT = 2, 1, 0


@dataclass(frozen=True)
class Options:
    """Readings of requirements the draft leaves open (see /req/casing/casing).

    ``casing_width``: ``total`` (the casing's width is the whole band) or
    ``extra`` (it extends that far beyond each side of the stroke).
    ``casing_pass``: ``all-first`` (every casing is drawn before any stroke, so
    crossings merge) or ``with-feature`` (each feature's casing is drawn with
    its own stroke). ``hatch_angle``: the direction a hatch angle turns from the
    x axis. ``dash_units``: the unit of ``dashPattern`` values. ``outline_unit``: the
    unit of a font outline's ``size``. ``outline_extent``: whether ``size`` is how
    far the outline extends beyond the glyph (``outward``, as the draft words
    it) or the width of a stroke centred on the glyph contour (``centered``).
    """

    casing_width: str = "total"
    casing_pass: str = "all-first"
    hatch_angle: str = "clockwise"  # or "counter-clockwise", from the x axis
    dash_units: str = "px"  # or "stroke-width": dashPattern values are multiples of the width
    outline_unit: str = "px"  # unit of a font outline's size; "pt" matches Font.size
    base_dir: Path | None = None  # where relative image paths start (the style's folder)
    outline_extent: str = "outward"  # or "centered": size is the width of a stroke on the contour


def build_symbol(
    sym: dict[str, Any], dimension: int, notes: list[str], options: Options = Options()
) -> QgsSymbol | None:
    """Return a QGIS symbol for a merged symbolizer, or None if nothing draws.

    Constructs QGIS cannot express yet are appended to *notes*, not dropped
    silently.
    """
    layers = {
        POLYGON: _polygon_layers,
        LINE: _line_layers,
        POINT: _point_layers,
    }[dimension](sym, notes, options)
    if dimension != POINT:
        layers += _marker_layers(sym.get("marker"), dimension, notes, options)
    if not layers:
        return None
    if options.casing_pass == "all-first":  # layer N of every feature before N+1
        for order, layer in enumerate(layers):
            layer.setRenderingPass(order)
    cls = {POLYGON: QgsFillSymbol, LINE: QgsLineSymbol, POINT: QgsMarkerSymbol}[dimension]
    symbol = cls(layers)
    opacity = sym.get("opacity")
    if isinstance(opacity, (int, float)):
        symbol.setOpacity(float(opacity))
    elif opacity is not None:
        notes.append(f"opacity {opacity!r} (expression)")
    return symbol


def _stroke_width(stroke: dict[str, Any], notes: list[str]) -> tuple[float, Any]:
    try:
        return length(stroke.get("width", 1))
    except Unsupported as exc:
        notes.append(f"stroke.width: {exc}")
        return 1.0, Qgis.RenderUnit.Pixels


def _polygon_layers(sym: dict[str, Any], notes: list[str], options: Options) -> list[Any]:
    fill, stroke = sym.get("fill"), sym.get("stroke")
    if not fill and not stroke:
        return []
    layer = QgsSimpleFillSymbolLayer()
    hatch = _pattern_layer(fill or {}, notes, options)
    if hatch is not None:
        layer = hatch
    elif fill and "color" in fill:
        try:
            layer.setFillColor(color(fill["color"], fill.get("opacity")))
        except Unsupported as exc:
            notes.append(f"fill.color: {exc}")
            layer.setBrushStyle(Qt.NoBrush)
    else:
        layer.setBrushStyle(Qt.NoBrush)
    if not stroke:
        if hatch is None:
            layer.setStrokeStyle(Qt.NoPen)
        return [layer]

    width, unit = _stroke_width(stroke, notes)
    main = _outline(stroke, stroke.get("color", "black"), width, unit, notes)
    casing = _casing_outline(stroke, width, unit, notes, options)
    center = stroke.get("centerLine") or stroke.get("center")
    pattern = _pattern_stroke_layer(stroke, notes, options)
    if pattern is not None:
        return _polygon_with_pattern_outline(layer, hatch, stroke, casing, center, main, pattern, notes)
    if not casing and not center and hatch is None:  # fill and outline together
        layer.setStrokeColor(main.strokeColor())
        layer.setStrokeWidth(width)
        layer.setStrokeWidthUnit(unit)
        layer.setPenJoinStyle(main.penJoinStyle())
        return [layer]
    if hatch is None:
        layer.setStrokeStyle(Qt.NoPen)  # fill alone, the outlines are layers of their own
    layers = [layer]
    if casing:
        layers.append(casing)
    layers.append(main)
    if center:
        layers.append(_styling_outline(center, stroke, notes, "stroke.center"))
    return layers


def _pattern_layer(fill, notes, options):
    """The hatch, dot pattern or stipple layer of *fill*, if it has one."""
    if fill.get("hatch") is not None:
        return _hatch_layer(fill, fill["hatch"], notes, options)
    if fill.get("dotpattern") is not None:
        return _dot_pattern_layer(fill, fill["dotpattern"], notes)
    if fill.get("stipple") is not None:
        return _stipple_layer(fill, fill["stipple"], notes)
    if fill.get("pattern") is not None:
        return _graphic_fill_layer(fill["pattern"], notes, options)
    return None


def _graphic_fill_layer(graphic, notes, options):
    """An ``Image`` repeated over the fill (at its own size); other graphics are not tiled yet."""
    if graphic.get("type") != "Image":
        notes.append(f"fill.pattern {graphic.get('type')!r} not carried over")
        return None
    path = resolve(graphic.get("image") or {}, options.base_dir)
    if path is None:
        notes.append(f"fill.pattern image {(graphic.get('image') or {}).get('path')!r}: file not found")
        return None
    if path.suffix.lower() == ".svg":
        return QgsSVGFillSymbolLayer(str(path), native_size(path)[0])
    layer = QgsRasterFillSymbolLayer(str(path))
    layer.setWidth(native_size(path)[0])
    layer.setSizeUnit(Qgis.RenderUnit.Pixels)
    return layer


def _dot(fill, notes) -> QgsMarkerSymbol:
    """The draft leaves dot size and colour open (#84): a 1 px square in the fill colour."""
    marker = QgsSimpleMarkerSymbolLayer(QgsSimpleMarkerSymbolLayerBase.Shape.Square, 1.0)
    marker.setSizeUnit(Qgis.RenderUnit.Pixels)
    marker.setStrokeStyle(Qt.NoPen)
    try:
        marker.setColor(color(fill.get("color", "black"), fill.get("opacity")))
    except Unsupported as exc:
        notes.append(f"fill.color: {exc}")
    notes.append("~dot size and colour read as 1 px in the fill colour (the draft leaves them open)")
    return QgsMarkerSymbol([marker])


def _dot_pattern_layer(fill, dotpattern, notes) -> QgsPointPatternFillSymbolLayer:
    """A regular grid of dots; ``distance`` is one value, ``[h, v]`` or ``{horizontal, vertical}``."""
    layer = QgsPointPatternFillSymbolLayer()
    distance = dotpattern.get("distance", 10)
    if isinstance(distance, list) and len(distance) == 2:
        horizontal, vertical = distance
    elif isinstance(distance, dict) and "horizontal" in distance:
        horizontal, vertical = distance["horizontal"], distance.get("vertical", distance["horizontal"])
    else:
        horizontal = vertical = distance
    (dx, ux), (dy, uy) = (_length_or(v, 10, notes, "dotpattern.distance") for v in (horizontal, vertical))
    layer.setDistanceX(dx)
    layer.setDistanceXUnit(ux)
    layer.setDistanceY(dy)
    layer.setDistanceYUnit(uy)
    layer.setSubSymbol(_dot(fill, notes))
    return layer


_STIPPLE_AREA = 10000.0  # px²: the area the dot count is given for


def _stipple_layer(fill, stipple, notes) -> QgsRandomMarkerFillSymbolLayer:
    """Random dots covering ``ratio`` of the area (dots are 1 px², so count = ratio * area)."""
    ratio = stipple.get("ratio", 0.5)
    if not isinstance(ratio, (int, float)):
        notes.append(f"stipple.ratio {ratio!r} (expression)")
        ratio = 0.5
    layer = QgsRandomMarkerFillSymbolLayer()
    layer.setCountMethod(QgsRandomMarkerFillSymbolLayer.CountMethod.DensityBased)
    layer.setPointCount(max(1, round(float(ratio) * _STIPPLE_AREA)))
    layer.setDensityArea(_STIPPLE_AREA)
    layer.setDensityAreaUnit(Qgis.RenderUnit.Pixels)
    layer.setSeed(1)  # the same dots at every render
    layer.setSubSymbol(_dot(fill, notes))
    return layer


def _hatch_layer(fill, hatch, notes, options) -> QgsLinePatternFillSymbolLayer:
    """Parallel lines; the draft's defaults are 1 px wide, 45 degrees, 10 px apart."""
    layer = QgsLinePatternFillSymbolLayer()
    width, w_unit = _length_or(hatch.get("width"), 1, notes, "hatch.width")
    distance, d_unit = _length_or(hatch.get("distance"), 10, notes, "hatch.distance")
    angle = hatch.get("angle", 45)
    if not isinstance(angle, (int, float)):
        notes.append(f"hatch.angle {angle!r} (expression)")
        angle = 45
    layer.setDistance(distance)
    layer.setDistanceUnit(d_unit)
    layer.setLineWidth(width)
    layer.setLineWidthUnit(w_unit)
    # QGIS draws the pattern line from the sub-symbol: its width must be set too
    layer.subSymbol().setWidth(width)
    layer.subSymbol().setOutputUnit(w_unit)
    # QGIS turns counter-clockwise from the x axis
    layer.setLineAngle(float(angle) if options.hatch_angle == "counter-clockwise" else -float(angle))
    try:
        layer.subSymbol().setColor(color(fill.get("color", "black"), fill.get("opacity")))
    except Unsupported as exc:
        notes.append(f"fill.color: {exc}")
    return layer


def _length_or(value, default, notes, name) -> tuple[float, Any]:
    if value is None:
        return float(default), Qgis.RenderUnit.Pixels
    try:
        return length(value)
    except Unsupported as exc:
        notes.append(f"{name}: {exc}")
        return float(default), Qgis.RenderUnit.Pixels


def _polygon_with_pattern_outline(layer, hatch, stroke, casing, center, main, pattern, notes):
    """Fill, then the plain outline when the stroke has a colour or width, then the pattern."""
    if hatch is None:
        layer.setStrokeStyle(Qt.NoPen)
    layers = [layer]
    if casing:
        layers.append(casing)
    if "color" in stroke or "width" in stroke:
        layers.append(main)
    if center:
        layers.append(_styling_outline(center, stroke, notes, "stroke.center"))
    layers.append(pattern)
    return layers


def _outline(stroke, col, width, unit, notes) -> QgsSimpleFillSymbolLayer:
    """An outline-only fill layer."""
    layer = QgsSimpleFillSymbolLayer()
    layer.setBrushStyle(Qt.NoBrush)
    layer.setStrokeWidth(width)
    layer.setStrokeWidthUnit(unit)
    try:
        layer.setStrokeColor(color(col, stroke.get("opacity")))
    except Unsupported as exc:
        notes.append(f"stroke.color: {exc}")
    layer.setPenJoinStyle(_JOIN.get(stroke.get("join"), Qt.BevelJoin))
    return layer


def _styling_outline(styling, stroke, notes, name) -> QgsSimpleFillSymbolLayer:
    width, unit = _stroke_width(styling, notes)
    layer = _outline(
        {**stroke, "opacity": styling.get("opacity")}, styling.get("color", "black"), width, unit, notes
    )
    return layer


def _casing_outline(stroke, width, unit, notes, options) -> QgsSimpleFillSymbolLayer | None:
    casing = stroke.get("casing")
    if not casing:
        return None
    cw, cu = _casing_width(casing, width, unit, notes, options)
    return _outline(
        {**stroke, "opacity": casing.get("opacity")}, casing.get("color", "black"), cw, cu, notes
    )


def _casing_width(casing, width, unit, notes, options) -> tuple[float, Any]:
    cw, cu = _stroke_width(casing, notes)
    if options.casing_width == "extra":
        if cu == unit:
            return width + 2 * cw, unit
        notes.append("~casing width 'extra' needs the stroke's unit, read as 'total'")
    return cw, cu


_JOIN = {"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}
_CAP = {"butt": Qt.FlatCap, "round": Qt.RoundCap, "square": Qt.SquareCap}


def _line_layer(col, opacity, width, unit, stroke, notes) -> QgsSimpleLineSymbolLayer:
    layer = QgsSimpleLineSymbolLayer()
    layer.setWidth(width)
    layer.setWidthUnit(unit)
    try:
        layer.setColor(color(col, opacity))
    except Unsupported as exc:
        notes.append(f"stroke.color: {exc}")
    layer.setPenJoinStyle(_JOIN.get(stroke.get("join"), Qt.BevelJoin))
    layer.setPenCapStyle(_CAP.get(stroke.get("cap"), Qt.FlatCap))
    return layer


def _line_layers(sym: dict[str, Any], notes: list[str], options: Options) -> list[Any]:
    stroke = sym.get("stroke")
    if not stroke:
        return []
    width, unit = _stroke_width(stroke, notes)
    main = _line_layer(stroke.get("color", "black"), stroke.get("opacity"), width, unit, stroke, notes)
    pattern = _pattern_stroke_layer(stroke, notes, options)
    if pattern is not None and "color" not in stroke and "width" not in stroke:
        return [pattern]  # a pattern alone replaces the plain line
    dash = stroke.get("dashPattern")
    if isinstance(dash, list) and dash:
        main.setUseCustomDashPattern(True)
        if options.dash_units == "stroke-width":
            main.setCustomDashVector([float(d) * width for d in dash])
            main.setCustomDashPatternUnit(unit)
        else:
            main.setCustomDashVector([float(d) for d in dash])
            main.setCustomDashPatternUnit(Qgis.RenderUnit.Pixels)
        notes.append(f"~stroke.dashPattern values read as {options.dash_units} (the draft leaves it open)")
    layers = [main]
    casing = stroke.get("casing")
    if casing:
        cw, cu = _casing_width(casing, width, unit, notes, options)
        layers.insert(0, _line_layer(casing.get("color", "black"), casing.get("opacity"), cw, cu, stroke, notes))
    center = stroke.get("centerLine") or stroke.get("center")
    if center:
        w, u = _stroke_width(center, notes)
        layers.append(_line_layer(center.get("color", "black"), center.get("opacity"), w, u, stroke, notes))
    if pattern is not None:
        layers.append(pattern)
    return layers


def _point_layers(sym: dict[str, Any], notes: list[str], options: Options) -> list[Any]:
    marker = sym.get("marker")
    if not marker:
        return []
    layers = []
    for element in marker.get("elements", []):
        layer = graphic_layer(element, notes, options.base_dir)
        if layer is not None:
            layers.append(layer)
    return layers


def _pattern_stroke_layer(stroke, notes: list[str], options: Options):
    """A graphic repeated along the stroke, ``patternGap`` apart (it follows the line)."""
    graphic = stroke.get("pattern")
    if graphic is None:
        return None
    symbol = marker_symbol([graphic], notes, options.base_dir)
    if symbol is None:
        return None
    layer = QgsMarkerLineSymbolLayer()
    layer.setPlacements(Qgis.MarkerLinePlacements(Qgis.MarkerLinePlacement.Interval))
    layer.setRotateSymbols(True)
    for key, setter, unit_setter in (
        ("patternGap", layer.setInterval, layer.setIntervalUnit),
        ("patternInitialGap", layer.setOffsetAlongLine, layer.setOffsetAlongLineUnit),
    ):
        if key not in stroke:
            continue
        try:
            value, unit = length(stroke[key])
        except Unsupported as exc:
            notes.append(f"stroke.{key}: {exc}")
            continue
        setter(value)
        unit_setter(unit)
    layer.setSubSymbol(symbol)
    return layer


def _marker_layers(marker, dimension: int, notes: list[str], options: Options) -> list[Any]:
    """A marker on a polygon sits at its centroid, on a line at every vertex."""
    if not marker:
        return []
    symbol = marker_symbol(marker.get("elements", []), notes, options.base_dir)
    if symbol is None:
        return []
    if dimension == POLYGON:
        layer = QgsCentroidFillSymbolLayer()
        layer.setSubSymbol(symbol)
        return [layer]
    layer = QgsMarkerLineSymbolLayer()
    layer.setPlacements(Qgis.MarkerLinePlacements(Qgis.MarkerLinePlacement.Vertex))
    layer.setRotateSymbols(False)  # a marker faces the viewer, it does not follow the line
    layer.setSubSymbol(symbol)
    return [layer]

