"""Render a draft-check render kit: ``style.cs.json``, the data and ``view.json``."""

from __future__ import annotations

import json
from pathlib import Path

from .renderer import Report, build, load_style
from .symbols import Options

_GEOMETRY = {0: "point", 1: "line", 2: "polygon"}


def render_kit(kit_dir: str | Path, style_file: str | Path, out: str | Path, options: Options) -> Report:
    """Draw every layer of the kit with the style, at the kit's extent, size and scale."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsMapRendererParallelJob, QgsMapSettings, QgsRectangle, QgsVectorLayer
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor

    from .coverage import build_coverage

    kit = Path(kit_dir)
    view = json.loads((kit / "view.json").read_text(encoding="utf-8"))
    style = load_style(style_file)
    scale = float(view["scaleDenominator"])
    report = Report()
    layers = []  # bottom first
    keep = []  # temporary files and renderers must outlive the render
    for entry in view["layers"]:
        layer_id = entry["id"]
        if entry["type"] == "coverage":
            bands = {p.name[len(layer_id) + 1 : -4]: p for p in sorted(kit.glob(f"{layer_id}.*.asc"))}
            coverage = build_coverage(style, layer_id, bands, scale, report)
            keep.append(coverage)
            layers.extend(coverage.layers)
            continue
        layer = QgsVectorLayer(str(kit / f"{layer_id}.geojson"), layer_id, "ogr")
        if not layer.isValid():
            raise ValueError(f"cannot open the data of layer {layer_id!r}")
        renderer, labeling, vreport = build(style, _GEOMETRY[layer.geometryType().value], layer_id, options)
        report.dropped += vreport.dropped
        report.assumed += vreport.assumed
        layer.setRenderer(renderer)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
        layers.append(layer)

    settings = QgsMapSettings()
    settings.setLayers(list(reversed(layers)))  # QGIS wants the top layer first
    settings.setDestinationCrs(QgsCoordinateReferenceSystem(view["crs"]))
    settings.setExtent(QgsRectangle(*view["bbox"]))
    settings.setOutputSize(QSize(view["width"], view["height"]))
    settings.setOutputDpi(25.4 / float(view.get("pixelSize_mm", 0.28)))
    settings.setBackgroundColor(QColor("white"))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(str(out))
    report.dropped = list(dict.fromkeys(report.dropped))
    report.assumed = list(dict.fromkeys(report.assumed))
    return report
