/**
 * course-boards.wf.js — OPTIONAL orchestration for the four-board review.
 *
 * Nothing in content-gen depends on this file. The protocol is `method/review-boards.md`; it runs
 * by hand and under any parallel-agent orchestrator. This is a convenience wrapper for runners that
 * expose `agent()`, `parallel()`, `phase()` and `log()`, and it is deliberately thin: the prompts
 * below are the asset, the plumbing is not.
 *
 * Every path is a parameter or an environment lookup. Nothing here is machine-specific.
 *
 *   args: {
 *     course:      "/abs/path/to/content/courses/<id>"   REQUIRED — the emitted course tree
 *     tone:        "backbone 0.7 / guest 0.3"            REQUIRED — the course tone override
 *     skill:       "/abs/path/to/skills/content-gen"     optional — else $CONTENT_GEN_SKILL
 *     writerStyle: "/abs/path/to/skills/writer-style"    optional — else $WRITER_STYLE_SKILL;
 *                                                        absent = the voice-validator step is skipped
 *     design:      "/abs/path/to/<course-design-dir>"    optional — outline / decision log / research
 *     batch:       "/abs/path/to/<batch-dir>"            optional — batch constants + boundary doc
 *     probes:      "..."                                 optional — this batch's write-time probes
 *     notes:       "..."                                 optional — write-phase carry-over notes
 *     today:       "YYYY-MM-DD"                          optional — defaults to the run date
 *     voiceCard:   "/abs/path/to/<voice>.card.yaml"      optional — writer-style profile card
 *   }
 */

export const meta = {
  name: 'course-boards',
  description: 'Four-board review for one written course: A facts+code (incl. the container compile gate) → B pedagogy → C rhetoric/voice/quiz → D cold read (findings) → fix → final gate + boards-report.md',
  whenToUse: 'A course whose drafts are fully written and write-verified, before render/export/PR',
  phases: [
    { title: 'Plan', detail: 'stems by module + course-wide quiz/em-dash stats, read from disk' },
    { title: 'BoardA', detail: 'facts + code per module, then the container compile gate' },
    { title: 'BoardB', detail: 'pedagogy per module' },
    { title: 'BoardC', detail: 'voice, quiz-label rebalance, yaml em-dashes, dialect + alt sweep' },
    { title: 'BoardD', detail: 'cold-read findings (no edits) + course-meta coherence' },
    { title: 'Fix', detail: 'apply Board D findings' },
    { title: 'Gate', detail: 'validate_course all+drafts, write boards-report.md' },
  ],
}

const A = typeof args === 'string' ? JSON.parse(args) : args
const ENV = (typeof process !== 'undefined' && process.env) || {}

const OUT = A && A.course
const TONE = A && A.tone
if (!OUT || !TONE) {
  throw new Error('bad args (need {course, tone, ...}); got: ' + JSON.stringify(args).slice(0, 300))
}

const SK = (A.skill || ENV.CONTENT_GEN_SKILL || '').replace(/\/$/, '')
if (!SK) throw new Error('no content-gen skill dir: pass args.skill or set $CONTENT_GEN_SKILL')
const WS = (A.writerStyle || ENV.WRITER_STYLE_SKILL || '').replace(/\/$/, '')
const DESIGN = (A.design || OUT).replace(/\/$/, '')
const BATCH = (A.batch || '').replace(/\/$/, '')
const NOTES = A.notes || 'none'
const TODAY = A.today || new Date().toISOString().slice(0, 10)
const COURSE_ID = OUT.split('/').filter(Boolean).pop()
const CARD = A.voiceCard || ''

// Write-time probes are per batch: values deliberately NOT frozen, which Board A re-verifies LIVE.
// Default to the standing categories (method/known-failure-modes.md §8) when the batch did not list its own.
const PROBES = A.probes || (
  'the categories that are never frozen: rollout quarters for unshipped upgrades; network capacity ' +
  'ceilings (teach the ratio, re-probe the number); package dist-tags and "latest" versions; supply ' +
  'and TVL figures; rate and stream limits; feature-gate activation status; proposal/SIMD status'
)

log(`boards: ${COURSE_ID}`)

