"""CartoSym ``Text`` label elements as QGIS label settings."""

from __future__ import annotations

from typing import Any

from qgis.core import (
    Qgis,
    QgsPalLayerSettings,
    QgsProperty,
    QgsTextBufferSettings,
    QgsTextFormat,
)
from qgis.PyQt.QtGui import QFont

from . import expressions
from .symbols import LINE, Options
from .units import Unsupported, color, length


def _text_source(text: Any, notes: list[str]) -> tuple[str, bool] | None:
    """``(field or expression, is_expression)`` for a Text's ``text`` value."""
    if isinstance(text, dict) and "property" in text:
        return text["property"], False
    try:
        if isinstance(text, str):
            return expressions.literal(text), True
        return expressions.to_qgis(text), True
    except Unsupported as exc:
        notes.append(f"Text.text: {exc}")
        return None


def label_settings(
    label: dict[str, Any],
    dimension: int,
    notes: list[str],
    options: Options,
    always: bool = False,
) -> list[QgsPalLayerSettings]:
    """One QGIS label setting per ``Text`` element of *label*.

    A ``Text`` of a marker (*always*) is drawn at every point: no label is left out.
    """
    out = []
    for element in label.get("elements", []):
        kind = element.get("type")
        if kind != "Text":
            if not always:
                notes.append(f"label element {kind!r}")
            continue
        source = _text_source(element.get("text"), notes)
        if source is None:
            continue
        settings = QgsPalLayerSettings()
        settings.fieldName, settings.isExpression = source
        settings.setFormat(_format(element.get("font") or {}, notes, options))
        settings.placement = (
            Qgis.LabelPlacement.Line if dimension == LINE else Qgis.LabelPlacement.OverPoint
        )
        if always:
            settings.displayAll = True
        _offset(settings, element.get("position"), notes)
        if element.get("alignment"):
            notes.append("Text.alignment not carried over")
        placement = label.get("placement") or {}
        priority = placement.get("priority")
        if isinstance(priority, (int, float)):
            settings.priority = max(0, min(10, int(priority)))  # higher draws first
        elif priority is not None:
            try:
                properties = settings.dataDefinedProperties()
                properties.setProperty(
                    QgsPalLayerSettings.Property.Priority,
                    QgsProperty.fromExpression(expressions.to_qgis(priority)),
                )
                settings.setDataDefinedProperties(properties)
                notes.append("~Label.placement.priority read as higher value wins (QGIS: 0 to 10)")
            except Unsupported as exc:
                notes.append(f"Label.placement.priority: {exc}")
        if placement.get("minSpacing") is not None:
            try:
                distance, unit = length(placement["minSpacing"])
                settings.repeatDistance = distance
                settings.repeatDistanceUnit = unit
                notes.append("~Label.placement.minSpacing read as the distance between repeated labels (px unless given)")
            except Unsupported as exc:
                notes.append(f"Label.placement.minSpacing: {exc}")
        if placement.get("maxSpacing") is not None:
            notes.append("Label.placement.maxSpacing")
        out.append(settings)
    return out


def _offset(settings: QgsPalLayerSettings, position: Any, notes: list[str]) -> None:
    """``position`` moves the label from its point; ``y`` is read as downwards."""
    if not position:
        return
    if isinstance(position, list):
        position = {"x": position[0], "y": position[1]}
    try:
        x, unit = length(position.get("x", 0))
        y, _ = length(position.get("y", 0))
    except Unsupported as exc:
        notes.append(f"Text.position: {exc}")
        return
    settings.xOffset = x
    settings.yOffset = y  # like a marker offset: positive moves down
    settings.offsetUnits = unit
    notes.append("~Text.position y read as downwards, like screen coordinates")


def _format(font: dict[str, Any], notes: list[str], options: Options) -> QgsTextFormat:
    qfont = QFont(font.get("face", "sans-serif"))
    qfont.setBold(bool(font.get("bold")))
    qfont.setItalic(bool(font.get("italic")))
    qfont.setUnderline(bool(font.get("underline")))
    fmt = QgsTextFormat()
    fmt.setFont(qfont)
    size = font.get("size", 12)  # the draft's Font.size is in points
    if isinstance(size, (int, float)):
        fmt.setSize(float(size))
        fmt.setSizeUnit(Qgis.RenderUnit.Points)
    else:
        notes.append("Font.size (expression) not carried over")
    try:
        fmt.setColor(color(font.get("color", "black")))
    except Unsupported as exc:
        notes.append(f"Font.color: {exc}")
    if isinstance(font.get("opacity"), (int, float)):
        fmt.setOpacity(float(font["opacity"]))
    outline = font.get("outline")
    if outline:
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        try:
            size_, unit = length(outline.get("size", 1))
        except Unsupported as exc:
            notes.append(f"Font.outline.size: {exc}")
            size_, unit = 1.0, Qgis.RenderUnit.Pixels
        # QGIS draws a stroke centred on the contour: half of its size shows outside,
        # while the draft has the outline extend outward by `size`
        buffer.setSize(size_ * 2)
        buffer.setSizeUnit(unit)
        try:
            buffer.setColor(color(outline.get("color", "black")))
        except Unsupported as exc:
            notes.append(f"Font.outline.color: {exc}")
        if isinstance(outline.get("opacity"), (int, float)):
            buffer.setOpacity(float(outline["opacity"]))
        buffer.setFillBufferInterior(False)
        fmt.setBuffer(buffer)
        notes.append("~Font.outline.size read in px (the draft leaves it open)")
    return fmt
