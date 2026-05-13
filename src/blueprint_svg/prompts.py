"""Prompt construction for the LLM pipeline.

The model never writes SVG. Its only job is to produce a JSON object that
validates against the `Diagram` pydantic schema. We help it by:

  1. A small `SYSTEM` prompt that pins the contract.
  2. The full JSON schema (from pydantic) as a reference.
  3. One few-shot example matching the *requested* diagram type.

Few-shot examples live in `examples/*.json` and are loaded at runtime so
docs and prompts stay in sync (edit the example, both update).
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Optional

from blueprint_svg.ir import Diagram, DiagramType

SYSTEM_PROMPT = """You are blueprint.svg's diagram planner.

Your only output is a single JSON object that matches the Diagram schema.
You do not write SVG. You do not narrate. No prose. No code fences. Just JSON.

Rules:
- `type` is one of: architecture, flowchart, er, sequence, mindmap.
- Every `node.id` is a short kebab-case slug (e.g. "auth-service"). Use semantic ids,
  never "node1"/"n1". The id becomes an HTML/SVG element id consumers will edit.
- `node.label` is the visible text (human-readable, can have spaces).
- `node.role` is a *semantic* style class: primary | secondary | accent | danger | muted | neutral.
  Pick roles that communicate meaning (e.g. external systems → "muted", primary path → "primary",
  failures → "danger"). Do not put colors in the IR.
- Edges reference node ids in `source` and `target`. Add `label` only when it adds info.
- Use `groups` to cluster related nodes (VPC, subsystem, swimlane). Cluster aggressively
  when 4+ nodes belong to a clear bucket.
- Shapes per type:
    architecture: box, rounded, cylinder (DB), cloud (external), note
    flowchart:    rounded (start/end), box (step), diamond (decision)
    er:           entity for tables
    sequence:     actor for participants (ordered left-to-right as listed)
    mindmap:      root (center), branch, leaf
- Keep diagrams compact: prefer 5-15 nodes for clarity. Split into multiple diagrams if larger.
"""


_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


def _load_example(diagram_type: DiagramType) -> Optional[dict]:
    """Find the matching example JSON for the requested type."""
    if not _EXAMPLES_DIR.exists():
        return None
    for path in sorted(_EXAMPLES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("type") == diagram_type:
            return data
    return None


def build_messages(
    user_prompt: str,
    diagram_type: DiagramType,
    image_data_url: Optional[str] = None,
) -> list[dict]:
    """Build a chat-completions messages list.

    If `image_data_url` is provided we send a multimodal user message
    (vision models like Qwen2.5-VL will see the image).
    """
    schema_json = json.dumps(Diagram.model_json_schema(), indent=2)
    example = _load_example(diagram_type)

    messages: list[dict] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + "\n\nDiagram JSON schema:\n```json\n"
            + schema_json
            + "\n```",
        }
    ]

    if example is not None:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Example request — type={diagram_type}: "
                    f"'{example.get('title', 'an example')}'."
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(example, indent=2),
            }
        )

    instruction = (
        f"Now produce a Diagram of type='{diagram_type}' for the following request. "
        "Respond with JSON only, no markdown fences."
    )

    if image_data_url:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{instruction}\n\nUser request: {user_prompt}"},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        )
    else:
        messages.append(
            {
                "role": "user",
                "content": f"{instruction}\n\nUser request: {user_prompt}",
            }
        )

    return messages
