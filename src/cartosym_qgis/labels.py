"""CartoSym ``Text`` label elements as QGIS label settings."""

from __future__ import annotations

from typing import Any

from qgis.core import (
    Qgis,
    QgsPalLayerSettings,
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
    label: dict[str, Any], dimension: int, notes: list[str], options: Options
) -> list[QgsPalLayerSettings]:
    """One QGIS label setting per ``Text`` element of *label*."""
    out = []
    for element in label.get("elements", []):
        kind = element.get("type")
        if kind != "Text":
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
        position = element.get("position")
        if position and any(position.get(k) for k in ("x", "y")):
            notes.append("Text.position (offset) not carried over")
        if element.get("alignment"):
            notes.append("Text.alignment not carried over")
        priority = (label.get("placement") or {}).get("priority")
        if isinstance(priority, (int, float)):
            settings.priority = max(0, min(10, int(priority)))
        out.append(settings)
    return out


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
            size_, unit = length(outline.get("size", 1), options.outline_unit)
        except Unsupported as exc:
            notes.append(f"Font.outline.size: {exc}")
            size_, unit = 1.0, Qgis.RenderUnit.Pixels
        # QGIS draws a stroke centred on the contour: half of its size shows outside
        buffer.setSize(size_ * 2 if options.outline_extent == "outward" else size_)
        buffer.setSizeUnit(unit)
        try:
            buffer.setColor(color(outline.get("color", "black")))
        except Unsupported as exc:
            notes.append(f"Font.outline.color: {exc}")
        if isinstance(outline.get("opacity"), (int, float)):
            buffer.setOpacity(float(outline["opacity"]))
        buffer.setFillBufferInterior(False)
        fmt.setBuffer(buffer)
        notes.append(f"~Font.outline.size read in {options.outline_unit} (the draft leaves it open)")
    return fmt
