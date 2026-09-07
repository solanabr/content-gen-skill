/**
 * course-visuals.wf.js — OPTIONAL orchestration for the visual authoring + render + QA pass.
 *
 * Nothing in content-gen depends on this file. The pass itself is
 * `references/visual-rendering.md` (author) and `references/visual-review.md` (QA), driven by
 * `tools/render_visuals.py`; both run by hand. This is a convenience wrapper for runners that
 * expose `agent()`, `parallel()`, `phase()` and `log()`.
 *
 * Every path is a parameter or an environment lookup. Nothing here is machine-specific.
 *
 *   args: {
 *     course: "/abs/path/to/content/courses/<id>"  REQUIRED — the emitted course tree
 *     skill:  "/abs/path/to/skills/content-gen"    optional — else $CONTENT_GEN_SKILL
 *     brand:  "/abs/path/to/brand-guide.md"        optional — else $CONTENT_GEN_BRAND,
 *                                                  else <skill>/brand/brand-guide.md
 *   }
 *
 * Concurrency law (method/known-failure-modes.md §5): never run this while a separate course-wide
 * render or review is live. Both write per-asset intermediates, so overlapping scopes race and the
 * loser reports a bogus render error. Disjoint lessons never collide.
 */

export const meta = {
  name: 'course-visuals',
  description: 'Author every scaffolded visual as on-brand HTML, render it, then LOOK at the PNGs and fix what the renderer actually did',
  whenToUse: 'A course whose drafts are written and boarded: assets/ is scaffolded but the cards still say TODO(render)',
  phases: [
    { title: 'Author', detail: "one agent per lesson fills that lesson's v*.html from its inlined spec" },
    { title: 'Render', detail: 'render the whole course to PNG' },
    { title: 'Review', detail: 'per-lesson visual QA: open the PNGs and judge them as images' },
    { title: 'Fix', detail: 'repair what review caught, re-render' },
    { title: 'Check', detail: 'coverage + a final course-wide look' },
  ],
}

const A = typeof args === 'string' ? JSON.parse(args) : args
const ENV = (typeof process !== 'undefined' && process.env) || {}

const OUT = A && A.course
if (!OUT) throw new Error('bad args (need {course, ...}); got: ' + JSON.stringify(args).slice(0, 200))

const SK = (A.skill || ENV.CONTENT_GEN_SKILL || '').replace(/\/$/, '')
if (!SK) throw new Error('no content-gen skill dir: pass args.skill or set $CONTENT_GEN_SKILL')
const BRAND = A.brand || ENV.CONTENT_GEN_BRAND || `${SK}/brand/brand-guide.md`
const ASSETS = `${OUT}/lessons/assets`
const COURSE_ID = OUT.split('/').filter(Boolean).pop()

log(`visuals: ${COURSE_ID}`)

// Read the work-list from disk deterministically — never from an agent's prose return.
const listing = await agent(
  `Run EXACTLY this and return ONLY its stdout, no prose and no code fences:\n` +
  `python3 - <<'EOF'\n` +
  `import os, json, glob\n` +
  `A = '${ASSETS}'\n` +
  `out = {}\n` +
  `for d in sorted(os.listdir(A)):\n` +
  `    p = os.path.join(A, d)\n` +
  `    if not os.path.isdir(p): continue\n` +
  `    todo = [os.path.basename(f) for f in sorted(glob.glob(p + '/v*.html'))\n` +
  `            if 'TODO(render)' in open(f, encoding='utf-8').read()]\n` +
  `    if todo: out[d] = todo\n` +
  `print(json.dumps(out))\n` +
  `EOF`,
  { label: 'work-list', phase: 'Author', effort: 'low' }
)
const work = JSON.parse((listing || '{}').match(/\{[\s\S]*\}/)?.[0] || '{}')
const lessons = Object.keys(work)
const total = lessons.reduce((n, k) => n + work[k].length, 0)
log(`${total} unauthored visual(s) across ${lessons.length} lesson(s)`)
if (!total) return { course: OUT, authored: 0, note: 'nothing to author' }

const HOUSE =
  `Read ${SK}/references/visual-rendering.md FIRST and follow it exactly, plus ${BRAND} for tokens.\n` +
  `Non-negotiables: WeasyPrint-safe CSS only — NO box-shadow, NO background-image:url(), NO JavaScript, NO animation, ` +
  `and NO display:contents (WeasyPrint ignores it, so make every grid/flex cell a real direct child). ` +
  `Emerald is the hero and yellow is the accent: colour the ONE thing the spec is actually about in yellow, everything ` +
  `else greens/ink on white. Never yellow text on cream, never emerald text on dark. ` +
  `Lead with <div class="stbr-eyebrow"> then an <h2 class="viz-title">. Leave the .stbr-decor block EXACTLY as scaffolded — ` +
  `it is per-asset brand decoration, and never let it sit on top of text.\n` +
  `CONTENT comes from the spec's data + prompt; STYLE comes from the brand. Render every node/row/series the data names. ` +
  `Ignore styling words in the prompt ("dark background", "monospace", "no icons") — those predate the brand.`

