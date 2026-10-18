from pathlib import Path

import pytest
from pycartosym.parser import CartoSymParser
from qgis.core import Qgis
from qgis.PyQt.QtGui import QColor, QImage

from cartosym_qgis import build_renderer, to_qml
from cartosym_qgis.expressions import analyse, to_qgis
from cartosym_qgis.render import render_png
from cartosym_qgis.units import Unsupported, color, length

DATA = Path(__file__).parent.parent / "data" / "landuse.geojson"

POLYGON_STYLE = """
Landuse
{
   fill: {color: gray; opacity: 0.5};
   stroke: {color: gray; width: 2.0 px};
   [viz.sd < 200000]
   {
      [FunctionCode = 'park'] { fill.color: darkGreen; }
      [viz.sd < 10000] { stroke.width: 4.0 px; }
   }
}
"""


def _style(text: str) -> dict:
    return CartoSymParser().parse_string_to_pydantic(text).to_dict()


def test_length_forms():
    assert length(3) == (3.0, Qgis.RenderUnit.Pixels)
    assert length({"mm": 2}) == (2.0, Qgis.RenderUnit.Millimeters)
    assert length({"value": 1, "unit": "cm"}) == (10.0, Qgis.RenderUnit.Millimeters)
    with pytest.raises(Unsupported):
        length({"op": "*", "args": [1, 2]})


def test_colour_forms():
    assert color("darkGreen").name() == "#006400"
    assert color([1, 2, 3]).name() == "#010203"
    assert color("#11223380").alpha() == 0x80
    assert color("gray", 0.5).alphaF() == pytest.approx(0.5, abs=0.01)


def test_selector_split():
    cond = analyse(
        {"op": "and", "args": [
            {"op": "=", "args": [{"sysId": "dataLayer.id"}, "Landuse"]},
            {"op": "<", "args": [{"sysId": "viz.sd"}, 10000]},
            {"op": "=", "args": [{"property": "kind"}, "park"]},
            {"op": ">", "args": [{"property": "area"}, 5]},
        ]}
    )
    assert cond.layer_ids == ["Landuse"] and cond.min_scale == 10000
    assert cond.equals == [("kind", "park")] and cond.filters == ['("area" > 5)']
    assert to_qgis({"op": "like", "args": [{"property": "n"}, "O%"]}) == "(\"n\" LIKE 'O%')"


def test_overlapping_rules_are_merged_in_each_cell():
    renderer, report = build_renderer(_style(POLYGON_STYLE), "polygon", "Landuse")
    rules = {(r.filterExpression(), r.minimumScale()): r for r in renderer.rootRule().children()}
    close_park = next(r for (f, m), r in rules.items() if "'park'" in f and m == 10000)
    layer = close_park.symbol().symbolLayer(0)
    assert layer.fillColor().name() == "#006400"  # from the park rule
    assert layer.strokeWidth() == 4.0  # from the scale rule: both applied
    far_other = next(r for (f, m), r in rules.items() if "NOT IN" in f and m == 200000)
    assert far_other.symbol().symbolLayer(0).strokeWidth() == 2.0
    assert not report.dropped


def test_unsupported_is_reported_not_silent():
    style = {"stylingRules": [{"symbolizer": {"fill": {"color": "red", "stipple": {"size": 2}}}}]}
    _, report = build_renderer(style, "polygon", "Landuse")
    assert any("stipple" in d for d in report.dropped)


def test_other_layer_and_geometry_are_skipped():
    style = _style("Roads[dataLayer.featuresGeometryDimensions = 1] { stroke: {color: red}; }")
    assert build_renderer(style, "polygon")[0].rootRule().children() == []
    assert len(build_renderer(style, "line")[0].rootRule().children()) == 1


def test_qml_has_rules_and_scale_range():
    renderer, _ = build_renderer(_style(POLYGON_STYLE), "polygon", "Landuse")
    qml = to_qml(renderer, "polygon")
    assert 'renderer-v2' in qml and 'type="RuleRenderer"' in qml
    assert 'scalemaxdenom="200000"' in qml


