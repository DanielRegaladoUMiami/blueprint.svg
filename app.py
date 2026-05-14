"""Gradio entrypoint for the blueprint.svg Hugging Face Space.

UI philosophy: this is a designer tool, not a generic demo. Dark "blueprint"
aesthetic — graph-paper canvas, mono typography for the IR JSON, corner
brackets around the preview like a CAD viewport, soft accent neon, and a
left rail of controls instead of stacked rows.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
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

_EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
_EXAMPLE_FILES = sorted(p.name for p in _EXAMPLES_DIR.glob("*.json")) if _EXAMPLES_DIR.exists() else []


# --------------------------------------------------------------------------
# Backend handlers
# --------------------------------------------------------------------------

def _render_diagram(diagram: Diagram) -> tuple[str, str, str, str, float]:
    t0 = time.perf_counter()
    layout = layout_diagram(diagram)
    svg = render_svg(diagram, layout)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    ir_json = json.dumps(diagram.model_dump(), indent=2)
    out_dir = Path(tempfile.mkdtemp(prefix="blueprint-svg-"))
    svg_path = out_dir / "diagram.svg"
    json_path = out_dir / "diagram.json"
    svg_path.write_text(svg)
    json_path.write_text(ir_json)
    return svg, ir_json, str(svg_path), str(json_path), elapsed_ms


def _viewport_html(svg: str, label: str = "diagram.svg") -> str:
    """Embed the SVG in a CAD-viewport-styled container with corner brackets."""
    return f"""
<div class="bp-viewport">
  <div class="bp-corner bp-corner--tl"></div>
  <div class="bp-corner bp-corner--tr"></div>
  <div class="bp-corner bp-corner--bl"></div>
  <div class="bp-corner bp-corner--br"></div>
  <div class="bp-viewport-label">{label}</div>
  <div class="bp-viewport-svg">{svg}</div>
</div>
"""


def _empty_viewport_html(message: str = "No diagram yet — generate one to begin.") -> str:
    return f"""
<div class="bp-viewport bp-viewport--empty">
  <div class="bp-corner bp-corner--tl"></div>
  <div class="bp-corner bp-corner--tr"></div>
  <div class="bp-corner bp-corner--bl"></div>
  <div class="bp-corner bp-corner--br"></div>
  <div class="bp-empty-state">
    <div class="bp-empty-glyph">⌗</div>
    <div class="bp-empty-text">{message}</div>
  </div>
</div>
"""


def _status_pill_html(state: str, detail: str = "") -> str:
    """Status indicator. state ∈ {idle, working, ok, error}."""
    return f"""
<div class="bp-status bp-status--{state}">
  <span class="bp-status-dot"></span>
  <span class="bp-status-text">{state.upper()}</span>
  <span class="bp-status-detail">{detail}</span>
