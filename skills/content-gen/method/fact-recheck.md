# Fact re-check — working an expired claim back to true

`references/research-grounding.md` says how a fact gets verified the **first** time.
This file is the second time, and every time after.

The tools are `tools/fact_freshness.py` (`report | stale | probes`) and
`validate_course.py freshness`. They can tell you a fact is old. Only a person or an
agent dispatching a real probe can tell you whether it is still true.

## Why this exists (the six defects)

An audit of five generated courses found, in shipped content:

| # | Defect | Class |
|---|---|---|
| 1 | A rent mechanism taught as current that no longer exists — the runtime rejects it up front | `protocol-param` |
| 2 | Rent constants matching no live cluster: the lesson printed 890,880 / 2,282,880; mainnet returns 810,624 / 2,077,224, devnet 650,240 / 1,666,240 | `onchain-number` |
| 3 | A protocol feature taught backwards (EIP-7702 delegation persists; the lesson said it does not) | `protocol-param` |
| 4 | A dead API taught as live — `quote-api.jup.ag` no longer resolves | `api` |
| 5 | An archived repo recommended as "the living reference" — read-only since 2025-03 | `api` |
| 6 | A hardcoded ATA rent figure invalidated mid-rollout by a network change, in ~10 sites including a graded quiz key | `onchain-number` |

Every one was **true when written**. None was a hallucination, a sloppy source, or a
missing grounding pass. They expired, quietly, and got re-shipped unread. That is a
different failure from ungrounded content and it needs a different gate: not "did you
check this?" but **"when did you last check this, and how would you check it again?"**

## The three fields

On every `lesson.research.claims[]` entry (`../references/output-contract.md`
§Research scaffold):

```yaml
- id: C4
  claim: "ATA rent-exempt minimum on mainnet is 2,077,224 lamports."
  kind: onchain-number          # closed vocabulary; sets the TTL
  status: verified
  verified_on: "2026-09-07"     # REQUIRED when verified. No date = no verification.
  mcp: helius                   # which kit surface answered
  value: "2077224 lamports (mainnet-beta, 165-byte account)"
  recheck: "helius heliusChain getMinimumBalanceForRentExemption 165 --cluster mainnet"
```

`recheck` is the field that makes this system work. A TTL without a probe just produces
an alarm nobody can act on; the honest response to "this is 40 days old, how do I check
it?" has to be one line you can paste. Prose (`"re-read the rent docs"`) is not a probe,
which is why it is a HARD failure on the four machine-readable kinds.

## The TTL table, and the evidence behind each number

Declared once in `tools/course_lib.py` (`TTL_DAYS`) so retuning one number reaches every
course. A per-claim `ttl_days` and a course-level `cadence.release.freshness_policy` may
only **shorten** these — lengthening is how an expired fact gets a second life without
anyone re-reading it.

| `kind` | TTL | Why that number |
|---|---:|---|
| `onchain-number` | **14d** | Defects #2 and #6. Rent-exempt minimums moved under a live rollout and invalidated a figure that was already in a graded quiz key. It is the fastest-moving thing a lesson prints and the only class in the audit that broke *twice*. 14d is also just under the corpus's median research-file age (~14–20 days), so it bites on a course's second publish rather than never. |
| `protocol-param` | **30d** | Defects #1 and #3. Feature gates activate on epoch boundaries; a Solana epoch is ~2–3 days, so 30d is roughly ten epochs — long enough that a stable parameter is not re-probed weekly, short enough to catch a cluster-wide activation before the next release wave. |
| `cli-default` | **30d** | Tracks the Agave/Anchor release train, which ships on roughly a monthly cadence. A scaffold's default output is exactly as perishable as the tool that emits it. |
| `version-pin` | **30d** | The same train, and it aligns with `references/pins.yaml`, which already runs its own `pinned_on` + `ttl_days` discipline. One re-probe pass can then refresh both instead of two schedules drifting apart. |
| `api` | **60d** | Defect #4 is the whole argument. The Jupiter claim was authored in the 2026-07-06 window and was dead by the audit — 63 days later. **A 90-day TTL still calls it fresh; 60 flags it.** Sixty days is the largest window that catches the one API death we actually observed. |
| `number` | **30d** | A bare figure with no cluster behind it. Between on-chain and concept; a real claim in the corpus (`speak-rpc/C1`) is caught here at 63 days. |
| `code` | **90d** | Shipped snippets are already re-compiled on every run by `verify_blocks.py` / `verify_code.py`. The TTL is a backstop for semantic rot the compiler cannot see, not the primary gate. |
| `concept` | **365d** | "DigiCash filed Chapter 11 in 1998" does not expire. A year is a liveness check on the **lesson**, not on the fact: if nobody has looked at a page in a year, its framing deserves a skim. |
| *(no `kind`)* | **30d** | A claim that does not say what it is gets the volatile default, never the concept default. Guessing "durable" on an undeclared claim is how a rent number would inherit a one-year TTL. |

**What the suggested table would have missed.** The starting proposal was `api: 90`. Run
against the real corpus that setting flags 1 claim; `api: 60` flags 2, and the extra one is
the dead-Jupiter class. That is the only change made to the suggestion, and it is the only
one the evidence supported.