// Stems are "<mNN>-<lN>-<lesson-id...>"; group by the POSITIONAL module prefix, the only part every
// course shares (a trailing slug is course-specific — method/known-failure-modes.md §7).
const modKey = (stem) => stem.split('-')[0]

const PATTERN_RULE = `SYSTEMIC PATTERNS: if you spot a defect pattern that plausibly repeats beyond your module (a repeated wrong phrase, a template artifact, a uniform tic), name it precisely in your return under flagged (prefix "SYSTEMIC:") but do NOT edit outside your module; the corpus-wide master round sweeps systemic patterns.`

const CANON = [
  BATCH && `batch constants + boundary edicts and canonical shared facts under ${BATCH}`,
  DESIGN !== OUT && `outline + decision log + research digest under ${DESIGN}`,
  `quality bar ${SK}/references/quality-bar.md`,
  `known failure modes ${SK}/method/known-failure-modes.md`,
].filter(Boolean).join(' · ')

phase('Plan')
// Deterministic: the boards branch on this, so it is read from disk by a script, never from prose.
const planDump = await agent(
  `Run EXACTLY this and return ONLY its stdout (no prose, no fences):\n` +
  `python3 - <<'EOF'\n` +
  `import glob, os, json, yaml\n` +
  `OUT = '${OUT}'\n` +
  `st = sorted(os.path.basename(p)[:-11] for p in glob.glob(OUT + '/lessons/briefs/*.brief.yaml'))\n` +
  `stats = {'quiz': {}, 'emdash': {}}\n` +
  `for p in sorted(glob.glob(OUT + '/lessons/briefs/*.brief.yaml')):\n` +
  `    stem = os.path.basename(p)[:-11]\n` +
  `    L = (yaml.safe_load(open(p)) or {}).get('lesson', {})\n` +
  `    qtot = qlongest = 0\n` +
  `    for blk in (L.get('quiz_blocks') or []):\n` +
  `        for q in (blk.get('questions') or []):\n` +
  `            opts = q.get('options') or []\n` +
  `            if not opts: continue\n` +
  `            qtot += 1\n` +
  `            lens = [len(o.get('label') or '') for o in opts]\n` +
  `            ci = [i for i, o in enumerate(opts) if o.get('correct')]\n` +
  `            if ci and lens[ci[0]] == max(lens) and lens.count(max(lens)) == 1: qlongest += 1\n` +
  `    if qtot: stats['quiz'][stem] = [qlongest, qtot]\n` +
  `    n = open(p, encoding='utf-8').read().count('\\u2014')\n` +
  `    if n: stats['emdash']['briefs/' + stem] = n\n` +
  `for p in [OUT + '/course.yaml', OUT + '/lessons/drafts/000-cover.md'] + sorted(glob.glob(OUT + '/modules/*/module.yaml')):\n` +
  `    if os.path.exists(p):\n` +
  `        n = open(p, encoding='utf-8').read().count('\\u2014')\n` +
  `        if n: stats['emdash'][p.replace(OUT + '/', '')] = n\n` +
  `tl = sum(v[0] for v in stats['quiz'].values()); tq = sum(v[1] for v in stats['quiz'].values())\n` +
  `os.makedirs(OUT + '/boards', exist_ok=True)\n` +
  `json.dump(stats, open(OUT + '/boards/c-stats.json', 'w'), indent=1)\n` +
  `print(json.dumps({'stems': st, 'n': len(st), 'longest_correct': [tl, tq], 'emdash_files': len(stats['emdash'])}))\n` +
  `EOF`,
  { label: 'plan+stats', phase: 'Plan', effort: 'low' }
)
function grab(ret, key) {
  const s = typeof ret === 'string' ? ret : JSON.stringify(ret || '')
  const i = s.indexOf(key)
  if (i < 0) return null
  let d = 0
  for (let j = i; j < s.length; j++) {
    if (s[j] === '{') d++
    else if (s[j] === '}') { d--; if (d === 0) { try { return JSON.parse(s.slice(i, j + 1)) } catch { return null } } }
  }
  return null
}
const plan = grab(planDump, '{"stems"')
if (!plan || !plan.stems || !plan.stems.length) {
  return { course: OUT, error: 'plan failed', raw: String(planDump).slice(0, 400) }
}
const stems = plan.stems
const byModule = {}
for (const s of stems) (byModule[modKey(s)] ||= []).push(s)
const mods = Object.keys(byModule).sort()
const prevOf = {}
for (const mk of mods) {
  const i = stems.indexOf(byModule[mk][0])
  prevOf[mk] = i > 0 ? stems[i - 1] : null
}
log(`plan: ${plan.n} lessons / ${mods.length} modules · longest-correct quiz tell ${plan.longest_correct[0]}/${plan.longest_correct[1]} · em-dash files ${plan.emdash_files}`)

