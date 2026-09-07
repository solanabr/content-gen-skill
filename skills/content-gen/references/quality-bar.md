# Quality bar — non-negotiables, checklists, and the validation procedure

Never ship a course architecture without passing this. It is the structural analog of the voice skill's
quality bar: the place where good-enough drafts are caught and fixed.

---

## The non-negotiables (must all hold)

1. **Backward-designed.** A measurable, Bloom-tagged terminal outcome exists *and* a capstone/assessment
   that proves it — written before the module list. Every module/lesson traces to an outcome.
2. **DAG-respected.** No lesson depends on a skill not yet taught (check against
   `solana-syllabus-dag.md`). Hard edges never violated.
3. **Build-first.** Every concept lives inside a shippable artifact or an auto-checkable task. No passive
   lesson without a "do" (except deliberately non-technical concept courses).
4. **Load-managed.** A scaffold/on-ramp is specified; one new element at a time; concrete-before-abstract;
   concepts introduced just-in-time, not front-loaded.
5. **Scaffolding fades.** A visible worked-example → completion → solo progression; difficulty ramps;
   worked examples removed in advanced modules.
6. **Gated on doing.** Each lesson ends in a build/retrieval; the course ends in a capstone; completion is
   gated on producing, not watching.
7. **Trade-offs named.** Every taught concept ships its cost/limit ("when not to use it").
8. **Voice-ready briefs.** Every lesson brief has a felt `hook`, `the_tradeoff`, an artifact, and a
   `dominant_job` tag (`lesson-brief-schema.md`).
9. **Routed, not over-stacked.** One backbone + ≤2 guests + a lesson template; routed from outcome+audience,
   not topic (`routing/ROUTING.md` §4).
10. **Tight, not exhaustive.** Topics that don't serve the terminal outcome are cut (the
    anti-over-engineering floor, `design-spine.md` §10).

## Deterministic (tool-enforced) vs judgement (LLM/human)

The non-negotiables split into what a machine can prove and what needs a reader.
**HARD** items are enforced by `../tools/validate_course.py` and must pass before
emit; **JUDGE** items are weighed by the `course-architect` agent / a human (the
tool cannot see them).

| Non-negotiable | Enforcement | Where |
|---|---|---|
| DAG self-consistent (acyclic, no forward deps, ids resolve) | HARD | `validate_course.py dag` |
| Canonical Solana order respected (accounts→programs→PDAs→CPIs→tokens→security) | JUDGE + step-3 grounding | agent vs `solana-syllabus-dag.md` |
| Every lesson gated on doing; brief schema complete; `dominant_job` ∈ enum; id-unique | HARD | `validate_course.py briefs` |
| Artifact ladder monotonic; difficulty/cadence sane | HARD ladder / ADVISORY band | `validate_course.py ladder` |
| Capstone references only taught skills | HARD | `validate_course.py capstone` |
| Backward design closure (every outcome ⇄ a proof) | HARD | `validate_course.py outcomes` |
| Hook is *felt* (not a definition) | JUDGE | agent / human read |
| `the_tradeoff` is a *real* cost (not a platitude) | JUDGE | agent / human read |
| `dominant_job` is *correct* for the lesson's real job | JUDGE | agent (see lesson-brief-schema §D tiebreakers) |
| One new element per lesson (cognitive load) | JUDGE | agent / human read |
| Route fits outcome+audience; not over-stacked | JUDGE | agent (router §6 failure modes) |
| Brief is voice-ready but not over-written | JUDGE | spot-write one lesson |
| Briefs don't parrot the docs' worked exemplar (the PDA/'no mappings' lesson) | JUDGE | agent / human read |
| Course opens with a motivate lesson that puts code in hands fast; closes with a conclusion | JUDGE (+ADVISORY in validator) | agent / human read |
| Draft carries the scaled visual floor (max(2, ceil(words/600))), all PARSING; fences clean; no prose wall >700w; do-element in the first 300w (opener 150) | HARD | `validate_course.py drafts` |
| Every lesson carries a research scaffold; verified claims cite a kit surface; artifact accretion edges run forward | HARD | `validate_course.py research` / `artifacts` |
| No corpus signature in briefs or drafts | HARD | blocklist grep (`corpus-signatures.txt`) |
| Alt text could stand in for the visual; visual types show two kinds of thinking | JUDGE (+shape ADVISORY) | agent / human read |
| Pace fits 2026 attention: payoff/empowerment beat every few paragraphs | JUDGE | agent / human read |
| Not corpus-shaped: no lesson traceable 1:1 to an exemplar's structure/beats | JUDGE | agent / human read |
| Every lesson's `flow.recap`/`flow.forward_hook` real; lessons can't be shuffled | JUDGE | agent / human read |
| Exposition generous: implication explained after every demo; ≥1 grounded color beat | JUDGE | agent / human read |