</div>
"""


def _history_strip_html(history: list[dict]) -> str:
    if not history:
        return '<div class="bp-history-empty">History will appear here after you generate a few diagrams.</div>'
    items = []
    for i, h in enumerate(history[-4:][::-1]):
        items.append(
            f"""<div class="bp-history-item">
              <div class="bp-history-label">#{len(history) - i} · {h["type"]}</div>
              <div class="bp-history-thumb">{h["svg"]}</div>
              <div class="bp-history-meta">{h["nodes"]} nodes · {h["ms"]:.0f} ms</div>
            </div>"""
        )
    return '<div class="bp-history">' + "".join(items) + "</div>"


def handle_text(prompt: str, diagram_type: str, token: str, history: list):
    if not prompt or not prompt.strip():
        raise gr.Error("Write a prompt describing the diagram you want.")
    if diagram_type not in DIAGRAM_TYPES:
        raise gr.Error(f"Unknown diagram type: {diagram_type}")
    try:
        diagram = generate_from_text(prompt.strip(), diagram_type=diagram_type, token=token or None)
    except LLMError as e:
        return (
            _empty_viewport_html(f"⚠ {e}"),
            "",
            None,
            None,
            _status_pill_html("error", str(e)[:80]),
            _history_strip_html(history),
            history,
        )
    svg, ir_json, svg_path, json_path, ms = _render_diagram(diagram)
    history = (history or []) + [
        {"type": diagram.type, "svg": svg, "nodes": len(diagram.nodes), "ms": ms}
    ]
    return (
        _viewport_html(svg, f"{diagram.type} · {diagram.title or 'untitled'}"),
        ir_json,
        svg_path,
        json_path,
        _status_pill_html("ok", f"{len(diagram.nodes)} nodes · {ms:.0f} ms"),
        _history_strip_html(history),
        history,
    )


def handle_image(image: Optional[Image.Image], notes: str, diagram_type: str, token: str, history: list):
    if image is None:
        raise gr.Error("Upload an image (whiteboard photo, screenshot, or sketch).")
    prompt = (notes or "").strip() or "Re-create this diagram cleanly and structurally."
    try:
        diagram = generate_from_image(
            image_bytes_from_pil(image),
            diagram_type=diagram_type,
            prompt=prompt,
            token=token or None,
        )
    except LLMError as e:
        return (
            _empty_viewport_html(f"⚠ {e}"),
            "",
            None,
            None,
            _status_pill_html("error", str(e)[:80]),
            _history_strip_html(history),
            history,
        )
    svg, ir_json, svg_path, json_path, ms = _render_diagram(diagram)
    history = (history or []) + [
        {"type": diagram.type, "svg": svg, "nodes": len(diagram.nodes), "ms": ms}
    ]
    return (
        _viewport_html(svg, f"{diagram.type} · {diagram.title or 'untitled'}"),
        ir_json,
        svg_path,
        json_path,
        _status_pill_html("ok", f"{len(diagram.nodes)} nodes · {ms:.0f} ms · vision"),
        _history_strip_html(history),
        history,
    )


def handle_example(example_name: str, history: list):
    path = _EXAMPLES_DIR / example_name
    data = json.loads(path.read_text())
    diagram = Diagram.model_validate(data)
    svg, ir_json, svg_path, json_path, ms = _render_diagram(diagram)
    history = (history or []) + [
        {"type": diagram.type, "svg": svg, "nodes": len(diagram.nodes), "ms": ms}
    ]
    return (
        _viewport_html(svg, f"{diagram.type} · {diagram.title or example_name}"),
        ir_json,
        svg_path,
        json_path,
        _status_pill_html("ok", f"example · {len(diagram.nodes)} nodes · {ms:.0f} ms"),
        _history_strip_html(history),
        history,
    )


# --------------------------------------------------------------------------
# Theme + CSS
# --------------------------------------------------------------------------

_THEME = gr.themes.Base(
    primary_hue=gr.themes.Color(
        c50="#eef2ff", c100="#e0e7ff", c200="#c7d2fe", c300="#a5b4fc",
        c400="#818cf8", c500="#6366f1", c600="#4f46e5", c700="#4338ca",
        c800="#3730a3", c900="#312e81", c950="#1e1b4b",
    ),
    secondary_hue=gr.themes.Color(
        c50="#ecfeff", c100="#cffafe", c200="#a5f3fc", c300="#67e8f9",
        c400="#22d3ee", c500="#06b6d4", c600="#0891b2", c700="#0e7490",
        c800="#155e75", c900="#164e63", c950="#083344",
    ),
    neutral_hue="slate",
    font=(gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"),
    font_mono=(gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"),
).set(
    body_background_fill="#0b1020",
    body_background_fill_dark="#0b1020",
    body_text_color="#e2e8f0",
    body_text_color_dark="#e2e8f0",
    background_fill_primary="#0f172a",
    background_fill_primary_dark="#0f172a",
    background_fill_secondary="#111827",
    background_fill_secondary_dark="#111827",
    border_color_primary="#1f2937",
    border_color_primary_dark="#1f2937",
    block_background_fill="#0f172a",
    block_background_fill_dark="#0f172a",
    block_border_color="#1e293b",
    block_border_color_dark="#1e293b",
    block_label_text_color="#94a3b8",
    block_label_text_color_dark="#94a3b8",
    block_title_text_color="#e2e8f0",
    block_title_text_color_dark="#e2e8f0",
    input_background_fill="#0b1224",
    input_background_fill_dark="#0b1224",
    input_border_color="#1e293b",
    input_border_color_dark="#1e293b",
    button_primary_background_fill="linear-gradient(135deg,#6366f1 0%,#22d3ee 100%)",
    button_primary_background_fill_hover="linear-gradient(135deg,#818cf8 0%,#67e8f9 100%)",
    button_primary_text_color="#0b1020",
    button_primary_border_color="transparent",
    button_secondary_background_fill="#1e293b",
    button_secondary_background_fill_hover="#334155",
    button_secondary_text_color="#e2e8f0",
)


_CSS = """
/* ============================================================
   blueprint.svg — custom styling
   Dark "blueprint" aesthetic: graph paper bg, neon accents,
   monospace IR, CAD-viewport preview with corner brackets.
   ============================================================ */