const FIND = {
  type: 'object', required: ['module', 'ok', 'fixed', 'flagged'],
  properties: {
    module: { type: 'string' }, ok: { type: 'boolean' },
    fixed: { type: 'array', items: { type: 'string' } },
    flagged: { type: 'array', items: { type: 'string' } },
  }, additionalProperties: false,
}

const COMMON = (mk) => `Course "${COURSE_ID}". Your module: ${mk}, brief stems ${JSON.stringify(byModule[mk])}. Today is ${TODAY}.
Paths: drafts ${OUT}/lessons/drafts/<stem>.md · briefs ${OUT}/lessons/briefs/<stem>.brief.yaml · frozen facts ${OUT}/lessons/facts/<stem>.facts.md (if present) · module yamls ${OUT}/modules/ · challenges ${OUT}/lessons/challenges/<lesson-id>/ · ${CANON}.
Edit ONLY files belonging to your module's lessons. ${PATTERN_RULE}`

phase('BoardA')
const aRes = (await parallel(mods.map(mk => () =>
  agent(
    `BOARD A: fact-check + code truth for module ${mk}. ${COMMON(mk)}
Write-phase carry-over notes from the verify stage (chase every one that touches your module): ${NOTES}

For EACH draft in your module:
1. FACTS: check every number, version, API name, account/program id, CLI command, date and cited event against the lesson's frozen facts file, the research digest verdicts, and the boundary doc's canonical phrasings. Frozen facts are the truth for everything EXCEPT the write-time probes, which were deliberately NOT frozen and must be re-verified LIVE now (use ToolSearch to load the solana-dev / context7 / helius MCP tools; WebSearch as fallback): ${PROBES}. Fix wrong claims in place; keep canonical wording where the boundary doc mandates it. If the draft references a dated cutover or launch, check whether it has since happened and fix the tense and the claim.
2. COMMANDS + INSTALLS: every tool invoked must show its install at first use in the course. Fix within your module; if first-use is in another module, flag it.
3. CHALLENGE INTERFACES: read this module's coding-challenge dirs; the interfaces, file names and function signatures the draft promises must match what the challenge actually ships. Reconcile (prefer fixing the draft to the frozen challenge spec).
4. RE-VERIFY after edits: python3 ${SK}/tools/dedash.py <draft> then python3 ${SK}/tools/verify_code.py --file <draft>. Never introduce a compile break with a prose fix. Container-only stacks will SKIP locally: record each SKIP in flagged as "RC:<stem>" (a later Docker gate compiles them; SKIP is NOT pass).
Return schema: module=${mk}; ok=(no unresolved factual defect remains); fixed=what you changed (short strings); flagged=what a human or the Docker gate must still chase.`,
    { label: `A:${mk}`, phase: 'BoardA', effort: 'high', schema: FIND }
  )
))).filter(Boolean)

const rcFlagged = aRes.flatMap(r => r.flagged || []).filter(f => f.startsWith('RC:')).length
const dockerRes = await agent(
  `BOARD A DOCKER GATE for course "${COURSE_ID}". The local toolchain cannot compile container-only code (a course may declare a release-candidate or otherwise unreleased stack). Board A recorded ${rcFlagged} RC-flagged drafts (there may be more; trust the tool, not the count).
1. Check docker: run "docker info" — if the daemon is down or unreachable, return ok=false with flagged=["DOCKER-BLOCKED: <exact error>"] and STOP (do not fake a pass).
2. Learn the tool: python3 ${SK}/tools/verify_code.py --help. Then run it with --env docker over this course's drafts (course-wide if supported, else per file over every draft in ${OUT}/lessons/drafts/ that verify_code SKIPped locally). First image pull may be slow; that is fine.
3. Every FAIL is a real compile break: FIX the code in the draft, faithful to the brief's frozen API (read the brief + facts before touching code), re-run until PASS or genuinely blocked. NEVER weaken code to make it compile (no stubbing, no deleting the failing block).
Return schema: module="docker-gate"; ok=(all container blocks compiled); fixed=breaks repaired; flagged=anything still failing or blocked, with the exact error.`,
  { label: 'A:docker-gate', phase: 'BoardA', effort: 'high', schema: FIND }
)

