"""Tests for the IR schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from blueprint_svg.ir import Diagram, Edge, Node


def _minimal_diagram(**overrides) -> Diagram:
    data = {
        "type": "architecture",
        "nodes": [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
        ],
        "edges": [{"source": "a", "target": "b"}],
    }
    data.update(overrides)
    return Diagram.model_validate(data)


def test_minimal_diagram_validates() -> None:
    d = _minimal_diagram()
    assert d.type == "architecture"
    assert len(d.nodes) == 2


def test_duplicate_node_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        Diagram.model_validate(
            {
                "type": "flowchart",
                "nodes": [
                    {"id": "x", "label": "X1"},
                    {"id": "x", "label": "X2"},
                ],
            }
        )


def test_node_id_must_be_slug() -> None:
    with pytest.raises(ValidationError):
        Node(id="not a slug!", label="Bad")


def test_edge_ref_validation() -> None:
    d = _minimal_diagram(edges=[{"source": "a", "target": "ghost"}])
    with pytest.raises(ValueError, match="Edge target"):
        d.validate_refs()


def test_group_ref_validation() -> None:
    d = _minimal_diagram(groups=[{"id": "g", "label": "G", "members": ["a", "ghost"]}])
    with pytest.raises(ValueError, match="Group"):
        d.validate_refs()


def test_theme_defaults_present() -> None:
    d = _minimal_diagram()
    assert "primary" in d.theme.tokens
    assert d.theme.tokens["primary"].startswith("#")
