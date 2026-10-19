"""Merged CartoSym symbolizers as QGIS symbols."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qgis.core import (
    Qgis,
    QgsFillSymbol,
    QgsGradientColorRamp,
    QgsGradientFillSymbolLayer,
    QgsGradientStop,
    QgsCentroidFillSymbolLayer,
    QgsLinePatternFillSymbolLayer,
    QgsMarkerLineSymbolLayer,
    QgsPointPatternFillSymbolLayer,
    QgsRandomMarkerFillSymbolLayer,
    QgsRasterFillSymbolLayer,
    QgsSVGFillSymbolLayer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProperty,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleMarkerSymbolLayerBase,
    QgsSymbol,
    QgsSymbolLayer,
)
from math import cos, radians, sin

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QColor

from . import expressions
from .markers import graphic_layer, marker_symbol, native_size, resolve
from .units import _UNITS, Unsupported, color, length

POLYGON, LINE, POINT = 2, 1, 0


@dataclass(frozen=True)
class Options:
    """Where relative image paths start (the style's folder)."""

    base_dir: Path | None = None


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
    z = sym.get("zOrder")
    z = int(z) if isinstance(z, (int, float)) else 0
    # with symbol levels QGIS draws pass by pass: a higher zOrder is drawn later (on top),
    # and within one zOrder layer N of every feature before layer N + 1 (casings first)
    for order, layer in enumerate(layers):
        layer.setRenderingPass(order + 16 * (z + 1000))
    cls = {POLYGON: QgsFillSymbol, LINE: QgsLineSymbol, POINT: QgsMarkerSymbol}[dimension]
    symbol = cls(layers)
    opacity = sym.get("opacity")
    if isinstance(opacity, (int, float)):
        symbol.setOpacity(float(opacity))
    elif opacity is not None:
        notes.append(f"opacity {opacity!r} (expression)")
    return symbol


def invisible_symbol(dimension: int) -> QgsSymbol:
    """A symbol that draws nothing: QGIS labels only the features a rule draws."""
    if dimension == POLYGON:
        layer = QgsSimpleFillSymbolLayer()
        layer.setBrushStyle(Qt.NoBrush)
        layer.setStrokeStyle(Qt.NoPen)
        return QgsFillSymbol([layer])
    if dimension == LINE:
        layer = QgsSimpleLineSymbolLayer()
        layer.setPenStyle(Qt.NoPen)
        return QgsLineSymbol([layer])
    layer = QgsSimpleMarkerSymbolLayer()
    layer.setColor(QColor(0, 0, 0, 0))
    layer.setStrokeStyle(Qt.NoPen)
    return QgsMarkerSymbol([layer])


def _is_expression(value: Any) -> bool:
    return isinstance(value, dict) and ("op" in value or "property" in value or "sysId" in value)


def _unit_expression(value: Any):
    """``(expression, QGIS unit)`` for ``{"px": <expression>}``, else None."""
    if isinstance(value, dict) and len(value) == 1:
        ((unit, inner),) = value.items()
        if _is_expression(inner) and unit in _UNITS:
            return inner, _UNITS[unit][0]
    return None


def _stroke_width(stroke: dict[str, Any], notes: list[str]) -> tuple[float, Any]:
    """The stroke width; one given by an expression is set on the layer by :func:`_data_defined_width`."""
    width = stroke.get("width")
    if _is_expression(width):
        return 1.0, Qgis.RenderUnit.Pixels
    if (wrapped := _unit_expression(width)) is not None:
        return 1.0, wrapped[1]
    try:
        return length(stroke.get("width", 1))
    except Unsupported as exc:
        notes.append(f"stroke.width: {exc}")
        return 1.0, Qgis.RenderUnit.Pixels


def _data_defined_width(layer, styling: dict[str, Any], notes: list[str]) -> None:
    """A width that is an expression (``lanes * 3 + 1``) is evaluated per feature (px unless given)."""
    width = styling.get("width")
    if (wrapped := _unit_expression(width)) is not None:
        width = wrapped[0]
    elif not _is_expression(width):
        return
    else:
        notes.append("~stroke.width expression read in px")
    try:
        expression = expressions.to_qgis(width)
    except Unsupported as exc:
        notes.append(f"stroke.width: {exc}")
        return
    layer.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeWidth, QgsProperty.fromExpression(expression))


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
    _data_defined_width(main, stroke, notes)
    casing = _casing_outline(stroke, width, unit, notes, options)
    center = stroke.get("centerLine") or stroke.get("center")
    pattern = _pattern_stroke_layer(stroke, notes, options)
    if pattern is not None:
        return _polygon_with_pattern_outline(layer, hatch, stroke, casing, center, main, pattern, notes)
    if not casing and not center and hatch is None:  # fill and outline together
        layer.setStrokeColor(main.strokeColor())
        layer.setStrokeWidth(width)
        layer.setStrokeWidthUnit(unit)
        _data_defined_width(layer, stroke, notes)
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
    if fill.get("gradient") is not None:
        return _gradient_layer(fill["gradient"], notes)
    return None


