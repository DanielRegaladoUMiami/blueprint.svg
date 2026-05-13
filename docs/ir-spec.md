# IR Specification

The Intermediate Representation is a single JSON object that validates
against the `Diagram` pydantic model in `src/blueprint_svg/ir.py`. The
LLM emits exactly one of these per request; the renderer consumes them.

This page is the human-readable reference. The authoritative source is
the schema itself: run `python -c "from blueprint_svg.ir import Diagram; \
import json; print(json.dumps(Diagram.model_json_schema(), indent=2))"`.

## Top-level: `Diagram`

| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | `"architecture" \| "flowchart" \| "er" \| "sequence" \| "mindmap"` | yes | Drives layout dispatch and shape vocabulary. |
| `title` | string | no | Used as `<title>` in the SVG and the IR's display name. |
| `description` | string | no | Used as `<desc>` (ARIA). |
| `nodes` | `Node[]` | yes | Must have unique ids. |
| `edges` | `Edge[]` | no | Must reference existing node ids. |
| `groups` | `Group[]` | no | Logical clusters; members must exist. |
| `theme` | `Theme` | no | Defaults to the built-in indigo/sky palette. |
| `layout` | `LayoutHints` | no | Override default `algo`/`rankdir`. |

## `Node`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | slug (`[a-zA-Z0-9_-]+`) | yes | Becomes the `<g id="...">` in the SVG. Use semantic names like `auth-service`, not `n1`. |
| `label` | string | yes | Visible text. Wrapped to ~20 chars. |
| `shape` | enum (see below) | no, default `"box"` | Visual primitive. |
| `role` | `StyleRole` | no, default `"primary"` | Semantic style class; maps to CSS variable. |
| `group` | string | no | Optional reference to a `Group.id`. |
| `note` | string | no | Optional `<desc>` text on the node element (ARIA). |

### Shape vocabulary

| Shape | Used by | Looks like |
|---|---|---|
| `box` | architecture, flowchart | sharp rectangle |
| `rounded` | architecture (services), flowchart (start/end) | rounded rectangle |
| `ellipse` | misc | ellipse |
| `diamond` | flowchart (decisions) | diamond |
| `cylinder` | architecture (databases) | DB cylinder |
| `cloud` | architecture (external/SaaS) | cloud blob |
| `note` | annotations | folded-corner note |
| `entity` | er | rounded entity box |
| `actor` | sequence | head + body figure |
| `lifeline` | sequence | tall thin column |
| `root` / `branch` / `leaf` | mindmap | rounded pills with size hints |

## `Edge`

| Field | Type | Required | Notes |
|---|---|---|---|
| `source` | string | yes | Node id. |
| `target` | string | yes | Node id. |
| `label` | string | no | Optional edge label, drawn near the midpoint. |
| `style` | `"solid" \| "dashed" \| "dotted"` | no, default `"solid"` | |
| `arrow` | `"none" \| "arrow" \| "both"` | no, default `"arrow"` | |
| `role` | `StyleRole` | no, default `"neutral"` | For colored edges (e.g. failure paths). |

## `Group`

A logical cluster (VPC, subsystem, swimlane). Rendered as a soft dashed
rectangle behind its members with a top-left label.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Becomes `<g id="group-...">`. |
| `label` | string | yes | |
| `members` | string[] | yes | Node ids inside this group. |
| `role` | `StyleRole` | no, default `"muted"` | |

## `Theme`

| Field | Type | Notes |
|---|---|---|
| `name` | string | Free-form name; not used by the renderer. |
| `tokens` | `{string: string}` | Maps role → CSS color. Becomes `--bp-<role>` variables. |

Default tokens: `primary`, `secondary`, `accent`, `danger`, `muted`,
`neutral`, `bg`, `fg`, `edge`, `group-bg`, `group-stroke`.

## `LayoutHints`

| Field | Type | Notes |
|---|---|---|
| `algo` | `"dot" \| "neato" \| "twopi" \| "circo" \| "fdp" \| "sequence"` | Override layout engine. |
| `rankdir` | `"TB" \| "LR" \| "BT" \| "RL"` | For `dot`. |
| `nodesep` | float | Graphviz `nodesep` (inches). |
| `ranksep` | float | Graphviz `ranksep` (inches). |

## Worked example

```json
{
  "type": "architecture",
  "title": "Minimal API",
  "nodes": [
    { "id": "client", "label": "Mobile app", "shape": "rounded", "role": "muted" },
    { "id": "api",    "label": "REST API",   "shape": "box",     "role": "primary" },
    { "id": "db",     "label": "Postgres",   "shape": "cylinder","role": "accent" }
  ],
  "edges": [
    { "source": "client", "target": "api",  "label": "HTTPS" },
    { "source": "api",    "target": "db",   "label": "SQL" }
  ]
}
```

After rendering you get an SVG with `<g id="client">`, `<g id="api">`,
`<g id="db">`, and `<g id="edge-client-api">`, `<g id="edge-api-db">`,
each addressable by CSS selector or DOM query.
