"""Merged CartoSym symbolizers as QGIS symbols."""

from __future__ import annotations

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
_NOTES = ("casing", "centerLine", "pattern", "hatch", "dotpattern", "stipple")


def build_symbol(sym: dict[str, Any], dimension: int, notes: list[str]) -> QgsSymbol | None:
    """Return a QGIS symbol for a merged symbolizer, or None if nothing draws.

    Constructs QGIS cannot express yet are appended to *notes*, not dropped
    silently.
    """
    layers = {
        POLYGON: _polygon_layers,
        LINE: _line_layers,
        POINT: _point_layers,
    }[dimension](sym, notes)
    if not layers:
        return None
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


def _polygon_layers(sym: dict[str, Any], notes: list[str]) -> list[Any]:
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
    if stroke:
        width, unit = _stroke_width(stroke, notes)
        layer.setStrokeWidth(width)
        layer.setStrokeWidthUnit(unit)
        try:
            layer.setStrokeColor(color(stroke.get("color", "black"), stroke.get("opacity")))
        except Unsupported as exc:
            notes.append(f"stroke.color: {exc}")
        layer.setPenJoinStyle(_JOIN.get(stroke.get("join"), Qt.BevelJoin))
    else:
        layer.setStrokeStyle(Qt.NoPen)
    _note_unsupported(fill, "fill", notes)
    _note_unsupported(stroke, "stroke", notes)
    return [layer]


_JOIN = {"miter": Qt.MiterJoin, "round": Qt.RoundJoin, "bevel": Qt.BevelJoin}
_CAP = {"butt": Qt.FlatCap, "round": Qt.RoundCap, "square": Qt.SquareCap}


def _line_layers(sym: dict[str, Any], notes: list[str]) -> list[Any]:
    stroke = sym.get("stroke")
    if not stroke:
        return []
    layer = QgsSimpleLineSymbolLayer()
    width, unit = _stroke_width(stroke, notes)
    layer.setWidth(width)
    layer.setWidthUnit(unit)
    try:
        layer.setColor(color(stroke.get("color", "black"), stroke.get("opacity")))
    except Unsupported as exc:
        notes.append(f"stroke.color: {exc}")
    layer.setPenJoinStyle(_JOIN.get(stroke.get("join"), Qt.BevelJoin))
    layer.setPenCapStyle(_CAP.get(stroke.get("cap"), Qt.FlatCap))
    dash = stroke.get("dashPattern")
    if isinstance(dash, list) and dash:
        layer.setUseCustomDashPattern(True)
        layer.setCustomDashVector([float(d) for d in dash])
        layer.setCustomDashPatternUnit(unit)
        notes.append("stroke.dashPattern: unit assumed to be the stroke's (spec open)")
    _note_unsupported(stroke, "stroke", notes)
    return [layer]


def _point_layers(sym: dict[str, Any], notes: list[str]) -> list[Any]:
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
