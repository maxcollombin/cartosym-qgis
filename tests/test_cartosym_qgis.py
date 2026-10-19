from pathlib import Path

import pytest
from pycartosym.parser import CartoSymParser
from qgis.core import Qgis, QgsPalLayerSettings
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
    style = {"stylingRules": [{"symbolizer": {"fill": {"color": "red", "pattern": {"type": "Dot"}}}}]}
    _, report = build_renderer(style, "polygon", "Landuse")
    assert any("fill.pattern" in d for d in report.dropped)


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





def test_assumption_is_reported_separately():
    style = {"stylingRules": [{"symbolizer": {"stroke": {"dashPattern": [2, 1]}}}]}
    _, report = build_renderer(style, "line")
    assert report.assumed and not report.dropped


def _hatch_layer(hatch, options=None):
    from cartosym_qgis.symbols import Options
    style = {"stylingRules": [{"symbolizer": {"fill": {"color": "red", "hatch": hatch}}}]}
    renderer, _ = build_renderer(style, "polygon", options=options or Options())
    # the layer belongs to the renderer: keep it alive for the caller
    return renderer.rootRule().children()[0].symbol().symbolLayer(0), renderer


def test_hatch_values_and_defaults():
    layer, _keep = _hatch_layer({"width": {"px": 2}, "angle": 0, "distance": {"px": 12}})
    assert (layer.distance(), layer.subSymbol().width(), layer.lineAngle()) == (12.0, 2.0, 0.0)
    default, _keep2 = _hatch_layer({})  # 1 px wide, 45 degrees, 10 px apart
    assert (default.distance(), default.subSymbol().width()) == (10.0, 1.0)
    assert default.lineAngle() == -45.0  # clockwise, QGIS turns counter-clockwise




LABEL_STYLE = {"stylingRules": [{"symbolizer": {"label": {"elements": [{
    "type": "Text", "text": {"property": "name"},
    "font": {"face": "DejaVu Sans", "size": 14, "bold": True, "color": "black",
             "outline": {"size": 3, "opacity": 0.75, "color": "white"}},
}]}}}]}


def _label(options=None):
    from cartosym_qgis.renderer import build
    from cartosym_qgis.symbols import Options
    renderer, labeling, report = build(LABEL_STYLE, "polygon", options=options or Options())
    settings = labeling.rootRule().children()[0].settings()
    return settings, (renderer, labeling)


def test_text_label_with_font_outline():
    settings, _keep = _label()
    assert settings.fieldName == "name" and not settings.isExpression
    fmt = settings.format()
    assert (fmt.size(), fmt.font().bold()) == (14.0, True)
    buffer = fmt.buffer()
    assert buffer.enabled() and buffer.color().name() == "#ffffff"
    assert buffer.opacity() == 0.75



def test_label_in_qml():
    from cartosym_qgis.renderer import build
    renderer, labeling, _ = build(LABEL_STYLE, "polygon")
    qml = to_qml(renderer, "polygon", labeling=labeling)
    assert '<labeling type="rule-based">' in qml
    assert 'bufferDraw="1"' in qml and 'bufferSizeUnits="Pixel"' in qml


def _fill_layer(fill):
    style = {"stylingRules": [{"symbolizer": {"fill": fill}}]}
    renderer, report = build_renderer(style, "polygon")
    return renderer.rootRule().children()[0].symbol().symbolLayer(0), (renderer, report)


@pytest.mark.parametrize(
    ("distance", "expected"),
    [({"px": 6}, (6.0, 6.0)), ([4, 8], (4.0, 8.0)), ({"horizontal": 10, "vertical": 5}, (10.0, 5.0))],
)
def test_dot_pattern_distance_forms(distance, expected):
    layer, _keep = _fill_layer({"color": "red", "dotpattern": {"distance": distance}})
    assert (layer.distanceX(), layer.distanceY()) == expected
    assert layer.subSymbol().color().name() == "#ff0000"


def test_stipple_dot_count_follows_the_ratio():
    layer, (_r, report) = _fill_layer({"color": "red", "stipple": {"ratio": 0.2}})
    assert layer.pointCount() == 2000 and layer.densityArea() == 10000.0
    assert any("dot size" in a for a in report.assumed)


EXAMPLES = Path(__file__).parent.parent / "examples"


def _image_options():
    from cartosym_qgis.symbols import Options
    return Options(base_dir=EXAMPLES)


def _first_symbol(style, geometry, options=None):
    renderer, report = build_renderer(style, geometry, options=options or _image_options())
    return renderer.rootRule().children()[0].symbol(), (renderer, report)


def test_image_marker_hot_spot_moves_the_image_to_the_point():
    style = {"stylingRules": [{"symbolizer": {"marker": {"elements": [
        {"type": "Image", "image": {"path": "pin.png"}, "hotSpot": [{"pc": 50}, {"pc": 100}]}
    ]}}}]}
    symbol, _keep = _first_symbol(style, "point")
    layer = symbol.symbolLayer(0)
    assert layer.size() == 24.0  # the image's own width
    assert (layer.offset().x(), layer.offset().y()) == (0.0, -16.0)  # tip (bottom centre) on the point