:root {
  --bp-ink: #e2e8f0;
  --bp-ink-dim: #94a3b8;
  --bp-line: #1e293b;
  --bp-paper: #0b1020;
  --bp-paper-soft: #0f172a;
  --bp-grid: rgba(99, 102, 241, 0.07);
  --bp-grid-strong: rgba(99, 102, 241, 0.14);
  --bp-accent: #22d3ee;
  --bp-accent-2: #818cf8;
  --bp-ok: #34d399;
  --bp-err: #f87171;
  --bp-warn: #fbbf24;
}

/* Graph paper background on the whole body */
.gradio-container, body, gradio-app {
  background-color: var(--bp-paper) !important;
  background-image:
    linear-gradient(var(--bp-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--bp-grid) 1px, transparent 1px),
    linear-gradient(var(--bp-grid-strong) 1px, transparent 1px),
    linear-gradient(90deg, var(--bp-grid-strong) 1px, transparent 1px) !important;
  background-size: 24px 24px, 24px 24px, 120px 120px, 120px 120px !important;
  background-position: -1px -1px !important;
}

.gradio-container { max-width: 1480px !important; }

/* ---------- Header ---------- */
#bp-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 20px; margin: 8px 0 16px;
  background: linear-gradient(180deg, rgba(15,23,42,0.95) 0%, rgba(15,23,42,0.6) 100%);
  border: 1px solid var(--bp-line); border-radius: 14px;
  backdrop-filter: blur(6px);
}
#bp-header .bp-brand {
  display: flex; align-items: baseline; gap: 14px;
}
#bp-header .bp-logo {
  font-family: "JetBrains Mono", monospace; font-weight: 700; font-size: 22px;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #6366f1, #22d3ee);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
#bp-header .bp-tagline {
  font-size: 13px; color: var(--bp-ink-dim);
  letter-spacing: 0.02em;
}
#bp-header .bp-meta {
  display: flex; gap: 18px; align-items: center;
  font-family: "JetBrains Mono", monospace; font-size: 11px;
  color: var(--bp-ink-dim); text-transform: uppercase; letter-spacing: 0.12em;
}
#bp-header .bp-meta a {
  color: var(--bp-accent); text-decoration: none;
  border-bottom: 1px dotted rgba(34, 211, 238, 0.4);
}

/* ---------- Status pill ---------- */
.bp-status {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 12px; border-radius: 999px;
  background: rgba(15, 23, 42, 0.8); border: 1px solid var(--bp-line);
  font-family: "JetBrains Mono", monospace; font-size: 11px;
  color: var(--bp-ink-dim); letter-spacing: 0.1em;
}
.bp-status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--bp-ink-dim);
}
.bp-status-text { color: var(--bp-ink); font-weight: 600; }
.bp-status-detail { color: var(--bp-ink-dim); text-transform: none; letter-spacing: 0; }
.bp-status--idle .bp-status-dot { background: var(--bp-ink-dim); }
.bp-status--working .bp-status-dot {
  background: var(--bp-warn);
  animation: bp-pulse 1.2s ease-in-out infinite;
}
.bp-status--ok .bp-status-dot {
  background: var(--bp-ok);
  box-shadow: 0 0 0 4px rgba(52, 211, 153, 0.15);
}
.bp-status--error .bp-status-dot {
  background: var(--bp-err);
  box-shadow: 0 0 0 4px rgba(248, 113, 113, 0.15);
}
@keyframes bp-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: 0.5; }
}

