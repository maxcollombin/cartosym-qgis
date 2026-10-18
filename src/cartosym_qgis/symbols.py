"""Merged CartoSym symbolizers as QGIS symbols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qgis.core import (
    Qgis,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleMarkerSymbolLayerBase,
    QgsSymbol,
)
from qgis.PyQt.QtCore import Qt

from .units import Unsupported, color, length

POLYGON, LINE, POINT = 2, 1, 0
_NOTES = ("pattern", "hatch", "dotpattern", "stipple")


@dataclass(frozen=True)
class Options:
    """Readings of requirements the draft leaves open (see /req/casing/casing).

    ``casing_width``: ``total`` (the casing's width is the whole band) or
    ``extra`` (it extends that far beyond each side of the stroke).
    ``casing_pass``: ``all-first`` (every casing is drawn before any stroke, so
    crossings merge) or ``with-feature`` (each feature's casing is drawn with
    its own stroke).
    """

    casing_width: str = "total"
    casing_pass: str = "all-first"


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
    if fill and "color" in fill:
        try:
            layer.setFillColor(color(fill["color"], fill.get("opacity")))
        except Unsupported as exc:
            notes.append(f"fill.color: {exc}")
            layer.setBrushStyle(Qt.NoBrush)
    else:
        layer.setBrushStyle(Qt.NoBrush)
    _note_unsupported(fill, "fill", notes)
    if not stroke:
        layer.setStrokeStyle(Qt.NoPen)
        return [layer]

    _note_unsupported(stroke, "stroke", notes)
    width, unit = _stroke_width(stroke, notes)
    main = _outline(stroke, stroke.get("color", "black"), width, unit, notes)
    casing = _casing_outline(stroke, width, unit, notes, options)
    center = stroke.get("centerLine") or stroke.get("center")
    if not casing and not center:  # one layer: fill and outline together
        layer.setStrokeColor(main.strokeColor())
        layer.setStrokeWidth(width)
        layer.setStrokeWidthUnit(unit)
        layer.setPenJoinStyle(main.penJoinStyle())
        return [layer]
    layer.setStrokeStyle(Qt.NoPen)  # fill alone, the outlines are layers of their own
    layers = [layer]
    if casing:
        layers.append(casing)
    layers.append(main)
    if center:
        layers.append(_styling_outline(center, stroke, notes, "stroke.center"))
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
    dash = stroke.get("dashPattern")
    if isinstance(dash, list) and dash:
        main.setUseCustomDashPattern(True)
        main.setCustomDashVector([float(d) for d in dash])
        main.setCustomDashPatternUnit(unit)
        notes.append("~stroke.dashPattern unit read as the stroke's (the draft leaves it open)")
    _note_unsupported(stroke, "stroke", notes)
    layers = [main]
    casing = stroke.get("casing")
    if casing:
        cw, cu = _casing_width(casing, width, unit, notes, options)
        layers.insert(0, _line_layer(casing.get("color", "black"), casing.get("opacity"), cw, cu, stroke, notes))
    center = stroke.get("centerLine") or stroke.get("center")
    if center:
        w, u = _stroke_width(center, notes)
        layers.append(_line_layer(center.get("color", "black"), center.get("opacity"), w, u, stroke, notes))
    return layers


def _point_layers(sym: dict[str, Any], notes: list[str], options: Options) -> list[Any]:
    marker = sym.get("marker")
    if not marker:
        return []
    layers = []
    for element in marker.get("elements", []):
        if element.get("type") != "Dot":
            notes.append(f"marker element {element.get('type')!r}")
            continue
        shape = QgsSimpleMarkerSymbolLayerBase.Shape.Circle
        size, unit = (10.0, Qgis.RenderUnit.Pixels)
        try:
            if "size" in element:
                size, unit = length(element["size"])
        except Unsupported as exc:
            notes.append(f"Dot.size: {exc}")
        layer = QgsSimpleMarkerSymbolLayer(shape, size)
        layer.setSizeUnit(unit)
        try:
            layer.setColor(color(element.get("color", "white"), element.get("opacity")))
        except Unsupported as exc:
            notes.append(f"Dot.color: {exc}")
        layer.setStrokeStyle(Qt.NoPen)
        layers.append(layer)
    return layers


def _note_unsupported(part: dict[str, Any] | None, name: str, notes: list[str]) -> None:
    for key in _NOTES:
        if part and part.get(key):
            notes.append(f"{name}.{key}")
