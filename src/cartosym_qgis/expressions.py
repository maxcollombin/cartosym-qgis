"""CQL2-JSON selectors as QGIS filter expressions and scale bounds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .units import Unsupported

_COMPARE = {"=": "=", "<>": "<>", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
_ARITH = {"+": "+", "-": "-", "*": "*", "/": "/", "%": "%", "^": "^"}
_FUNCTIONS = {"upperCase": "upper", "lowerCase": "lower", "casei": "lower"}


def conjuncts(selector: Any) -> list[Any]:
    """Split a selector into its top-level ``and`` terms."""
    if selector is None:
        return []
    if isinstance(selector, dict) and selector.get("op") == "and":
        return [t for arg in selector["args"] for t in conjuncts(arg)]
    return [selector]


def _field(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise Unsupported(f"literal {value!r}")


def to_qgis(node: Any) -> str:
    """Translate a CQL2-JSON node to a QGIS expression string."""
    if isinstance(node, dict):
        if "property" in node:
            return _field(node["property"])
        if "sysId" in node:
            if node["sysId"] == "viz.sd":
                return "@map_scale"
            raise Unsupported(f"system identifier {node['sysId']!r}")
        if "op" in node:
            return _operation(node["op"], node["args"])
        raise Unsupported(f"expression {node!r}")
    if isinstance(node, list):
        return "(" + ", ".join(to_qgis(n) for n in node) + ")"
    return _literal(node)


def _operation(op: str, args: list[Any]) -> str:
    t = [to_qgis(a) for a in args]
    lower = op.lower()
    if op in _COMPARE:
        return f"({t[0]} {_COMPARE[op]} {t[1]})"
    if lower in ("and", "or"):
        return "(" + f" {lower.upper()} ".join(t) + ")"
    if lower == "not":
        return f"(NOT {t[0]})"
    if op in _ARITH:
        return f"({t[0]} {_ARITH[op]} {t[1]})"
    if lower in ("like", "ilike"):
        return f"({t[0]} {lower.upper()} {t[1]})"
    if lower == "in":
        return f"({t[0]} IN {t[1]})"
    if lower == "between":
        return f"({t[0]} BETWEEN {t[1]} AND {t[2]})"
    if lower == "isnull":
        return f"({t[0]} IS NULL)"
    if op in _FUNCTIONS:
        return f"{_FUNCTIONS[op]}({', '.join(t)})"
    raise Unsupported(f"operator {op!r}")


@dataclass
class Conditions:
    """What a selector says, split by how QGIS can use it."""

    filters: list[str] = field(default_factory=list)  # QGIS expressions
    equals: list[tuple[str, Any]] = field(default_factory=list)  # property = literal
    min_scale: float = 0.0  # QGIS: most zoomed-out denominator (0 = no bound)
    max_scale: float = 0.0  # QGIS: most zoomed-in denominator (0 = no bound)
    geometry_dimension: int | None = None
    layer_ids: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # human-readable, unsupported


def analyse(selector: Any) -> Conditions:
    """Split *selector* into layer, geometry, scale and attribute conditions."""
    out = Conditions()
    for term in conjuncts(selector):
        if _sysid_compare(term, "dataLayer.id"):
            out.layer_ids.append(str(term["args"][1]))
        elif _sysid_compare(term, "dataLayer.type"):
            continue
        elif _sysid_compare(term, "dataLayer.featuresGeometryDimensions"):
            out.geometry_dimension = int(term["args"][1])
        elif _scale_bound(term, out):
            continue
        elif (eq := _property_equals(term)) is not None:
            out.equals.append(eq)
        else:
            try:
                out.filters.append(to_qgis(term))
            except Unsupported as exc:
                out.dropped.append(str(exc))
    return out


def _sysid_compare(term: Any, name: str) -> bool:
    return (
        isinstance(term, dict)
        and term.get("op") == "="
        and isinstance(term["args"][0], dict)
        and term["args"][0].get("sysId") == name
    )


def _scale_bound(term: Any, out: Conditions) -> bool:
    """Record ``viz.sd`` bounds as QGIS scale range; True if *term* was one."""
    if not (isinstance(term, dict) and term.get("op") in ("<", "<=", ">", ">=")):
        return False
    left, right = term["args"]
    if not (
        isinstance(left, dict)
        and left.get("sysId") == "viz.sd"
        and isinstance(right, (int, float))
    ):
        return False
    if term["op"] in ("<", "<="):  # only closer than 1:right
        out.min_scale = float(right)
    else:  # at least 1:right
        out.max_scale = float(right)
    return True


def _property_equals(term: Any) -> tuple[str, Any] | None:
    """``(property, literal)`` for ``property = 'text'`` / ``= number``, else None."""
    if not (isinstance(term, dict) and term.get("op") == "="):
        return None
    left, right = term["args"]
    if isinstance(left, dict) and "property" in left:
        prop, lit = left["property"], right
    elif isinstance(right, dict) and "property" in right:
        prop, lit = right["property"], left
    else:
        return None
    if isinstance(lit, bool) or not isinstance(lit, (str, int, float)):
        return None
    return prop, lit


def literal(value: Any) -> str:
    """A literal as QGIS expression text."""
    return _literal(value)


def field_ref(name: str) -> str:
    """A property as QGIS expression text."""
    return _field(name)
