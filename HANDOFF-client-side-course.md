# Handoff → Thom: finish `solana-client-side-mastery`

From Kaue's build sessions (last: 2026-08-31). This doc is everything you need to take the course
from its current state to a merged PR on `solanabr/academy-courses`, following the exact pipeline
that shipped `mastering-anchor-v2` (PR #44) and `solana-payments-commerce` (PR #48). Use those two
PRs as your reference for what "done" looks like.

## 0. Get the working content (blocking)

Course content is **gitignored** in this repo — the drafts live only on Kaue's machine. Ask him for:

- `content/courses/solana-client-side-mastery/` — the course working dir (drafts, briefs, facts,
  challenges, manifest.json)
- `content/wave2/` — the wave-level docs and workflow scripts (`WAVE.md`,
  `boundary-adjudication.md`, `CHECKPOINT.md`, `_write.wf.js`, `_boards.wf.js`, `_visuals.wf.js`,
  `_quiz-balance.wf.js`) plus `content/wave2/solana-client-side-mastery/` (outline-v2.md,
  research digest, decision log)

Read `content/wave2/CHECKPOINT.md` first — it is the wave's institutional memory (verification
traps, resume mechanics, publish-path facts). `boundary-adjudication.md` is BINDING: 45 per-course
edicts + 17 canonical shared facts that writers and review boards must obey.

## 1. Train YOUR voice pack first (before writing a single lesson)

The course is written through the **writer-style skill**:
**https://github.com/solanabr/writer-style-skill** — clone it as a sibling checkout (the workflow
scripts discover it by name).

It's a two-layer engine: an always-on PRIMARY voice pack that reproduces a specific author's
idiolect, plus SECONDARY craft profiles routed by the piece's job. The current course drafts were
written with the shipped `kaue` pack blended as `helius 0.8 / hotz 0.2` (hayes guest on
MEV-economics, m06). To continue in your own voice:

1. In the writer-style repo, run the **persona-builder** agent (`/new-persona`) — it builds
   `profiles/thom/` from a corpus of your own on-register writing. Feed it your *technical-guide*
   register, not your tweets: the skill's hard-won dosage lesson is that calibrating a course to
   tweet-density produces cosplay.
2. The two things that make or break the pack (see `skills/writer-style/method/primary-profile.md`):
   **idiolect at the right dose per register**, and the **naturalness floor** — uneven texture, a
   human seam in every passage (first-person confession, a real number from experience, an aside).
   Perfectly groomed prose is a bigger AI-tell than over-enthusiasm.
3. Validate with `skills/writer-style/tools/validate_voice.py` and the generate-and-blind-compare
   test in `method/agent-prompts.md` before trusting the pack.
4. Then pass your pack in the workflows' `tone` arg (e.g. `"thom 0.8 / hotz 0.2"`).

**Voice-seam warning:** 35/35 lessons are already drafted in the kaue-blend voice. If you rewrite
or add lessons in your voice, Board C (rhetoric) and Board D (cold read) must explicitly check the
seam between the two registers — the same issue the wave already tracks for digital-assets'
Fable/Opus split. The cheaper path: keep existing drafts, apply your voice to fixes/expansions, and
let Board C harmonize.

## 2. Where the course stands (2026-08-31)

| thing | state |
|---|---|
| Drafts | **35/35 lessons + cover written** (`lessons/drafts/`, stems `m00-l1-m01-l1.md` style — positional module prefix ≠ real lesson id) |
| Module verifies | **0/10 — all owed.** The write workflow's verify stage died on a session limit. Re-run: `Workflow _write.wf.js {courseId:"solana-client-side-mastery", tone:...}` — writers keep complete on-disk drafts, only verify runs live. Verify also produces the carry-over notes Board A needs. |
| Coding challenges | 9 dirs on disk (m01-l2, m02-l3, m03-l2, m04-l4, m05-l1, m06-l1, m07-l1, m08-l1, m09-l2). **≥4 are known to violate the challenge-executor contract** (below) — run `verify_challenges.py` and fix all violations before boards. |
| Quiz answer-length tell | **137/151 single-selects have the correct option as the longest** (learners can score by guessing long). Must end <40%. |
| Boards / visuals / export / PR | none run yet |

Module map (10 modules, artifact domain "Pit Wall" — a race-engineer's console for your own
on-chain operations): m01 client's-Solana → m02 kit-v7 stack & RPC engineering → m03 wallet & UX →
m04 compute & fees → m05 landing science → m06 Jito/BAM/MEV → m07 DEX aggregation → m08 streaming
data → m09 indexing & history → m10 pit-wall capstone.

