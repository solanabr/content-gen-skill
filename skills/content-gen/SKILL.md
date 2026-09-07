---
name: content-gen
description: "Use when creating educational Solana/Web3 content of any form — a course or curriculum, a hands-on tutorial, a code/protocol/transaction walkthrough, an explainer/primer/deep-dive, an essay or long-form article, a litepaper/whitepaper, a slide deck (text spec), or a tweet/thread/TL;DR — including planning, outlining, sequencing, scaffolding, or writing it. Triggers: 'write a tutorial/explainer/essay/thread/tweet/deck about X', 'design/architect/outline a Solana course', 'draft our litepaper', 'turn these notes into a lesson/article', 'explain X for developers', 'make slides for my talk'. Not for reference docs, marketing copy, or code review."
license: MIT
user-invocable: true
---

# ContentGen (Solana educational-content architect & writer)

One skill, eight content forms: **course · tutorial · walkthrough · explainer ·
essay · litepaper · slides · post** (tweets/threads are `post` sub-profiles). Built on three always-true layers — the pedagogical **design spine**
(`design-spine.md`, always on), the routed **pattern layer** (`patterns/*.md` via
`routing/ROUTING.md`, course-scale shapes), and the **Solana prerequisite DAG**
(`references/solana-syllabus-dag.md`, the order the domain forces) — plus a **form
router** (`forms/FORMS.md`) that decides which pipeline runs at all.

## Scope & deliverable (canonical — every other doc defers here)

- **Default deliverable: fully written text**, finished with a visual-placeholder
  pass (`references/visual-placeholders.md`; density `visuals: none|light|rich`).
  `deliverable: brief-only` is available when the user asks for just the
  structure/outline.
- **Voice seam:** every brief carries a `dominant_job` tag. If the sibling
  `writer-style` skill is installed, prose is written by handing the brief to
  `/write-in-voice` (its router consumes `dominant_job` directly). Resolve the
  **installed skill at runtime** — latest release, discovered by name, never a
  hardcoded path/version/profile file (upstream:
  github.com/solanabr/writer-style-skill). If it is not installed, this skill
  writes the prose itself from the brief — plain technical register, felt hook,
  named trade-offs, no persona imitation.
- **Courses** additionally emit a validated filesystem (`content/courses/<id>/`) of
  per-lesson briefs; lessons are then written one at a time through the same voice
  seam.
- Technical claims are **grounded at design time** against live sources
  (`references/research-grounding.md`) and still pass a **human accuracy review**
  before publish. The skill never deploys anything.
