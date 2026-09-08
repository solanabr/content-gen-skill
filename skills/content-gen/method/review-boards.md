# Method: review-boards
> The four-board review a written course passes before it renders, exports, or ships: A facts and code,
> B pedagogy, C rhetoric and assessment language, D a cold read as a paying student. Then Fix, then Gate.

One reviewer reading for everything finds nothing. Four boards, each with **one** job and its own reading
protocol, find different defects — and Board D finds the ones the other three structurally cannot,
because it is the only pass that reads without the spec.

Run the boards **sequentially** (each sees the previous board's fixes); run each board as **parallel
per-module agents** plus a reconciler. The whole thing is orchestrated by
`workflows/course-boards.wf.js`, which is optional convenience — the protocol below is the asset, and it
works run by hand.

> The one rule: **a board that finds nothing must say what it checked.** An empty findings list is
> credible only next to the list of things that were looked at.

---

## Shared setup (before Board A)

1. **Dump the plan deterministically.** One low-effort step runs a script that prints a single JSON line:
   the lesson stems, and the course-wide statistics the boards will need (per-stem
   `[correct-is-strictly-longest, total-questions]`, files containing em-dashes with counts). Write the
   stats to `<course>/boards/c-stats.json`. Never let a board start from an agent's prose summary of the
   corpus — see `known-failure-modes.md` §6.
2. **Group stems by the positional module prefix** (`stem.split('-')[0]`). Lesson-id suffixes vary by
   course; the positional prefix does not (`known-failure-modes.md` §7).
3. **Give every board the same context block**: its module and stems, the paths to drafts / briefs /
   frozen facts / module files / challenges / research digest / outline / decision log / the batch's
   boundary doc / `references/quality-bar.md`, and today's date.
4. **Two standing constraints on every board agent:**
   - *Edit only files belonging to your module's lessons.*
   - *Systemic patterns:* if you spot a defect that plausibly repeats beyond your module (a repeated
     wrong phrase, a template artifact, a uniform tic), name it precisely in your return under `flagged`
     with the prefix `SYSTEMIC:` — but do **not** edit outside your module. The corpus-wide round sweeps
     systemic patterns.
5. **Return schema, boards A-C:** `module`, `ok` (boolean: no unresolved defect of this board's kind
   remains), `fixed` (short strings), `flagged` (what a human or a later gate must still chase).

---

## Board A — facts and code truth

For each draft in the module:

1. **Facts.** Check every number, version, API name, account/program id, CLI command, date and cited
   event against the lesson's **frozen facts** file, the research digest's verdicts, and the batch's
   canonical phrasings. Frozen facts are the truth for everything *except* the **write-time probes**,
   which were deliberately not frozen and must be re-verified **live now** (load the `solana-dev` /
   `context7` / `helius` MCPs; web search as fallback). Fix wrong claims in place; keep canonical wording
   where the boundary doc mandates it. If the draft references a dated cutover or launch, check whether
   it has since happened and fix **the tense and the claim** — a course written before a date and
   reviewed after it will assert a future that already resolved.
2. **Commands and installs.** Every tool invoked must show its install at first use in the course. (The
   repeat offender is a CLI fenced without its installer line.) Fix within your module; if first use is
   in another module, flag it.
3. **Challenge interfaces.** Read the module's coding-challenge directories: the interfaces, file names
   and function signatures the draft *promises* must match what the challenge actually ships. Reconcile,
   preferring to fix the draft to the frozen challenge spec.
4. **Re-verify after editing.** Run `dedash.py` then `verify_code.py --file <draft>`. **Never introduce a
   compile break with a prose fix.** Container-only stacks will SKIP locally: record each SKIP in
   `flagged` as `RC:<stem>`. **SKIP is not pass** — the Docker gate below is what resolves them.

### Board A's container gate (runs once, after the per-module agents)

The local toolchain cannot compile container-only code. A dedicated agent:

1. **Checks the daemon first** (`docker info`). If it is down or unreachable, return `ok=false` with
   `flagged=["DOCKER-BLOCKED: <exact error>"]` and **stop**. Do not fake a pass.
2. Learns the tool (`verify_code.py --help`), then runs it with `--env docker` over every draft that
   SKIPped locally. The first image pull is slow; that is fine.
3. Treats **every FAIL as a real compile break**: fix the code in the draft, faithful to the brief's
   frozen API (read the brief and facts before touching code), re-run until PASS or genuinely blocked.
   **Never weaken code to make it compile** — no stubbing, no deleting the failing block.

Trust the tool, not the count of RC flags Board A produced.

## Board B — pedagogy and recap honesty

Load `references/instructional-design-canon.md` and `design-spine.md`. Tell each agent which lesson
*precedes* its module's first lesson, so continuity can be checked across the module seam.

1. **Recap honesty.** `flow.recap` must claim only what the previous lesson **actually built** — read the
   real previous draft, within and across modules. The forward hook must point at what truly comes next.
   This is the check that catches a course promising itself things it never delivers.
2. **Arc.** Something to **do** inside the first 300 words (150 for an opener); the autonomy fade stated
   out loud and actually fading across the module (guided → prompted → solo); the Lab numbered, runnable
   in order, with every step's expected result stated; the Challenge doable from what has been taught
   (check declared prerequisites against the outline DAG — no forward dependency).
3. **Contract.** `est_length` respected. **Flag padding and starvation rather than bulk-rewriting.** No
   700+-word prose wall: split with a runnable fence or a visual where pacing dies.
4. **Voice-routing sanity.** The brief's `dominant_job` routed the voice. Guest-only jobs used as a
   module **backbone** are deliberate in specific outlined places: confirm against the outline and
   decision log and record `confirmed-deliberate` in `fixed`, or flag if truly unplanned. **Do not
   rewrite voice** — Board C owns prose voice.

Small surgical fixes in place; structural rewrites get **flagged, not performed**. Run `dedash.py` after
any edit.

## Board C — rhetoric, voice, and assessment-layer language

Give it the course tone default and the stats file from setup.

1. **Quiz label rebalance.** The systemic tell is that the correct option is almost always the **longest**
   label. In the module's briefs, rewrite option **labels** so correct-is-longest survives in at most
   about a third of questions: usually **expand** a plausible distractor with real, wrong-path
   specificity; sometimes **tighten** the correct label. Never change which option is correct, never
   weaken a distractor's plausibility, never touch ids or `correct` flags, and keep feedback lines
   consistent with any rewritten label. Full craft rules: `quiz-authoring.md`.
   **Option position is out of scope for this board and for every prompt it writes.** Answer-slot
   distribution is owned by the shipped quiz tooling and enforced by `validate_course.py`, which HARD-fails
   course-wide slot skew. A reviewer must not hand-permute option order, and must not instruct a writer
   to place answers at a slot: correctness is keyed by option **id**, so position is a mechanical
   transform a tool does correctly and a fan-out of agents does not. Rotation instructions written into
   authoring prompts are what produced the defect this board exists to catch — do not re-invent them.
2. **Em-dashes outside lesson prose.** The house ships zero. Purge them from the module's briefs (quiz
   prompts, labels, feedback, hooks, specs) and module files **by syntactic role**: sentence-boundary
   dash → period or semicolon; appositive pair → commas or parentheses; list-introducing dash → colon.
   **Never a blind comma swap** (it mints comma splices), and vary the repair so the corpus does not
   acquire a uniform comma-appositive fingerprint.