**What no TTL setting catches.** Defect #3 (a feature taught backwards) and defect #5 (an
archived repo) were *wrong at authoring time*, not expired. A TTL cannot find those. What
finds them is the `recheck` probe being runnable at all: the first time someone executes
`curl -sSI <repo>` or reads the gate account, the claim fails. That is why an un-runnable
probe is a HARD failure and not a nag.

## Dispatch: from the stale list to a real answer

```bash
python3 tools/fact_freshness.py stale  --course content/courses/<id>   # the gate: exit 1 if anything expired
python3 tools/fact_freshness.py probes --course content/courses/<id>   # the worklist, ordered
python3 tools/fact_freshness.py probes --course content/courses/<id> --include-aging
```

`probes` prints, per claim: the lesson, the kind, the age against its TTL, the claim text,
the surface that answered last time, and the probe. Work it top-down.

1. **Run the `recheck` exactly as written**, through the surface in `mcp`. The mapping from
   `kind` to kit entrypoint is `../references/research-grounding.md` §"Grounding need → kit
   entrypoint": `onchain-number` → **helius**, `api`/`concept` → **solana-dev** then
   **context7**, `code` → **solana-dev** `program_autofixer`, "is this still true?" →
   **deep-research** / `solana-researcher`. Dispatch is literal: actually call the surface.
   A re-check done from model memory re-creates the exact defect this layer exists to catch,
   and is worse than the original because it now carries a fresh date.
2. **No network, no kit?** Follow the degradation ladder in `research-grounding.md`. If you
   cannot probe, the claim's `status` becomes `unverified` and it goes in `open_questions` —
   it does **not** get a new `verified_on`. A date is a record of a probe, never a promise.
3. **Unchanged** → bump `verified_on` to today. Nothing else moves.
4. **Changed** → the sweep below. Do not stop at the claim.
5. If the claim has no `recheck` yet, write one *while you are there*. That is the whole
   backfill: one line, once, and the next re-check costs nothing.

## The sweep rule: one correction, every site

**A correction is never a single-line edit.** Defect #6 is the proof — one ATA rent figure
was wrong in about ten places, including a graded quiz answer key, because it had been
pasted forward from the lesson that first computed it. Fixing the prose sentence would have
left the quiz grading learners against a number that no longer exists.

When a re-check comes back **changed**, before touching anything:

```bash
grep -rn "<the old value>" content/courses/<id>/           # every literal, all forms
grep -rn "890,880\|890880\|0.00089088" content/courses/<id>/    # commas, bare, and SOL-denominated
```

Then fix, in this order, and check each one off:

1. `manifest.json` — the claim's `value`, `verified_on`, `evidence`, and `recheck`
2. the same claim in `lessons/research/<stem>.research.yaml` (they are reconciled, and
   `fact_freshness.py report` prints `DRIFT` when they disagree)
3. `lessons/facts/<stem>.facts.md` — the frozen fact, which is a writer-style diff target
4. **every lesson draft** the grep found, not only the lesson that owns the claim
5. **`quiz_blocks`** — option labels, the `correct` flag, and per-option feedback. A stale
   number in a distractor is a wrong answer key, which is the only defect class here that
   actively penalizes a learner.
6. **`coding_challenges`** — `starter`, `solution`, and especially `tests.json`
   `expectedOutput`, where a hardcoded lamport figure turns a correct submission red
7. rendered visuals: the ` ```visual ` spec AND the `.html` source, then re-render
8. any `frozen_facts` entry in another lesson that quoted the number

Finally, re-run the gate and prove the sweep landed:

```bash
python3 tools/validate_course.py all --course content/courses/<id>
python3 tools/fact_freshness.py stale --course content/courses/<id>
python3 tools/verify_challenges.py content/courses/<id>     # if a tests.json moved
```

## Claims that predate `verified_on` (the grandfather clause)

`verified_on` shipped on `course_lib.FRESHNESS_EPOCH` (2026-09-07). Claims written before
it have no date and never will — 112 of the 127 claims in the ten-course corpus are in that
state. Both obvious answers are dishonest: treating them as fresh is the failure this layer
exists to prevent, and treating them as infinitely old HARD-fails the whole corpus on day
one, which gets the gate switched off within a week.

So an undated claim is **dated from the epoch**: *we do not know when you checked this, so
the clock starts the day we started asking.* The consequences follow from the table above
with no special cases — an undated `onchain-number` expires 14 days after the epoch, an
undated `api` at 60, an undated `concept` gets a year — and the missing-field rule itself is
ADVISORY for one publish cycle (`UNDATED_GRACE_DAYS`, 30 days) and HARD after.

A date is inferred from `evidence` only behind an explicit marker (`(dispatched
2026-07-06)`, `verified 2026-07-06`). A bare year inside a cited URL is **not** inferred:
`coindesk.com 2026-01-21` is an article's publication date, not a verification date, and
mining it would manufacture staleness that nobody could act on. Write the field.

## What green does not mean

`fact_freshness.py stale` passing means *no declared claim is past its TTL*. It does not
mean the lesson's facts are fresh, because **a fact that is not a claim is on no clock at
all.** Eight of the ten courses in the corpus declare zero claims while freezing volatile
numbers in `frozen_facts` — including the course that shipped the wrong rent constants.
`report` and `validate_course.py freshness` call that out by name (`ZERO claims`); it is an
advisory rather than a hard failure only because promoting 200 lessons' frozen facts is a
migration, not a fix. Treat it as the loudest advisory in the gate.
