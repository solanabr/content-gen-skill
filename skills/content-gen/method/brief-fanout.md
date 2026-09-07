# Method: brief-fanout
> How to write a whole course's lesson briefs in parallel without corrupting the manifest: one skeleton,
> one fragment per module, a deterministic assemble, then a gate that runs until green.

Writing 25 briefs serially is slow; writing them into one `manifest.json` in parallel is a race. The
shape that works is **skeleton → per-module fragments → deterministic merge → gate**. No agent ever
hand-merges JSON, and no agent's freeform return is ever the structure the workflow branches on.

This protocol is runner-agnostic: it works by hand, and it works under any parallel-agent orchestrator.
Only two of its steps must be tools rather than prompts — the disk read in Phase 1b and the merge in
Phase 3.

> The one rule: **the skeleton's lesson ids are the contract.** A fragment that renames, drops or invents
> a lesson id is the thing to fix. The assembler refuses rather than reconciling silently.

---

## Phase 1 — the skeleton

One architect agent writes `manifest.skeleton.json`: everything **except** `lessons`. It owns the course
frame and the order of module and lesson ids:

- `schema_version`
- `course` — id, title, one-line promise, version, status, created, `audience{who, prior_model,
  prerequisites[]}`, `terminal_outcomes[{id,bloom,statement}]`, format, `length_target{hours,lessons,weeks}`,
  credential, `toolchain[]` (with versions and freshness notes), `routing{backbone_pattern[], lesson_template,
  guest_patterns[], security}`, `artifact_ladder[]`, `visuals`, `deliverable`, and the cover `overview`
  paragraph — **whose audience and prerequisites must match the `audience` block** (a standing Board D
  failure mode).
- `dag` — `nodes[]` (kebab skill nodes, course-specific) + `edges[[from,to]]`. **Must be acyclic; every
  edge references a declared node.**
- `glossary` — `[{term, def, first_taught}]` over the load-bearing terms.
- `concept_ledger` — `[{concept, introduced_in}]`.
- `modules` — `[{id, title, driving_question, outcome{bloom,statement}, traces_to[], artifact,
  artifact_rung, depends_on[], requires_skills[], teaches_skills[], patterns[], difficulty_band,
  lessons[] (ORDERED lesson ids), retrieval_checkpoint}]`.
- `cadence` — pedagogy (fading schedule, difficulty curve, worked-examples-removed-after, spiral,
  retrieval checkpoints, cumulative checkpoint) + release (mode, start date, timezone, schedule,
  freshness policy).
- `assessment` — model, `proof_matrix` (**every** terminal outcome appears), checkpoints, cumulative
  checkpoint, capstone (statement, `requires_skills` all taught earlier, rubric, credential, traces_to).
- `academy: {}` — left empty; platform metadata is added at publish time.

