# DESIGN SPINE — the always-on pedagogical non-negotiables

*This is the keystone, the analog of the voice skill's always-on spine. Where that spine owns the
**tone**, this owns the **teaching**. It is **always on** — applied to every course, whatever pattern the
router picks. The patterns shape; the spine decides whether the shape actually teaches.*

> **The top rule — design BACKWARD, sequence FORWARD, and put every concept inside a shippable thing.**
> Start from the outcome and its proof; sequence up the prerequisite graph; never teach a concept the
> learner can't immediately *use* on a real artifact. A course that is complete but unsequenced, or
> sequenced but passive, is the structural equivalent of over-tidy prose: it stops feeling like a
> builder's path and becomes a textbook.

---

## 0. The essence (prompt-primer)
A great Solana course is **a graduated series of real builds, ordered by what each one depends on, with
the scaffolding quietly removed as the learner gets stronger.** It opens on a **felt problem** (never a
definition), reaches a **first win fast**, introduces each concept **the moment a build needs it**, shows
a **worked example before asking for one**, **names the trade-off** of every design choice, and **proves
mastery by making the learner do the thing** — not watch it. It respects the learner's **prior model**
(an EVM dev and an absolute beginner do not start in the same place) and protects **momentum** above
completeness. Design *that*, every time.

---

## 1. Backward design — outcome → assessment → activities (do this first, always)
Never start from a topic list. Start from the **terminal outcome**, written as a measurable, Bloom-tagged
capability: *"By the end, the learner can **build, test, and deploy** a PDA-backed SPL-token vault with
correct signer and owner checks."* Then design the **capstone/assessment that would prove it**. *Only
then* derive the modules that lead there. Every module and lesson must trace to an outcome; if it doesn't,
cut it. (Wiggins & McTighe.)

- **Objectives use action verbs, never "know/understand."** Tag each with its Bloom level; the course
  should *climb*: define → explain → implement → analyze → design.
- **Every outcome has a matching proof.** No outcome without an assessment; no assessment without an
  outcome.

## 2. The prerequisite DAG is law (sequence forward)
Solana imposes a real dependency order (`references/solana-syllabus-dag.md`). **No lesson may depend on a
skill not yet taught.** The consensus spine: Rust basics → account model → programs/instructions →
transactions/fees → PDAs → CPIs → SPL tokens → security → DeFi composites.

- **Choose the entry point by the learner's prior model**, not by the topic's logic. EVM devs lead with
  the 1:1 mappings (compute≈gas, errors≈revert) for early wins, *then* hit the genuinely different parts
  (accounts/storage, PDAs). Beginners lead with the account model. The DAG is the same; the door changes.
- **Front-load the mental model only as far as the first build needs it.** Don't teach all of rent, BPF,
  and Sealevel before there's a program to attach them to (see §4, just-in-time).

## 3. Build-first / whole-task — every concept lives in a shippable artifact
The atomic unit is a **build or an auto-checkable task**, not a passive lesson. Each concept is taught
*inside* a real artifact the learner ships. Use the **canonical artifact ladder** as the spine of the
builds: `hello-world → counter (state) → SPL token → a PDA app (vault/escrow/review) → DeFi (AMM/auction)
→ composability (CPI) → freeform capstone`. (4C/ID whole-task; PBL.)

- **One accreting artifact where possible** — a single project that grows (à la the zombie game) gives
  every new concept an immediate home and compounds motivation.
- **A driving question per module** — "how do we let users stake SOL trustlessly?" — not "chapter 4:
  PDAs."

## 4. Manage cognitive load — one new thing at a time, concrete-first, just-in-time
Working memory is tiny. Cut **extraneous** load, manage **intrinsic** load, protect **germane** load.
(Sweller.)

- **Provide a scaffold / zero-install on-ramp.** A working Anchor/Rust starter, a Playground/Docker path —
  so the learner spends budget on the concept, not the toolchain.
- **Introduce one new element per step.** Never make a beginner fight Rust lifetimes *and* Anchor macros
  *and* on-chain semantics at once.