def test_render_colours(tmp_path):
    out = tmp_path / "r.png"
    render_png(_style(POLYGON_STYLE), DATA, out, layer_id="Landuse", size=200, scale=100000)
    image = QImage(str(out))
    assert image.width() == 200
    # at 1:100000 the four polygons sit around the centre: one green (park), others grey
    pixels = [QColor(image.pixel(x, y)) for x in range(90, 110) for y in range(90, 110)]
    assert any(c.green() > c.red() + 20 for c in pixels)
    assert any(abs(c.green() - c.red()) < 5 and c.red() < 250 for c in pixels)


ROADS = {"stylingRules": [{"symbolizer": {"stroke": {
    "color": "white", "width": {"px": 4},
    "casing": {"color": "black", "width": {"px": 2}},
    "centerLine": {"color": "red", "width": {"px": 1}},
}}}]}


def _layers(options=None):
    from cartosym_qgis.symbols import Options
    renderer, report = build_renderer(ROADS, "line", options=options or Options())
    symbol = renderer.rootRule().children()[0].symbol()
    return renderer, [(l.width(), l.color().name()) for l in symbol.symbolLayers()]


def test_casing_below_and_center_above():
    _, layers = _layers()
    assert layers == [(2.0, "#000000"), (4.0, "#ffffff"), (1.0, "#ff0000")]


def test_casing_width_extra_extends_beyond_each_side():
    from cartosym_qgis.symbols import Options
    _, layers = _layers(Options(casing_width="extra"))
    assert layers[0] == (8.0, "#000000")  # 4 + 2 * 2


def test_casing_pass_selects_symbol_levels():
    from cartosym_qgis.symbols import Options
    assert _layers()[0].usingSymbolLevels()
    assert not _layers(Options(casing_pass="with-feature"))[0].usingSymbolLevels()


def test_rendering_passes_only_for_all_first():
    from cartosym_qgis.symbols import Options
    for options, passes in ((Options(), [0, 1, 2]), (Options(casing_pass="with-feature"), [0, 0, 0])):
        renderer, _ = build_renderer(ROADS, "line", options=options)
        symbol = renderer.rootRule().children()[0].symbol()
        assert [l.renderingPass() for l in symbol.symbolLayers()] == passes


def test_assumption_is_reported_separately():
    style = {"stylingRules": [{"symbolizer": {"stroke": {"dashPattern": [2, 1]}}}]}
    _, report = build_renderer(style, "line")
    assert report.assumed and not report.dropped


def _hatch_layer(hatch, options=None):
    from cartosym_qgis.symbols import Options
    style = {"stylingRules": [{"symbolizer": {"fill": {"color": "red", "hatch": hatch}}}]}
    renderer, _ = build_renderer(style, "polygon", options=options or Options())
    return renderer.rootRule().children()[0].symbol().symbolLayer(0)


def test_hatch_values_and_defaults():
    layer = _hatch_layer({"width": {"px": 2}, "angle": 0, "distance": {"px": 12}})
    assert (layer.distance(), layer.subSymbol().width(), layer.lineAngle()) == (12.0, 2.0, 0.0)
    default = _hatch_layer({})  # 1 px wide, 45 degrees, 10 px apart
    assert (default.distance(), default.subSymbol().width()) == (10.0, 1.0)
    assert default.lineAngle() == -45.0  # clockwise, QGIS turns counter-clockwise


def test_hatch_angle_direction_option():
    from cartosym_qgis.symbols import Options
    layer = _hatch_layer({"angle": 30}, Options(hatch_angle="counter-clockwise"))
    assert layer.lineAngle() == 30.0


def test_dash_units_option():
    from cartosym_qgis.symbols import Options
    style = {"stylingRules": [{"symbolizer": {"stroke": {"width": {"px": 3}, "dashPattern": [2, 1]}}}]}
    for units, vector in (("px", [2.0, 1.0]), ("stroke-width", [6.0, 3.0])):
        renderer, _ = build_renderer(style, "line", options=Options(dash_units=units))
        layer = renderer.rootRule().children()[0].symbol().symbolLayer(0)
        assert list(layer.customDashVector()) == vector