`frame`/`demystify` as a whole-lesson `dominant_job` is an ADVISORY flag (they are
guest-only jobs) — the agent confirms or re-tags.

## Course-level checklist
- [ ] Terminal outcome(s) measurable + Bloom-tagged; capstone proves them.
- [ ] Audience + prior model identified; entry point chosen accordingly.
- [ ] Prerequisite DAG drawn; sequence respects it; no forward dependencies.
- [ ] Backbone + lesson template routed from outcome+audience; stacking budget respected.
- [ ] Artifact ladder threaded; difficulty ramps as a fading schedule.
- [ ] Assessment model chosen (self → auto → on-chain → capstone → credential); doing-gated.
- [ ] Length honest and tight; no outcome-irrelevant topics.
- [ ] Spaced retrieval / interleaving / spiral present; cumulative checkpoint before capstone.

## Lesson-brief checklist (per lesson)
- [ ] 1-3 measurable objectives, Bloom-tagged (no "know/understand").
- [ ] Prerequisites listed and already taught.
- [ ] `hook` is a felt problem/exploit/demo, not a definition.
- [ ] `concept_spec` introduces ONE new element; worked example specified.
- [ ] `artifact_spec` is a real build (a ladder rung / accretion).
- [ ] `exercise_spec` has a completion problem + a solo task + acceptance criteria.
- [ ] `the_tradeoff` present.
- [ ] `just_in_time.define` + `footguns` set; nothing front-loaded.
- [ ] `assessment` gates on doing.
- [ ] `dominant_job` tagged; `voice_notes` flag set where needed (esp. security).
- [ ] `difficulty` fits the fading curve; `est_length` set.

## The validation procedure (do this before handing off)
1. **Run the deterministic gate.** `python3 ../tools/validate_course.py all --manifest manifest.json`
   (and again `--course <dir>` after emit). Every HARD must pass. This mechanizes
   the outcome⇄proof trace, the DAG walk, the ladder, the capstone-coverage, and
   the brief schema — don't re-do them by hand.
2. **Run the JUDGE items.** Read for the judgement rows above: is each `hook`
   felt, each `the_tradeoff` real, each `dominant_job` correct, one new element
   per lesson?
3. **Run 3-5 representative course topics through the router** (`routing/ROUTING.md`)
   and check for the §6 failure modes (topic-routing, passive course, beginner
   cliff, security-too-early, twice-build bloat, over-stacking, untagged handoff).
4. **Spot-write one lesson from its brief** (or pass it to `writer-style`) and
   confirm the brief is sufficient and voice-ready — a felt hook, a named
   trade-off, a real artifact, a clear job. If the writer would have to invent
   structural facts, the brief is underspecified; if it dictates the prose, it's
   overspecified.
5. **Accuracy gate (IN scope at design time).** Grounding is mandatory:
   `references/research-grounding.md` says DAG order, API names, artifact specs,
   and load-bearing numbers are verified against the Solana AI Kit's live sources,
   and each lesson's `research.yaml` records the evidence. The remaining human
   gate is a correctness review of the grounded claims before publish — note it in
   the course handoff. `onchain-number` facts go stale; the cadence freshness
   policy re-pulls them.

## Common defects → fixes (quick reference)
- Topic-list masquerading as a course → re-derive from the terminal outcome.
- Concepts before the build that needs them → move to just-in-time, at point of use.
- Even difficulty / every lesson equally dense → add plateaus; ramp; fade.
- Security sprinkled throughout for a build course → consolidate into a late tier or inline Footguns.
- Briefs with no `dominant_job` / no trade-off → fill them; they're the voice handoff.
- 60-day course no one finishes → cut to the outcome; tight beats exhaustive.


