/**
 * course-visual-review.wf.js — OPTIONAL orchestration for the visual QA pass, on its own.
 *
 * Nothing in content-gen depends on this file. The pass is `references/visual-review.md`, driven by
 * `tools/render_visuals.py`; it runs by hand. This wrapper exists because the review half of
 * `course-visuals.wf.js` is the half that gets lost: it has no author phase and no final gate, so
 * there is no tail to lose when a long run dies. Use it to resume a course whose visuals are all
 * authored and rendered but whose per-lesson QA was cut short.
 *
 * Every path is a parameter or an environment lookup. Nothing here is machine-specific.
 *
 *   args: {
 *     course:  "/abs/path/to/content/courses/<id>"  REQUIRED — the emitted course tree
 *     lessons: ["m00-l1-m01-l1", ...]               REQUIRED — the asset dirs to review
 *     skill:   "/abs/path/to/skills/content-gen"    optional — else $CONTENT_GEN_SKILL
 *     brand:   "/abs/path/to/brand-guide.md"        optional — else $CONTENT_GEN_BRAND,
 *                                                   else <skill>/brand/brand-guide.md
 *   }
 *
 * Concurrency law (method/known-failure-modes.md §5): the per-lesson agents below re-render their
 * own lesson with --only, so they never collide. Do NOT run a course-wide render or review at the
 * same time — overlapping scopes race on the same per-asset intermediates and the loser reports a
 * bogus render error that re-renders clean in isolation.
 */

export const meta = {
  name: 'course-visual-review',
  description: 'Open the rendered PNGs lesson by lesson and fix what the renderer actually did — no author phase, no gate, so there is no tail to lose',
  whenToUse: 'A course whose visuals are all authored and rendered but whose per-lesson visual QA was cut short',
  phases: [{ title: 'Review', detail: 'one agent per lesson: open the images, fix the HTML, re-render, look again' }],
}

const A = typeof args === 'string' ? JSON.parse(args) : args
const ENV = (typeof process !== 'undefined' && process.env) || {}

const OUT = A && A.course
const lessons = A && A.lessons
if (!OUT || !Array.isArray(lessons) || !lessons.length) {
  throw new Error('bad args (need {course, lessons:[...]}); got: ' + JSON.stringify(args).slice(0, 300))
}

const SK = (A.skill || ENV.CONTENT_GEN_SKILL || '').replace(/\/$/, '')
if (!SK) throw new Error('no content-gen skill dir: pass args.skill or set $CONTENT_GEN_SKILL')
const BRAND = A.brand || ENV.CONTENT_GEN_BRAND || `${SK}/brand/brand-guide.md`
const ASSETS = `${OUT}/lessons/assets`
const COURSE_ID = OUT.split('/').filter(Boolean).pop()

log(`visual review: ${COURSE_ID} — ${lessons.length} lesson(s)`)

const REV = {
  type: 'object', required: ['lesson', 'ok', 'fixed'],
  properties: {
    lesson: { type: 'string' },
    ok: { type: 'boolean' },
    fixed: { type: 'array', items: { type: 'string' } },
    flagged: { type: 'array', items: { type: 'string' } },
  },
  additionalProperties: false,
}

phase('Review')
const reviewed = (await parallel(lessons.map(les => () => agent(
  `Visual QA for lesson "${les}" of "${COURSE_ID}". Read ${SK}/references/visual-review.md and apply it, and read ` +
  `${BRAND} so your repairs stay on-brand.\n\n` +
  `Every visual in ${ASSETS}/${les}/ is already authored and already rendered. Your job is NOT to re-author them — it is ` +
  `to LOOK AT THE RENDERED PNGs in that directory with the Read tool (actually open every image) and repair what the ` +
  `renderer did to them. Structural inspection of the HTML is not a substitute: the entire point of this pass is catching ` +
  `the delta between what the CSS said and what WeasyPrint produced.\n\n` +
  `Hunt the glitch family this pipeline produces repeatedly:\n` +
  `- a nested flex/grid row that WeasyPrint shrink-wrapped, collapsing bars or columns to content width\n` +
  `- text overflowing or clipped at a card edge; a label with white-space:nowrap running over its neighbour\n` +
  `- a title pushed off the top of the 1600x900 canvas, or content running past the bottom\n` +
  `- CSS-triangle arrowheads that did not render, or that landed detached from their connector\n` +
  `- the .stbr-decor blob sitting on top of text, or dark text sitting on the decor\n` +
  `- illegible contrast: yellow on cream, emerald on dark\n` +
  `- a bar chart whose drawn bar heights do not match its own printed numbers\n` +
  `- any row/node/series named in the spec comment that silently did not make it into the image\n\n` +
  `WeasyPrint-safe CSS only: NO box-shadow, NO background-image:url(), NO JavaScript, NO animation, NO display:contents. ` +
  `Make every grid/flex cell a real direct child. Do not edit the spec comment, the <head>, or the .stbr-decor block.\n\n` +
  `Fix what you find in the HTML, then re-render just this lesson with:\n` +
  `  python3 ${SK}/tools/render_visuals.py render ${OUT} --only ${les}\n` +
  `Then OPEN THE PNGs AGAIN and confirm the repair actually landed. Iterate until clean.\n\n` +
  `Honesty rule: if a spec's data cannot support the chart it asks for, keep the honest rendering (real values, no ` +
  `truncated axis, no invented data) and report it in flagged rather than faking the visual.\n\n` +
  `Return schema: lesson="${les}"; ok=(every image in the lesson is clean); fixed=one line per repair you actually made ` +
  `and verified in the re-rendered PNG; flagged=anything left that needs a human eye.`,
  { label: `review:${les}`, phase: 'Review', effort: 'high', schema: REV }
)))).filter(Boolean)

return {
  course: OUT,
  courseId: COURSE_ID,
  reviewed: reviewed.length + '/' + lessons.length,
  ok: reviewed.filter(r => r.ok).length + '/' + reviewed.length,
  not_ok: reviewed.filter(r => !r.ok).map(r => r.lesson),
  fixed: reviewed.flatMap(r => (r.fixed || []).map(f => `${r.lesson}: ${f}`)),
  flagged: reviewed.flatMap(r => (r.flagged || []).map(f => `${r.lesson}: ${f}`)),
}
