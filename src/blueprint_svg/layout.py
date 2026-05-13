"""Layout engine: turns an IR Diagram into 2D coordinates.

Strategy:
- architecture/flowchart/er/mindmap → shell out to Graphviz `dot` with
  `-Tjson`, which returns node bounding boxes and edge splines in points.
- sequence → custom column/row layout (Graphviz can't represent lifelines
  cleanly), no external process needed.

We deliberately avoid `pygraphviz` (C extension, painful on macOS) and just
call the `dot` binary via subprocess. The Space installs it through
packages.txt; locally `brew install graphviz` is enough.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from blueprint_svg.ir import Diagram

# Graphviz outputs in points; 1 inch = 72 points. We scale to pixels (1:1).
_PT_PER_IN = 72.0


@dataclass
class NodeBox:
    id: str
    x: float  # center x (px)
    y: float  # center y (px)
    w: float  # width (px)
    h: float  # height (px)


@dataclass
class EdgePath:
    source: str
    target: str
    # Polyline approximation in px. Graphviz returns cubic beziers; we keep
    # the control point list and let the renderer emit a smooth path.
    points: list[tuple[float, float]] = field(default_factory=list)
    label_pos: Optional[tuple[float, float]] = None


@dataclass
class LayoutResult:
    width: float
    height: float
    nodes: dict[str, NodeBox]
    edges: list[EdgePath]


def layout_diagram(diagram: Diagram) -> LayoutResult:
    """Dispatch to the right layout backend for this diagram type."""
    if diagram.type == "sequence":
        return _layout_sequence(diagram)
    return _layout_graphviz(diagram)


# --------------------------------------------------------------------------
# Graphviz backend
# --------------------------------------------------------------------------

_DEFAULT_ALGO_BY_TYPE = {
    "architecture": "dot",
    "flowchart": "dot",
    "er": "dot",
    "mindmap": "twopi",
}

_DEFAULT_RANKDIR_BY_TYPE = {
    "architecture": "LR",
    "flowchart": "TB",
    "er": "LR",
}


def _layout_graphviz(diagram: Diagram) -> LayoutResult:
    if shutil.which("dot") is None:
        raise RuntimeError(
            "Graphviz `dot` binary not found on PATH. "
            "Install with: `brew install graphviz` (macOS) or "
            "`apt-get install graphviz` (Linux). On HF Spaces this is "
            "handled by packages.txt."
        )

    algo = diagram.layout.algo or _DEFAULT_ALGO_BY_TYPE.get(diagram.type, "dot")
    rankdir = diagram.layout.rankdir or _DEFAULT_RANKDIR_BY_TYPE.get(diagram.type, "TB")

    dot_src = _diagram_to_dot(diagram, rankdir=rankdir)
    proc = subprocess.run(
        [algo, "-Tjson"],
        input=dot_src.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Graphviz `{algo}` failed (exit {proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    data = json.loads(proc.stdout)
    return _parse_graphviz_json(data)


def _diagram_to_dot(diagram: Diagram, rankdir: str) -> str:
    """Render the IR as Graphviz DOT source.

    We embed node ids as-is so we can match them back from the JSON output.
    Sizes are kept uniform-ish; the renderer will redraw shapes anyway, we
    only need Graphviz for *positions*.
    """
    lines: list[str] = ["digraph G {"]
    lines.append(f'  rankdir="{rankdir}";')
    lines.append(f'  nodesep={diagram.layout.nodesep};')
    lines.append(f'  ranksep={diagram.layout.ranksep};')
    lines.append('  node [shape=box, fontname="Inter", fontsize=12, '
                 'width=1.6, height=0.6, fixedsize=false];')
    lines.append('  edge [fontname="Inter", fontsize=10];')

    # Groups → clusters (Graphviz: subgraph cluster_*)
    grouped: set[str] = set()
    for g in diagram.groups:
        lines.append(f'  subgraph "cluster_{g.id}" {{')
        lines.append(f'    label="{_escape(g.label)}";')
        for m in g.members:
            lines.append(f'    "{m}";')
            grouped.add(m)
        lines.append("  }")

    for n in diagram.nodes:
        lines.append(f'  "{n.id}" [label="{_escape(n.label)}"];')

    for e in diagram.edges:
        attrs: list[str] = []
        if e.label:
            attrs.append(f'label="{_escape(e.label)}"')
        if e.arrow == "none":
            attrs.append('dir=none')
        elif e.arrow == "both":
            attrs.append('dir=both')
        attr_str = f' [{", ".join(attrs)}]' if attrs else ""
        lines.append(f'  "{e.source}" -> "{e.target}"{attr_str};')

    lines.append("}")
    return "\n".join(lines)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _parse_graphviz_json(data: dict) -> LayoutResult:
    """Graphviz JSON: bb='x0,y0,x1,y1', objects[].pos='x,y', width/height in in.

    Graphviz uses a y-up coordinate system; SVG is y-down. We flip y here so
    downstream code can think in screen-space.
    """
    bb = [float(v) for v in data["bb"].split(",")]
    _, _, x1, y1 = bb
    width = x1
    height = y1

    nodes: dict[str, NodeBox] = {}
    for obj in data.get("objects", []):
        if "pos" not in obj:
            continue  # cluster wrappers have no pos
        name = obj.get("name") or obj.get("id")
        if not name or name.startswith("cluster_"):
            continue
        x, y = (float(v) for v in obj["pos"].split(","))
        w = float(obj.get("width", 1.6)) * _PT_PER_IN
        h = float(obj.get("height", 0.6)) * _PT_PER_IN
        nodes[name] = NodeBox(id=name, x=x, y=height - y, w=w, h=h)

    edges: list[EdgePath] = []
    objects = data.get("objects", [])
    for ed in data.get("edges", []):
        tail = objects[ed["tail"]].get("name", "")
        head = objects[ed["head"]].get("name", "")
        pts: list[tuple[float, float]] = []
        if "pos" in ed:
            # Format: "e,x,y x0,y0 x1,y1 ..."  (e, marks an endpoint)
            for tok in ed["pos"].split():
                tok = tok.lstrip("es,")
                try:
                    x, y = (float(v) for v in tok.split(","))
                    pts.append((x, height - y))
                except ValueError:
                    continue
        label_pos = None
        if "lp" in ed:
            lx, ly = (float(v) for v in ed["lp"].split(","))
            label_pos = (lx, height - ly)
        edges.append(EdgePath(source=tail, target=head, points=pts, label_pos=label_pos))

    return LayoutResult(width=width, height=height, nodes=nodes, edges=edges)


# --------------------------------------------------------------------------
# Sequence backend (no external process)
# --------------------------------------------------------------------------

def _layout_sequence(diagram: Diagram) -> LayoutResult:
    """Sequence diagrams: actors as columns, messages as rows.

    Convention used by the prompt:
        - nodes with shape='actor' or shape='lifeline' are columns (ordered as given)
        - edges are messages, drawn top-to-bottom in `diagram.edges` order
    """
    col_w = 160.0
    row_h = 50.0
    margin_x = 60.0
    margin_y = 60.0
    header_h = 60.0

    actors = [n for n in diagram.nodes if n.shape in ("actor", "lifeline")]
    if not actors:
        actors = diagram.nodes  # fall back: treat all as columns

    cols = {n.id: i for i, n in enumerate(actors)}

    nodes: dict[str, NodeBox] = {}
    for n in actors:
        i = cols[n.id]
        nodes[n.id] = NodeBox(
            id=n.id,
            x=margin_x + i * col_w + col_w / 2,
            y=margin_y + header_h / 2,
            w=col_w - 24,
            h=header_h - 20,
        )

    edges: list[EdgePath] = []
    for i, e in enumerate(diagram.edges):
        if e.source not in cols or e.target not in cols:
            continue
        y = margin_y + header_h + (i + 1) * row_h
        x0 = margin_x + cols[e.source] * col_w + col_w / 2
        x1 = margin_x + cols[e.target] * col_w + col_w / 2
        edges.append(
            EdgePath(
                source=e.source,
                target=e.target,
                points=[(x0, y), (x1, y)],
                label_pos=((x0 + x1) / 2, y - 8),
            )
        )

    width = margin_x * 2 + len(actors) * col_w
    height = margin_y * 2 + header_h + (len(diagram.edges) + 1) * row_h
    return LayoutResult(width=width, height=height, nodes=nodes, edges=edges)
