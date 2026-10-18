"""CartoSym lengths, angles and colours as QGIS values."""

from __future__ import annotations

from typing import Any

from qgis.core import Qgis
from qgis.PyQt.QtGui import QColor

# unit -> (QGIS render unit, factor applied to the value)
_UNITS: dict[str, tuple[Any, float]] = {
    "px": (Qgis.RenderUnit.Pixels, 1.0),
    "mm": (Qgis.RenderUnit.Millimeters, 1.0),
    "cm": (Qgis.RenderUnit.Millimeters, 10.0),
    "pt": (Qgis.RenderUnit.Points, 1.0),
    "in": (Qgis.RenderUnit.Inches, 1.0),
    "m": (Qgis.RenderUnit.MetersInMapUnits, 1.0),
    "ft": (Qgis.RenderUnit.MetersInMapUnits, 0.3048),
}


class Unsupported(Exception):
    """A CartoSym construct with no QGIS counterpart (yet)."""


def length(value: Any, default_unit: str = "px") -> tuple[float, Any]:
    """Return ``(number, QGIS render unit)`` for a CartoSym length.

    Accepts a bare number (``default_unit``), ``{"px": 2}`` and the
    ``{"value": 2, "unit": "px"}`` form of ``Style.to_dict()``.
    """
    unit = default_unit
    if isinstance(value, dict):
        if "value" in value and "unit" in value:
            unit, value = value["unit"], value["value"]
        elif len(value) == 1:
            ((unit, value),) = value.items()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Unsupported(f"length {value!r} (expression or unknown form)")
    if unit not in _UNITS:
        raise Unsupported(f"unit {unit!r}")
    qgis_unit, factor = _UNITS[unit]
    return float(value) * factor, qgis_unit


def color(value: Any, opacity: float | None = None) -> QColor:
    """Return a QColor for a CartoSym colour, with *opacity* (0..1) as alpha."""
    if isinstance(value, str) and value.startswith("#"):
        digits = value[1:]
        if len(digits) == 8:  # #RRGGBBAA, Qt reads #AARRGGBB
            c = QColor(f"#{digits[6:]}{digits[:6]}")
        else:
            c = QColor(value)
    elif isinstance(value, str):
        c = QColor(value)
    elif isinstance(value, (list, tuple)) and len(value) >= 3:
        c = QColor(*(int(round(float(v))) for v in value[:3]))
    elif isinstance(value, dict) and {"r", "g", "b"} <= value.keys():
        c = QColor(int(value["r"]), int(value["g"]), int(value["b"]))
    else:
        raise Unsupported(f"colour {value!r}")
    if not c.isValid():
        raise Unsupported(f"colour {value!r}")
    if opacity is not None:
        c.setAlphaF(c.alphaF() * float(opacity))
    return c
