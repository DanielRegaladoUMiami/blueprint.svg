"""blueprint.svg — layered, editable SVG diagrams from a structured IR."""

from blueprint_svg.ir import (
    Diagram,
    Edge,
    Group,
    Node,
    Theme,
)
from blueprint_svg.layout import layout_diagram
from blueprint_svg.renderer import render_svg

__all__ = [
    "Diagram",
    "Edge",
    "Group",
    "Node",
    "Theme",
    "layout_diagram",
    "render_svg",
]

__version__ = "0.1.0"