phase('BoardB')
const bRes = (await parallel(mods.map(mk => () =>
  agent(
    `BOARD B: pedagogy for module ${mk}. ${COMMON(mk)} Also load ${SK}/references/instructional-design-canon.md and ${SK}/design-spine.md. Continuity: the lesson before this module's first is ${prevOf[mk] ? `stem ${prevOf[mk]} (read its closing section for the recap-honesty check)` : 'nothing (course opener)'}.
For EACH draft, judge and fix:
1. RECAP HONESTY: flow.recap must claim only what the previous lesson actually built (read the actual previous draft, in and across modules). Forward hook must point at what truly comes next.
2. ARC: something to DO inside the first 300 words (150 for an opener); the autonomy fade is stated out loud and actually fades across the module (guided → prompted → solo); the Lab is numbered, runnable in order, and every step's expected result is stated; the Challenge is doable from what has been taught (check declared prerequisites against the outline DAG — no forward dependency).
3. CONTRACT: est_length respected — flag padding and starvation rather than bulk-rewriting; no 700+-word prose wall (split with a fence or visual where pacing dies).
4. VOICE ROUTING SANITY: the brief's dominant_job routed the guest voice. Guest-only jobs used as a module BACKBONE are deliberate in specific outlined places: confirm against the outline + decision log and record "confirmed-deliberate" in fixed, or flag if truly unplanned. Do not rewrite voice (Board C owns prose voice).
Small surgical fixes in place; structural rewrites get flagged, not performed. After any edit: python3 ${SK}/tools/dedash.py <draft>.
Return schema: module=${mk}; ok; fixed; flagged.`,
    { label: `B:${mk}`, phase: 'BoardB', effort: 'high', schema: FIND }
  )
))).filter(Boolean)

phase('BoardC')
const VOICE_STEP = WS
  ? `4. DRAFT VOICE: export WRITER_STYLE_SKILL="${WS}"; run python3 ${WS}/tools/validate_voice.py tells --file <draft>${CARD ? ` --card ${CARD}` : ''} on each draft and fix flagged tells. Then python3 ${SK}/tools/dedash.py <draft>.`
  : `4. DRAFT VOICE: no writer-style skill is configured for this run, so judge voice by reading: flag hollow transitions, uniform sentence openings, and filler. Then python3 ${SK}/tools/dedash.py <draft>.`
const cRes = (await parallel(mods.map(mk => () =>
  agent(
    `BOARD C: rhetoric, voice and assessment-layer language for module ${mk}. ${COMMON(mk)} Course tone default: ${TONE}. Course-wide stats at ${OUT}/boards/c-stats.json (quiz = per-stem [correct-is-strictly-longest, total-questions]; emdash = files with U+2014 counts). Craft rules: ${SK}/method/quiz-authoring.md.
1. QUIZ LABEL REBALANCE (systemic tell: the correct option is almost always the longest label). In your module's brief yamls, rewrite option LABELS so correct-longest survives in at most ~1/3 of questions: usually EXPAND a plausible distractor with real (wrong-path) specificity, sometimes TIGHTEN the correct label. NEVER change which option is correct, never weaken a distractor's plausibility, never touch ids or correct flags, keep feedback lines consistent with any rewritten label.
   OPTION POSITION IS OUT OF SCOPE AND IS TOOL-OWNED. Answer-slot distribution is enforced by validate_course.py (course-wide slot skew is a HARD) and corrected by the shipped quiz tooling. Do NOT hand-permute option order, and do NOT write a position instruction into any prompt you produce: correctness is keyed by option id, so position is a mechanical transform a tool does correctly and a fan-out of agents does not. Rotation instructions written into authoring prompts are what produced the defect this board exists to catch.
2. EM-DASHES OUTSIDE LESSON PROSE: the house ships zero. Purge U+2014 from your module's brief yamls (quiz prompts/labels/feedback, hooks, specs) and module.yaml BY SYNTACTIC ROLE: sentence-boundary dash → period or semicolon; appositive pair → commas or parens; list-introducing dash → colon. NEVER a blind comma swap (it mints comma splices), and vary the repair so the corpus does not acquire a uniform comma-appositive fingerprint.
3. YAML SAFETY: after editing any yaml, round-trip it: python3 -c "import yaml,sys;yaml.safe_load(open(sys.argv[1]))" <file>. A parse error means you broke quoting — fix before returning.
${VOICE_STEP}
5. VISUAL FIELD SWEEP (parallel-writer dialect strata): in every draft's visual blocks, prompt/purpose/data/alt must be consistent English at one register; alt must be a real 8-30 word descriptive sentence (not a label, not a title echo); purpose must not contradict prompt. Normalize.
Return schema: module=${mk}; ok; fixed (include your quiz rebalance tally like "rebalanced 5/9"); flagged.`,
    { label: `C:${mk}`, phase: 'BoardC', effort: 'high', schema: FIND }
  )
))).filter(Boolean)

