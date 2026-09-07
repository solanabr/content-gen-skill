# Method: wave-orchestration
> Building several courses as one batch: the fixed process contract each course runs, and the
> boundary-adjudication protocol that stops N courses from teaching the same thing N times, badly.

A batch is not N independent courses. Shared subject matter means shared facts, overlapping scope, and
cross-references that only work if someone decided, once and in writing, who owns what. That decision is
made **before** architecture and is binding through writing and review.

> The one rule: **taught once, cross-referenced everywhere else.** For every shared topic there is one
> owner course; siblings name the owner in prose and teach only what their own artifact requires.

---

## The process contract (every course, no exceptions)

Skipping a stage is a defect, not a shortcut.

1. **Research.** Sweeps → a synthesis digest with **frozen-fact candidates** → an adversarial refutation
   pass over the load-bearing claims → a reconciled digest tagging each fact `[CONFIRMED]` /
   `[REFUTED]` / `[UNCERTAIN]`. **Nothing from model memory gets frozen.** Only `[CONFIRMED]` facts are
   freezable; the rest become write-time probes.
2. **Architecture.** The course architect runs the design pipeline (backward design → DAG → routing →
   sequencing → briefs) **grounded in the digest**; then a **separate** agent runs an adversarial
   structure review attacking scope, order, length and the artifact ladder; the architect revises. Key
   decisions get adversarial pairs.
3. **Emit + validate.** Manifest → the deterministic gate → scaffold emit → gate green
   (`brief-fanout.md`).
4. **Write.** Lessons through the voice seam with the course tone override; dedash; the visual floor;
   `verify_code.py` on every lesson with runnable code; quizzes and, where the code is Rust or
   TypeScript, coding challenges (`lesson-writing.md`).
5. **Four review boards**, sequential, each a parallel fan-out plus a reconciler: **A** technical
   fact-check against live sources, **B** pedagogy, **C** rhetoric and assessment language, **D** cold
   read as a student (`review-boards.md`). Each board writes findings → fixes are applied → the validator
   re-runs. **A board that finds nothing must say what it checked.**
6. **Ship.** Export, branch per course off fresh `main`, one PR per course. **Push only after that
   course's boards are green.**
7. **Master round** (batch-level, after all PRs). Parallel judges across the whole corpus: consistency,
   errors, repetitions, cross-reference opportunities, and a re-check of the boundary map. Fixes land as
   follow-up commits on each PR. This is also where every `SYSTEMIC:` flag the boards raised gets swept
   corpus-wide.

## Boundary adjudication (the anti-overlap protocol)

Run this once, between research and architecture, and record it in **one** document every architect,
writer and board reads.

**§1 — the boundary map.** For each topic two or more courses could teach, name the **single owner** and
state what the others may keep. Anchor the map to real dependencies: if course B lists course A as a
prerequisite, A owns the primitives and B teaches only its own domain-specific application of them.

**§2 — cross-reference format.** Siblings name the owner course and the lesson **topic** in prose ("the
Digital Assets course walks the transfer-hook interface end to end"). **Never invent URLs.** A
cross-reference is a pointer, not a substitute for the theory the referring course's own build needs.

**§3 — canonical shared facts.** When two courses print the same number, pin one canonical phrasing.
Typically the owner course prints the precise, attributed form and siblings use an agreed rounded form.
Resolve contested figures against the **primary source**, and record the resolution: a press variant that
the research pass refuted must not reappear as "both numbers exist".

**§4 — write-time probes.** List the values deliberately **not** frozen, batch-wide, so every writer and
Board A knows to verify them live rather than trusting a stale digest line.

**§5 — per-course edicts.** Numbered, addressed to a specific course and often a specific lesson. These
are binding at architecture time and at write time, and boards check them.

### The adversarial pass on the adjudication itself

The boundary doc gets attacked by a reviewer who has read every outline in full, with a severity taxonomy
(`BLOCKER` / `MAJOR` / `MINOR`) and explicit counts. This is not ceremony — the characteristic failure of
a dedup pass is real and asymmetric:

- **False dedup is the main hazard.** An edict that orders a course to cut theory **its own artifact
  requires** damages that course to save a duplication that was never a duplication. The test is not "do
  two courses mention this" but "**does this course's build need it**". Cut *generality* that belongs to
  the owner; keep the minimum a build needs.
- **A course with no prerequisite inside the batch must stay self-contained.** Deferring load-bearing
  theory to a sibling its readers are not taking violates that course's own design contract.
- **Overlap verdicts are per-row and reversible**: a row can downgrade from `DUP` to `LEGIT with mandated
  wiring` while its useful edits (added cross-references, caveat alignment, parameterized numbers)
  survive unchanged.
- **A canonical-fact ruling must not contradict a `[CONFIRMED]` digest resolution.** When it does, the
  digest wins and the edict is rewritten.

## Batch-level constants worth fixing up front

- **A baseline course** the batch must equal or exceed in depth *and* breadth, with the honest caveat:
  **length comes from scope coverage, never from inflating prose.** Long is the point; padded is the
  failure.
- **Tone as an explicit override** per course, in the voice skill's own override form, capped at backbone
  plus one guest and recorded in the tone manifest. The per-lesson `dominant_job` still applies: the
  course mix is the default, and a lesson whose job belongs to another lane declares its own override in
  the brief. Router guardrails hold regardless of the mix.
- **Scale targets** as a range the architect finalizes, not a number the writer must hit by padding.
- **A shared defect list** — the known pipeline failure modes this batch must not reship
  (`known-failure-modes.md`). Every board is pointed at it by name.

## Running the batch

- **Probe before you blast.** One small workflow before a full fan-out; two different rate limits kill
  long runs and only one of them resets on the clock.
- **Always resume, never restart.** Completed agents persist and replay free; a restarted phase pays for
  all of them again. Do not edit an early-phase prompt on a run you intend to resume — caching is
  prefix-based (`known-failure-modes.md` §6).
- **Keep the per-course state on disk**, not in the run: outline, decision log, digest, boards report and
  a `status.yaml` per phase. A batch that survives a limit death is one whose next agent can reconstruct
  where it was from files alone.