def test_marker_on_a_polygon_is_at_its_centroid_and_on_a_line_at_its_vertices():
    marker = {"elements": [{"type": "Dot", "color": "red"}]}
    polygon, _k1 = _first_symbol({"stylingRules": [{"symbolizer": {"fill": {"color": "gray"}, "marker": marker}}]}, "polygon")
    assert [l.layerType() for l in polygon.symbolLayers()] == ["SimpleFill", "CentroidFill"]
    line, _k2 = _first_symbol({"stylingRules": [{"symbolizer": {"stroke": {"color": "gray"}, "marker": marker}}]}, "line")
    assert [l.layerType() for l in line.symbolLayers()] == ["SimpleLine", "MarkerLine"]


def test_missing_image_is_reported():
    style = {"stylingRules": [{"symbolizer": {"marker": {"elements": [{"type": "Image", "image": {"path": "nope.png"}}]}}}]}
    _, report = build_renderer(style, "point", options=_image_options())
    assert any("file not found" in d for d in report.dropped)


def test_pattern_stroke_follows_the_line_at_the_gap():
    style = {"stylingRules": [{"symbolizer": {"stroke": {
        "pattern": {"type": "Image", "image": {"path": "arrow.png"}}, "patternGap": 40, "patternInitialGap": 5}}}]}
    symbol, _keep = _first_symbol(style, "line")
    assert symbol.symbolLayerCount() == 1  # no colour or width: the pattern replaces the line
    layer = symbol.symbolLayer(0)
    assert (layer.interval(), layer.offsetAlongLine()) == (40.0, 5.0)
    assert layer.rotateSymbols()


def test_image_fill_pattern_is_tiled():
    style = {"stylingRules": [{"symbolizer": {"fill": {"pattern": {"type": "Image", "image": {"path": "tree.png"}}}}}]}
    symbol, _keep = _first_symbol(style, "polygon")
    assert symbol.symbolLayer(0).layerType() == "RasterFill"


def _sym(symbolizer, geometry="polygon"):
    renderer, report = build_renderer({"stylingRules": [{"symbolizer": symbolizer}]}, geometry)
    return renderer.rootRule().children()[0].symbol(), (renderer, report)


def test_gradient_fill_follows_the_css_angle():
    key = lambda c, p=None: {"color": c} if p is None else {"color": c, "percent": p}
    symbol, _keep = _sym({"fill": {"gradient": {"type": "linear", "angle": 90, "keys": [key("red"), key("blue", 1)]}}})
    layer = symbol.symbolLayer(0)
    assert layer.layerType() == "GradientFill"
    # 90 degrees = towards the right: from the left edge to the right edge
    assert (layer.referencePoint1().x(), layer.referencePoint2().x()) == (0.0, 1.0)


def test_dash_offset_and_expression_width():
    symbol, _keep = _sym({"stroke": {"dashPattern": [4, 2], "dashOffset": {"px": 3},
                                     "width": {"op": "*", "args": [{"property": "lanes"}, 2]}}}, "line")
    layer = symbol.symbolLayer(0)
    assert layer.dashPatternOffset() == 3.0
    assert 'lanes' in layer.dataDefinedProperties().property(layer.Property.StrokeWidth).expressionString()


def test_dot_is_drawn_with_its_stroke():
    symbol, _keep = _sym({"marker": {"elements": [{"type": "Dot", "stroke": {"width": {"px": 6}, "color": "red"}}]}}, "point")
    layer = symbol.symbolLayer(0)
    assert (layer.size(), layer.color().name()) == (6.0, "#ff0000")


def test_text_marker_is_a_label_that_is_never_left_out():
    from cartosym_qgis.renderer import build
    style = {"stylingRules": [{"symbolizer": {"marker": {"elements": [{"type": "Text", "text": "Oslo"}]}}}]}
    renderer, labeling, _ = build(style, "point")
    settings = labeling.rootRule().children()[0].settings()
    assert settings.displayAll and settings.isExpression
    assert renderer.rootRule().children()  # an invisible symbol, so QGIS labels the features


def test_label_offset_spacing_and_priority_expression():
    from cartosym_qgis.renderer import build
    style = {"stylingRules": [{"symbolizer": {"label": {
        "elements": [{"type": "Text", "text": {"property": "n"}, "position": [{"px": 5}, {"px": 12}]}],
        "placement": {"minSpacing": {"px": 60}, "priority": {"property": "rank"}}}}}]}
    _r, labeling, _ = build(style, "line")
    settings = labeling.rootRule().children()[0].settings()
    assert (settings.xOffset, settings.yOffset, settings.repeatDistance) == (5.0, 12.0, 60.0)
    assert settings.dataDefinedProperties().isActive(QgsPalLayerSettings.Property.Priority)


def test_inline_image_and_raw_csjson(tmp_path):
    from cartosym_qgis.markers import resolve
    svg = "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20width%3D%2210%22%20height%3D%2210%22/%3E"
    assert resolve({"path": svg}, None).suffix == ".svg"
    from cartosym_qgis.renderer import load_style
    (tmp_path / "s.cs.json").write_text('{"stylingRules": [{"symbolizer": {"gamma": 2}}]}')
    assert load_style(tmp_path / "s.cs.json")["stylingRules"][0]["symbolizer"] == {"gamma": 2}  # not validated