phase('BoardD')
const DFIND = {
  type: 'object', required: ['module', 'findings'],
  properties: {
    module: { type: 'string' },
    findings: {
      type: 'array', items: {
        type: 'object', required: ['severity', 'where', 'what'],
        properties: { severity: { enum: ['HARD', 'SOFT'] }, where: { type: 'string' }, what: { type: 'string' } },
        additionalProperties: false,
      },
    },
  }, additionalProperties: false,
}
const dRes = (await parallel([
  ...mods.map(mk => () =>
    agent(
      `BOARD D: COLD READ of module ${mk} of course "${COURSE_ID}". You are a paying student, not a reviewer with the spec. Read ONLY: ${prevOf[mk] ? `the closing of ${OUT}/lessons/drafts/${prevOf[mk]}.md for continuity, then` : ''} each draft ${OUT}/lessons/drafts/<stem>.md for stems ${JSON.stringify(byModule[mk])}, in order. Do NOT open briefs, facts, outlines, or research (that is the point). Do NOT edit anything.
Report every place you, as a student: got confused; met a term used before it was ever explained in what you have read; caught the text contradicting itself or an earlier lesson; were promised something the lesson never delivered; noticed the invented artifact/domain go inconsistent (names, interfaces, numbers drifting); stopped trusting the author. Also flag anything that smells machine-written (uniform tics, hollow transitions, filler).
severity: HARD = a student would be blocked or misled; SOFT = friction. where = stem + nearest heading. Be concrete enough that a fixer who has the spec can act without asking you.
Return schema: module=${mk}; findings=[...] (empty array if genuinely clean).`,
      { label: `D:${mk}`, phase: 'BoardD', effort: 'high', schema: DFIND }
    )),
  () => agent(
    `BOARD D META: course-surface coherence for "${COURSE_ID}". Read ${OUT}/course.yaml, ${OUT}/lessons/drafts/000-cover.md, ${OUT}/README.md (if present), ${OUT}/manifest.json, ${OUT}/assessment.yaml, ${OUT}/cadence.yaml. Do NOT edit.
Check (known template failure modes): declared audience ("who") vs what the overview/cover text actually demands of the reader — they must describe the same student; total hours vs actual content volume (${plan.n} lessons; a course this size claiming tiny hours, or cover time-math contradicting course.yaml, is a HARD); cover "era/rung/ladder" narrative only if the module count and artifact ladder genuinely support it; every repo, tool or artifact the cover asserts must exist on disk in this course (no leaked thesis from a sibling course, no invented toolkit repos); duration units are HOURS; title/slug/lesson-count agreement between manifest.json and course.yaml; em-dashes in course.yaml/cover text (report; Board C may have missed surfaces).
Return schema: module="course-meta"; findings=[...].`,
    { label: 'D:course-meta', phase: 'BoardD', effort: 'high', schema: DFIND }
  ),
])).filter(Boolean)