/* ---------- Sidebar panel ---------- */
#bp-sidebar .form, #bp-sidebar > div {
  background: rgba(15, 23, 42, 0.65) !important;
}
#bp-sidebar h3 {
  font-family: "JetBrains Mono", monospace;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.18em;
  color: var(--bp-ink-dim); margin: 18px 0 8px;
}

/* Bigger, brand-y primary button */
button.primary, .bp-cta button {
  font-family: "Inter", sans-serif !important;
  font-weight: 600 !important; letter-spacing: -0.01em !important;
  border-radius: 12px !important; height: 46px !important;
  font-size: 15px !important;
  box-shadow: 0 8px 28px -10px rgba(99, 102, 241, 0.7) !important;
  transition: transform 120ms ease, box-shadow 120ms ease !important;
}
button.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 36px -10px rgba(34, 211, 238, 0.55) !important;
}

/* ---------- CAD viewport ---------- */
.bp-viewport {
  position: relative;
  background:
    radial-gradient(circle at 50% 0%, rgba(99,102,241,0.08), transparent 60%),
    #fdfdfb;
  border: 1px solid var(--bp-line);
  border-radius: 14px;
  padding: 28px;
  min-height: 460px;
  overflow: auto;
  animation: bp-fade-in 320ms ease-out;
}
.bp-viewport--empty {
  background:
    radial-gradient(circle at 50% 50%, rgba(99,102,241,0.06), transparent 60%),
    #0b1224;
  min-height: 460px; display: grid; place-items: center;
}
@keyframes bp-fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.bp-viewport-svg { animation: bp-svg-reveal 480ms ease-out; }
@keyframes bp-svg-reveal {
  from { opacity: 0; transform: scale(0.985); }
  to { opacity: 1; transform: scale(1); }
}
.bp-viewport-svg svg { max-width: 100%; height: auto; display: block; margin: 0 auto; }
.bp-viewport-label {
  position: absolute; top: 8px; left: 14px;
  font-family: "JetBrains Mono", monospace; font-size: 10px;
  color: var(--bp-ink-dim); letter-spacing: 0.12em; text-transform: uppercase;
  background: rgba(255,255,255,0.7); padding: 2px 8px; border-radius: 4px;
}
.bp-viewport--empty .bp-viewport-label {
  background: rgba(15,23,42,0.7); color: var(--bp-ink-dim);
}

/* Corner brackets */
.bp-corner {
  position: absolute; width: 14px; height: 14px;
  border-color: var(--bp-accent); border-style: solid; border-width: 0;
  opacity: 0.7;
}
.bp-corner--tl { top: 6px; left: 6px; border-top-width: 2px; border-left-width: 2px; }
.bp-corner--tr { top: 6px; right: 6px; border-top-width: 2px; border-right-width: 2px; }
.bp-corner--bl { bottom: 6px; left: 6px; border-bottom-width: 2px; border-left-width: 2px; }
.bp-corner--br { bottom: 6px; right: 6px; border-bottom-width: 2px; border-right-width: 2px; }

/* Empty state */
.bp-empty-state { text-align: center; color: var(--bp-ink-dim); }
.bp-empty-glyph {
  font-size: 56px; color: var(--bp-accent-2); margin-bottom: 8px;
  font-family: "JetBrains Mono", monospace; opacity: 0.4;
}
.bp-empty-text {
  font-family: "JetBrains Mono", monospace; font-size: 12px;
  letter-spacing: 0.08em;
}

