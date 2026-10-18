"""Headless QGIS rendering of a styled vector layer."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_GEOMETRY = {0: "point", 1: "line", 2: "polygon"}
_DPI = 96.0


@contextmanager
def qgis_app() -> Iterator[None]:
    """Start QGIS without a display, and shut it down afterwards."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    app = QgsApplication([], False)
    app.initQgis()
    try:
        yield
    finally:
        app.exitQgis()


def render_png(
    style: dict,
    data: str | Path,
    out: str | Path,
    layer_id: str | None = None,
    size: int = 600,
    scale: float | None = None,
    options=None,
):
    """Render *data* with *style* to a PNG; return the build report."""
    from qgis.core import QgsMapRendererParallelJob, QgsMapSettings, QgsVectorLayer
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor

    from .renderer import build_renderer
    from .symbols import Options

    layer = QgsVectorLayer(str(data), layer_id or Path(data).stem, "ogr")
    if not layer.isValid():
        raise ValueError(f"cannot open {data}")
    geometry = _GEOMETRY[layer.geometryType().value]
    renderer, report = build_renderer(style, geometry, layer_id or layer.name(), options or Options())
    layer.setRenderer(renderer)

    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(layer.crs())
    settings.setOutputSize(QSize(size, size))
    settings.setOutputDpi(_DPI)
    settings.setBackgroundColor(QColor("white"))
    extent = layer.extent().buffered(max(layer.extent().width(), layer.extent().height()) * 0.05)
    if scale:  # centre on the data, then size the extent for the requested 1:scale
        width = size / _DPI * 0.0254 * scale
        c = extent.center()
        extent.set(c.x() - width / 2, c.y() - width / 2, c.x() + width / 2, c.y() + width / 2)
    settings.setExtent(extent)
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    job.renderedImage().save(str(out))
    return report
