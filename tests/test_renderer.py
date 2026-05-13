"""End-to-end smoke tests: IR JSON → layout → SVG."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from blueprint_svg import Diagram, layout_diagram, render_svg

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "examples").glob("*.json"))

needs_graphviz = pytest.mark.skipif(
    shutil.which("dot") is None, reason="Graphviz `dot` binary not installed."
)


@pytest.mark.parametrize("example_path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
@needs_graphviz
def test_example_renders_to_valid_svg(example_path: Path) -> None:
    data = json.loads(example_path.read_text())
    diagram = Diagram.model_validate(data)
    layout = layout_diagram(diagram)
    svg = render_svg(diagram, layout)

    # 1. Parses as XML.
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")

    # 2. Every IR node id appears as a <g id="..."> in the output.
    ids = {el.get("id") for el in root.iter() if el.get("id")}
    for n in diagram.nodes:
        assert n.id in ids, f"Node id {n.id!r} missing from rendered SVG"

    # 3. Theme CSS variables are present in the style block.
    style_text = "".join(el.text or "" for el in root.iter() if el.tag.endswith("style"))
    assert "--bp-primary" in style_text


@needs_graphviz
def test_sequence_diagram_uses_custom_layout() -> None:
    """Sequence diagrams must lay out columns even though Graphviz wouldn't."""
    data = json.loads((Path(__file__).resolve().parents[1] / "examples" / "sequence_oauth.json").read_text())
    diagram = Diagram.model_validate(data)
    layout = layout_diagram(diagram)
    # All actor nodes should share roughly the same y coordinate (header row).
    actor_ys = [layout.nodes[n.id].y for n in diagram.nodes if n.shape == "actor"]
    assert max(actor_ys) - min(actor_ys) < 1.0
