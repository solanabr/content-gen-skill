# BRIEF FOR THE AGENT BUILDING solana-under-the-hood (with Leafar · from Kaue's build agent, 2026-08-31)

You are building a 30-lesson course from its finished architecture: **"Solana Under the Hood"** —
the validator internals course. Promise: hand-assemble, sign, and land a transaction into your own
raw `no_std` sBPF program, trace it through the live validator pipeline component by component,
judge TowerBFT against Alpenglow from source, and read Solana's roadmap from feature-gate accounts
instead of headlines. Research, architecture, boundary adjudication, and lesson briefs are DONE and
gate-PASS. **Zero lessons are written.** You start at the write phase.

This brief is your operating contract, compressed from shipping the sibling wave-2 courses
(solanabr/academy-courses PR #44 mastering-anchor-v2, PR #48 solana-payments-commerce). Every rule
was paid for with a real failure.

## MODEL

Run on Claude Fable 5 (/model fable). The shipped sibling courses are the Fable-voice baseline and
subagents inherit the session model — set it once and every workflow writer/reviewer follows. If
you ever switch models mid-course, record the seam; Board C/D must check register drift across it.

## FIRST: A BRAINSTORMING SESSION WITH LEAFAR (do this before writing anything)

Leafar knows Solana deeply — validator internals are his territory. The briefs were written without
him; a structured session with him BEFORE the write fan-out is worth more than any review board
after it (changing briefs pre-write is cheap; re-writing lessons post-board is not). Run it as a
working session, module by module through `content/wave2/solana-under-the-hood/outline-v2.md`:

1. **Fact interrogation.** For each module, surface the brief's central claims and let him
   challenge them — especially m06 Sealevel/scheduler, m07 ingestion/propagation, m08 consensus
   (TowerBFT vs Alpenglow — ask what he'd bet has CHANGED since the research froze on 2026-08-22),
   m09 economics, m10 clients/IBRL roadmap. Write confirmed corrections into the lesson
   `facts/` files and amend briefs BEFORE writers run.
2. **War stories.** The writer-style method requires a "human seam" in every passage (a real
   number from experience, a confession, an operator's aside). Leafar's first-hand validator/ops
   stories are exactly that material — collect them per module and pass them to writers via the
   brief's voice_notes or the workflow `notes` arg. This is what will make this course feel lived
   rather than researched.
3. **Emphasis + depth calls.** He should rank where the outline under- and over-invests. Log
   deltas in `decision-log.md`; anything that changes lesson scope goes into the briefs now.
4. **Voice decision.** Planned course tone: `vitalik 0.6 / helius 0.4; balaji guest ONLY on
   roadmap/IBRL M10`. Options: keep it, or build a `leafar` pack with the writer-style
   persona-builder (`/new-persona` in github.com/solanabr/writer-style-skill — feed it his
   technical-guide register, not tweets; see method/primary-profile.md for the two make-or-break
   properties: idiolect dosage per register + the naturalness floor). Decide together BEFORE
   writing; a mid-course voice switch creates a seam the boards must then police.
5. **Contested probes.** The wave's write-time probe list (boundary-adjudication §4) includes the
   Alpenglow rollout quarter ("late 2026" is the safe phrasing; re-probe solana.com/upgrades),
   block CU ceiling, SWQoS limits, tx-v1 gate status, SIMD-0268 CPI depth, nonce-deprecation
   SIMD. For THIS course these aren't sidebars — they're the syllabus. Get Leafar's read, then
   still have Board A verify live at review time.

## READ THE SHIPPED COURSES FIRST (register + structure reference)

You have not seen any wave output. Before writing, read real lessons from the courses that already
shipped — clone solanabr/academy-courses and study:

- **`courses/btc-to-sol-evolution/`** (LIVE on main) — the original register baseline: lesson
  shape, prose-to-code cadence, quiz/challenge blocks, visual placement, intro.md structure.
- **`mastering-anchor-v2`** (PR #44 branch `feat/mastering-anchor-v2-25-08-2026`, merged or
  pending) — the deepest wave-2 course and the closest analog in technical density; read 3-4
  full lessons including a lab lesson and the cover.
- **`solana-payments-commerce`** (PR #48) — the most recently shipped; its export tree is the
  cleanest example of what CI accepts (challenges, skills, slots.lock, banner).

Match their bar. A lesson is 3000+ words with a do-element inside the first 300, ~1 visual spec
per 600 words (floor 2), runnable fences that actually compile, and a quiz whose correct option is
NOT the longest.

## SETUP

1. Repo: github.com/solanabr/content-gen-skill. Unpack Kaue's zip INTO the repo root — restores
   `content/courses/solana-under-the-hood/` + `content/wave2/` (gitignored; content never commits
   here, it PRs into solanabr/academy-courses).
2. Sibling checkouts: writer-style-skill (workflow scripts find it by name) and academy-courses
   (reference + PR target; gh CLI authenticated).
3. Read in order: `content/wave2/CHECKPOINT.md` (institutional memory — §CODE VERIFICATION
   especially: this course is Rust-heavy), `WAVE.md`, `boundary-adjudication.md` (BINDING),
   `content/wave2/solana-under-the-hood/outline-v2.md` + research/digest.md.
4. Toolchain: WeasyPrint; node 23+ (tsc via course `verify-ts/node_modules` — npm i typescript
   there when needed); **cargo/rustc 1.89+** (raw no_std sBPF module + Rust challenges); python3
   with jsonschema + yaml.
5. Ensure content-gen-skill PR #2 + follow-ups are in your checkout — `verify_challenges.py`
   there enforces the executor contract; without it you ship challenges that fail CI.

## STATE (exact, 2026-08-31)

- Research + architecture + boundary council + briefs + emit: DONE, `validate_course.py all` =
  GATE: PASS on the emitted skeleton.
- **Drafts: 0/30 written** (only 000-cover.md exists; cover is generated-authoritative — verify
  its claims against course.yaml before shipping, a sibling course's cover once asserted a repo
  that didn't exist).
- 11 modules / 30 lessons: machine-and-method → transactions-on-the-wire → accounts-database-layer
  → programs-loaders-ELF → raw-programs-syscalls (build-it-twice) → sealevel-scheduler →
  ingestion-time-propagation → consensus-today-tomorrow → economics-of-the-machine →
  clients-and-IBRL-roadmap → whole-machine capstone.
- 11 coding challenges planned in briefs (mixed rust + typescript). None authored yet — author
  them DURING write, against the executor contract below, so no retrofit pass is needed.
- Quiz answer-length tell in the briefs: **129/132 (98%) correct-is-longest** — brief-writers do
  this every time. Writers should not worsen it; the dedicated rebalance pass fixes it after
  boards (target <40%).
- `course_id` = `course-solana-under-the-hood` (28 chars) — under the 32 cap, no override needed.
  Manifest `academy` block still required at export (step 8).
- Stems are positional: `m00-l1-m01-l1.md` = positional module 0, REAL lesson id m01-l1; module
  grouping always uses the positional prefix p[0].

## WRITE PHASE (your first workflow)

`Workflow _write.wf.js args {courseId:"solana-under-the-hood", tone:"vitalik 0.6 / helius 0.4;
balaji guest ONLY on roadmap/IBRL M10"}` (adjust tone per the Leafar voice decision; pass his
war-story notes via the briefs). Plan → parallel per-lesson writers (writer-style voice + visual
placeholder specs + dedash) → per-module verify. Writers are idempotent: on a session-limit death,
disk keeps complete drafts; resume same runId+args (same session) or relaunch same scriptPath+args
(fresh session). Batch expectation: a 30-lesson write is ~2 usage windows; the verify tail is what
gets cut — always finish it before boards (its carry-over notes feed Board A).

## THE CHALLENGE-EXECUTOR CONTRACT (author challenges to this from day one)

The platform grades **TypeScript standard** challenges by splicing sucrase-TYPE-stripped code into
a `new Function` body in a bare JS realm (source: solanabr/superteam-academy
`packages/challenge-executor/src/executor.ts`).
1. No ESM value syntax in starter/solution (`export function` = SyntaxError in the splice;
   `export interface/type` is erased, harmless). Imports: only `@solana/web3.js` is mocked —
   challenges are self-contained single files.
2. No web APIs: only TextEncoder/TextDecoder are mocked. URLSearchParams/URL/fetch/Buffer/btoa →
   ReferenceError on every test. Query strings by hand with `encodeURIComponent`.
3. First-match function detection: the executor calls the FIRST `function name(` OR
   `const name = (` match — even a parenthesized non-function initializer. The graded function
   must be the first such construct in the file.
4. tests.json `input` = comma-split positional fragments: number (`123n` ok), 'quoted string',
   true/false/null, or grader-bound identifier. NO object/array literals; irreducibly structured
   data → one single-quoted JSON string + JSON.parse (no post-split fragment may start with `{`).
Symptom of violation: passes local tsc/node, fails EVERY test identically in CI.
**Rust challenges are DEFERRED by CI** (runtime grading, fail-closed) — local
`verify_challenges.py` is their ONLY gate; never treat SKIP as PASS.
Scope: only the GRADED challenge runs in the sandbox; lesson LABS run in the learner's own
Node/cargo — full APIs available there.

## RUST VERIFICATION TRAPS (this course is the wave's most Rust-heavy)

`verify_blocks.py <course> --lang rust` (and `--lang ts`) compiles every block against the versions
THE COURSE ITSELF teaches (harvested from its own Cargo.toml/npm blocks — never guessed pins).
Guarded traps, do not reintroduce: guessed pins invent failures; a harness that cannot build must
never report PASS; **a silently swapped oracle INVERTS findings** (`anchor-lang = "*"` resolves to
stable and judges newer code as broken with confident, plausible errors) — always confirm the
resolved versions in the printed `ORACLE:` line before believing any FAIL. For `no_std` sBPF
blocks expect SKIPs for fragments whose context lives across fences — SKIP means "can't judge",
never "pass". Block classification (standalone/item/fields/method/body) exists because naive
wrapping minted false FAILs — trust the triage table in CHECKPOINT §CODE VERIFICATION.

## CANONICAL FACTS (wave-standardized; for THIS course they are the syllabus — verify live, then teach the derivation)

- Target slot time **300ms** (SIMD-0525 stage 2, epoch 1024, 2026-08-28); 400ms/350ms only as
  history; 250/200ms cuts staged in code. Teach "derive it, never memorize it".
- Blockhash lifetime: 150 blocks (`MAX_PROCESSING_AGE`) × slot time ≈ 45s today.
- ATA rent: 2,039,280 lamports ≈ 0.00204 SOL. Node floor 24. Kit pins per-workspace.
- Alpenglow: say "late 2026" unless a fresher probe says otherwise; m08/m10 must be written so a
  date slip doesn't rot them (feature-gate reading IS the lesson).
If a number gets corrected anywhere, sweep the ENTIRE course for the pattern (drafts, quiz text,
challenge fixtures, visual specs, cover, README) — a half-applied correction makes the course
self-contradictory, worse than uniformly wrong. Never re-date "as I write on <date>" claims when
fixing surrounding facts — de-anchor ("in force since epoch 1024") instead.

## PIPELINE AFTER WRITE (one heavy workflow per usage window)

1. Verify (end of write workflow) → `validate_course.py all` + `drafts` → GATE: PASS.
2. Challenge check: `verify_challenges.py <course>` → every TS+Rust challenge upholds
   solution-passes/starter-fails. A challenge is FOUR synced artifacts: tests.json, starter,
   solution, AND the lesson prose quoting the signature (+ manifest coding_challenges[].prompt).
3. Code blocks: `verify_blocks.py --lang rust` and `--lang ts` → 0 FAIL, oracle confirmed.
4. Boards: `_boards.wf.js {courseId, tone, notes:<verify carry-overs + Leafar-session notes>}`.
   TRAP: Board C historically wrote quiz fixes into `briefs/*.brief.yaml`, but quizzes SHIP from
   `manifest.json → lessons[].brief.quiz_blocks` — patch Board C to edit the manifest via
   `quiz_balance.py split/merge`, or port briefs→manifest after with a structural-invariant check
   (question ids, option ids/order, `correct` flags must not move).
5. Quiz balance: `quiz_balance.py report` → <40% longest-correct (from 98%). Trim over-long
   answers into `explanation`, match distractor length/register. Re-run report after ANY later
   quiz-text edit.
6. Visuals: `render_visuals.py scaffold` (idempotent) → `_visuals.wf.js` (author → render →
   per-lesson PNG review that OPENS the images → fix → gate). Traps: never run course-wide
   render/review while per-lesson reviewers are live (per-asset intermediates race); a prose edit
   that adds a visual block RENUMBERS later slots (compare spec comments, migrate matching
   authored HTML, run `decorate`, delete orphaned old-slot HTML AND PNGs, re-render `--only`);
   validator demands ~1 parsing visual per 600 words, floor 2.
7. Banner: `scaffold-banner` → author per `brand/brand-guide.md` (WeasyPrint-safe CSS; emerald
   hero, yellow on exactly ONE element) → `render-banner` → open the PNG and judge it.
8. Export: `academy_export.py emit --course ... --out <academy-courses>/courses/
   solana-under-the-hood`. REQUIRED manifest `academy` block: `{ creator: <wallet — PR #48 used
   3WECquwCtcKVRYNWBPFWE28ag3b1CDKchLZPXxifAJzQ>, difficulty: "advanced",
   skills_map: {<each module teaches_skills node>: <slug>}, default_skills: [...] }`. The 8
   permitted slugs: solana-fundamentals, account-model, transactions, keypairs-wallets,
   rpc-reads, solana-programs, anchor, solana-kit — never invent slugs; without skills_map
   lessons export skill-less. Strip any em-dash from `course.one_line_promise` in the MANIFEST
   (it becomes the description verbatim).
9. Pre-flight (content-lint isn't local — emulate): jsonschema vs `<academy-courses>/schema/*`
   → 0 errors; **the exporter is ADDITIVE** — emit to a fresh temp dir, `diff -rq`, delete every
   "Only in <export>" stale file (CI's orphan gate flags them); grep the EXPORT for em-dashes
   (they hide in quiz hints, challenge comments, visual labels, yaml descriptions — fix by
   syntactic role, never blind comma-substitution); alt text with NO brackets ever; nothing over
   1 MiB.
10. Pre-PR review: 3 parallel cold-read agents over the EXPORTED tree (early/middle/late slices +
    course shell) — structural integrity, canon consistency, quiz sanity (re-derive arithmetic in
    feedback; verify any "the scaffold ships X" claim is TRUE and empty-input paths fail loudly).
    On payments this caught a 1000× numeric error and a vacuous lab gate all other gates missed.
11. PR: branch off FRESH origin/main of academy-courses; touch ONLY
    `courses/solana-under-the-hood/`; trackId 0 / trackLevel 0 (adopted-electives lane, immutable
    on-chain); raise the catalog-row question in the PR body; copy PR #48's body structure (gates
    evidence + explicit human-owed items — e.g. a live run of the raw-sBPF build-it-twice lab).

## FAILURE PLAYBOOKS

- Session-limit deaths mid-workflow are ROUTINE. Disk is ahead of the reported result — count
  files before re-running. Resume {scriptPath, resumeFromRunId, same args} same-session (caching
  is PREFIX-based: never edit an early agent's prompt on a run you'll resume); fresh session →
  relaunch same scriptPath+args.
- A dead run is recoverable without resume: `<session>/subagents/workflows/<runId>/journal.jsonl`
  holds every finished agent's result; `agent-<id>.jsonl` holds every dead agent's full prompt.
  A 41-agent boards run was resurrected from its journal. Check there BEFORE re-running phases.
- Never trust an agent's "fixed it" summary — grep the corpus yourself after every fixer pass.
- When a checker FAILs, ask whether it matched real usage or its own documentation
  (substring-vs-real-usage is the toolchain's recurring bug).
- When CI fails every test of a challenge identically while local passes: it's the calling
  contract, not the content — READ the consumer's source (superteam-academy:
  packages/challenge-executor, packages/content-lint/src/checks/), then encode the rule into
  verify_challenges.py WITH a selftest.

## EXPANSION (bring these INTO the brainstorm — Leafar may want some in v1)

- m06 Sealevel → the scheduler's evolution (central scheduler vs greedy), account-contention
  economics, program-level parallelism design patterns.
- m07 ingestion → Turbine deep-dive (shred propagation math), QUIC/SWQoS internals, leader
  pipeline stage-by-stage from Agave source.
- m08 consensus → Alpenglow from the whitepaper: Votor/Rotor mechanics, what dies with TowerBFT
  (vote transactions, tower storage), migration sequencing via feature gates.
- m09 economics → MEV supply chain end-to-end (Jito, BAM), priority-fee market microstructure,
  validator P&L modeling with real numbers.
- m10 clients → Firedancer architecture vs Agave (tiles, sandboxing), client diversity math,
  what "IBRL" concretely gates on.
- Cross-course: this course is the natural "why" layer under every other wave course — propose
  cross-links (payments' landing science ← m07; anchor-v2's CU costs ← m06/m09) in the PR body
  for the master cross-course round.

Questions → Kaue (Superteam Brazil). Reference PRs: solanabr/academy-courses #44, #48; live
baseline: courses/btc-to-sol-evolution on main. — Kaue's agent