## 3. THE CHALLENGE-EXECUTOR CONTRACT (cost two CI round-trips on PR #48 — don't relearn it)

The platform grades TypeScript challenges by splicing sucrase-type-stripped code into a
`new Function` body in a **bare JS realm** (source: `solanabr/superteam-academy`
`packages/challenge-executor`). Three rules, all enforced locally by
`skills/content-gen/tools/verify_challenges.py` (PR #2 of this repo):

1. **No ESM value syntax.** `export function` survives type-stripping and is a SyntaxError in the
   splice — every test fails identically. `export interface/type` is erased (harmless). Imports:
   only `@solana/web3.js` is mocked; anything else = undefined names. Challenges are self-contained.
2. **No web APIs.** Only `TextEncoder`/`TextDecoder` are mocked. `URLSearchParams`, `URL`, `fetch`,
   `Buffer`, `btoa`… all throw ReferenceError. Build query strings by hand with
   `encodeURIComponent` (core JS is fine).
3. **First-match function detection.** The executor calls the FIRST `function name(` or
   `const name = (` match in the file — even a parenthesized non-function initializer like
   `const CAP = (10);`. The graded function must be the first such construct.
4. Test `input` strings are **comma-split positional scalars**: each fragment must be a number
   (incl. `123n`), a `'quoted string'`, `true/false/null`, or a grader-bound identifier. No object
   or array literals. Irreducibly structured data → one quoted JSON string + `JSON.parse` inside.

Symptom signature of all of these: solution passes local tsc/node, **fails EVERY test identically**
in CI's gate-6. `verify_challenges.py <course>` now catches all four locally — trust a FAIL from it.

## 4. Remaining pipeline (in order, with the traps)

Each phase = one workflow run. **One heavy fan-out per usage window** — two parallel 40-agent runs
split the budget and both die at the tail (the fix/gate half, which is the half that applies
findings). On a session-limit death, resume the SAME runId+args (same session) or relaunch the same
scriptPath+args (fresh session — writers/fixers are idempotent against disk). Disk is always ahead
of the workflow's reported result: check `lessons/drafts/` before re-running anything.

1. **Verify** — re-run `_write.wf.js` (writers replay free, 10 verifies run). GATE: PASS on
   `validate_course.py all` + `drafts`.
2. **Challenge compat pass** — `verify_challenges.py content/courses/solana-client-side-mastery`;
   fix every FAIL (tests + starter + solution + the lesson prose that quotes the signature — keep
   all four in sync; the draft's fenced starter block must match the shipped starter file).
3. **Boards** — `_boards.wf.js {courseId, tone, notes:<verify carry-overs>}`. Four boards: A
   facts+code (re-verifies the 7 write-time probes LIVE), B pedagogy, C rhetoric/voice/quiz, D cold
   read → fixer → gate + `boards-report.md`. **Trap:** Board C previously wrote quiz fixes into
   `briefs/*.brief.yaml`, but quizzes ship from **`manifest.json` → lessons[].brief.quiz_blocks** —
   either patch Board C's prompt to edit the manifest (via `quiz_balance.py split/merge`) or port
   briefs→manifest afterwards with a structural-invariant check (question ids, option ids/order,
   `correct` flags must not move).
4. **Quiz balance** — `quiz_balance.py report` must end <40% longest-correct (from 91%). Rebalance
   = trim over-long answers into `explanation` + lengthen distractors. `merge` refuses structural
   moves, so a per-lesson fan-out is safe.
5. **Canon check** — current chain facts the whole wave standardized on (payments is the reference):
   target slot time **300ms** (SIMD-0525 stage 2, epoch 1024, 2026-08-28; 400ms/350ms only as
   history), blockhash window = 150 blocks × slot time ≈ **45s** ("derive, never memorize"), ATA
   rent **2,039,280 lamports ≈ 0.00204 SOL**. Board A verifies live; if it corrects a number, sweep
   the WHOLE course for the pattern (drafts, quiz text, challenge fixtures, visual specs) — partial
   fixes make the course internally inconsistent, which is worse.
6. **Visuals** — `render_visuals.py scaffold` (writes `v*.html` starters from draft visual blocks,
   idempotent) → `_visuals.wf.js {courseId}` (author → render → per-lesson PNG review → fix →
   gate). Traps: never run a course-wide `render`/`review` while per-lesson reviewers are live
   (shared per-asset intermediates race); if a lesson gains/loses a visual block, slots renumber —
   migrate the shifted authored HTML (spec comments tell you if they match), run `decorate`, delete
   the orphaned old-slot files AND their PNGs.
7. **Banner** — `render_visuals.py scaffold-banner` → author per `brand/brand-guide.md` (WeasyPrint-
   safe CSS; emerald hero, yellow on ONE element) → `render-banner` → open the PNG and judge it.
8. **Export** — `academy_export.py emit --course ... --out <academy-courses>/courses/<slug>`.
   **This course's `course_id` needs an override:** `course-solana-client-side-mastery` = 33 chars,
   over the 32-char CI cap. Set in manifest: `academy: { course_id: "course-client-side-mastery",
   creator: <wallet — PR #48 used 3WECquwCtcKVRYNWBPFWE28ag3b1CDKchLZPXxifAJzQ>, difficulty: ...,
   skills_map: {<module teaches_skills node>: <one of the 8 skills.yaml slugs>},
   default_skills: [...] }`. Without a skills_map, lessons export skill-less. The 8 permitted
   slugs: solana-fundamentals, account-model, transactions, keypairs-wallets, rpc-reads,
   solana-programs, anchor, solana-kit. Never invent slugs.
9. **Pre-flight** (the app repo's real linter isn't local): validate the emitted tree against
   `<academy-courses>/schema/*.json` with `jsonschema`; **diff the export against a fresh emit to a
   temp dir** — any "Only in" file is a stale orphan CI will flag (the exporter is additive, it
   never deletes); grep the export for em-dashes (challenge comments, manifest quiz hints, and
   visual labels all leaked them at least once — house rule is zero, fix by syntactic role, never
   blind comma-substitution); nothing over 1 MiB.
10. **Pre-PR review** — 3 parallel cold-read agents over the EXPORTED tree (early/middle/late
    slices): structural integrity, canon consistency, quiz sanity. On payments this caught a 1000×
    numeric error in quiz feedback and a lab whose gate passed vacuously — cheap insurance.
11. **PR** — branch off FRESH `origin/main` of `solanabr/academy-courses`; the PR touches ONLY
    `courses/<slug>/` (pilula precedent, e72eb74; no CATALOG/skills/paths edits — raise the
    catalog-row question in the PR body). Ship at trackId 0 / trackLevel 0 (adopted-electives
    lane; both fields immutable on-chain). Copy PR #48's body structure: gates evidence + explicit
    owner notes for anything a human still owes (e.g. a live run of the flagship labs).

## 5. Expansion points — where the course can go deeper

Grounded in the module map; each is a natural add-on lesson (or a follow-up elective) that the
current outline deliberately scoped out:

- **m05 landing science → SWQoS and the QUIC layer.** Stake-weighted QoS mechanics, leader-schedule-
  aware submission timing, and why landing behavior changes as slot times keep stepping down
  (SIMD-0525 has two more staged cuts, 250ms and 200ms, already gated in code).
- **m06 → searcher-side MEV.** The course teaches the client-dev defensive view; a deep-dive on
  bundle simulation, tip-optimization curves, and the BAM plugin landscape is the offensive half.
- **m08 streaming → Yellowstone gRPC/Geyser.** WebSocket subscriptions are the floor; Geyser
  plugins, snapshot+replay ingestion, and commitment-aware dedup are what production indexers run.
- **m09 indexing → reorg-safe ingestion + compressed assets.** Historical backfill via archival
  RPCs, fork-aware upserts, and DAS-based indexing of compressed accounts/cNFTs.
- **m03 wallet UX → wallet-standard internals, embedded wallets/passkeys, mobile wallet adapter.**
  The course stops at adapter usage; the standard itself and the mobile path are their own lessons.
- **m02 kit stack → kit v8.** v8 exists (the wave pins ^7 per ecosystem peers); a "what v8 changes"
  lesson will be due when `@solana-program/*` and `@solana/react` move.
- **Alpenglow.** Slated "late 2026" — when it lands, m05's confirmation/finality material and every
  latency number in the course changes; that's either a major revision or a capstone-follow-up
  module. The course's own "derive it, never memorize it" refrain is the hook.

## 6. Fast context links

- Shipped reference PRs: solanabr/academy-courses **#44** (anchor-v2), **#48** (payments)
- Toolchain hardening PR (executor-contract rules live here): solanabr/content-gen-skill **#2**
- Writer-style skill: **https://github.com/solanabr/writer-style-skill**
- Executor source of truth: solanabr/superteam-academy `packages/challenge-executor/src/executor.ts`
  and `packages/content-lint/src/checks/` (the CI gates)
- Wave docs (ask Kaue for the dir): `content/wave2/CHECKPOINT.md`, `WAVE.md`,
  `boundary-adjudication.md`, `content/wave2/solana-client-side-mastery/outline-v2.md`
