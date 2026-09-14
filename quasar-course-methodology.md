# How we build a course from zero — the method behind the wave-2 courses

Companion to `quasar-course-prompt.md`. This is the distilled process that produced
`btc-to-sol-evolution` (live), `mastering-anchor-v2` (PR #44) and `solana-payments-commerce`
(PR #48) on solanabr/academy-courses — written for building **The Quasar Course** from nothing.
Unlike the wave-2 handoffs, NOTHING exists for this course yet: no research, no outline, no
briefs. You run the full pipeline, and Tuts (Quasar core contributor) is your primary source.

## The pipeline (12 phases; each gates the next)

1. **Charter / scope (with Tuts).** One page: audience + prior model (who exactly? a dev who
   knows Anchor wanting Quasar? a Rust dev? a beginner?), the one-line promise ("by the end you
   can …" — concrete, verifiable, ends in a shipped artifact), hours target, and the **invented
   artifact domain** — every wave course runs one continuous fictional build the learner
   assembles lesson by lesson (payments = a record-shop commerce stack; client-side = a
   race-engineer "Pit Wall"). Pick one with Tuts that shows Quasar off honestly.
2. **Research.** Sweep the Quasar repo, docs, release notes, examples, issues — produce
   `research/digest.md` where EVERY claim is tagged `[CONFIRMED]` / `[REFUTED]` / `[UNCERTAIN]`
   with its source, then an adversarial pass (`adversarial-verdicts.md`) that tries to refute the
   confirmed ones. For a young language this phase is mostly **interviewing Tuts** — his answers
   become sourced facts. HARD RULE: zero Quasar claims from the model's own memory; a niche
   language is maximum hallucination territory. Every fact traces to the repo, the docs, a live
   compile, or Tuts by name.
3. **Architecture** → `outline-v2.md`, 11 sections: (1) terminal outcomes, Bloom-tagged, +
   capstone; (2) audience & prior model + honest prerequisites; (3) fundamentals-ordering
   decision; (4) pattern routing per lesson job; (5) artifact ladder — each lesson's rung, what
   it consumes/produces (the validator enforces this graph); (6) module map; (7) assessment
   model; (8) cadence/difficulty curve (plateaus are deliberate, spikes spaced); (9) boundary
   compliance (what this course does NOT teach — point at other courses instead of duplicating);
   (10) scale rationale; (11) risks + write-time probes (facts that may change before writing —
   freeze or re-verify at write). Then an outline REVIEW pass + `decision-log.md`.
4. **Briefs + emit.** Per-lesson briefs (objectives, hook, concept spec, the tradeoff,
   just-in-time prerequisites, assessment incl. quiz blocks + coding challenges, voice notes,
   flow, est_length) → assembled deterministically into `manifest.json` → emitted course
   skeleton → `validate_course.py all` GATE: PASS. Tools: `scaffold_course.py` starts the dir;
   the wave used `_briefs_emit.wf.js` + `_assemble_manifest.py` for the fan-out (ask Kaue for
   `content/wave2/`'s workflow scripts, or re-author — they're thin orchestration over the
   tracked tools).
5. **Write.** Parallel per-lesson writers through the writer-style skill (voice pack + visual
   placeholder specs + dedash), then per-module verify. Lesson bar: 3000+ words; a do-element
   inside the first 300 words; ~1 visual spec per 600 words (floor 2, fields
   type/title/purpose/data/prompt/alt); runnable fences that actually compile; recap honesty
   (never claim the reader built something they didn't); prose walls broken before 700 words.
6. **Four review boards** (`_boards.wf.js` pattern): A facts+code (re-verifies every probe LIVE,
   compiles code), B pedagogy (recap chains, artifact ladder, cognitive load), C rhetoric/voice/
   quiz, D cold-read (fresh-eyes findings) → fixer → final gate + `boards-report.md`.
   TRAP: quiz fixes must land in `manifest.json → lessons[].brief.quiz_blocks` (the ship source),
   not in brief yamls.
7. **Quiz balance.** `quiz_balance.py report` — brief-writers make the correct option the
   longest ~95-98% of the time, every time; learners can score by guessing long. Must end <40%.
   `split`/`merge` enable a per-lesson fan-out; `merge` structurally refuses moved ids/order/
   correct flags.
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
12. **Post-ship**: expansion memo + human-owed items (a live run of flagship labs before
    announcement).

## The verification doctrine (what makes the gates real)

- **A checker must model the REAL consumer's rules, not its own.** Local green means nothing if
  CI/the grader disagrees. When they diverge, read the consumer's source
  (solanabr/superteam-academy: `packages/challenge-executor`, `packages/content-lint/src/checks`)
  and encode the rule locally WITH a selftest. Seven such divergences are already encoded in
  `verify_challenges.py` / `validate_course.py` — see their docstrings.
- **The challenge-executor contract** (TS challenges): code is type-stripped and spliced into a
  `new Function` body in a bare JS realm → no ESM value syntax, no web APIs (only
  TextEncoder/TextDecoder mocked), the FIRST `function name(`/`const name = (` match is what
  gets called, and test inputs are comma-split positional scalars. Non-TS challenges (rust — and
  quasar will be the same) are DEFERRED by CI to runtime grading: **local verification is their
  only gate.**
- **Code blocks compile against the versions the course itself teaches** — never guessed pins.
  `verify_blocks.py` triages SKIP (fragment context missing) / WARN / FAIL (reader would hit it),
  and guards the oracle: a silently-substituted compiler/library version INVERTS findings
  (a wildcard pin once judged correct code broken with 19 confident false failures). For Quasar
  this means **building a small quasar-block harness in the same shape**: pin the exact compiler
  Tuts blesses, refuse to report if the resolved version differs, SKIP what can't be judged,
  never let "no diagnostics parsed" score PASS.
- **Facts have provenance.** Frozen facts live in per-lesson `facts/` files; contested ones are
  "write-time probes" that Board A re-verifies live. When a fact is corrected ANYWHERE, sweep
  the whole course (drafts, quiz text, challenge fixtures, visual specs, cover) — a
  half-applied correction makes the course self-contradictory. Never re-date "as I write on
  <date>" claims; de-anchor them instead.
- **Never trust an agent's "fixed it" summary** — grep the corpus after every fixer pass.

## Young-language hazards (Quasar-specific discipline)

- **Pin exact versions and date every claim.** A pre-1.0 language changes under you. Every
  lesson states the compiler version it was verified against; the course teaches "derive/check,
  never memorize" the same way wave-2 teaches slot-time derivation.
- **Expect the write-time probe list to be long**: syntax that may change, features behind
  flags, roadmap items. Freeze with Tuts what v1 of the course commits to; everything else is
  phrased as versioned or omitted.
- **Tuts reviews Board A's output personally** — he is the only authoritative oracle for
  language-semantics claims. Budget his review time per module, not one heroic pass at the end.
- **Compare-to-Anchor content must be fair and current**: anchor-v2's course (PR #44) is the
  wave's Anchor source of truth; cross-reference it rather than re-deriving Anchor claims.

## Operational rules (cost real failures; do not relearn)

- One heavy fan-out per usage window; the tail (fixer/gate) is what dies first and it's the half
  that applies findings. Session-limit deaths are routine: disk is ahead of the reported result —
  count files, then resume same runId+args (same session; caching is prefix-based, never edit an
  early prompt) or relaunch same scriptPath+args (fresh session; writers are idempotent).
- Dead runs are recoverable from `journal.jsonl` + `agent-*.jsonl` in the run's transcript dir
  (full results of finished agents, full prompts of dead ones).
- The exporter is ADDITIVE — diff against a fresh emit to a temp dir; every "Only in" file is a
  stale orphan CI flags.
- Em-dashes are banned and hide in quiz hints, challenge comments, visual labels, yaml
  descriptions; fix by syntactic role, never blind comma-substitution.
- Alt text: no brackets, ever. Assets ≤1 MiB. Workflow `args` arrive as a JSON string — parse
  defensively.

## Tracked tooling (in this repo, `skills/content-gen/`)

`tools/`: scaffold_course.py · validate_course.py (all/drafts gates + selftests) ·
quiz_balance.py · render_visuals.py (scaffold/decorate/render/review/check + banner) ·
academy_export.py · verify_challenges.py (executor-contract enforcement) · verify_blocks.py
(version-pinned block compilation) · dedash.py. `references/`: quality-bar.md ·
visual-placeholders.md · academy-schema.md · writer-style integration. The wave-2 orchestration
scripts (`_write.wf.js`, `_boards.wf.js`, `_visuals.wf.js`, `_quiz-balance.wf.js`,
`_briefs_emit.wf.js`) live in gitignored `content/wave2/` — ask Kaue for the pack or re-author
from this doc's phase descriptions.
