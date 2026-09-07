# Form: course

The meta-form: a multi-module curriculum that *sequences* the other forms
(tutorials, walkthroughs, explainers, slides) up a prerequisite DAG toward a
capstone. Machinery: the course pipeline in `../SKILL.md` (12 steps, manifest,
`tools/validate_course.py` gate, `content/courses/<id>/` emission). This file is the
form-level recipe — what a good Solana course IS, distilled from a 7-course corpus
teardown (`courses-corpus/PATTERNS.md`; per-course `META.md` files for depth).

**Scale band:** 3+ modules / 6+ lessons; below that, route `tutorial`.
**Visuals default:** `light` (per lesson).

## Corpus stance (read first)

The corpora are teachers, not templates. Analyze them to learn WHY a move works
(named history carries momentum; layered exposition sticks; cliffhangers pull),
then express the move in THIS house's way — lab-first, empowering, faster. A
lesson whose structure or beats can be traced 1:1 to a corpus exemplar is a
defect (quality-bar JUDGE row); we are not any of them, and the target is to be
measurably better, not adjacent.

## Bookends & narrative flow (non-negotiable)

- **`000-cover.md` is an INDEX, never a lesson.** It carries only scannable
  reference — the one-line promise, audience, tools, concepts, module map,
  outcomes, time. NO narrative, history, or teaching content: that opens the
  first lesson. Duplicating context onto the cover while a lesson also teaches it
  is the defect this rule prevents. The emitted tree opens with an
  objective cover page (scaffold generates it from the manifest): full summary
  of what is covered, prerequisites, tools/libraries/SDKs used
  (`course.toolchain`), concepts tackled, module map, time budget, outcomes.
  Direct and scannable — everything a person checks BEFORE committing to a
  course, zero storytelling.
- **A course opener lesson, always** — `dominant_job: motivate`, and it already
  puts code in the reader's hands: the felt problem the course answers,
  demonstrated with 1–2 runnable micro-demos in the first minutes (make them DO
  the problem, not read about it), the arc map, what they'll have built, and
  the house rules. The reader should feel smart twice before the lesson ends. A
  course that opens on pure story loses the 2026 reader as surely as one that
  opens on an unexplained wall of commands.
- **A conclusion lesson** — what was built, the concept map re-stated, where to go
  next. Never end on the last exercise.