/* ---------- History strip ---------- */
.bp-history {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
  padding: 12px 0;
}
.bp-history-item {
  background: rgba(15, 23, 42, 0.6); border: 1px solid var(--bp-line);
  border-radius: 10px; padding: 10px; overflow: hidden;
  transition: border-color 160ms ease, transform 160ms ease;
}
.bp-history-item:hover {
  border-color: var(--bp-accent); transform: translateY(-2px);
}
.bp-history-label {
  font-family: "JetBrains Mono", monospace; font-size: 10px;
  color: var(--bp-accent); letter-spacing: 0.1em; text-transform: uppercase;
  margin-bottom: 6px;
}
.bp-history-thumb {
  background: #fdfdfb; border-radius: 6px; padding: 4px;
  height: 110px; overflow: hidden; display: grid; place-items: center;
}
.bp-history-thumb svg { max-width: 100%; max-height: 100%; }
.bp-history-meta {
  font-family: "JetBrains Mono", monospace; font-size: 10px;
  color: var(--bp-ink-dim); margin-top: 6px; letter-spacing: 0.04em;
}
.bp-history-empty {
  font-family: "JetBrains Mono", monospace; font-size: 11px;
  color: var(--bp-ink-dim); padding: 18px; text-align: center;
  border: 1px dashed var(--bp-line); border-radius: 10px;
}

/* ---------- IR code panel ---------- */
#bp-ir-panel .cm-editor, #bp-ir-panel pre {
  background: #0b1224 !important; border-radius: 10px;
  font-size: 12px !important;
}
#bp-ir-panel label { color: var(--bp-ink-dim) !important; }

/* Section divider */
.bp-section-title {
  font-family: "JetBrains Mono", monospace;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.18em;
  color: var(--bp-ink-dim); margin: 18px 0 10px;
  display: flex; align-items: center; gap: 10px;
}
.bp-section-title::before, .bp-section-title::after {
  content: ""; flex: 1; height: 1px; background: var(--bp-line);
}

/* Tabs */
.tab-nav button {
  font-family: "JetBrains Mono", monospace !important;
  font-size: 11px !important; letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
}
.tab-nav button.selected {
  color: var(--bp-accent) !important;
  border-bottom: 2px solid var(--bp-accent) !important;
}

/* Footer */
#bp-footer {
  margin-top: 28px; padding: 16px 20px;
  border-top: 1px solid var(--bp-line);
  font-family: "JetBrains Mono", monospace; font-size: 11px;
  color: var(--bp-ink-dim); letter-spacing: 0.06em;
  display: flex; justify-content: space-between;
}
#bp-footer a { color: var(--bp-accent); text-decoration: none; }
"""


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

_HEADER_HTML = """
<div id="bp-header">
  <div class="bp-brand">
    <div class="bp-logo">⌗ blueprint.svg</div>
    <div class="bp-tagline">Structured diagrams · layered SVG · editable IR</div>
  </div>
  <div class="bp-meta">
    <span>v0.1.0</span>
    <span>·</span>
    <a href="https://github.com/DanielRegaladoUMiami/blueprint.svg" target="_blank">github</a>
    <span>·</span>
    <span>Qwen 2.5</span>
  </div>
</div>
"""

_FOOTER_HTML = """
<div id="bp-footer">
  <span>blueprint.svg — Apache 2.0 · Daniel Regalado</span>
  <span>The model writes JSON. The renderer draws SVG. Edit either.</span>