- **The generation pipeline is fixed** (skipping a stage is a defect, not a
  shortcut): **(1) research through the solana-ai-kit surfaces** — the
  `solana-researcher`/`solana-guide` agents, the `deep-research` skill, the
  `solana-dev`/`context7`/`helius` MCPs — never from model memory (degradation
  ladder only when the kit is absent); **(2) draft** — structure complete, every
  frozen fact placed; **(3) writer-style pass** produces the delivered text
  (mandatory when installed); **(4) visual-placeholder pass**; **(5) validators**
  (this skill's gate + writer-style's facts/tells); **(6) optional render + review pass** —
  `references/visual-rendering.md` turns the ` ```visual ` specs into on-brand PNGs, then
  `references/visual-review.md` QAs every render (fresh-eyes visual check + `render_visuals.py
  review`) and re-authors any glitched card (opt-in; needs WeasyPrint + a rasterizer).

## Step 0 — route the form (always first)

Load `forms/FORMS.md`. Explicit ask wins; infer otherwise; on ambiguity default to
the smallest fully-written form that serves the outcome. Then load **only**
`forms/<form>.md` for the routed form and follow its recipe through the shared
pipeline (FORMS.md §shared). `course` loads `forms/course.md` (the form recipe,
corpus-informed) and runs the pipeline below.

## The course pipeline

Each step names the docs it loads (stay lean — load only what the step needs) and
whether it MUST ground against live sources.

1. **Intake.** Course idea/goal, **audience** + prior model (absolute-beginner /
   web2-dev / evm-dev / solana-dev-leveling-up / non-technical), **terminal
   outcome**, scope & length, format, credential goal, `visuals` density,
   `deliverable` mode. Defaults over interrogation; ask only on a missing
   *critical* field.
2. **Backward design (always first).** Measurable, Bloom-tagged terminal
   outcome(s) + the capstone that proves them — *before* any module list. _Loads:_
   `design-spine.md` §1.
3. **Map the prerequisite DAG.** Derive the skill graph; entry point by prior
   model. **MUST GROUND** (order + that named primitives exist and are current).
   _Loads:_ `references/solana-syllabus-dag.md`, `references/research-grounding.md`.
4. **Route.** Backbone + lesson template + ≤2 guests by **outcome + audience**
   (never topic). _Loads:_ `routing/ROUTING.md`. Names patterns; doesn't load them.
5. **Load only the routed patterns.** Never all of `patterns/`.
6. **Sequence.** Modules/lessons up the DAG; thread the artifact ladder; ramp
   difficulty as a fading schedule; fast first win; one "aha" per lesson. **MUST
   GROUND** every concrete API/tool/number that will land in a brief. _Loads:_
   `design-spine.md` §§3–5.
7. **Write per-lesson briefs.** Fill `lesson-brief-schema.md` §C (set `kind:
   build|concept` and `dominant_job`). Voice-ready, not voice-written.
8. **Design cadence.** Pedagogy (fade / ramp / spiral / retrieval) + release
   (drip / effort / freshness). _Loads:_ `design-spine.md` §§5, 9.
9. **Research scaffolds.** Per lesson: claims/APIs/numbers to ground, with a
   `source_priority`; freeze verified facts. **MUST GROUND.** → `lessons/research/*`
   + `lessons/facts/*`.
10. **Assessment & capstone.** Proof model; **gate on doing**; capstone uses only
    taught skills. _Loads:_ `design-spine.md` §6.
11. **Validate, then EMIT.** Assemble `manifest.json`
    (`references/output-contract.md`); run the gate; fix every HARD; emit; re-check:
    ```bash
    python3 "$SKILL/tools/validate_course.py" all --manifest manifest.json
    python3 "$SKILL/tools/scaffold_course.py" emit --manifest manifest.json --out content/courses/<id>
    python3 "$SKILL/tools/validate_course.py" all --course content/courses/<id>
    ```
    Then the JUDGE items in `references/quality-bar.md`.
12. **Write the lessons.** Work `content/courses/<id>/queue/NEXT.md` through the voice seam
    (Scope & deliverable above), one lesson at a time; run the visual pass on each
    draft; update `_state.yaml`. In `brief-only` mode, stop after the handoff
    packet and note the human accuracy gate.
13. **Interactive plugins + Academy publish.** Author per-lesson `quiz_blocks` and (Rust/TS lessons)
    `coding_challenges` in the manifest briefs (lesson-brief-schema §H). **Do not think about option
    order — a tool assigns it; hand-ordering is a gate failure.** Write each question's options in
    whatever order they occur to you, then run the quiz pipeline in exactly this sequence
    (`quiz_edit.py merge` refuses any file whose option order moved, so permutation is the LAST
    mutation before validation):
    ```bash
    #   optional: fan a label/feedback rewrite over one editor per lesson
    python3 "$SKILL/tools/quiz_edit.py"   split content/courses/<id>  # → lessons/quizzes/*.json
    #   ... edit labels/feedback/explanations ONLY; ids, block keys, correctness and order are refused
    python3 "$SKILL/tools/quiz_edit.py"   merge content/courses/<id>
    python3 "$SKILL/tools/quiz_layout.py" permute --course content/courses/<id>  # hash-assigns order + ledger
    python3 "$SKILL/tools/quiz_layout.py" report  --course content/courses/<id>  # stats + ledger + length gaps
    ```
    Then project to the Academy publish tree and prove the challenge contract:
    ```bash
    python3 "$SKILL/tools/validate_course.py" all --course content/courses/<id>   # quiz + challenge checks
    python3 "$SKILL/tools/render_visuals.py" scaffold-banner content/courses/<id> # course banner → Academy thumbnail
    #   ... author branding/banner.html (references/banner.md), then:
    python3 "$SKILL/tools/render_visuals.py" render-banner   content/courses/<id> # → branding/banner.webp (≤1MiB)
    python3 "$SKILL/tools/academy_export.py" emit --course content/courses/<id> --out content/academy/courses/<slug>
    python3 "$SKILL/tools/verify_challenges.py" content/courses/<id>              # starter fails / solution passes
    ```
    The export embeds each lesson's rendered visuals as `![alt](assets/vNN-*.png)` and copies the
    PNGs + HTML sources — so the Step-12 visual pass (render_visuals.py) must have run first, or
    visuals degrade to blockquote placeholders with warnings.
    Additive: the export writes only under `content/academy/`; the source course is untouched.
    Contract + schema in `references/academy-schema.md`.

## What you load when (keep context lean)

| Step | Load | Ground? |
|---|---|---|
| 0 route form | `forms/FORMS.md` → one `forms/<form>.md` | no |
| 2 backward design | `design-spine.md` §1 | no |
| 3 map DAG | `references/solana-syllabus-dag.md` + `references/research-grounding.md` | **yes** |
| 4 route patterns | `routing/ROUTING.md` | no |
| 5 patterns | only the routed `patterns/*.md` | no |
| 6 sequence | `design-spine.md` §§3–5 | **yes** |
| 7 briefs | `lesson-brief-schema.md` | reuse step 6 |
| 8–10 cadence/research/assess | `design-spine.md` §§5,6,9 | **yes** |
| 11 emit | `references/output-contract.md`, `references/quality-bar.md`, `tools/` | — |
| 12 write | `references/visual-placeholders.md` (+ writer-style if installed) | reuse 9 |
| 13 plugins/publish (optional) | `references/academy-schema.md`, `lesson-brief-schema.md` §H, `references/banner.md` | — |

If grounding tooling is unavailable, follow the degradation ladder in
`references/research-grounding.md` — never silently mark a claim verified from memory.

## Tools

Resolve the skill directory, then call tools with absolute paths:

```bash
SKILL="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/skills/content-gen}"
[ -d "$SKILL" ] || SKILL=".claude/skills/content-gen"
[ -d "$SKILL" ] || SKILL="skills/content-gen"
# (you loaded this SKILL.md from disk — its parent directory is also a valid $SKILL)
python3 "$SKILL/tools/test_tools.py"                                 # all selftests
python3 "$SKILL/tools/validate_course.py" all --course content/courses/<id>  # deterministic gate
python3 "$SKILL/tools/scaffold_course.py" emit --manifest m.json --out content/courses/<id>
```

- `tools/validate_course.py` — `dag | briefs | quiz | ladder | capstone | outcomes | research |
  artifacts | length | fixes | drafts | challenges | all` (`drafts` HARD-enforces the scaled visuals
  floor; `quiz` is the whole-course quiz gate; `fixes` needs `--course`). HARD = breaks the DAG walk or the writer handoff;
  ADVISORY = a smell to weigh. A statistical metric under its sample floor says
  **INCONCLUSIVE, not passed**, and never green-lights a course by staying quiet.
- `tools/scaffold_course.py` — `emit` (idempotent; `--force`), `check` (dry-run). Honors
  human edits via `course.lock.json` hash drift.
- `tools/assemble_manifest.py` — the other half of the brief fan-out: `scaffold_course.py` splits a
  manifest into per-lesson work, this folds the fragments back into one `manifest.json`. Exits 2 with
  `ASSEMBLE-FAIL` on a missing, extra, or duplicated lesson rather than quietly assembling a short
  course. 17-check selftest.
- `tools/quiz_metrics.py` — the statistics behind the quiz gate, stdlib-only and importable, so
  `validate_course.py quiz` and `quiz_layout.py report` can never disagree about a number. A port of
  `academy-courses/scripts/quiz_stats.py`, with which it must stay in agreement. Every test is
  two-sided: a key that *never* repeats its slot fails exactly as hard as one that always does.
- `tools/quiz_layout.py` — `permute | verify | report`. Option order is derived from
  `sha256(salt | courseId | lessonSlug | blockKey | questionId)` and recorded in a **layout ledger**
  in the manifest, so `verify` is a byte-comparison — provenance, not statistics, and therefore
  conclusive at n=1 where every distributional test is powerless. It touches array order and nothing
  else, asserting that by comparing the option multiset before and after, which makes it safe on an
  already-translated course. **This is where option order comes from; never a prompt, never a hand.**
- `tools/quiz_edit.py` — `split | merge`: a per-lesson editing seam over `manifest.json`'s
  `quiz_blocks`, so a fan-out of editors does not race on one file. `merge` refuses any file whose
  block key, question id, option id, `correct` flag, `multiSelect` flag, or option ORDER moved —
  wording is the only thing an editor may change. Run it BEFORE `quiz_layout.py permute`.
- `tools/fix_sweep.py` — `plan | check | close | list`: the executable half of
  `method/fix-protocol.md`. **Never correct a shipped claim at the line you found it.**
  `plan --claim "<text>"` lists every surface that carries it (draft prose and its twin two
  lessons later, the ` ```visual ` spec a re-render rebuilds from, `alt:`, the `visual-src` HTML,
  the brief, quiz feedback, challenge files, facts/research, the cover, the exported copy) and
  writes `<course>/fixes/<id>.yaml`. Twins are found by **normalised code-fence hashing**, so a
  snippet duplicated under rewritten comments is found by structure. `check` fails while any
  surface still matches OR **any rendered image is older than its HTML source** — the machine-
  checkable form of "the picture still teaches what the prose retracted". `validate_course.py
  fixes` HARD-fails any sweep left `status: open`.
- `tools/dedash.py` — strips em-dashes (the top AI tell) from drafts, deterministically:
  commas in prose/visual specs, hyphens in code comments, code/output fences protected.
  Run it as the final step of the writing pass; `validate_course.py drafts` HARD-fails
  a lesson with >2 em-dashes outside code (house policy: essentially none).
- `tools/verify_code.py` — **compiles/runs every code block the piece ships, for ANY
  form.** `verify_code.py <course-or-content-dir>` (or `--file <one.md>`) extracts each
  fenced block and dispatches it to a real toolchain; `--env docker` runs the pinned,
  version-matched image (`verify/Dockerfile`). FAIL = a real compile/run break; SKIP =
  that language needs the container (resolve with `--env docker`, never ship on SKIP).
  It is CI **tier 5** (`ci.py --tiers 5`). This is non-negotiable: **no piece that
  contains runnable code is "done" until `verify_code.py` is green on it.**
- `tools/render_visuals.py` — the **optional render + review pass**: turns each ` ```visual `
  spec into an on-brand PNG via the shipped `brand/` core + WeasyPrint (`extract → scaffold →
  author each `.viz` → decorate → render → review → check`). `render` FAILS any card that
  overflows the 1600×900 canvas; `review` adds a static QA (page-overflow + forbidden-CSS lint)
  that pairs with the fresh-eyes visual pass in `references/visual-review.md`. Deterministic, no
  browser; SKIP if WeasyPrint/rasterizer absent. Additive — the ` ```visual ` spec stays in the
  markdown; the PNG is written beside the lesson. `scaffold-banner` / `render-banner` produce the
  one course-level visual — the Academy card thumbnail — in `branding/` (photo-backdrop or
  pure-brand; `references/banner.md`).
- `tools/academy_export.py` — the **optional Academy publish projection**: `emit --course
  content/courses/<id> --out content/academy/courses/<slug>` materializes the platform's YAML
  block tree (`course.yaml` + per-lesson `lesson.yaml` with prose/quiz/code blocks + copied
  challenge files) from the manifest, drafts, and brief `quiz_blocks`/`coding_challenges`.
  Auto-detects `branding/banner.{webp,jpg,jpeg}` → course `thumbnail:`; `duration` is HOURS
  (derived from `length_target.hours` unless `academy.duration` is set).
  One-way and additive — reads the course read-only, writes only under `--out`
  (`references/academy-schema.md`).
- `tools/verify_challenges.py` — proves the **Academy runtime contract** for every
  `coding_challenge`: the solution passes all `tests.json` cases and the starter fails ≥1, in a
  real toolchain (tsc+node for TypeScript; rustc / `cargo check` vs anchor-lang for Rust). FAIL =
  a real contract violation; SKIP = toolchain unavailable (never a pass).
- Stdlib-only, each with `--selftest`. The deterministic gate applies to the
  **course** form; other forms gate on their form-file checklist — but `verify_code.py`
  runs on every form, because any piece can ship code.

## The pattern layer (course-scale shapes, quick reference)

| Pattern | Shapes… | Lead when the course/audience needs… |
|---|---|---|
| **concept-spine** | the mental-model backbone | model built before/around building; conceptual or non-dev courses |
| **challenge-ladder** | the build backbone | hands-on builders; one shipped artifact per rung |
| **overview-lab-challenge** | the default *lesson* template | read → guided → unguided |
| **completion-loop** | micro-lessons, faded worked examples | absolute beginners; lowest load |
| **build-it-twice** | abstraction-layered depth | "why the framework exists" — native↔Anchor |
| **security-epoch** | the late security tier | exploit→patch→fuzz/CTF; pre-mainnet |
| **map-from-known** | the audience-specific opener | strong adjacent priors (EVM→Solana) |
| **client-integration** | the off-chain/client side | dApp / mobile / frontend / SDK courses |
| **optimization-loop** | measure→optimize→re-measure | compute-unit / performance outcomes |
| **testing-thread** | testing as a thread, not a module | the acceptance gate on every build |

## Agents & commands
- `/create-content "<ask>"` — route the form and deliver the finished piece.
- `/architect-course "<brief>"` — the course pipeline end-to-end.
- `/validate-course --course content/courses/<id>` — the deterministic gate.
- agent `content-composer` — owns the non-course forms (route → brief → write →
  visual pass).
- agent `course-architect` — owns the course form (intake → emit → lesson writing).

## Method notes

How a wave was actually run, lifted out of the one-off scripts that ran it. Load a
file only when you are doing that job.

| `method/` | Covers |
|---|---|
| **`known-failure-modes.md`** | **Read first.** The failures that recur across waves — the substring-vs-real-usage law (a grep for a tool name flags "forgets" and "byte cast"), and **SKIP is not PASS**. |
| **`fix-protocol.md`** | **Read before applying ANY correction to a shipped course.** The fifteen surfaces one claim lives on, and why fixing the filed line alone manufactured ~17% of the next audit's findings. |
| `brief-fanout.md` | One agent per module writing lesson briefs, then `assemble_manifest.py` folding them back. |
| `lesson-writing.md` | Working the queue one lesson at a time through the voice seam. |
| `quiz-authoring.md` | Writing the questions. Option order is not in it — that is `tools/quiz_layout.py`'s job, deliberately. |
| `review-boards.md` | The adversarial review passes and what each board owns. |
| `wave-orchestration.md` | Running several courses at once without them colliding. |
| `pattern-authoring.md` | Adding a pattern to `patterns/`. |
| `router-hardening.md` | Changing `routing/ROUTING.md` without breaking existing routes. |

Optional runners for these live in `workflows/*.wf.js`. The method files are the
source of truth; a runner is one way to execute one, never the specification.

## The one rule above all
**Route the form, design backward from a measurable outcome, ground every claim,
put the teaching inside something real (an artifact, a tour, an argument), name the
trade-off — then deliver finished text the reader can use, with visuals specified
but never overdone.** Educational content that is complete but unsequenced, or
polished but passive, fails the same way over-tidy prose does: it stops feeling
like a builder's path and starts feeling like a textbook.

See `three-layer-model.md` for how the layers compose, `forms/FORMS.md` for the
form router, `references/output-contract.md` for the course filesystem, and
`design-spine.md` for the non-negotiables.