- **Every lesson carries the thread** — `flow.recap` (one line: where we stand,
  calling back the previous artifact) opens it; `flow.forward_hook` (a cliffhanger
  or promise, corpus-style: "Then in 2008, a pseudonymous developer published a
  solution") closes it. A lesson that could be shuffled into any order has no arc.
- **Color is content** — 1–3 pieces of grounded trivia/history per lesson (named
  incidents, dated failures, war stories: DigiCash's bankruptcy, the 2017 SHA-1
  collision, Cyprus 2013). The corpus exemplars teach *through* these, not around
  them. Ground them like any other fact.
- **Write generously, move fast.** Favor over-explaining: state the fact,
  demonstrate it, then explain the implication and where it resurfaces later.
  But pace it for 2026 attention — short runs, frequent payoffs, the reader
  feeling smart/empowered every few paragraphs ("you just did X", checkpoints
  that land). Course lessons run long by design — roughly 3000–4500 prose words, more for
  keystone/foundational topics and less for narrow ones (judge by the topic,
  not a target). This is enforced through the **brief's `est_length`** — that
  number is the writer's contract, the validator flags targets under 3000w, and
  the NEXT.md handoff repeats it — so length is driven by the spec, never by
  hand-padding a draft. A lesson that only gestures at its subject reads thin;
  past ~5500 words it is usually two lessons.
  Tightness lives at SCOPE level — cut topics, never explanation (§10).
- **Paragraphs breathe.** Vary paragraph length from a one-sentence punch to a
  four-sentence developed run; a page of uniform two-line paragraphs reads like
  phrases stitched together, and a page of uniform blocks reads machine. The
  validator flags staccato distributions (advisory) — the fix is developing
  ideas, never padding them.
- **Visuals scale with length — hard rule, and they must PARSE.** The floor is `max(2, ceil(prose_words / 600))`: a short lesson carries 2, a ~2,400-word lesson carries 4. More text earns more graphics; the ratio is a floor, not a metronome — place each visual where it certifies a payoff, never on a beat. Only
  blocks with all six fields and a valid type count toward the floor
  (`validate_course.py drafts`); two blocks should show two different KINDS of
  visual thinking (type diversity is advisory). Course lessons run
  `visuals: rich` by default.
- **No em-dashes.** The em-dash is the top AI tell; the house ships essentially none.
  The writing pass ends with `tools/dedash.py` (deterministic), and
  `validate_course.py drafts` HARD-fails >2 em-dashes outside code. writer-style only
  *advises* on em-dash overuse and counts whole files, so this is enforced on our side.
- **Text-block aesthetics.** Long explanation never pools into a wall: a
  stretch of prose is broken by the thing it explains — a runnable fence or a
  visual — as a natural rhythm, not a fixed pattern. The validator flags
  450+-word runs and HARD-fails 700+. Same instinct at the top: something to DO
  inside the first 300 words of every lesson (150 for the opener).
- **The accretion graph is checkable.** Build lessons declare
  `artifact: {id, consumes: [...]}` in the brief; edges must run forward and
  non-terminal tools get consumed downstream ("the toolkit becomes the bot" as
  a DAG, not a promise). Orphans are flagged; deliberate dead-ends carry
  `terminal: <reason>`.
- **Checkpoint contract.** The from-memory close states its answer shape
  ("if your sentence lands anywhere near X, you have it") so it stays a
  30-second win, not an anxiety gate — vary the phrasing per lesson.
  `assessment` may be a string or `{gate, answer_shape}`.

## Structure recipe (corpus-validated defaults)

- **Artifact ladder** — the corpus consensus rung sequence: counter (state) → SPL
  token → PDA app → freeform capstone. Give the heavy rungs a *relatable domain
  of your own invention* — the corpus shows why the move works (Risein's
  restaurant-review app is the famous case); reusing a studied course's artifact
  is a blocklist HARD failure (`../references/corpus-signatures.txt`).
- **One lesson shell, enforced** — `Summary → theory (ONE header name, pick it
  once) → numbered Lab → Challenge → feedback beat`, with the autonomy fade stated
  out loud: "don't code along in the overview; absolutely code along in the lab;
  do the challenge alone." Template drift kills the shell's value.
- **Fundamentals ordering is a deliberate fork** — bottom-up canon
  (accounts→programs→PDAs→CPIs), top-down (start from the tx a user submits), or
  map-from-known inversion (frontload the prior-model 1:1s to bank wins — EVM
  audiences only, gate on the prior). Pick one and say why; don't drift.
- **build-it-twice, sequential variant** — Anchor throughout, then ONE late
  "strip the framework" module rebuilding the same primitives native (~80% of the
  payoff at ~1× cost). Reserve every-rung dual-track for auditor outcomes.
- **Proof-escalation ladder** — within exercises: in-process SVM test (LiteSVM/
  Mollusk) → localnet + demo script → devnet deploy, with `solana program close`
  rent hygiene baked in. A real on-chain moment, no autograder to maintain.
- **Practice shape — artifacts gate, quizzes check.** Distributed per-unit tasks
  converging on one integrative capstone. Every **gate** is artifact-based
  (build/deploy/exploit/inspect) and **no MCQ ever gates a lesson** — the corpus
  agrees; nothing in it is gated on a quiz. But the corpus having zero quizzes *at
  all* is a gap, not a rule: spaced retrieval is its worst weakness, and the spine's
  retrieval checkpoints (`../design-spine.md` §9) are the edge. So every lesson also
  carries a formative quiz (`quiz_blocks`, `../lesson-brief-schema.md` §H) that gives
  per-option feedback and awards nothing. The distinction is the point: a quiz that
  gated would have to be unguessable to be fair, and a quiz that only checks still
  has to be honest — which is why `validate_course.py quiz` measures it either way.
- **Security tier** — late, offense-first (exploit → patch → re-test), assessed by
  making the learner *write the exploit* ("green test = you broke it") or fuzz.
  Gate behind build fluency; inline Footguns earlier.
- **Client half** — the most-skipped part of the corpus; if the outcome is a
  usable dApp, thread `client-integration` explicitly rather than assuming it.
- **Cadence affordance** — publish a measured (not back-computed) time budget per
  unit; centralize version pins so re-pinning is one edit, not a hunt.

## Brief

Course/module/lesson specs per `../lesson-brief-schema.md` §§A–C (lesson `kind:
build|concept`); the deterministic gate and emission per `../SKILL.md` steps 11–12.

## Checklist (form-level; the validator covers structure)
- [ ] `000-cover.md` present and current (re-emit after manifest edits).
- [ ] Opener lesson present (motivate + runnable micro-demos) and a conclusion lesson closes the arc.
- [ ] Every draft carries ≥2 visual blocks (`validate_course.py drafts`).
- [ ] (Optional) render the ` ```visual ` specs to on-brand PNGs — `tools/render_visuals.py`
      per `../references/visual-rendering.md` (opt-in; needs WeasyPrint). Additive: the specs
      stay in the drafts; PNGs land under `lessons/assets/`.
- [ ] If rendered, the **review pass is clean** — `render_visuals.py review` + the fresh-eyes
      visual QA in `../references/visual-review.md`; no card overflows, overlaps, or clips.
- [ ] No lesson traceable 1:1 to a corpus exemplar — learned from, never copied.
- [ ] Every lesson has `flow.recap` + `flow.forward_hook` and ≥1 grounded piece of color.
- [ ] Lesson shell uniform across all lessons; fade stated explicitly.
- [ ] Fundamentals ordering chosen deliberately and named in `course.yaml` notes.
- [ ] Every rung has an interim check — no capstone-only practice (a learner must
      not be able to watch three builds and hit the capstone cold).
- [ ] Every lesson carries a formative quiz; option order was assigned by
      `tools/quiz_layout.py permute` (never by hand) and `validate_course.py quiz`
      is clean, with no metric sitting at INCONCLUSIVE that a few more questions
      would resolve.
- [ ] No honor-system gates where proof-of-mastery is a stated feature.
- [ ] Toolchain explicit (framework, harness, cluster) and versions pinned once.
- [ ] No stub lessons — every emitted lesson is self-contained without a video.


## Hardening rules (distilled from review — each prevents a shipped defect)

These are non-negotiable and mostly machine-enforced; the JUDGE ones are read by the reviewer.

- **When a statistical property must hold, COMPUTE IT IN A TOOL. Never ask for it in
  a prompt.** A stronger instruction produces a different artifact, not randomness.
  The worked example is the quiz answer key. The gate HARD-failed ">50% of keys in
  one slot", so the wave-2 generator was told to seed each module's first answer at
  `module_index % 3` and rotate forward. It complied perfectly: every wave-2 course
  is near-perfectly balanced on the marginal the gate measured, and 85-94%
  predictable on the sequence it did not. Nine of ten courses passed. Option order
  is now assigned by `tools/quiz_layout.py permute` from a hash and recorded in a
  ledger; hand-ordering is a gate failure. Apply the same test to any new rule you
  are tempted to write into a prompt: if a script could check it, a script should
  produce it.
- **No editor/agent scaffolding in a draft.** A lesson opens on its `#` H1 title; any
  text above it ("Returning the fixed lesson:", "I've identified…") is leaked agent
  reasoning. HARD: `validate_course.py drafts` fails a draft that does not open on H1.
- **Honest recaps (no fabricated callbacks).** `flow.recap` may reference ONLY what the
  previous lesson actually did or produced. Do not claim the reader "stored a number" or
  "handed over an account list" if that lesson never had them. JUDGE + writer instruction.
- **Demonstrate, don't assert, accretion.** If the course promises "the toolkit becomes
  the bot," a late lesson must SHOW a prior rung being wired in (a worked step), not just
  state it. A capstone that hands over a pre-built artifact fails the promise.
- **Teach languages honestly.** Declare every language a lab makes the reader AUTHOR
  (Solidity, Rust/Anchor, TS…), state the true reading level in the prerequisites, and
  teach each just-in-time with a short "you don't need to know X; here's the 30-second
  version" on-ramp. Never silently assume a language the stated prerequisite doesn't cover.
- **Version pins carry a freshness note.** Any pinned toolchain version/command in a
  brief or draft (Agave CLI, Anchor, crates, SDKs, Solidity) ships with a "verify against
  current docs; tracks <release train>" note, because it rots fast. Ground it live at
  authoring time; never freeze a version from memory.
- **Scope claims match what's taught.** Don't promise "ship to mainnet/production," a DEX
  swap, or a bridge unless a lesson actually teaches it; otherwise mark it an explicit,
  clearly-labelled bonus/extension and say "beyond this course."
- **length_target.lessons matches reality.** HARD: `validate_course.py length` fails if the
  declared lesson count drifts from the actual count (the cover renders it).

## The runnable-code gate (biggest lesson from round-2 review)

A "run-first" course must ship code that ACTUALLY RUNS. LLM generation produces
plausible-but-uncompiled code (round 2 found a non-compiling `CpiContext::new`, an
`ImportError`, scalar-vs-array RPC params, a missing `__main__` guard whose output
contradicted the narration, and a `forge init` that clobbered its own test). Structure/
voice/facts gates do NOT catch these. Before a course is "done":
- **Execute the runnable content in a real toolchain — `tools/verify_code.py`.** It
  extracts every fenced code block from `lessons/drafts/*.md` and compiles/runs it:
  `python3 tools/verify_code.py content/courses/<id>` (local) or `--env docker` to run
  inside the pinned, version-matched toolchain (`verify/Dockerfile`: anchor/forge/cargo/
  solana/node/python at the versions the content DECLARES — a local toolchain that
  disagrees is reported, never trusted). It is CI **tier 5** (`ci.py --tiers 5`, or
  `VERIFY_ENV=docker`). A `FAIL` is a real compile/run break and blocks done; a `SKIP`
  means that language needs the container — resolve every SKIP by running `--env docker`,
  do not ship on SKIPs alone. Where no toolchain is reachable at all, an adversarial
  code-correctness review (solana-researcher + live docs) is the mandatory proxy.
- **Every lesson shows its setup/install** for any tool it invokes (advisory gate added:
  `validate_course.py drafts` flags a tool used with no install step). Match it to the
  stated prerequisite.
- **Interactive coding challenges carry their own harder gate.** If a lesson brief adds a
  `coding_challenge` (Rust/TS only), the starter MUST fail its `tests.json` and the solution
  MUST pass — that contract is the grade. Prove it with `tools/verify_challenges.py
  content/courses/<id>` before publish (it is what the Academy platform runs for TypeScript on
  every PR). Author the challenge's solution from code that already verifies (reuse the course's
  `verify-anchor`/`verify-ts` harnesses), so the solution is real, not plausible.
- **Lesson code ↔ shipped code ↔ recap ↔ hook must agree** — reconcile them (round 2 found
  an `increment`/`initialize` desync and an account-model mismatch between two lessons).
- **A tool built in one lesson must be CALLED with that same interface in every later lesson.**
  Per-file syntax checks miss this; the only thing that catches it is assembling the
  multi-lesson toolkit into one dir and importing/running it (a later lesson `from x import y`
  where lesson-that-built-x never exported `y` is a hard `ImportError` the reader hits, not
  the author). When a lesson builds a reusable artifact, grep every later lesson's call sites
  against the built API before shipping. And **freeze the CORRECT (verified) API in the facts
  sheet** — a `frozen_fact` copied from not-yet-run code pins the bug in place and makes the
  facts gate defend it.
