import json
from pathlib import Path

import numpy as np
import pytest
from qgis.PyQt.QtGui import QColor, QImage

from cartosym_qgis.coverage import _ramp_items, evaluate
from cartosym_qgis.kit import render_kit
from cartosym_qgis.symbols import Options
from cartosym_qgis.units import Unsupported

PRJ = ('PROJCS["ETRS89 / UTM zone 33N",GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",'
       'SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
       'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",15],'
       'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
       'UNIT["metre",1],AUTHORITY["EPSG","25833"]]')


def _band(path: Path, rows: list[list[float]]) -> None:
    head = f"ncols {len(rows[0])}\nnrows {len(rows)}\nxllcorner 597000\nyllcorner 6643000\ncellsize 10\nNODATA_value -9999\n"
    path.write_text(head + "\n".join(" ".join(str(v) for v in r) for r in rows) + "\n")
    path.with_suffix(".prj").write_text(PRJ)


def _kit(tmp_path: Path, style: dict) -> Path:
    kit = tmp_path / "kit"
    kit.mkdir()
    # 2 x 2 cells: NDVI (B08 - B04) / (B08 + B04) is 1, 0, 1, 0; SCL marks the cell at the top right as cloud
    _band(kit / "S.B04.asc", [[0, 10], [0, 10]])
    _band(kit / "S.B08.asc", [[10, 10], [10, 10]])
    _band(kit / "S.SCL.asc", [[0, 9], [0, 0]])
    (kit / "view.json").write_text(json.dumps({
        "crs": "EPSG:25833", "bbox": [597000, 6643000, 597020, 6643020], "width": 40, "height": 40,
        "scaleDenominator": 1000.0, "pixelSize_mm": 0.28, "layers": [{"id": "S", "type": "coverage"}],
    }))
    (kit / "style.cs.json").write_text(json.dumps(style))
    return kit


NDVI = {"stylingRules": [{
    "selector": {"op": "=", "args": [{"sysId": "dataLayer.id"}, "S"]},
    "symbolizer": {
        "singleChannel": {"op": "/", "args": [{"op": "-", "args": [{"property": "B08"}, {"property": "B04"}]},
                                              {"op": "+", "args": [{"property": "B08"}, {"property": "B04"}]}]},
        "colorMap": [[0.0, "black"], [1.0, "white"]],
        "alphaChannel": 1.0,
    },
    "nestedRules": [{"selector": {"op": "=", "args": [{"property": "SCL"}, 9]}, "symbolizer": {"alphaChannel": 0.0}}],
}]}


def test_division_is_real_valued():
    result = evaluate({"op": "/", "args": [7, 2]}, {})
    assert result == 3.5
    bands = {"a": np.array([1.0, 2.0]), "b": np.array([0.0, 4.0])}
    out = evaluate({"op": "/", "args": [{"property": "a"}, {"property": "b"}]}, bands)
    assert np.isnan(out[0]) and out[1] == 0.5


def test_unknown_band_is_refused():
    with pytest.raises(Unsupported):
        evaluate({"property": "nope"}, {})


def test_colour_and_opacity_maps_are_merged_on_their_breakpoints():
    items = _ramp_items([[0, "black"], [1, "white"]], [[0, 1.0], [0.5, 0.0]], None)
    assert [i.value for i in items] == [0.0, 0.5, 1.0]
    assert [round(i.color.alphaF(), 2) for i in items] == [1.0, 0.0, 0.0]  # opacity is clamped beyond its ends
    assert items[1].color.red() in (127, 128)  # halfway between black and white


def test_ndvi_with_a_cloud_mask(tmp_path):
    kit = _kit(tmp_path, NDVI)
    out = tmp_path / "out.png"
    report = render_kit(kit, kit / "style.cs.json", out, Options())
    image = QImage(str(out))
    pixel = lambda x, y: QColor(image.pixel(x, y))
    # image rows run north to south: top row = B04 [0, 10], bottom row the same
    assert pixel(10, 30).red() > 240  # NDVI 1 -> white
    assert pixel(10, 10).red() > 240
    assert pixel(30, 30).red() < 15   # NDVI 0 -> black
    assert pixel(30, 10).red() == 255 and pixel(30, 10).green() == 255  # cloud: transparent, so the background
    assert not report.dropped
