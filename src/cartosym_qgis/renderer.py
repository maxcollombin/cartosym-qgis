"""Build a QGIS rule-based renderer from a CartoSym style."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

from qgis.core import QgsRuleBasedLabeling, QgsRuleBasedRenderer

from . import expressions
from .labels import label_settings
from .symbols import LINE, POINT, POLYGON, Options, build_symbol
from .units import Unsupported

_DIMENSION = {"point": POINT, "line": LINE, "polygon": POLYGON}


@dataclass
class Report:
    """What could not be carried over, so nothing is lost silently."""

    dropped: list[str] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)  # a reading chosen where the draft is open

    def add(self, rule: str, what: str) -> None:
        self.dropped.append(f"{rule}: {what}")

    def note(self, rule: str, note: str) -> None:
        """Record a symbol-builder note: ``~`` marks an assumption, else a drop."""
        if note.startswith("~"):
            self.assumed.append(f"{rule}: {note[1:]}")
        else:
            self.add(rule, f"{note} not carried over")


def load_style(path: str | Path) -> dict[str, Any]:
    """Read a ``.cscss`` or CS-JSON file into the ``Style.to_dict()`` shape."""
    from pycartosym.models import Style
    from pycartosym.parser import CartoSymParser

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".cscss":
        style = CartoSymParser().parse_string_to_pydantic(text)
    else:
        style = Style.from_dict(json.loads(text))
    return style.to_dict()


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if key == "alter":
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class _Node:
    """One CartoSym rule: its own symbolizer and every condition of its chain."""

    name: str
    sym: dict[str, Any]
    equals: set[tuple[str, Any]]
    filters: set[str]
    min_scale: float  # visible when scale denominator < min_scale (inf = unbounded)
    max_scale: float  # ... and >= max_scale
    drops: bool = False


_MAX_CELLS = 4096


def build_renderer(
    style: dict[str, Any],
    geometry: str,
    layer_id: str | None = None,
    options: Options = Options(),
) -> tuple[QgsRuleBasedRenderer, Report]:
    """Like :func:`build`, without the labeling."""
    renderer, _labeling, report = build(style, geometry, layer_id, options)
    return renderer, report


def build(
    style: dict[str, Any],
    geometry: str,
    layer_id: str | None = None,
    options: Options = Options(),
) -> tuple[QgsRuleBasedRenderer, QgsRuleBasedLabeling, Report]:
    """Return ``(renderer, labeling, report)`` for the rules that apply to *geometry*.

    CartoSym merges every matching rule in document order, so overlapping
    sibling rules combine. QGIS rules do not, so the conditions are split
    into cells (one state per property tested with ``=``, one per scale
    interval, one per other condition) and each cell gets one rule carrying
    the symbolizer merged from the rules active in it.

    Raises:
        Unsupported: If the style needs more than 4096 cells.
    """
    dimension = _DIMENSION[geometry]
    report = Report()
    nodes: list[_Node] = []
    for rule in style.get("stylingRules", []):
        _walk(rule, [], dimension, layer_id, report, nodes)

    groups: dict[str, list[Any]] = {}
    exprs: list[str] = []
    bounds: set[float] = set()
    for n in nodes:
        for prop, lit in n.equals:
            if lit not in groups.setdefault(prop, []):
                groups[prop].append(lit)
        exprs.extend(f for f in sorted(n.filters) if f not in exprs)
        bounds.update(b for b in (n.min_scale, n.max_scale) if 0 < b < float("inf"))
    cuts = sorted(bounds)  # scale intervals: [0, c0), [c0, c1), ..., [ck, inf)
    edges = [0.0, *cuts, float("inf")]
    intervals = list(zip(edges[:-1], edges[1:]))

    n_cells = len(intervals) * 2 ** len(exprs)
    for lits in groups.values():
        n_cells *= len(lits) + 1
    if n_cells > _MAX_CELLS:
        raise Unsupported(f"style too intricate for QGIS rules ({n_cells} condition cells)")

    root = QgsRuleBasedRenderer.Rule(None)
    label_root = QgsRuleBasedLabeling.Rule(None)
    props = list(groups)
    for states in product(*(range(len(groups[p]) + 1) for p in props)):
        chosen = {p: (groups[p][i] if i < len(groups[p]) else None) for p, i in zip(props, states)}
        for flags in product((True, False), repeat=len(exprs)):
            truth = dict(zip(exprs, flags))
            for low, high in intervals:
                active = [
                    n for n in nodes
                    if all(chosen.get(p, None) == lit for p, lit in n.equals)
                    and all(truth[f] for f in n.filters)
                    and n.max_scale <= low and high <= n.min_scale
                ]
                if not active:
                    continue
                merged: dict[str, Any] = {}
                for n in active:
                    merged = _merge(merged, n.sym)
                notes: list[str] = []
                if merged.get("visibility", True) is False:
                    continue
                symbol = build_symbol(merged, dimension, notes, options)
                terms = _cell_filter(chosen, groups, truth)
                scale = (int(low), 0 if high == float("inf") else int(high))
                for settings in label_settings(merged.get("label") or {}, dimension, notes, options):
                    label_root.appendChild(
                        QgsRuleBasedLabeling.Rule(
                            settings, scale[1], scale[0], " AND ".join(terms)
                        )
                    )
                for note in notes:
                    report.note(active[-1].name, note)
                if symbol is None:
                    continue
                root.appendChild(
                    QgsRuleBasedRenderer.Rule(
                        symbol,
                        maximumScale=int(low),
                        minimumScale=0 if high == float("inf") else int(high),
                        filterExp=" AND ".join(terms),
                        label=" + ".join(dict.fromkeys(n.name for n in active if n.name != "rule")) or "rule",
                    )
                )
    report.dropped = list(dict.fromkeys(report.dropped))
    report.assumed = list(dict.fromkeys(report.assumed))
    renderer = QgsRuleBasedRenderer(root)
    # Symbol levels draw layer 0 of every feature, then layer 1, ...: all casings first.
    renderer.setUsingSymbolLevels(options.casing_pass == "all-first")
    return renderer, QgsRuleBasedLabeling(label_root), report


def _cell_filter(chosen: dict[str, Any], groups: dict[str, list[Any]], truth: dict[str, bool]) -> list[str]:
    terms = []
    for prop, lit in chosen.items():
        ref = expressions.field_ref(prop)
        if lit is not None:
            terms.append(f"{ref} = {expressions.literal(lit)}")
        else:
            rest = ", ".join(expressions.literal(v) for v in groups[prop])
            terms.append(f"({ref} IS NULL OR {ref} NOT IN ({rest}))")
    for expr, value in truth.items():
        terms.append(expr if value else f"NOT coalesce({expr}, FALSE)")
    return terms


def _walk(
    rule: dict[str, Any],
    inherited: list[expressions.Conditions],
    dimension: int,
    layer_id: str | None,
    report: Report,
    nodes: list[_Node],
) -> None:
    name = rule.get("name") or "rule"
    cond = expressions.analyse(rule.get("selector"))
    for dropped in cond.dropped:
        report.add(name, f"selector dropped ({dropped})")
    if layer_id and cond.layer_ids and layer_id not in cond.layer_ids:
        return
    if cond.geometry_dimension is not None and cond.geometry_dimension != dimension:
        return
    chain = [*inherited, cond]
    nested = rule.get("nestedRules", [])
    for _ in (c for c in nested if c.get("selector") is None):
        report.add(name, "nested rule without selector (else) ignored")
    nodes.append(
        _Node(
            name,
            rule.get("symbolizer") or {},
            {e for c in chain for e in c.equals},
            {f for c in chain for f in c.filters},
            min((c.min_scale for c in chain if c.min_scale), default=float("inf")),
            max(c.max_scale for c in chain),
        )
    )
    for child in nested:
        if child.get("selector") is not None:
            _walk(child, chain, dimension, layer_id, report, nodes)


def to_qml(
    renderer: QgsRuleBasedRenderer,
    geometry: str,
    crs: str = "EPSG:4326",
    labeling: QgsRuleBasedLabeling | None = None,
) -> str:
    """Serialise *renderer* as QML, through a throw-away memory layer."""
    from qgis.core import QgsReadWriteContext, QgsVectorLayer
    from qgis.PyQt.QtXml import QDomDocument

    wkb = {"point": "Point", "line": "LineString", "polygon": "Polygon"}[geometry]
    layer = QgsVectorLayer(f"{wkb}?crs={crs}", "style", "memory")
    layer.setRenderer(renderer.clone())
    if labeling is not None:
        layer.setLabeling(labeling.clone())
        layer.setLabelsEnabled(True)
    doc = QDomDocument()
    layer.exportNamedStyle(doc, QgsReadWriteContext())
    return doc.toString(2)
