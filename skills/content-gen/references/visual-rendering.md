# Rendering a `visual` spec into an on-brand image

The writing pipeline leaves ` ```visual ` specs (type/title/purpose/data/prompt/alt).
The **render pass** turns each into an on-brand PNG the Claude-Design way: author HTML/CSS,
render it through WeasyPrint. Load `../brand/brand-guide.md` (tokens + palette) alongside this.

## The loop
1. `render_visuals.py extract <course>` — the work-list of every `visual` block.
2. `render_visuals.py scaffold <course>` — writes one brand-linked starter `lessons/assets/<lesson>/v<NN>-<type>.html` per block (canvas 1600×900, links `_brand.css`, the spec inlined as a comment).
3. **You author each `.viz`.** Open the starter, replace `<!-- TODO(render) -->` with real on-brand HTML that renders the spec's `data`. This is the creative step.
4. `render_visuals.py render <course>` — WeasyPrint → PDF → PNG (deterministic, no browser). `check` reports coverage.

## Two rules
- **`data` + `prompt` drive CONTENT; the brand drives STYLE.** Render exactly the nodes/rows/series the `data` names, in the structure the `prompt` describes. Ignore any styling words in an old `prompt` ("dark background, monospace, no icons") — those predate the brand; the look comes from the tokens, not the prompt.
- **WeasyPrint-safe CSS only.** OK: flexbox, grid, absolute positioning, borders, `border-radius`, `linear/radial-gradient`, `@font-face`, 2D transforms, inline `<svg>`. NOT OK (silently dropped or breaks reproducibility): `box-shadow`, `font-stretch`, `background-image: url()`, JavaScript, animation, and **`display:contents`** (WeasyPrint ignores it, so a grid/flex child that relies on it lands in the wrong place — collapsed cells, a title pushed off the top). Make every grid/flex cell a real direct child instead. Separate elements with borders / tint fills / full-bleed fields, never shadow.

## House style (every visual)
- Sits on the cream page; the content lives in a white card (`--surface-card`, `--radius-2xl`) OR a full-bleed emerald/dark field for a punchier one. Generous padding (`--space-7/8`).
- Lead with a short **eyebrow** (`class="stbr-eyebrow"`, the spec's one-line purpose or a 2-4 word tag) then the **title** as an Archivo heading (`<h2>`/`<h3>`, `--weight-black` for display weight since width is unavailable).
- **Emerald is the hero, yellow is the accent** — colour the ONE thing that matters yellow (the drop point, the winner, the highlighted bar); everything else greens/ink on white. Never yellow text on cream, never emerald text on dark.
- Optional: one morph blob bleeding off a corner as decoration — a sized `<div>` with an organic `border-radius` (e.g. `border-radius:47% 53% 44% 56% / 58% 42% 58% 42%`) filled `--stbr-yellow`/`--stbr-emerald`, `position:absolute`, partly off-canvas, `overflow:hidden` on the card. Never on top of text. Skip it if the diagram is dense.
- Text: Inter for labels/body, dark on light. Keep it legible at a glance; a diagram is not a paragraph.

## Connectors & arrows (WeasyPrint-safe)
Use **inline `<svg>`** for arrows/lines (a `<line>`/`<path>` in `--stbr-dark` or `--stbr-emerald`, ~2px, with a small triangle `<polygon>` arrowhead), OR CSS: a thin `<div>` line + a `::after` triangle via `border`. Label an arrow with a small Inter chip beside it. For a grid of nodes, place nodes with flex/grid and draw the connectors in one absolutely-positioned full-size `<svg>` layer behind them.

## Per type
- **flowchart** — nodes as white rounded boxes (dark title + optional Inter sub-line), left-to-right or top-down, arrows between. Mark the failure/drop node in yellow. One idea per node.
- **diagram** (architecture / dataflow) — component boxes + labeled connectors; if there's a "foundation" (a node the others sit on), make it a wide emerald/dark bar with cream type; others are white cards above it.
- **chart** — CSS bars/columns (`<div>` heights proportional to the real numbers — never fake them), emerald fill, the highlighted series/bar in yellow; Inter axis + value labels; a one-line caption.
- **table** — designed data table: header row `--surface-inverse` (or emerald) with cream type, body rows on white with `--border-subtle` dividers, alternating `--surface-paper` optional; shade the key row/cell faint yellow.
- **comparison** — 2–3 column cards side by side, a column header each, aligned attribute rows; a full-width **verdict band** at the bottom in emerald with cream type stating the takeaway.
- **annotated-code** — a dark code panel (`--surface-inverse`, `--font-mono`, cream text) with the snippet; call-outs in emerald/yellow chips pointing at the line that matters (an inline `<svg>` connector or an offset label).
- **timeline** — a horizontal rule with dot nodes, labels alternating above/below, dates/steps in Inter; the emphasized span drawn as a thicker emerald or yellow segment.

## Fidelity check before render
Every node/row/series in `data` appears; the one accent is the spec's actual point; contrast is legible; nothing relies on shadow; no `background-image`. Then `render`.

## Fit & safety (avoid the common render glitches)
- **Never put a mixed text run directly inside a flex container.** If an element is `display:flex`, every run of text between its children becomes an *anonymous flex item*, and the flexbox spec discards whitespace BETWEEN items. So `.cell { display:flex }` wrapped around `in a separate <b>ProgramData</b> account` renders `in a separateProgramDataaccount` — both spaces gone. This is correct CSS, not a WeasyPrint bug; browsers do it too, which is why it survives a browser spot-check. It shipped in 35 elements across 17 files in five courses before anyone traced it, and an audit misfiled it as a renderer defect. **Fix:** wrap the content in a single `<span>` so the container has exactly one flex item. Do not "fix" it by switching to `display:block` if the container relies on `align-items:center` inside a stretched row — you will lose the centring. The same trap applies to `display:grid`.
- **A stacked badge inside a flex row does not stack.** `display:inline-block; margin-top:8px` on a child of a `display:flex` row makes it a sibling flex item, so it sits beside its label rather than under it and the margin does nothing. If you want it under, the parent needs `flex-direction:column` (plus `align-items:flex-start`), or the label and badge both need to live inside one wrapped child.

WeasyPrint lays out flex / absolute / text differently than you assume — most glitches come from that gap. Build to these rules, then **render and actually LOOK** (structural checks are not enough; a fresh review pass follows — see `visual-review.md`):
- **Fit ONE page.** The whole visual must fit the 1600×900 canvas — content is centred in `.viz` with 72px padding, so keep it inside ~1456×756. If a card spans a 2nd page, `render` FAILS it. Cut content or shrink type; never overflow.
- **Keep off the edges.** Never full-bleed a row/box to `x=0`/`x=1600` or the top/bottom edge — leave margin. The ONLY thing that touches the canvas edges is the corner/border decoration (added behind content).
- **No overlap.** Separate boxes with flex/grid `gap` or explicit spacing — never let two panels sit on top of each other, and don't absolutely-position a panel over another. Size rows to their content so nothing collides.
- **Contain your chips.** Annotation chips, pills, and labels must fit inside their parent — give it enough width/height/padding; don't let a chip spill past the box edge.
- **Anchor connectors.** An arrow/line must start and end ON the nodes it connects. Prefer laying nodes out with flex/grid and drawing short connectors between adjacent nodes; use one absolute full-size `<svg>` layer only when you compute endpoints from the real node positions. A line pointing at empty space is a glitch.
- **Headings fit their box.** Give a heading its own line/height; a large title in a small panel overruns the body beneath it — reserve the space or shrink the heading.
- **Distrust WeasyPrint's flex/grid sizing.** It sizes items differently than a browser and causes most glitches: a flex/grid row often stretches *taller* than its content (four "230px" rows silently blow past the 756px budget → 2-page overflow), and vertical centering can hide that clipping from your eye but not from the page-count check. Size rows to their content (compact fixed heights, not `1fr` stretch), give paired columns equal explicit box heights so their steps align, and re-render + LOOK after any flex/grid change.
- **An inline `<svg>` connector layer needs explicit `width` + `height`**, not just a `viewBox` — without them WeasyPrint collapses it to a tiny artifact (a stray glyph in a corner) and none of your lines draw. Size the SVG to the node area and compute endpoints in that coordinate space so arrows land on real nodes.