**HARD rules the validator enforces, so get them right at skeleton time:** every id kebab-case; DAG
acyclic; `depends_on` / `requires_skills` reference real modules and nodes; lesson order within a module
is the teaching order (**no forward dependency** — a lesson's prerequisites must be taught earlier);
capstone requires only skills taught before it; `length_target.lessons` **exactly** equals the enumerated
lesson count. Use the **exact** lesson ids and module structure from the locked outline; do not invent or
drop lessons. Fold in every boundary edict that touches structure.

Have the agent self-check before returning:

```bash
python3 -c "import json;d=json.load(open('<dir>/manifest.skeleton.json'));print('modules',len(d['modules']),'lessons',sum(len(m['lessons']) for m in d['modules']),'declared',d['course']['length_target']['lessons'])"
```

All three numbers must agree.

## Phase 1b — read the skeleton from disk, not from the return

**The skeleton is authoritative on disk. Do not trust the skeleton agent's freeform return** — its shape
and field names vary, and structured-output binding is unreliable for large returns. A separate
low-effort agent runs exactly one command and returns only its stdout:

```bash
python3 -c "import json;d=json.load(open('<dir>/manifest.skeleton.json'));print(json.dumps({'modules':[{'id':m['id'],'title':m.get('title',m['id']),'lesson_ids':m['lessons']} for m in d['modules']],'total_lessons':sum(len(m['lessons']) for m in d['modules'])}))"
```

The caller extracts the JSON by **brace-matching from the first `{"modules"`**, and aborts the run if the
extraction fails. That extractor is three lines and it is what makes the fan-out safe: the module map that
drives N parallel agents comes from the file, never from prose. Same law in `known-failure-modes.md` §6;
the write phase uses the identical pattern for its plan step.

## Phase 2 — one brief-writer per module

Each agent gets its module id and title, its **exact ordered lesson ids** ("write a full brief for each,
none extra"), and the canon: the locked outline's per-lesson scope, the research digest, the boundary
edicts, `lesson-brief-schema.md` and `references/output-contract.md`.

It writes **one file**: `<dir>/briefs/<module-id>.lessons.json`, a JSON **array** of lesson objects:

```
{ "id", "module", "order", "brief": { ...lesson-brief-schema §C, all required keys... },
  "research": { "lesson_id", "status", "source_priority": [...],
                "frozen_facts": [ ...atomic, one value per line... ] } }
```

Two rules bite here:

- **`frozen_facts` are atomic** — a version, an id, a number, or one exact command per line. Only
  `[CONFIRMED]` digest facts get frozen. `[REFUTED]` and `[UNCERTAIN]` become **write-time probes**, never
  frozen values.
- **Length is set by `est_length` and is the writer's contract.** Write the **spec**, not the prose.

**Quizzes** (every lesson, 3+ questions): scenario-driven and tied to what the learner just did; three
options; distractors are real misconceptions in the same length and register as the answer; single-select
means exactly one correct; `feedback` on every wrong option and a teaching `explanation` on every
question. The full craft rules — including the length-band rule that this stage systematically violates —
are in `quiz-authoring.md`.

**Coding challenges** are **selective**: only where the lesson's real code is Rust or TypeScript *and* the
outline marked a challenge; at most the strongest one per module, and none if none fit. Author **real
files** under `lessons/challenges/<lesson-id>/<challenge-id>/`: a `starter` that genuinely **fails** its
tests, a `solution` that genuinely **passes**, and `tests.json`. Reference them course-relative in the
brief. **The starter-fails / solution-passes contract is the grade** — the solution must be the real
working code, because it is verified later and plausible-but-uncompiled code fails that gate.

## Phase 3 — assemble, validate, emit, validate

One engineer agent runs this pipeline with Bash, **iterating until green**:

```bash
python3 "$SKILL/tools/assemble_manifest.py" <dir>                                   # -> <dir>/manifest.json
python3 "$SKILL/tools/validate_course.py"  all --manifest <dir>/manifest.json
python3 "$SKILL/tools/scaffold_course.py"  emit --manifest <dir>/manifest.json --out <course>
python3 "$SKILL/tools/validate_course.py"  all --course <course>
```

1. **Assemble.** On `ASSEMBLE-FAIL` (missing, extra or duplicate lesson versus the skeleton), open the
   offending fragment or the skeleton and reconcile — **the skeleton's `module.lessons` is the source of
   truth for ids**; fix the fragment to match, re-assemble.
2. **Validate the manifest.** Fix **every** HARD by editing the manifest or the fragment and
   re-assembling. Recurring HARDs: a non-kebab id; a DAG edge to an unknown node; a **forward dependency**
   (a lesson's prerequisite taught later — reorder or fix the prereq); a single-select question without
   exactly one correct option; a capstone requiring a skill never taught; `length_target.lessons` not
   equal to the actual count. Re-run until zero HARD; advisories may remain, but **note them** rather than
   letting a green gate imply they are absent (`known-failure-modes.md` §2).
3. **Emit** the course tree.
4. **Validate the emitted course** — this pass resolves challenge files on disk, so it catches a challenge
   whose starter, solution or tests file is missing. Either create the file or drop the challenge from the
   brief, re-assemble and re-emit. Re-run until clean.
5. **Write `<dir>/status.yaml`**: `phase: emitted`, with module / lesson / challenge counts and any
   remaining advisories.

Return: whether the tree emitted, whether the emitted course validates with zero HARD, the lesson count,
how many HARDs were fixed, the challenge count, and a two-to-three sentence summary including remaining
advisories.

## Why the assembler is a tool and not a prompt

`assemble_manifest.py` merges the skeleton with every fragment and **stamps** `module` and `order` from
the declaration, so ordering cannot drift. It exits 2 with `ASSEMBLE-FAIL` on a missing, extra or
duplicated lesson id, or on a fragment that is not a JSON array of lesson objects with briefs. An agent
merging the same JSON by hand produces a file that looks right and has silently lost a lesson. Determinism
is not an optimization here; it is the only thing standing between a fan-out and a corrupted manifest.