const AUTH = {
  type: 'object', required: ['lesson', 'authored', 'notes'],
  properties: {
    lesson: { type: 'string' },
    authored: { type: 'integer' },
    notes: { type: 'string' },
    flagged: { type: 'array', items: { type: 'string' } },
  },
  additionalProperties: false,
}

phase('Author')
const authored = (await parallel(lessons.map(les => () => agent(
  `Author every unfinished visual for lesson "${les}" of course "${COURSE_ID}".\n` +
  `Files (in ${ASSETS}/${les}/): ${work[les].join(', ')}.\n` +
  `Each file is a 1600x900 scaffold whose spec (type/title/purpose/data/prompt) is inlined as an HTML comment near the top. ` +
  `Replace the "<!-- TODO(render): build this visual -->" placeholder with real on-brand HTML that renders THAT spec. ` +
  `Do not edit the comment, the <head>, or the .stbr-decor block.\n\n${HOUSE}\n\n` +
  `A diagram is not a paragraph: it must read at a glance. If the spec's data is too thin to justify the type it asks ` +
  `for, build the closest honest thing and say so in flagged rather than inventing data that is not in the spec.\n` +
  `Return schema: lesson="${les}"; authored=count of files you finished; notes=one line on the approach; ` +
  `flagged=specs you could not render faithfully, with the reason.`,
  { label: `author:${les}`, phase: 'Author', effort: 'high', schema: AUTH }
))))

const okAuthored = authored.filter(Boolean)
log(`authored ${okAuthored.reduce((n, r) => n + (r.authored || 0), 0)}/${total}`)

phase('Render')
const rendered = await agent(
  `Render the visuals for course "${COURSE_ID}".\n` +
  `1. Run: python3 ${SK}/tools/render_visuals.py render ${OUT}\n` +
  `2. Then: python3 ${SK}/tools/render_visuals.py check ${OUT}\n` +
  `If render reports failures, open the offending HTML, fix the WeasyPrint-unsafe construct (the usual causes are ` +
  `box-shadow, background-image:url(), display:contents, or an unclosed tag) and re-run until it is clean.\n` +
  `Return the final check line verbatim plus any file you had to repair.`,
  { label: 'render', phase: 'Render', effort: 'medium' }
)

phase('Review')
const REV = {
  type: 'object', required: ['lesson', 'ok', 'fixed'],
  properties: {
    lesson: { type: 'string' }, ok: { type: 'boolean' },
    fixed: { type: 'array', items: { type: 'string' } },
    flagged: { type: 'array', items: { type: 'string' } },
  },
  additionalProperties: false,
}
const reviewed = (await parallel(lessons.map(les => () => agent(
  `Visual QA for lesson "${les}" of "${COURSE_ID}". Read ${SK}/references/visual-review.md and apply it.\n` +
  `LOOK AT THE RENDERED PNGs in ${ASSETS}/${les}/ with the Read tool — actually open the images. Structural checks on ` +
  `the HTML are not enough; the whole point of this pass is catching what WeasyPrint DID, not what the CSS said.\n` +
  `Hunt the known glitch family: text overflowing or clipped at a card edge, a title pushed off the top, collapsed or ` +
  `mis-placed grid cells, overlapping absolute elements, decoration sitting on top of text, illegible contrast ` +
  `(yellow on cream, emerald on dark), a bar chart whose bar heights do not match its numbers, and any spec row/node ` +
  `that silently did not make it into the image.\n` +
  `Fix what you find in the HTML and re-render just that lesson with: ` +
  `python3 ${SK}/tools/render_visuals.py render ${OUT} --only ${les}\n` +
  `Then look again. Return schema: lesson="${les}"; ok=(every image is clean); fixed=what you repaired; flagged=anything ` +
  `left that needs a human.`,
  { label: `review:${les}`, phase: 'Review', effort: 'high', schema: REV }
)))).filter(Boolean)

phase('Check')
const gate = await agent(
  `Final visual gate for "${COURSE_ID}".\n` +
  `1. python3 ${SK}/tools/render_visuals.py check ${OUT} — every visual must be rendered.\n` +
  `2. python3 ${SK}/tools/validate_course.py all --course ${OUT} and ` +
  `python3 ${SK}/tools/validate_course.py drafts --course ${OUT} — both must stay GATE: PASS.\n` +
  `3. Spot-check by OPENING six rendered PNGs from different lessons and confirm they read at a glance.\n` +
  `Return the check line, both gate lines, and a one-paragraph verdict on whether the visual layer is ship-ready.`,
  { label: 'gate', phase: 'Check', effort: 'high' }
)

return {
  course: OUT,
  courseId: COURSE_ID,
  visuals: total,
  authored: okAuthored.reduce((n, r) => n + (r.authored || 0), 0),
  review_ok: reviewed.filter(r => r.ok).length + '/' + lessons.length,
  flagged: okAuthored.flatMap(r => r.flagged || []).concat(reviewed.flatMap(r => r.flagged || [])),
  render: rendered,
  gate,
}
