# Architecture

This document walks the request from user input to final SVG.

## High-level pipeline

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ User input   │ ───▶ │   LLM        │ ───▶ │   Layout     │ ───▶ │  Renderer    │
│ (text|image) │      │   (Qwen)     │      │  (Graphviz)  │      │  (Python)    │
└──────────────┘      └──────────────┘      └──────────────┘      └──────────────┘
        │                    │                     │                     │
        │                    ▼                     ▼                     ▼
        │             IR JSON object        positions per node     SVG string with
        │             (validated by         + edge splines         semantic <g id>s
        │              pydantic)                                   and CSS vars
        ▼
   Gradio UI also accepts an IR JSON directly (the Gallery tab),
   skipping the LLM entirely. Useful for cost-free demos and tests.
```

## Stage 1 — Input

Two entry points, both end up calling the same LLM client:

- **Text tab** → `blueprint_svg.llm.generate_from_text(prompt, diagram_type)`.
- **Image tab** → `blueprint_svg.llm.generate_from_image(image_bytes, diagram_type, prompt)`.

The image path base64-encodes the upload into a `data:image/png;base64,...`
URL and packs it into a multimodal `chat.completions` message.

## Stage 2 — Prompt construction

`blueprint_svg.prompts.build_messages` returns a `messages` list:

1. **System** — pins the contract: "you produce one JSON object that matches
   this schema, no prose, no code fences". The pydantic-generated JSON
   Schema is appended inline so the model has it in-context.
2. **Few-shot pair** — the single example from `examples/` whose `type`
   matches the request. The user turn is the *headline* of the example;
   the assistant turn is the example JSON verbatim.
3. **User turn** — the actual request, plus the image attachment if any.

Why only one few-shot? Because the schema + a single high-quality example
is what moves the needle. More examples burn context for diminishing
returns on a 72B model. Tune this in `prompts.SYSTEM_PROMPT` and the
`examples/` directory.

## Stage 3 — Parsing

The model still occasionally wraps in ```` ```json ```` or prefixes prose.
`llm._parse_diagram` is defensive:

1. Strip Markdown code fences.
2. If output doesn't start with `{`, slice from the first `{` to the last `}`.
3. `json.loads` → `Diagram.model_validate` → `validate_refs()`
   (edges/groups must point to existing node ids).

Any failure raises `LLMError`, which Gradio surfaces as a red banner.

## Stage 4 — Layout

`blueprint_svg.layout.layout_diagram` dispatches by `diagram.type`:

- `architecture | flowchart | er | mindmap` → shell out to the `dot`
  binary with `-Tjson`. We parse the returned bounding boxes and edge
  splines. (No `pygraphviz`: cheaper to depend on the binary and skip a
  C extension that's painful on macOS.)
- `sequence` → custom layout. Graphviz can't represent lifelines as
  vertical columns with horizontally-stacked messages, so we lay out
  actors as columns and edges as rows in `_layout_sequence`.

Graphviz works in points with **y-up**. The parser flips y to **y-down**
so the rest of the codebase can think in screen-space.

## Stage 5 — Rendering

`blueprint_svg.renderer.render_svg` walks the IR + layout and emits SVG:

- `<style>` block declares one CSS variable per theme token
  (`--bp-primary`, `--bp-bg`, ...). Role-based selectors map node roles
  to colors through `color-mix(in srgb, var(--bp-<role>) 12%, white)` —
  the soft tinted fill is what makes it look like a real diagram, not
  a flat blob.
- Each node becomes a `<g id="{node.id}" data-role="..." data-shape="...">`.
  The id is the semantic slug from the IR, so consumers can grab
  individual elements without parsing.
- Edges become `<g id="edge-{src}-{tgt}">` with a `<path>` and optional
  label `<text>`. Arrowheads are a shared `<marker>` in `<defs>`.
- Groups become rounded dashed rectangles under a separate
  `<g id="groups">` z-layer so they sit *below* nodes/edges.

The output is plain SVG 1.1 — no JS, no foreignObject, no exotic
features — so it works in browsers, Figma's SVG import, Inkscape, and
PDF renderers.

## Why this design

The whole project is built around the bet that **structure + a small
deterministic renderer beats a smarter end-to-end model** for diagrams,
because the diagram is intrinsically structural. The LLM's hard job is
"what's in the diagram"; the easy-but-tedious job is "how do I lay it
out and stroke it cleanly", and that's exactly what Graphviz and 300
lines of Python do well. Trying to push the renderer into the model
loses you semantic ids, layout consistency, and themability — and gains
you nothing in return.
