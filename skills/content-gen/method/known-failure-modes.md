# Method: known-failure-modes
> The laws this pipeline paid for in shipped defects. Every checker, board prompt, and fan-out runner
> in this skill must obey them. Re-deriving any one of these costs a corrupted course or a wasted wave.

These are not style preferences. Each line below is a defect that reached a draft, a validator, or a
learner, and the rule that stops it recurring. Read this **before** writing a new tool, a new board
prompt, or a new orchestration runner — not after the checker fires.

---

## 1. The first law: substring match is not real usage

**A check that greps raw text for a token will match that token in prose, in a comment, and in its own
documentation.** This has been shipped three separate times in three different tools, always the same
shape:

| Where | The false match | The fix |
|---|---|---|
| `validate_course.py` install-steps | matched `for`**`get`**`s` in prose as the `forge` CLI | scope the match to **fenced code**, not the whole file |
| `render_visuals.py render-banner` | matched `banner-bg-blur.png` inside the scaffold's **own authoring comment**, so every pure-brand banner was misread as photo mode and failed | test **comment-stripped** markup (`_COMMENT_RE`) |
| `verify_challenges.py` Rust entry point | took the **first** `fn` in the file, which for a trait-modelling challenge is `fn check(&self, ..)`; it generated an uncallable `check(500, 100)` and reported the *solution* as failing every test | select **structurally** — prefer a column-0 `fn` with no `self` |
| `continuity.py` call-site scan | a Python `def transfer(sender, receiver, amount)` in module 0 vs an Anchor `transfer(cpi_ctx, amount)` in module 5 — one common English word, two unrelated symbols | compare **within one language**, never across |
| `continuity.py` call-site scan | a helper redefined in a later lesson's own fences was still measured against module 2's version — a defect reported in the one place a reader could not possibly be confused | use the **nearest preceding** definition, and skip a lesson that re-establishes the symbol itself |
| `continuity.py` call-site scan | blanking string literals to spaces deleted an argument: `toBaseUnits("1.50", DECIMALS)` counted as ONE arg, so every correct call became a hit | blank the string **contents**, keep the delimiters |
| `continuity.py` definitions | `const body = (await res.json()) as Shape` read as a one-parameter arrow function, so every later `body()` was a mismatch | an arrow definition must be **followed by `=>`**; the keyword alone is not the structure |

The four `continuity.py` rows are one shakedown of one tool against the ten courses in
`content/courses/`: 93 hits, 36.8% of inspected call sites, before those four fixes; 16 hits
and no mis-parses after. **Run the corpus before you believe a checker**, and prefer the fix
that names the missing structure (same language, nearest definition, real arrow syntax) over
the fix that adds a name to a stoplist.

The rule, for every checker this skill ships:

- **Scope the match before you make it.** Fenced code, comment-stripped markup, a parsed field — never
  the raw file, unless the raw file genuinely is the domain.
- **Never let position stand in for structure.** "The first `fn`", "the last block", "line 1" are
  heuristics; a real selector states the property it wants (column-0, no receiver, top-level).
- **A checker must not match its own scaffolding.** Anything the tool itself writes (authoring
  comments, TODO markers, placeholder names) is invisible to that tool's later checks.
- **A tool that ships an example of the thing it forbids will flag itself.** Verify a checker against
  its own output before shipping it.

> **When a checker fires, first ask whether it matched real usage or its own documentation.** That
> question, asked first, is the whole of this section. It has been the answer three times out of three.

## 2. Gate discipline

- **SKIP is not PASS.** `verify_code.py` and `verify_challenges.py` SKIP when a toolchain is absent
  (container-only stacks, an uninstalled compiler). A SKIP means *nothing was proved*. Resolve every
  SKIP through the pinned container (`--env docker`) before any ship claim. Record each SKIP explicitly
  so the later gate can chase it; never let it drain into a pass count.
- **`GATE: PASS` is not evidence of quality; it is evidence that no HARD fired.** A systemic defect
  that the validator rates ADVISORY sails through a green gate. When an advisory describes a *corpus-wide*
  pattern rather than a single file, treat it as blocking for that run and say so in the report.
- **Never fake a pass around a blocked dependency.** If the container daemon is down, the correct
  return is `ok=false` with the exact error, not a substituted local run.
- **Attest what was actually verified, in the words that are true.** Compiling a git *branch tip* is
  not compiling a *tagged release*, even when the course legitimately teaches the branch. Read the
  resolved version out of the lockfile rather than repeating the declaration, and note that a
  lockfile's first entry for a package may be a **transitive** registry copy, not the direct git dep.

## 3. Advisories that recur (sweep these, do not wait for them)

The same advisories return on every course, because the generators that produce them are systematically
biased, not randomly wrong. Sweep the corpus; do not spot-check.

- **Quiz answer length.** Brief-writers make the correct option the longest option nearly every time
  (measured at 94% of single-select questions across a whole wave, in one course 98 of 104). A learner
  can score without reading. Measure it course-wide, never per-lesson. See `quiz-authoring.md`.
- **Weak visual `alt` text** — a label or a title echo instead of a real 8-30 word descriptive sentence.
- **A tool invoked without its install line** at first use in the course.
- **Guest-only `dominant_job` values used as a module backbone** — sometimes deliberate, so confirm
  against the outline and record "confirmed-deliberate", or flag; never silently accept.
