# Contributing

Thanks for poking around. This project is small on purpose: one IR, one
renderer, one Gradio app. Keep PRs focused.

## Dev setup

```bash
git clone https://github.com/DanielRegaladoUMiami/blueprint.svg.git
cd blueprint.svg

# system dep
brew install graphviz                # macOS
sudo apt-get install graphviz        # Debian/Ubuntu

# Python
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[app,dev]"

# Sanity check (no LLM call)
pytest -q
python app.py    # opens http://localhost:7860
```

## Adding a diagram type

1. Add the type literal to `DiagramType` in `src/blueprint_svg/ir.py`.
2. Pick (or add) the shapes you need to `NodeShape` and implement them
   in `renderer._shape_svg`.
3. Decide layout. Either:
   - reuse Graphviz by adding entries in `layout._DEFAULT_ALGO_BY_TYPE` /
     `_DEFAULT_RANKDIR_BY_TYPE`, **or**
   - write a custom backend like `_layout_sequence` if Graphviz can't
     express the layout (lifelines, swimlanes with explicit lanes, etc.).
4. Add a high-quality `examples/<type>_<topic>.json`. This file is both
   the showcase in the Gallery tab and the few-shot exemplar for the LLM.
5. Update `docs/ir-spec.md` shape table and `prompts.SYSTEM_PROMPT` shape
   guidance.
6. Add a `tests/test_renderer.py` parametrized case if the type needs
   special assertions (e.g. the sequence test asserts column alignment).

## Adding a shape

1. Extend `NodeShape` in `ir.py`.
2. Add a branch in `renderer._shape_svg` returning the SVG markup. Use
   `class="bp-node-bg"` so the role-based fill/stroke selectors apply.
3. Add a test case that renders a node with the new shape.

## Adding a theme

Themes are just `Theme.tokens` dicts. To ship a built-in:

1. Add a constant dict in `ir.py` (e.g. `OCEAN_THEME = {...}`).
2. Expose it from `blueprint_svg/__init__.py`.
3. Document it in `README.md` under "Retheming".

If you want runtime theme switching in the UI, add a Gradio dropdown in
`app.py` that overrides `diagram.theme` before calling `render_svg`.

## Code style

- Type hints everywhere. `from __future__ import annotations` at the top.
- `ruff` config lives in `pyproject.toml` (`line-length = 100`).
- Tests run on the in-repo source (`PYTHONPATH=src pytest`).

## Roadmap ideas (good first issues)

- **Icons in nodes.** Wire Iconify icon names into `Node.icon` and embed
  inline SVG in `_render_one_node`.
- **PNG/PDF export.** `cairosvg` can rasterize. Add a download dropdown.
- **Theme picker.** Three built-in palettes + a custom-hex form.
- **IR diff tool.** Given two IR JSONs, render a side-by-side SVG
  highlighting added/removed nodes — useful for "diagram-as-code" PRs.
- **Fine-tuning dataset.** Scrape Mermaid/D2 corpora, transcribe to IR,
  fine-tune a 7B model to replace Qwen-72B for cheap inference.
