"""Intermediate Representation (IR) schema for blueprint.svg diagrams.

The IR is the contract between the LLM (which produces JSON) and the renderer
(which consumes it). Keeping it small, explicit, and validated is what lets the
final SVG come out with semantic groups, themable CSS, and predictable layout.

See docs/ir-spec.md for the human-readable spec.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DiagramType = Literal["architecture", "flowchart", "er", "sequence", "mindmap"]

NodeShape = Literal[
    "box",
    "rounded",
    "ellipse",
    "diamond",
    "cylinder",
    "cloud",
    "note",
    "entity",
    "actor",
    "lifeline",
    "root",
    "branch",
    "leaf",
]

# Semantic style "roles". The renderer maps each role to a CSS variable
# (e.g. role="primary" → fill: var(--bp-primary)). Themes override the
# variable values, not the role assignments, so a single diagram retheme
# without re-running the LLM.
StyleRole = Literal["primary", "secondary", "accent", "danger", "muted", "neutral"]

EdgeStyle = Literal["solid", "dashed", "dotted"]
ArrowKind = Literal["none", "arrow", "both"]


class Node(BaseModel):
    """A single labeled element in the diagram."""

    id: str = Field(..., description="Semantic, unique id. Becomes <g id='...'>.")
    label: str = Field(..., description="Visible text on the node.")
    shape: NodeShape = "box"
    role: StyleRole = "primary"
    group: Optional[str] = Field(
        default=None,
        description="Optional group id this node belongs to.",
    )
    note: Optional[str] = Field(
        default=None,
        description="Optional aria/desc string for accessibility.",
    )

    @field_validator("id")
    @classmethod
    def _id_must_be_slug(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(
                "Node id must be a non-empty slug of [a-zA-Z0-9_-]. "
                f"Got: {v!r}"
            )
        return v


class Edge(BaseModel):
    """Directed (or undirected) connection between two nodes."""

    source: str
    target: str
    label: Optional[str] = None
    style: EdgeStyle = "solid"
    arrow: ArrowKind = "arrow"
    role: StyleRole = "neutral"


class Group(BaseModel):
    """Logical cluster of nodes (e.g. a VPC, a swimlane, a subgraph)."""

    id: str
    label: str
    members: list[str] = Field(default_factory=list)
    role: StyleRole = "muted"


class Theme(BaseModel):
    """Maps StyleRole names to CSS color values.

    Emitted by the renderer as `:root { --bp-<role>: <value>; }` so consumers
    can override any token without touching the SVG body.
    """

    name: str = "default"
    tokens: dict[str, str] = Field(
        default_factory=lambda: {
            "primary": "#4f46e5",
            "secondary": "#0ea5e9",
            "accent": "#f59e0b",
            "danger": "#ef4444",
            "muted": "#94a3b8",
            "neutral": "#475569",
            "bg": "#ffffff",
            "fg": "#0f172a",
            "edge": "#334155",
            "group-bg": "#f1f5f9",
            "group-stroke": "#cbd5e1",
        }
    )


class LayoutHints(BaseModel):
    """Optional layout hints. The layout engine picks sensible defaults per type."""

    algo: Optional[Literal["dot", "neato", "twopi", "circo", "fdp", "sequence"]] = None
    rankdir: Optional[Literal["TB", "LR", "BT", "RL"]] = None
    nodesep: float = 0.5
    ranksep: float = 0.75


class Diagram(BaseModel):
    """Top-level IR object. The LLM's only job is to produce a valid one of these."""

    type: DiagramType
    title: Optional[str] = None
    description: Optional[str] = None
    nodes: list[Node]
    edges: list[Edge] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    theme: Theme = Field(default_factory=Theme)
    layout: LayoutHints = Field(default_factory=LayoutHints)

    @field_validator("nodes")
    @classmethod
    def _unique_node_ids(cls, v: list[Node]) -> list[Node]:
        seen: set[str] = set()
        for n in v:
            if n.id in seen:
                raise ValueError(f"Duplicate node id: {n.id!r}")
            seen.add(n.id)
        return v

    def validate_refs(self) -> None:
        """Check that every edge/group reference points to an existing node id."""
        ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in ids:
                raise ValueError(f"Edge source {e.source!r} not in nodes.")
            if e.target not in ids:
                raise ValueError(f"Edge target {e.target!r} not in nodes.")
        for g in self.groups:
            for m in g.members:
                if m not in ids:
                    raise ValueError(f"Group {g.id!r} member {m!r} not in nodes.")