</div>
"""


with gr.Blocks(title="blueprint.svg", theme=_THEME, css=_CSS, analytics_enabled=False) as demo:

    history_state = gr.State([])

    gr.HTML(_HEADER_HTML)

    with gr.Row(equal_height=False):
        # -------- LEFT: controls --------
        with gr.Column(scale=4, min_width=320, elem_id="bp-sidebar"):
            gr.HTML('<div class="bp-section-title">input</div>')
            with gr.Tabs():
                with gr.Tab("Text"):
                    text_prompt = gr.Textbox(
                        label="Describe your diagram",
                        lines=7,
                        placeholder=(
                            "e.g. A streaming pipeline: producers → Kafka → Flink → "
                            "an S3 data lake and a Postgres serving layer. Show monitoring with Datadog."
                        ),
                    )
                    text_type = gr.Dropdown(
                        DIAGRAM_TYPES, value="architecture", label="Diagram type", filterable=False
                    )
                    text_btn = gr.Button("⌗  Generate", variant="primary", elem_classes=["bp-cta"])

                with gr.Tab("Image"):
                    img_input = gr.Image(label="Whiteboard / screenshot / sketch", type="pil")
                    img_type = gr.Dropdown(
                        DIAGRAM_TYPES, value="architecture", label="Diagram type", filterable=False
                    )
                    img_notes = gr.Textbox(
                        label="Notes (optional)",
                        lines=2,
                        placeholder="e.g. 'label the queue as SQS, this is the v2 architecture'",
                    )
                    img_btn = gr.Button("⌗  Reconstruct", variant="primary", elem_classes=["bp-cta"])

                with gr.Tab("Gallery"):
                    gr.Markdown(
                        "Hand-crafted IRs. They double as few-shot exemplars and as a free, "
                        "no-LLM smoke test of the renderer.",
                        elem_classes=["bp-help-text"],
                    )
                    gallery_pick = gr.Dropdown(
                        _EXAMPLE_FILES,
                        value=_EXAMPLE_FILES[0] if _EXAMPLE_FILES else None,
                        label="Example",
                        filterable=False,
                    )
                    gallery_btn = gr.Button("⌗  Render", variant="primary", elem_classes=["bp-cta"])

            gr.HTML('<div class="bp-section-title">advanced</div>')
            with gr.Accordion("Hugging Face token (optional)", open=False):
                gr.Markdown(
                    "The Space runs **Qwen2.5-7B** on the HF free tier — works "
                    "anonymously, with rate limits. Paste your own token to "
                    "auto-upgrade to **Qwen2.5-72B** (charged to your HF "
                    "account). Get one at "
                    "[huggingface.co/settings/tokens]"
                    "(https://huggingface.co/settings/tokens) with the "
                    "`Make calls to Inference Providers` scope.",
                )
                token = gr.Textbox(
                    label="HF token",
                    placeholder="hf_...",
                    type="password",
                    show_label=False,
                )

        # -------- RIGHT: canvas + IR --------
        with gr.Column(scale=8, min_width=520):
            with gr.Row():
                gr.HTML('<div class="bp-section-title" style="margin:0;flex:1;">canvas</div>')
                status = gr.HTML(_status_pill_html("idle"), elem_id="bp-status-wrap")

            preview = gr.HTML(_empty_viewport_html(), elem_id="bp-preview")

            with gr.Row():
                svg_file = gr.File(label="diagram.svg", scale=1)
                json_file = gr.File(label="diagram.json", scale=1)

            with gr.Accordion("IR (JSON) — the structured representation", open=False, elem_id="bp-ir-panel"):
                ir_code = gr.Code(label="", language="json", lines=18)

    gr.HTML('<div class="bp-section-title">recent generations</div>')
    history_html = gr.HTML(_history_strip_html([]))

    gr.HTML(_FOOTER_HTML)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    out_components = [preview, ir_code, svg_file, json_file, status, history_html, history_state]

    text_btn.click(
        fn=lambda *a: (_status_pill_html("working", "calling model..."), *([gr.update()] * 6)),
        inputs=None,
        outputs=[status, preview, ir_code, svg_file, json_file, history_html, history_state],
        queue=False,
    ).then(
        handle_text,
        inputs=[text_prompt, text_type, token, history_state],
        outputs=out_components,
    )

    img_btn.click(
        fn=lambda *a: (_status_pill_html("working", "vision model..."), *([gr.update()] * 6)),
        inputs=None,
        outputs=[status, preview, ir_code, svg_file, json_file, history_html, history_state],
        queue=False,
    ).then(
        handle_image,
        inputs=[img_input, img_notes, img_type, token, history_state],
        outputs=out_components,
    )

    gallery_btn.click(
        handle_example,
        inputs=[gallery_pick, history_state],
        outputs=out_components,
    )


if __name__ == "__main__":
    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
    )