phase('Fix')
const allFindings = dRes.flatMap(r => (r.findings || []).map(f => ({ module: r.module, ...f })))
const hard = allFindings.filter(f => f.severity === 'HARD')
log(`Board D: ${allFindings.length} findings (${hard.length} HARD)`)
let fixRes = { module: 'd-fixer', ok: true, fixed: [], flagged: [] }
if (allFindings.length) {
  fixRes = await agent(
    `You apply Board D cold-read findings to course "${COURSE_ID}". Unlike Board D you have full spec access: briefs at ${OUT}/lessons/briefs/, facts at ${OUT}/lessons/facts/, ${CANON}. Findings (JSON): ${JSON.stringify(allFindings)}.
Apply every HARD finding and every SOFT finding whose fix is unambiguous and local. A finding that demands a structural rewrite, contradicts the spec, or looks like reviewer error: skip it and record why in flagged. Keep fixes surgical and in the course voice; never introduce em-dashes; after editing any draft run python3 ${SK}/tools/dedash.py <file>; after editing any yaml round-trip it with yaml.safe_load. When a finding reveals a pattern (same defect phrased in several lessons), sweep the WHOLE course for that pattern, not just the cited file.
Return schema: module="d-fixer"; ok=(all HARDs resolved); fixed; flagged=skipped findings with reasons.`,
    { label: 'D:fixer', phase: 'Fix', effort: 'high', schema: FIND }
  ) || fixRes
}

phase('Gate')
const GATE = {
  type: 'object', required: ['gate', 'hard_left', 'summary'],
  properties: { gate: { enum: ['PASS', 'FAIL'] }, hard_left: { type: 'integer' }, summary: { type: 'string' } },
  additionalProperties: false,
}
const boardsDigest = {
  A: aRes.map(r => ({ m: r.module, ok: r.ok, fixed: (r.fixed || []).length, flagged: r.flagged })),
  docker: dockerRes ? { ok: dockerRes.ok, fixed: dockerRes.fixed, flagged: dockerRes.flagged } : 'AGENT-DIED',
  B: bRes.map(r => ({ m: r.module, ok: r.ok, fixed: (r.fixed || []).length, flagged: r.flagged })),
  C: cRes.map(r => ({ m: r.module, ok: r.ok, fixed: r.fixed, flagged: r.flagged })),
  D: { findings: allFindings.length, hard: hard.length, fixer: fixRes },
}
const REPORT = `${DESIGN}/boards-report.md`
const gate = await agent(
  `FINAL GATE for course "${COURSE_ID}" after four review boards. Board digest (JSON): ${JSON.stringify(boardsDigest).slice(0, 20000)}.
1. Run python3 ${SK}/tools/validate_course.py all --course ${OUT} and python3 ${SK}/tools/validate_course.py drafts --course ${OUT}. Fix any [HARD] that is trivial (missing visual field, stray em-dash, leaked preamble); re-run until clean or the remaining HARDs are structural.
2. Write ${REPORT}: per-board fixed/flagged tables from the digest, every unresolved item (Docker gate blocks, probe uncertainties, systemic "SYSTEMIC:" patterns for the master round, skipped D findings), and a one-paragraph verdict: is this course ready for visual render + export + PR? A board that reported nothing must have said what it checked; note any that did not.
Return schema: gate=PASS only if both validators are clean AND the Docker gate ok was true; hard_left=count of unresolved HARDs; summary=the verdict paragraph.`,
  { label: 'gate+report', phase: 'Gate', effort: 'high', schema: GATE }
)

return {
  course: OUT,
  courseId: COURSE_ID,
  lessons: plan.n,
  boards: {
    A_ok: aRes.filter(r => r.ok).length + '/' + mods.length,
    docker_ok: dockerRes ? dockerRes.ok : null,
    B_ok: bRes.filter(r => r.ok).length + '/' + mods.length,
    C_ok: cRes.filter(r => r.ok).length + '/' + mods.length,
    D_findings: allFindings.length,
    D_hard: hard.length,
  },
  gate: gate ? gate.gate : 'GATE-AGENT-DIED',
  hard_left: gate ? gate.hard_left : -1,
  summary: gate ? gate.summary : 'gate agent died; re-run the Gate phase via resume',
  report: REPORT,
}
