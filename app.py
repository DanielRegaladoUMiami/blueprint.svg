"""Gradio entrypoint for the blueprint.svg Hugging Face Space.

The Space's runtime looks for a top-level `app.py`, so this file stays at the
repo root and imports the library from `src/blueprint_svg/`.

UI structure:
  * Tab 1 — Text → diagram (prompt + diagram type)
  * Tab 2 — Image → diagram (whiteboard photo / screenshot + optional notes)
Both tabs share the same output panel: rendered SVG preview, downloadable
SVG file, and the IR JSON (also downloadable) so users can version it in git
or re-render after manual edits.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

# Make the in-repo package importable both locally and in the Space.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import gradio as gr  # noqa: E402
from PIL import Image  # noqa: E402

from blueprint_svg import Diagram, layout_diagram, render_svg  # noqa: E402
from blueprint_svg.llm import (  # noqa: E402
    LLMError,
    generate_from_image,
    generate_from_text,
    image_bytes_from_pil,
)

DIAGRAM_TYPES = ["architecture", "flowchart", "er", "sequence", "mindmap"]

# Load the bundled examples so the Gallery tab can showcase them without
# spending tokens.
_EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


def _render_diagram(diagram: Diagram) -> tuple[str, str, str, str]:
    layout = layout_diagram(diagram)
    svg = render_svg(diagram, layout)
    ir_json = json.dumps(diagram.model_dump(), indent=2)

    # Materialize files for download
    out_dir = Path(tempfile.mkdtemp(prefix="blueprint-svg-"))
    svg_path = out_dir / "diagram.svg"
    json_path = out_dir / "diagram.json"
    svg_path.write_text(svg)
    json_path.write_text(ir_json)

    return svg, ir_json, str(svg_path), str(json_path)


def _wrap_svg_in_html(svg: str) -> str:
    """Gradio's HTML component will render an inline SVG directly."""
    return (
        '<div style="background:#fff;padding:16px;border-radius:8px;'
        'overflow:auto;max-width:100%;">' + svg + "</div>"
    )


def handle_text(prompt: str, diagram_type: str, token: str) -> tuple:
    if not prompt or not prompt.strip():
        raise gr.Error("Write a prompt describing the diagram you want.")
    if diagram_type not in DIAGRAM_TYPES:
        raise gr.Error(f"Unknown diagram type: {diagram_type}")
    try:
        diagram = generate_from_text(
            prompt.strip(),
            diagram_type=diagram_type,
            token=token or None,
        )
    except LLMError as e:
        raise gr.Error(str(e)) from e
    svg, ir_json, svg_path, json_path = _render_diagram(diagram)
    return _wrap_svg_in_html(svg), ir_json, svg_path, json_path


def handle_image(
    image: Optional[Image.Image],
    notes: str,
    diagram_type: str,
    token: str,
) -> tuple:
    if image is None:
        raise gr.Error("Upload an image (whiteboard photo, screenshot, or sketch).")
    prompt = notes.strip() or "Re-create this diagram cleanly and structurally."
    try:
        diagram = generate_from_image(
            image_bytes_from_pil(image),
            diagram_type=diagram_type,
            prompt=prompt,
            token=token or None,
        )
    except LLMError as e:
        raise gr.Error(str(e)) from e
    svg, ir_json, svg_path, json_path = _render_diagram(diagram)
    return _wrap_svg_in_html(svg), ir_json, svg_path, json_path


def handle_example(example_name: str) -> tuple:
    path = _EXAMPLES_DIR / example_name
    data = json.loads(path.read_text())
    diagram = Diagram.model_validate(data)
    svg, ir_json, svg_path, json_path = _render_diagram(diagram)
    return _wrap_svg_in_html(svg), ir_json, svg_path, json_path


_EXAMPLE_FILES = sorted(p.name for p in _EXAMPLES_DIR.glob("*.json")) if _EXAMPLES_DIR.exists() else []


_TAGLINE = (
    "**Layered, editable SVG diagrams** — from text or images. "
    "The model produces a structured IR (JSON), a deterministic renderer turns "
    "it into SVG with semantic `<g id>`s and CSS theme variables. "
    "Edit individual elements in Figma/Inkscape, or restyle the whole diagram "
    "by overriding three CSS variables."
)