- **Concrete before abstract.** A specific token transfer before the general CPI/account model; the
  pattern before the principle. (Concreteness fading.)
- **Just-in-time concepts.** Define a concept at its first point of use, with the gotcha flagged right
  there as a NOTE/TIP/**Footgun**.

## 5. The fading-scaffold triad — worked example → completion problem → solo build
The single most reused move in the corpus (Overview→Lab→Challenge; guided→guided→unguided;
worked→completion→solo). It *is* the worked-example effect plus scaffolding/fading.

- **Show a fully worked, annotated example first** (novices learn more from studying than from floundering).
- **Then a completion problem** — a skeleton with TODOs (the learner writes the missing instruction).
- **Then a from-scratch task** with the scaffold removed.
- **Fade across the module and the course.** Difficulty curve = fading schedule. **Remove worked examples
  in advanced modules** (expertise-reversal: they start to hurt the proficient).

## 6. Gate on doing, not watching — proof of learning is non-negotiable
Every lesson ends in a retrieval or a build the learner must complete; every course ends in a **capstone**.
Pick a proof model to fit the context and credential goal:
self-assessment + provided solution → auto-graded tests → on-chain cryptographic verification →
capstone build → completion NFT / certificate. **Completion is gated on producing something**, never on
finishing the videos. Provide solutions "as a resource, not a crutch."

### 6.1 Formative checkpoints — artifacts gate, quizzes check
A lesson's *terminal* proof is `assessment` (a build or retrieval the learner must complete). **Formative**
checks — the `quiz_blocks` and optional `coding_challenges` in a brief (lesson-brief-schema §H) — sit
*inside* the lesson and give immediate feedback; they never gate passing. Guidance:
- **Quizzes** verify understanding with per-option feedback and an explanation; put them after the
  overview (concept check) and/or after the lab (readiness check). Language-agnostic — even a Bitcoin or
  CLI lesson earns one. They award no gate. **Never choose the option order**: write the options in
  whatever order they occur to you and let `tools/quiz_layout.py permute` assign it from a hash.
  Hand-ordering is a gate failure — anyone asked to "spread the answers evenly" produces a *scheme*,
  and a scheme is exactly what a learner learns to read
  (references/academy-schema.md §Option order is computed, never chosen).
- **Coding challenges** are runnable, RUST/TYPESCRIPT-only exercises whose grade IS the test run: the
  starter must fail, the solution must pass (`tools/verify_challenges.py` proves it). Use them where the
  lesson's real code is Solana TS or a Rust/Anchor program; a base challenge can double as the lesson's
  `assessment`, extra ones are labelled bonus and never required.
- These are the **Academy platform plugins** (`references/academy-schema.md`); `tools/academy_export.py`
  materializes them. They are **additive** — a lesson without them is unchanged.

## 7. Name the trade-off — on every design choice (the credibility engine, and the voice bridge)
Every concept the course teaches has a cost, a limit, or a "when not to use it." **Surface it.** This is
both good engineering pedagogy *and* the exact hook Kaue's voice spine needs ("always name the
trade-off"). A brief that ships a named trade-off writes itself in his voice.

## 8. Momentum & motivation — one "aha" per unit, a fast first win, anti-pattern honesty
- **One sharp "aha" per lesson** — a single mental unlock, not a topic dump.
- **A fast first win** — the learner should *do* something real and see it work early ("by the end of
  Lesson 1 you can deploy a program"). Bank small victories before the hard parts.
- **Teach the footguns explicitly** — a named "Common Bugs / Footguns" treatment beats scattered warnings.
- **Color carries momentum** — named history, dated failures, and war stories (grounded, never invented)
  are teaching devices, not decoration; the strongest courses teach *through* them.
- **Productive failure, sometimes.** For a few key ideas, let the learner *attempt* the hard thing before
  the clean solution ("try to stop this double-spend"), then consolidate. Pairs with exploit-first security.

## 9. Retention by design — spaced retrieval, interleaving, spiral
- **End modules with retrieval** (a question or a build), not rereading. (Testing effect.)
- **Reuse earlier concepts in later projects** — account validation should reappear in every build.
- **Spiral / 101→201** — revisit a hard topic deeper later rather than exhausting it once.
- **A cumulative checkpoint** before the capstone.

## 10. The anti-over-engineering floor (the "naturalness floor" analog)
The voice spine's deepest rule is *don't smooth prose into a tell.* The design analog: **don't smooth a
course into a curriculum no one finishes.** Protect these against the urge to be exhaustive:

- **Completeness is not the goal; capability is.** Cut topics that don't serve the terminal outcome, even
  correct, interesting ones. A tight 6-hour course that ships beats a 60-day one that's abandoned.
- **Tight in scope, generous in depth.** The axe falls on TOPICS, never on explanation: within a kept
  topic, favor over-explaining — demonstrate, then explain the implication, then say where it resurfaces.
  A lesson that names a concept without developing it is a stub, not a lesson.
- **Uneven difficulty is fine and human** — plateaus of routine practice between spikes of new, hard
  ideas. Don't make every lesson equally dense (that's the structural "even-tidiness" tell).
- **Don't gold-plate the scaffolding.** Enough starter code to remove friction, not so much that there's
  nothing left to build.
- **Leave room for the writer.** The brief specifies *what* and *why*; it does not pre-write the prose,
  the jokes, or the analogies — that's the voice skill's job. An over-specified brief strangles the voice.

---

## 11. Voice-congruence calibration (how this spine harmonizes with `writer-style`)
The two skills are designed to snap together. Architect so that writing in Kaue's voice is *natural*:

- **Every lesson brief carries a felt hook** → feeds his **pain-first** opener.
- **Every concept ships its trade-off** → feeds his **always-name-the-trade-off** move.
- **Every lesson is a real build with real numbers** → feeds his **build-in-public, order-of-magnitude**
  proof.
- **Every brief carries a `dominant_job` tag** (`show-how | derive-why | demystify | economics | frame |
  sustain | motivate`) → feeds the **voice router** directly (Helius / Vitalik / Hotz / Hayes / Balaji /
  spine). See `lesson-brief-schema.md`.
- **Course openers and "why this matters" beats** are tagged `motivate` → carried by Kaue's spine, not a
  craft backbone (the voice skill's own rule).

> Net: the architecture decides *what is taught, in what order, proven how*; it leaves *how it sounds* to
> the voice. Design briefs that are a gift to the writer — a hook, a trade-off, a real artifact, and a job
> tag — and the two skills produce one coherent course.

---

### Worked micro-illustration (the spine, applied in one breath)
> **Topic:** PDAs. **Audience:** EVM devs. **Outcome (Bloom: implement):** *learner can derive a PDA and
> use it to store per-user state.*
> Backward: capstone uses a PDA vault, so this lesson must end in a working PDA write. DAG: accounts +
> programs already taught; CPI comes *after* this. Entry by prior model: "In Solidity you'd use a
> `mapping(address => ...)`; Solana has no mappings — here's the felt problem." Build-first: extend the
> running counter to be per-user. Load: introduce *only* `find_program_address` here; defer signing-with-a-PDA
> to the CPI lesson (just-in-time). Triad: show a worked derivation → completion problem (fill the seeds) →
> solo (add a second PDA). Trade-off to name: PDAs are deterministic and bump-canonical, but you must store
> the bump or recompute it — and the wrong seed scheme is an exploit. Proof: test passes that two users get
> distinct, recoverable accounts. `dominant_job: derive-why` (a contested "why no mappings") → voice routes
> Vitalik craft over Kaue's spine.

*(Outcome-first, DAG-respected, prior-model door, one concept, worked→completion→solo, trade-off named,
gated on a passing test, voice-ready. That is the spine.)*

Sources behind these rules: `references/instructional-design-canon.md` — load only when challenging
or extending a spine rule, never routinely.
