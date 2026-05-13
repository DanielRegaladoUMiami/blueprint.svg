# Prompting strategy

## What the LLM sees

For every request, `blueprint_svg.prompts.build_messages` constructs:

```
[system]   ← SYSTEM_PROMPT + the IR JSON schema (from pydantic)
[user]     ← "Example request — type=architecture: 'Three-tier web app'."
[assist.]  ← <the matching examples/*.json verbatim>
[user]     ← "Now produce a Diagram of type='architecture' for ..." + image (if any)
```

Total prompt size is roughly:
- system: ~1.5 KB (instructions) + ~6 KB (JSON schema)
- few-shot: ~1–2 KB per example
- user request: variable

That fits comfortably in any modern context window and keeps inference
costs low.

## Why few-shot instead of fine-tuning

Fine-tuning a diagram-producing model is the *right* answer for v2 (see
`docs/contributing.md` for the dataset proposal), but for a weekend MVP:

- A 72B instruct model with one well-chosen few-shot hits ~90% schema
  compliance on the five supported diagram types.
- The remaining ~10% is recovered by `llm._parse_diagram`'s defensive
  parsing (fence stripping, JSON object extraction).
- You can change the system prompt or examples and ship in minutes, not
  in a training run.

## Choosing few-shot examples

The examples in `examples/` are deliberately:

- **Short** (5–15 nodes). Long examples make the model verbose.
- **Diverse in roles**. They show `primary`/`secondary`/`accent`/`danger`/`muted` mixed naturally, so the model learns role *meaning* (failure path = danger, external = muted), not just role *names*.
- **Idiomatic for the type**. Architecture uses cylinders for DBs and clouds for SaaS. Flowcharts use diamonds for decisions. The model picks up the shape vocabulary by mimicry.

When adding a new diagram type, drop the new example in `examples/`
named `<type>_<topic>.json`. `_load_example` finds it by `type` field
automatically.

## Failure modes and what they look like

| Symptom | Likely cause | Fix |
|---|---|---|
| `LLMError: Model output was not valid JSON` | Model wrapped in prose or extra fences. | Already handled in `_parse_diagram`. If still failing, lower `temperature` (it's `0.2` by default). |
| `Edge target 'foo' not in nodes` | Model invented a node id in an edge. | Improve the prompt: emphasize "every edge.source and edge.target MUST be one of the node.id values you listed above". |
| Diagrams look cramped | `layout.nodesep` / `ranksep` too small for the dataset. | Raise the defaults in `ir.LayoutHints`. |
| Image tab returns vaguely-related diagram | Vision model didn't capture detail. | Switch `BP_VISION_MODEL` to a stronger model, or add to the image notes textbox. |

## Lowering token usage

- The JSON schema is the biggest chunk of the system prompt. If you only
  ever generate one type, you can hand-trim a sub-schema for that type
  and inject it instead.
- The few-shot example is loaded by reading the matching JSON from disk.
  Trim labels/descriptions in `examples/` to shrink the prompt.
- Set `max_tokens` in `llm._chat` based on observed output sizes (2048 is
  generous for diagrams up to ~20 nodes).
