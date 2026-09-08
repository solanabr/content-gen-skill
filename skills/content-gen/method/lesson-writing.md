# Method: lesson-writing
> The per-lesson writer contract — what a writer loads, in what order, what is frozen, what is
> non-negotiable in the output, and the verify half that proves it. This is the body of SKILL.md step 12.

One agent writes **one** lesson from **one** brief. It does not invent scope, it does not renegotiate
length, and it does not mutate a frozen fact. Everything below is either a validator rule or a defect
this pipeline has already shipped once.

> The one rule: **facts first, voice last.** The brief's frozen facts and `concept_spec` are the truth;
> the voice is how they are said. A writer who improves a number has broken the course.

---

## 1. Load order

Read, in this order, before writing a word:

1. **The brief** (`lessons/briefs/<stem>.brief.yaml`) — the whole contract.
2. **Its frozen facts** (`lessons/facts/<stem>.facts.md`) if present.
3. **The batch's writing constants and boundary canon** — canonical shared-fact *phrasings* (if this
   lesson states one, use the canonical wording) and any numbered edict addressed to this lesson
   (cross-references in prose, no invented URLs). See `wave-orchestration.md`.
4. **The voice seam.** If the sibling `writer-style` skill is installed, **resolve it at runtime** — the
   installed release, discovered by name, never a hardcoded path or profile file — and follow its
   write-in-voice command: its profile, its card, a handful of exemplars (always the seam), its
   course-lesson format container, and the one routed secondary. If it is not installed, write the prose
   here: plain technical register, felt hook, named trade-offs, no persona imitation.

## 2. Tone routing

A course-level tone is an explicit override and outranks the router. **The brief's `dominant_job` is the
per-lesson authority**: route the secondary voice from the job, using the course default weighting when
the job is a generic show-how. The budget is hard: **primary (free) + backbone (1) + guest (≤1)**.

Guardrails hold regardless of the mix: guest-only jobs never lead a lesson; a contrarian or
provocation-shaped voice never leads security; an economics voice stays builder-facing rather than
cynical. Record the routed mix in the return (e.g. `backbone 0.7 / guest 0.3, route:requested`).

## 3. Facts first, voice last

Every number, id, API and command in the brief is **frozen**: rephrase around it, never mutate it. For
any value the boundary doc marks a **write-time probe** — rollout quarters, capacity ceilings, dist-tags,
supply figures, gate-activation status — verify it **live** through the research MCPs, or state it with
the canonical hedge. **Never freeze a churning number from memory** (`known-failure-modes.md` §8).

## 4. Resume awareness (read this before writing to a file that exists)

If the target draft already exists, a previous run died mid-write. **Read it first.** Keep it **only** if
it is complete — it reaches the closing forward hook — and meets every constraint below, applying light
fixes. If it is partial or noncompliant, **rewrite from scratch.** A surviving half-draft that gets
"finished" is the worst of the three outcomes: it inherits neither run's structure.

## 5. Non-negotiables in the output

Validator rules and house policy, all of them enforced downstream:

- **Open on the `# ` H1 title.** No text above it — leaked agent reasoning above the H1 is a HARD fail.
- **Hit the brief's `est_length`.** It is a contract (course lessons typically 3000-4500 words; keystones
  higher). Write to it; **never pad to reach it**.
- **The lesson shell:** Summary, then theory under one header name, then a **numbered** Lab, then a
  Challenge, then a feedback beat — with the **autonomy fade stated out loud**.
- **Something to DO in the first 300 words** (150 for an opener).
- **`flow.recap` opens the lesson** and is honest: only what the previous lesson *truly* built.
  **`flow.forward_hook` closes it.**
- **1-3 grounded color beats** from the brief. Never invented.
- **No em-dashes.** The house ships essentially none. Write with periods, colons, commas. Do not rely on
  `dedash.py` to rescue you — it is a belt, and its comma substitution can mint comma splices.
- **No 700+-word prose walls.** Break with a runnable fence or a visual where pacing dies.
- **Every tool shows its install at first use.** Version pins carry a freshness note.

## 6. Visuals

Insert ` ```visual ` placeholder blocks per `references/visual-placeholders.md`:

- **Floor: `max(2, ceil(prose_words / 600))`.**
- **All six fields** — `type`, `title`, `purpose`, `data`, `prompt`, `alt`. `alt` is a real 8-30 word
  descriptive sentence, not a label or a title echo.
- Placed **mid-text where the reader needs them**; never appendixed, never two adjacent.
- **At least two different kinds.**
- Fill `data` and `prompt` from the brief's grounded facts. **Never invent chart numbers.**

Leave the specs in place — rendering is a later pass.

## 7. Code

**Every fenced code block must be real and runnable or compilable against the brief's declared
toolchain.** It is verified downstream; do not ship plausible-but-uncompiled code. A tool this lesson's
artifact builds must match the interface frozen in the facts, because a later lesson will call it by that
interface.

## 8. Close the loop before returning

```bash
python3 "$SKILL/tools/dedash.py" <draft>          # belt over your own no-em-dash discipline
#   ... plus the writer-style tells validator against the course voice card, if installed; fix flagged tells
```

Return only: the stem, the final prose word count, the visual-block count, the tone you routed, and any
code language you could not self-check.

## 9. The verify half (one agent per module, after the writers)

Writing is not done when the file exists. Per module, over each of its drafts:

1. `dedash.py <draft>` (idempotent belt).
2. `verify_code.py --file <draft>`. **FAIL is a real compile or run break** in a locally-runnable
   language: fix the code in the draft, faithful to the brief's frozen API. If the lesson's real toolchain
   is container-only, a **SKIP is expected — record it, never fake a fix** (`known-failure-modes.md` §2).
3. Then the whole-course draft gate: `validate_course.py drafts --course <course>` (≥2 valid visuals per
   lesson, opens-on-H1, em-dash ceiling outside code, no prose walls, install-step advisory). **Fix every
   HARD that traces to a draft in your own module. Do not touch other modules' drafts.**

Return: `drafts_ok` (true only if no HARD traces to your module), a short `verify_code` tally
(`P passed / F fixed / S skipped(container)`), and notes on anything a review board must chase — a SKIP
language, an interface you had to reconcile, a probe you could not verify live.
