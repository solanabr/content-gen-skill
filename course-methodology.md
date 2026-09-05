# How we build a course from zero — the method behind the shipped Academy courses

Companion to `hackathon-course-prompt.md`. This is the distilled process that produced
`btc-to-sol-evolution` (live), `mastering-anchor-v2` (PR #44) and `solana-payments-commerce`
(PR #48) on solanabr/academy-courses — written for building a new course from nothing: no
research, no outline, no lessons. You run the full pipeline; your named domain expert is the
primary source.

## The pipeline (12 phases; each gates the next)

1. **Charter / scope (with your expert).** One page: audience + prior model (who exactly, what
   do they already believe/know), the one-line promise ("by the end you can …" — concrete,
   verifiable, ends in a shipped artifact), hours target, course language, and the **artifact
   ladder's domain** — every shipped course runs one continuous build the learner assembles
   lesson by lesson (payments = a record-shop commerce stack; client-side = a race-engineer
   "Pit Wall" console). Pick one that makes the course feel like ONE build, not a playlist.
2. **Research.** Sweep every primary source — produce `research/digest.md` where EVERY claim is
   tagged `[CONFIRMED]` / `[REFUTED]` / `[UNCERTAIN]` with its source, then an adversarial pass
   (`adversarial-verdicts.md`) that tries to refute the confirmed ones. Expert interviews become
   sourced facts (attributed by name). HARD RULE: no domain claims from the model's own memory —
   everything traces to a live source, a verified doc, or the expert.
3. **Architecture** → `outline-v2.md`, 11 sections: (1) terminal outcomes, Bloom-tagged, +
   capstone; (2) audience & prior model + honest prerequisites; (3) fundamentals-ordering
   decision; (4) pattern routing per lesson job; (5) artifact ladder — each lesson's rung, what
   it consumes/produces (the validator enforces this graph); (6) module map; (7) assessment
   model; (8) cadence/difficulty curve (plateaus deliberate, spikes spaced); (9) boundary
   compliance — what this course does NOT teach, pointing at sibling courses instead of
   duplicating; (10) scale rationale; (11) risks + write-time probes (facts that may change
   before writing — freeze or re-verify at write). Then an outline REVIEW pass + decision-log.
4. **Briefs + emit.** Per-lesson briefs (objectives, hook, concept spec, the tradeoff,
   just-in-time prerequisites, assessment incl. quiz blocks + coding challenges, voice notes,
   flow, est_length) → assembled deterministically into `manifest.json` → emitted skeleton →
   `validate_course.py all` GATE: PASS. Tools: `scaffold_course.py` starts the dir; the wave
   used `_briefs_emit.wf.js` + `_assemble_manifest.py` for the fan-out (ask Kaue for the
   gitignored `content/wave2/` workflow-script pack, or re-author — it is thin orchestration
   over the tracked tools).
5. **Write.** Parallel per-lesson writers through the writer-style skill (voice pack + visual
   placeholder specs + dedash), then per-module verify. Lesson bar: 3000+ words; a do-element
   inside the first 300 words; ~1 visual spec per 600 words (floor 2; fields
   type/title/purpose/data/prompt/alt); runnable/checkable steps that actually work; recap
   honesty (never claim the reader built something they didn't); prose walls broken before 700
   words.
6. **Four review boards** (`_boards.wf.js` pattern): A facts (re-verifies every probe LIVE — for
   a platform-process course this means walking the actual platforms), B pedagogy (recap chains,
   artifact ladder, cognitive load), C rhetoric/voice/quiz, D cold-read (fresh-eyes findings) →
   fixer → final gate + `boards-report.md`. TRAP: quiz fixes must land in `manifest.json →
   lessons[].brief.quiz_blocks` (the ship source), not in brief yamls.
7. **Quiz balance.** `quiz_balance.py report` — brief-writers make the correct option the
   longest ~95-98% of the time, every time; learners can score by guessing long. Must end <40%.
   `split`/`merge` enable a per-lesson fan-out; `merge` structurally refuses moved
   ids/order/correct flags.
8. **Visuals.** `render_visuals.py scaffold` → author every card as on-brand WeasyPrint-safe
   HTML → render → a review pass that OPENS the PNGs → fix → gate. Brand: emerald hero, yellow
   on exactly ONE element, no box-shadow/JS/background-image.
9. **Banner** (`scaffold-banner` → author → `render-banner`) — doubles as the Academy thumbnail.
10. **Export** (`academy_export.py emit`) — projects the course into the Academy tree
    (lesson.yaml blocks, slots.lock.json, skills mapped onto the 8 permitted slugs, banner).
    Requires a manifest `academy` block (course_id ≤32 chars, creator wallet, difficulty,
    skills_map, default_skills).
11. **Pre-flight + 3-agent cold-read review of the EXPORTED tree**, then **PR** to
    solanabr/academy-courses: branch off fresh main, touch ONLY `courses/<slug>/`, trackId 0 /
    trackLevel 0 (adopted-electives lane). PR #48's body is the template.
12. **Post-ship**: expansion memo + explicitly-listed human-owed items.

## The verification doctrine

- **A checker must model the REAL consumer's rules, not its own.** Local green means nothing if
  CI or the platform grader disagrees. When they diverge, read the consumer's source
  (solanabr/superteam-academy: `packages/challenge-executor`, `packages/content-lint/src/checks`)
  and encode the rule locally WITH a selftest — seven such divergences are already encoded in
  `verify_challenges.py` / `validate_course.py`.
- **The challenge-executor contract** (TypeScript challenges): code is type-stripped and spliced
  into a `new Function` body in a bare JS realm → no ESM value syntax, no web APIs (only
  TextEncoder/TextDecoder mocked), the FIRST `function name(`/`const name = (` match is what
  gets called, test inputs are comma-split positional scalars. Non-TS challenges are DEFERRED by
  CI to runtime grading — local verification is their only gate.
- **Facts have provenance.** Frozen facts live per-lesson in `facts/`; contested ones are
  write-time probes Board A re-verifies live. When a fact is corrected ANYWHERE, sweep the whole
  course (drafts, quiz text, challenge fixtures, visual specs, cover) — a half-applied
  correction makes the course self-contradictory, which is worse than uniformly wrong. Never
  re-date "as I write on <date>" claims when fixing surrounding facts; de-anchor them instead.
- **Never trust an agent's "fixed it" summary** — grep the corpus after every fixer pass.

## Operational rules (each cost a real failure; do not relearn)

- One heavy fan-out per usage window; the tail (fixer/gate) dies first and it's the half that
  applies findings. Session-limit deaths are ROUTINE: disk is ahead of the reported result —
  count files, then resume same runId+args (same session; caching is prefix-based, never edit an
  early prompt on a run you'll resume) or relaunch same scriptPath+args (fresh session; writers
  are idempotent against disk).
- Dead runs are recoverable from `journal.jsonl` + `agent-*.jsonl` in the run's transcript dir
  (full results of finished agents, full prompts of dead ones) — check before re-running phases.
- The exporter is ADDITIVE — diff against a fresh emit to a temp dir; every "Only in" file is a
  stale orphan CI flags.
- Em-dashes are banned and hide in quiz hints, challenge comments, visual labels, yaml
  descriptions; fix by syntactic role, never blind comma-substitution.
- Image alt text: no brackets, ever. Assets ≤1 MiB. Workflow `args` arrive as a JSON string —
  parse defensively.

## Tracked tooling (this repo, `skills/content-gen/`)

`tools/`: scaffold_course.py · validate_course.py (all/drafts gates + selftests) ·
quiz_balance.py · render_visuals.py (scaffold/decorate/render/review/check + banner) ·
academy_export.py · verify_challenges.py (executor-contract enforcement) · verify_blocks.py
(version-pinned code-block compilation) · dedash.py. `references/`: quality-bar.md ·
visual-placeholders.md · academy-schema.md. Study 3-4 full lessons of the shipped courses before
writing — they are the register and structure bar.