3. **YAML safety.** After editing any YAML, round-trip it (`yaml.safe_load`). A parse error means the
   quoting broke; fix before returning.
4. **Draft voice.** If the sibling `writer-style` skill is installed, resolve it at runtime and run its
   tells validator against each draft with the course's voice card; fix flagged tells. Then `dedash.py`.
5. **Visual field sweep** (the parallel-writer dialect strata). In every draft's visual blocks,
   `prompt` / `purpose` / `data` / `alt` must be consistent English at one register; `alt` must be a real
   8-30 word descriptive sentence, not a label and not a title echo; `purpose` must not contradict
   `prompt`. Normalize.

Include the rebalance tally in `fixed` (e.g. `rebalanced 5/9`).

## Board D — the cold read

This is the board that cannot be replaced by a checker, and its constraint is the whole method:

> **You are a paying student, not a reviewer with the spec.** Read only the drafts, in order (plus the
> closing of the preceding lesson for continuity). **Do NOT open briefs, facts, outlines, or research —
> that is the point.** Do NOT edit anything.

Report every place you, as a student:

- got confused;
- met a term used before it was ever explained *in what you have read*;
- caught the text contradicting itself or an earlier lesson;
- were promised something the lesson never delivered;
- noticed the invented artifact or domain go inconsistent (names, interfaces, numbers drifting);
- stopped trusting the author.

Also flag anything that smells machine-written: uniform tics, hollow transitions, filler.

**Severity:** `HARD` = a student would be blocked or misled. `SOFT` = friction. **`where`** = stem plus
nearest heading. Be concrete enough that a fixer who *has* the spec can act without asking you. Return
an empty findings array only if the module is genuinely clean.

### Board D meta — course-surface coherence

One extra agent reads only the course surface (`course.yaml`, the cover draft, README, `manifest.json`,
`assessment.yaml`, `cadence.yaml`) and does not edit. Known template failure modes:

- declared audience versus what the overview and cover text actually **demand** of the reader — they must
  describe the same student;
- total hours versus actual content volume; cover time-math contradicting `course.yaml` is a HARD;
- cover "era / rung / ladder" narrative only if the module count and artifact ladder genuinely support it;
- every repo, tool or artifact the cover asserts must **exist on disk in this course** — no leaked thesis
  from a sibling course, no invented toolkit repos;
- duration units are hours; title / slug / lesson-count agreement between `manifest.json` and
  `course.yaml`;
- em-dashes on the course surface (Board C may not have swept these files).

## Fix — apply Board D's findings

Board D deliberately has no spec, so its findings need a fixer who does: briefs, facts, the boundary doc,
the outline.

- Apply **every HARD**, and every SOFT whose fix is unambiguous and local.
- A finding that demands a structural rewrite, contradicts the spec, or looks like reviewer error: skip
  it and **record why** in `flagged`.
- Keep fixes surgical and in the course voice; never introduce em-dashes; `dedash.py` after editing a
  draft; round-trip any YAML.
- **When a finding reveals a pattern** (the same defect phrased in several lessons), sweep the **whole
  course** for that pattern, not just the cited file.

## Gate — validate, then report

1. Run `validate_course.py all --course <course>` and `validate_course.py drafts --course <course>`. Fix
   any trivial HARD (missing visual field, stray em-dash, leaked preamble); re-run until clean or the
   remaining HARDs are genuinely structural.
2. Write `boards-report.md`: per-board fixed/flagged tables, **every unresolved item** (container-gate
   blocks, probe uncertainties, `SYSTEMIC:` patterns for the corpus round, skipped Board D findings), and
   a one-paragraph verdict on whether the course is ready for the visual pass, export, and PR.
3. **`gate: PASS` only if both validators are clean AND the container gate returned `ok`.** A green
   validator with a blocked container gate is not a pass (`known-failure-modes.md` §2).