## Assessment layer — artifacts gate, quizzes check

Two different jobs, and conflating them is how a course ends up with neither.

**Artifacts gate.** Every check that decides whether a learner has the skill is artifact-based:
build, deploy, exploit, inspect, pass the test. `forms/course.md` §Structure recipe says "never
MCQs", and that is right *about gating* — the corpus has zero quizzes and no autograded MCQ has
ever gated a lesson here.

**Quizzes check.** A quiz is a formative retrieval beat inside the lesson: immediate per-option
feedback, no XP, no gate (`design-spine.md` §6.1). The corpus having zero quizzes is a **gap**, not
a rule — spaced retrieval is the corpus-wide weakness the spine's checkpoints exist to fix. Every
lesson earns one, including Bitcoin, EVM and CLI lessons where no code block is possible.

| Non-negotiable | Enforcement | Where |
|---|---|---|
| Option order is COMPUTED from a hash and recorded in a layout ledger; the ledger verifies | HARD | `validate_course.py quiz` + `tools/quiz_layout.py` |
| Answer key not exploitable: order-1/order-2 Markov accuracy vs a permutation null | HARD | `validate_course.py quiz` |
| Slot-repeat rate consistent with chance — **two-sided**, so never-repeats fails too | HARD | `validate_course.py quiz` |
| Key position + key length RANK uniform per option-count stratum, and not TOO uniform | HARD | `validate_course.py quiz` |
| No content-blind strategy beats chance (longest / shortest / only-hedged / no-absolute / prompt-overlap / least-like-the-others) | HARD | `validate_course.py quiz` |
| ≥4 options; exactly 5 when the mean label is ≤70 chars; multiSelect floors at 5 with 2 ≤ correct ≤ k−2 | HARD | `validate_course.py quiz` |
| `feedback` on EVERY option including the correct one; `explanation` on every question | HARD | `validate_course.py quiz` |
| No em-dashes anywhere in quiz text | HARD | `validate_course.py quiz` |
| Quizzes emitted INLINE in `lesson.yaml`; no standalone `*.quiz.yaml` | HARD | `validate_course.py quiz` (course-dir scan) |
| Any metric under its sample floor reports INCONCLUSIVE, not passed | HARD (by construction) | `tools/quiz_metrics.py` |
| Distractors are REAL misconceptions a learner of this lesson would hold, not near-misses invented to fill a slot | JUDGE | agent / human read |
| The prompt is a scenario tied to something the learner just ran, not a definition lookup | JUDGE | agent / human read |
| The correct option's `feedback` names the distinction, rather than saying "correct" | JUDGE | agent / human read |
| A multiSelect question is set-valued because the subject matter is, never to add difficulty | JUDGE | agent / human read |
| The quiz checks the lesson's ONE new element, not trivia from its color beats | JUDGE | agent / human read |
| No question is answerable from the lesson TITLE alone | JUDGE (+ answer-leak ADVISORY) | agent / human read |

**The law behind the HARD rows:** *when a statistical property must hold, compute it in a tool;
never ask for it in a prompt.* The previous gate HARD-failed ">50% of keys in one slot" and the
generator was told to satisfy it by rotating the key a→b→c per module. The marginal came out
perfect and the sequence came out 85-94% predictable. A stronger instruction produces a different
artifact, not randomness.

## Review-hardening JUDGE rows (added from the course review)

| Non-negotiable | Enforcement | Where |
|---|---|---|
| Draft opens on its H1 (no leaked agent/editor scaffolding) | HARD | `validate_course.py drafts` |
| `length_target.lessons` == actual lesson count | HARD | `validate_course.py length` |
| Essentially no em-dashes (top AI tell) | HARD | `validate_course.py drafts` + `tools/dedash.py` |
| `flow.recap` references only what the previous lesson actually did | JUDGE | agent / human read |
| Languages the labs require are declared + taught just-in-time; prerequisite is honest | JUDGE | agent / human read |
| Toolkit-accretion / capstone SHOWS a prior rung wired in (not asserted) | JUDGE | agent / human read |
| Scope claims (mainnet/DEX/bridge) are taught or explicitly labelled bonus | JUDGE | agent / human read |
