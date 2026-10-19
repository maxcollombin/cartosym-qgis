"""CartoSym graphics (``Dot``, ``Image``) as QGIS marker symbol layers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qgis.core import (
    Qgis,
    QgsMarkerSymbol,
    QgsRasterMarkerSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleMarkerSymbolLayerBase,
    QgsSvgMarkerSymbolLayer,
)
from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QImage

from .units import Unsupported, color, length

_DEFAULT_IMAGE_SIZE = 16.0  # px, when the image cannot be measured


def resolve(image: dict[str, Any], base_dir: Path | None) -> Path | None:
    """The file of an image resource (``path``, else a local ``uri``), if it exists."""
    for key in ("path", "uri"):
        value = image.get(key)
        if not isinstance(value, str) or "://" in value:
            continue
        path = Path(value)
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        if path.is_file():
            return path
    return None


def native_size(path: Path) -> tuple[float, float]:
    """``(width, height)`` of an image in px."""
    if path.suffix.lower() == ".svg":
        from qgis.PyQt.QtSvg import QSvgRenderer

        size = QSvgRenderer(str(path)).defaultSize()
    else:
        size = QImage(str(path)).size()
    if size.isEmpty():
        return _DEFAULT_IMAGE_SIZE, _DEFAULT_IMAGE_SIZE
    return float(size.width()), float(size.height())


def _hot_spot(
    element: dict[str, Any], size: tuple[float, float], notes: list[str]
) -> tuple[float, float]:
    """Offset ``(x, y)`` in px that puts the image's hot spot on the point.

    The hot spot defaults to the image centre; ``pc`` is read as a percentage
    of the image size, as in the draft's examples (``hotSpot: 50 pc 50 pc``).
    """
    spot = element.get("hotSpot")
    if spot is None:
        return 0.0, 0.0
    if isinstance(spot, dict):
        spot = [spot.get("x"), spot.get("y")]
    out = []
    for value, extent in zip(spot[:2], size):
        if isinstance(value, dict) and len(value) == 1:
            ((unit, number),) = value.items()
        elif isinstance(value, dict) and "unit" in value:
            unit, number = value["unit"], value["value"]
        else:
            unit, number = "px", value
        if not isinstance(number, (int, float)):
            notes.append("Image.hotSpot (expression) not carried over")
            return 0.0, 0.0
        out.append(float(number) / 100 * extent if unit == "pc" else float(number))
    if any(isinstance(v, dict) and "pc" in v for v in spot[:2]):
        notes.append("~Image.hotSpot 'pc' read as a percentage of the image")
    # the offset moves the image the other way: hot spot at (hx, hy) from the top left
    return size[0] / 2 - out[0], size[1] / 2 - out[1]


def graphic_layer(element: dict[str, Any], notes: list[str], base_dir: Path | None):
    """A marker symbol layer for a ``Dot`` or ``Image`` element, or None."""
    kind = element.get("type")
    if kind == "Dot":
        layer = _dot(element, notes)
    elif kind == "Image":
        layer = _image(element, notes, base_dir)
    else:
        notes.append(f"graphic {kind!r}")
        return None
    if layer is not None:
        _position(layer, element, notes)
    return layer


def _dot(element: dict[str, Any], notes: list[str]) -> QgsSimpleMarkerSymbolLayer:
    size, unit = 10.0, Qgis.RenderUnit.Pixels  # the draft's default Dot: white, 10 px
    try:
        if "size" in element:
            size, unit = length(element["size"])
    except Unsupported as exc:
        notes.append(f"Dot.size: {exc}")
    layer = QgsSimpleMarkerSymbolLayer(QgsSimpleMarkerSymbolLayerBase.Shape.Circle, size)
    layer.setSizeUnit(unit)
    try:
        layer.setColor(color(element.get("color", "white"), element.get("opacity")))
    except Unsupported as exc:
        notes.append(f"Dot.color: {exc}")
    layer.setStrokeStyle(Qt.NoPen)
    return layer


def _image(element: dict[str, Any], notes: list[str], base_dir: Path | None):
    image = element.get("image") or {}
    path = resolve(image, base_dir)
    if path is None:
        notes.append(f"Image {image.get('path') or image.get('uri')!r}: file not found")
        return None
    size = native_size(path)
    svg = path.suffix.lower() == ".svg"
    layer = (QgsSvgMarkerSymbolLayer if svg else QgsRasterMarkerSymbolLayer)(str(path), size[0])
    layer.setSizeUnit(Qgis.RenderUnit.Pixels)
    if not svg and isinstance(element.get("opacity"), (int, float)):
        layer.setOpacity(float(element["opacity"]))
    dx, dy = _hot_spot(element, size, notes)
    layer.setOffset(QPointF(dx, dy))
    layer.setOffsetUnit(Qgis.RenderUnit.Pixels)
    for key in ("tint", "blackTint", "alphaThreshold"):
        if key in element:
            notes.append(f"Image.{key} not carried over")
    return layer


def _position(layer, element: dict[str, Any], notes: list[str]) -> None:
    """``position`` is a translation from the point (``y`` read as downwards)."""
    position = element.get("position")
    if not position:
        return
    if isinstance(position, list):
        position = {"x": position[0], "y": position[1]}
    try:
        x, unit = length(position.get("x", 0))
        y, _ = length(position.get("y", 0))
    except Unsupported as exc:
        notes.append(f"position: {exc}")
        return
    old = layer.offset()
    layer.setOffset(QPointF(old.x() + x, old.y() + y))
    layer.setOffsetUnit(unit)
    notes.append("~Graphic.position y read as downwards, like screen coordinates")


def marker_symbol(
    elements: list[dict[str, Any]], notes: list[str], base_dir: Path | None
) -> QgsMarkerSymbol | None:
    """A marker symbol drawing every supported element, or None."""
    layers = [
        layer
        for element in elements
        if (layer := graphic_layer(element, notes, base_dir)) is not None
    ]
    return QgsMarkerSymbol(layers) if layers else None
