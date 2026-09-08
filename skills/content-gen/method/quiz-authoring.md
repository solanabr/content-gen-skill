# Method: quiz-authoring
> How to write quiz options that actually test understanding, and the invariant contract any later
> rewrite pass must not break. The distractor is the assessment; the correct label is just the claim.

A quiz question is only a check on understanding if a learner who did not read the lesson cannot pick
the answer from the *shape* of the options. Every failure mode below is a surface tell that leaks the
answer without teaching anything.

> The one rule: **a distractor must be wrong for a reason a real learner could hold.** If you cannot
> name the misconception it embodies, it is filler, and the question has fewer options than it claims.

---

## Authoring rules (write to these; a later pass will measure them)

1. **Keep every option in one length band.** All options in a question should sit roughly within ±25%
   of each other in characters. The correct option being the longest is the single most common tell in
   generated quizzes; it lets a learner score well without reading. Fix it from **both** ends — usually
   by expanding the distractors, sometimes by tightening the answer.

2. **Give each distractor the same technical register and specificity as the answer.** Name real types,
   real APIs, real mechanisms from this course's subject matter. A vague distractor beside a specific
   answer is the same tell as a short one beside a long one.

3. **Trim answers that are over-explained.** If the correct option is carrying a justification or a
   mechanism walk-through, move that prose into the question's `explanation` field (append to it, never
   delete what is already there) and leave the option itself as the crisp claim. **The explanation is
   where the teaching belongs; the option is a choice, not a lesson.**

4. **Every distractor must stay plausibly wrong for a concrete reason** — a real misconception, a
   version-to-version confusion, an adjacent API that does something else. Never a joke option, never a
   vague near-duplicate of the answer, never something a reader could argue is *also* correct.

5. **Feedback must track the label.** Where a distractor carries a `feedback` string, keep it accurate
   to the text as written: it should say why that specific wrong answer is tempting and what is actually
   true. Rewriting a label without updating its feedback ships a contradiction.

6. **`multiSelect` questions are a different problem.** Leave them alone unless a wrong option is
   conspicuously shorter than every correct one. The length tell is a single-select failure mode.

7. **Scenario-driven, tied to what the learner just did.** A question that could be answered from the
   course description rather than the lesson is not assessing the lesson. Single-select means exactly
   one correct option; every question carries a teaching `explanation`; every wrong option carries
   `feedback`.

**Option position is not an authoring concern.** It is owned by the shipped tooling and enforced by
`validate_course.py` (course-wide answer-slot skew is a HARD). Do not write a position instruction into
an authoring prompt, and do not hand-place answers: correctness is keyed by option **id**, so any
position work is a mechanical transform, not a writing decision.

## The edit-invariant contract (for any rewrite or rebalance pass)

A pass that rewrites quiz text must be structurally unable to move which answer is right. State these as
hard constraints in the prompt, **and** enforce them in the merge step so a large fan-out cannot silently
relocate a correct answer:

- Do **not** change any question `id` or option `id`.
- Do **not** change which option has `correct: true`, and do not add or remove options.
- Do **not** reorder options.
- Keep the JSON shape byte-valid: same keys, same nesting, same top-level fields.
- **Only label / feedback / explanation text may change.**

The merge tool refuses the whole file if question ids, option ids, option order, or `correct` flags
moved. That refusal is the point: it makes a thirty-agent rewrite safe.

## Running a rebalance pass

Quizzes live in **one** file (`manifest.json`, under `lessons[].brief.quiz_blocks`), so a per-lesson
fan-out would race on it. Split first, edit per lesson, merge back:

```bash
python3 "$SKILL/tools/quiz_balance.py" report <course>   # measure the corpus before deciding
python3 "$SKILL/tools/quiz_balance.py" split  <course>   # -> <course>/lessons/quizzes/<stem>.json
#   ... one agent per lesson edits its own file, under the invariant contract above ...
python3 "$SKILL/tools/quiz_balance.py" merge  <course>   # refuses any file whose structure moved
```

Measure with `report` **before and after**. The defect is corpus-wide by construction (generators are
systematically biased, see `known-failure-modes.md` §3-4), so a per-lesson impression of "these look
fine" is not evidence. Residual correct-is-longest cases that are ties within a few characters are
acceptable; a wide spread is not.

When a rewrite needs the real mechanism to build a distractor from, read the lesson draft — a distractor
invented without checking is how a "wrong" option turns out to be true.