_TOKEN_HELP = (
    "Optional. Leave blank to use the Space's `HF_TOKEN` secret. "
    "Provide your own token only if you want the call charged to your account."
)


with gr.Blocks(title="blueprint.svg", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 📐 blueprint.svg")
    gr.Markdown(_TAGLINE)

    with gr.Accordion("Advanced — Hugging Face token", open=False):
        token = gr.Textbox(
            label="HF token (optional)",
            placeholder="hf_...",
            type="password",
            info=_TOKEN_HELP,
        )

    with gr.Tabs():
        with gr.Tab("Text → diagram"):
            with gr.Row():
                with gr.Column(scale=2):
                    text_type = gr.Dropdown(
                        DIAGRAM_TYPES,
                        value="architecture",
                        label="Diagram type",
                    )
                    text_prompt = gr.Textbox(
                        label="Prompt",
                        lines=6,
                        placeholder=(
                            "e.g. A streaming ingestion pipeline: producers → Kafka → "
                            "a Flink job → an S3 data lake and a Postgres serving layer. "
                            "Show monitoring with Datadog."
                        ),
                    )
                    text_btn = gr.Button("Generate", variant="primary")
                with gr.Column(scale=3):
                    text_svg = gr.HTML(label="Preview")
                    with gr.Row():
                        text_svg_file = gr.File(label="diagram.svg")
                        text_json_file = gr.File(label="diagram.json")
                    text_json = gr.Code(label="IR (JSON)", language="json")

            text_btn.click(
                handle_text,
                inputs=[text_prompt, text_type, token],
                outputs=[text_svg, text_json, text_svg_file, text_json_file],
            )

        with gr.Tab("Image → diagram"):
            with gr.Row():
                with gr.Column(scale=2):
                    img_input = gr.Image(
                        label="Whiteboard / screenshot / sketch",
                        type="pil",
                    )
                    img_type = gr.Dropdown(
                        DIAGRAM_TYPES,
                        value="architecture",
                        label="Diagram type",
                    )
                    img_notes = gr.Textbox(
                        label="Notes (optional)",
                        lines=3,
                        placeholder="Optional: 'this is the v2 architecture, label the queue as SQS'",
                    )
                    img_btn = gr.Button("Reconstruct", variant="primary")
                with gr.Column(scale=3):
                    img_svg = gr.HTML(label="Preview")
                    with gr.Row():
                        img_svg_file = gr.File(label="diagram.svg")
                        img_json_file = gr.File(label="diagram.json")
                    img_json = gr.Code(label="IR (JSON)", language="json")

            img_btn.click(
                handle_image,
                inputs=[img_input, img_notes, img_type, token],
                outputs=[img_svg, img_json, img_svg_file, img_json_file],
            )

        with gr.Tab("Gallery"):
            gr.Markdown(
                "Hand-crafted IRs that ship with the repo. They double as "
                "few-shot examples for the LLM and as a smoke test for the renderer."
            )
            with gr.Row():
                gallery_pick = gr.Dropdown(
                    _EXAMPLE_FILES,
                    value=_EXAMPLE_FILES[0] if _EXAMPLE_FILES else None,
                    label="Example",
                )
                gallery_btn = gr.Button("Render")
            gallery_svg = gr.HTML()
            with gr.Row():
                gallery_svg_file = gr.File(label="diagram.svg")
                gallery_json_file = gr.File(label="diagram.json")
            gallery_json = gr.Code(label="IR (JSON)", language="json")
            gallery_btn.click(
                handle_example,
                inputs=[gallery_pick],
                outputs=[gallery_svg, gallery_json, gallery_svg_file, gallery_json_file],
            )

    gr.Markdown(
        "---\n"
        "**Why this isn't just Claude generating SVG.** Claude produces an "
        "SVG blob: hundreds of `<path>` nodes, no semantic ids, no theme tokens. "
        "blueprint.svg routes the model through a JSON IR + a deterministic "
        "renderer with Graphviz layout, so the output has named groups, CSS "
        "variables, ARIA labels, and survives editing in Figma. "
        "Source: [github.com/DanielRegaladoUMiami/blueprint.svg]"
        "(https://github.com/DanielRegaladoUMiami/blueprint.svg)"
    )


if __name__ == "__main__":
    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
    )