def _gradient_layer(gradient: dict[str, Any], notes: list[str]) -> QgsGradientFillSymbolLayer | None:
    """A linear, radial or conic gradient across the feature's bounding box.

    ``angle`` is read like CSS (0 towards the top, clockwise); ``position`` and
    ``size`` are fractions of the bounding box, ``size`` being the diameter.
    """
    keys = gradient.get("keys") or []
    if len(keys) < 2:
        notes.append("fill.gradient needs at least two keys")
        return None
    stops = []
    try:
        colors = [color(k["color"], k.get("opacity")) for k in keys]
    except Unsupported as exc:
        notes.append(f"fill.gradient key colour: {exc}")
        return None
    for index, key in enumerate(keys[1:-1], 1):
        offset = key.get("percent")
        if not isinstance(offset, (int, float)):
            offset = index / (len(keys) - 1)
        stops.append(QgsGradientStop(float(offset), colors[index]))
    kind = gradient.get("type", "linear")
    if kind not in ("linear", "radial", "conic", "conical"):
        notes.append(f"fill.gradient type {kind!r} (expression) read as linear")
        kind = "linear"
    angle = radians(float(gradient.get("angle", 0)) if isinstance(gradient.get("angle", 0), (int, float)) else 0)
    dx, dy = sin(angle), -cos(angle)  # screen y points down
    position = gradient.get("position") or [0.5, 0.5]
    size = gradient.get("size", 1)
    layer = QgsGradientFillSymbolLayer()
    layer.setGradientColorType(QgsGradientFillSymbolLayer.GradientColorType.ColorRamp)
    layer.setColorRamp(QgsGradientColorRamp(colors[0], colors[-1], False, stops))
    layer.setCoordinateMode(Qgis.SymbolCoordinateReference.Feature)
    if kind == "linear":
        layer.setGradientType(QgsGradientFillSymbolLayer.GradientType.Linear)
        layer.setReferencePoint1(QPointF(0.5 - dx / 2, 0.5 - dy / 2))
        layer.setReferencePoint2(QPointF(0.5 + dx / 2, 0.5 + dy / 2))
    else:
        centre = QPointF(float(position[0]), float(position[1]))
        if kind == "radial":
            layer.setGradientType(QgsGradientFillSymbolLayer.GradientType.Radial)
            layer.setReferencePoint2(QPointF(centre.x() + float(size) / 2, centre.y()))
        else:
            layer.setGradientType(QgsGradientFillSymbolLayer.GradientType.Conical)
            layer.setReferencePoint2(QPointF(centre.x() + dx / 2, centre.y() + dy / 2))
        layer.setReferencePoint1(centre)
    notes.append("~fill.gradient angle read like CSS (0 towards the top, clockwise), position and size relative to the feature")
    return layer


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
    # the draft turns clockwise from the x axis, QGIS counter-clockwise
    layer.setLineAngle(-float(angle))
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
    cw, cu = _casing_width(casing, notes)
    return _outline(
        {**stroke, "opacity": casing.get("opacity")}, casing.get("color", "black"), cw, cu, notes
    )


def _casing_width(casing, notes) -> tuple[float, Any]:
    """The casing's ``width`` is read as the whole band (the draft leaves it open)."""
    return _stroke_width(casing, notes)


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
    _data_defined_width(main, stroke, notes)
    pattern = _pattern_stroke_layer(stroke, notes, options)
    if pattern is not None and "color" not in stroke and "width" not in stroke:
        return [pattern]  # a pattern alone replaces the plain line
    dash = stroke.get("dashPattern")
    if isinstance(dash, list) and dash:
        main.setUseCustomDashPattern(True)
        main.setCustomDashVector([float(d) for d in dash])
        main.setCustomDashPatternUnit(Qgis.RenderUnit.Pixels)
        notes.append("~stroke.dashPattern values read in px (the draft leaves it open)")
        if stroke.get("dashOffset") is not None:
            try:
                offset, offset_unit = length(stroke["dashOffset"])
                main.setDashPatternOffset(offset)
                main.setDashPatternOffsetUnit(offset_unit)
            except Unsupported as exc:
                notes.append(f"stroke.dashOffset: {exc}")
    layers = [main]
    casing = stroke.get("casing")
    if casing:
        cw, cu = _casing_width(casing, notes)
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