- **Parallel-writer dialect strata** — when N agents write N lessons, the `prompt` / `purpose` / `data` /
  `alt` fields drift into N registers. Normalize course-wide, not per-file.
- **Em-dashes outside lesson prose.** The prose gate covers drafts; quiz text, YAML descriptions, module
  files, and covers are separate surfaces that need their own sweep.

## 4. Generator bias is systematic; corpus-measure it

If one lesson has a tic, the whole course has it. Any defect found in a spot-check must be re-asked as
"what is the corpus rate?" and fixed at that scale. The reverse also holds: **a fix applied to the file
in view, when the defect is a pattern, is not a fix.** Owner corrections sweep the corpus.

**Mixed-authorship seams are real and visible.** When half a course is written by one model or era and
half by another, register and rhythm drift at the seam. A course written across a model switch needs an
explicit seam check in the voice pass and the cold read; an all-one-model course from the same batch is
the useful baseline to judge it against.

## 5. Concurrency and scope

- **Never run a corpus-wide `render` / `review` while per-item agents are live.** Both write per-asset
  intermediates (`.pdf`, `.__render.html`), so two processes touching the same card race and the loser
  reports a bogus error that re-renders clean in isolation. **Different lessons never collide; only
  overlapping scopes do.** Scope every concurrent pass to disjoint sets.
- **A QA step too slow to run is a QA step that does not run.** A `review` that ignored its `--only`
  filter re-rendered a PDF per card, making one course ~50 minutes; every per-lesson reviewer quietly
  gave up on it and the within-page clip check was lost for a whole wave. Honor scope flags, and treat
  "reviewers stopped running it" as a tool bug, not a discipline problem.
- **Build intermediates are not sources.** `*.__render.html` are WeasyPrint intermediates; copying them
  into an export put orphan duplicates in the PR and made the export non-deterministic (file count
  varied with whether a render was mid-flight). Exports must skip intermediates explicitly.

## 6. Fan-out and orchestration

- **Never trust an agent's freeform return for structure.** Schema binding is unreliable for large
  returns: agents sometimes return prose with JSON embedded, or rename fields. Any structure the
  workflow branches on must be read **deterministically from disk** by a dump step that prints one JSON
  line, with the caller extracting it by brace-matching. The file is authoritative; the return is a
  courtesy.
- **Resume caching is PREFIX-based, not keyed.** Editing an *early* agent's prompt invalidates **every**
  cached agent after it, even ones whose own prompts are unchanged (one plan-prompt edit re-ran 70+
  completed agents). Never edit early-call prompts on a run you intend to resume; add new behavior in
  later calls, or accept the full re-run cost knowingly.
- **Run ids are stable across resume**, so always resume rather than restart: completed agents persist
  to disk and replay free. Never re-run a whole phase from scratch after a limit death.
- **Every writer must be resume-aware.** On finding its output file already present, a writer reads it
  first: keep it only if it is *complete* (reaches its closing beat) and compliant, applying light
  fixes; if partial or noncompliant, rewrite from scratch. A half-written draft that survives is worse
  than none.
- **Probe before you blast.** Two different limits kill long runs — a session window that resets on the
  clock, and a weekly model cap that does not. Send one small workflow before launching a full batch.
- **Workflow `args` arrive as a JSON string.** Every runner starts with
  `const A = typeof args === 'string' ? JSON.parse(args) : args`.
- **Fan-out on a single shared file races.** When the data being edited lives in one document (all
  quizzes in one `manifest.json`), split it to per-item files, fan out, then merge with a tool that
  **structurally refuses** any edit outside the permitted fields.

## 7. Naming and structure

- **Derive structure from the invariant part of a name, never a trailing component.** Lesson stems are
  `<mNN>-<lN>-<lesson-id...>` and the lesson-id half varies by course (some append a slug). Grouping by
  `parts[len-2]` produced 27 bogus modules; grouping by the positional prefix `parts[0]` is correct for
  every course. Same law as §1: structure, not position-from-the-end.
- **Ids are contracts.** A skeleton's declared ids are the source of truth for a fan-out; a fragment
  that renames or drops one is the thing to fix, and the assembler must refuse rather than reconcile
  silently.

## 8. Facts and freshness

- **Values that churn are never frozen.** Only `[CONFIRMED]` research facts become frozen facts;
  `[REFUTED]` / `[UNCERTAIN]` become **write-time probes** that the writer verifies live or states with
  a canonical hedge. The categories that must always be probes, not frozen numbers:
  rollout quarters for unshipped upgrades · network capacity ceilings (teach the ratio, re-probe the
  number) · package dist-tags and "latest" versions · supply and TVL figures · rate and stream limits ·
  feature-gate activation status · proposal/SIMD status.
- **A dated claim expires.** A draft that asserts an upcoming cutover must have its *tense and claim*
  re-checked once that date passes; "will ship" becomes a factual question about what actually shipped.
- **Version pins carry a freshness note**, and a pin the local toolchain cannot install is verified in
  the pinned container or not at all.

## 9. Reporting

- **A board that finds nothing must say what it checked.** An empty findings list is only credible
  attached to the list of things that were looked at.
- **Name systemic patterns, but do not edit outside your scope.** A reviewer who spots a defect that
  plausibly repeats beyond their assignment flags it (prefix `SYSTEMIC:`) for the corpus-wide round;
  they do not chase it across other people's files mid-pass.
