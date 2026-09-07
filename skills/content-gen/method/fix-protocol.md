# Method: fix-protocol
> How to correct a fact in a shipped course without manufacturing the next round of findings.
> Load this **before** applying any audit fix, review-board correction, or freshness re-pin.

A round-2 audit of the wave-2 courses returned 278 confirmed findings. **Roughly 17% of them —
about 48 — were fallout from round 1's own fix wave.** Not bad fixes: *narrow* ones. The
correction landed at the line somebody filed, and the same claim went on shipping from the twin
passage two lessons later, the quiz feedback, the image alt text, the `visual-src` markup, the
`<!-- spec -->` comment a future re-render rebuilds from, and the exported copy.

**Six shipped images still taught models the corrected prose beside them retracted.** One lesson's
fixed prose says "you do not get a silent v1 artifact, you get a loud failure" while the flowchart
two lines above it renders "builds clean, no V2 errors" → "v1 artifact, silently wrong". Another
retracts a fabricated documentation quote in prose and keeps rendering it, inside quotation marks,
under the heading "The docs' own words".

This skill's own handoff records the identical shape at a smaller scale: *the staircase removal
landed in l3's prompt and prose but not its `purpose:` line, and the rejected staircase metaphor
still runs in l1.*

The failure is never the edit. It is that a claim has **fourteen** homes and everybody remembers
the first one.

---

## 1. The surface list (read it every time; do not recall it)

A course lesson is one idea rendered into many artifacts. Correcting the idea means correcting
every rendering of it. In descending order of how easily each is missed:

| # | Surface | Where it lives | Why it is missed |
|---|---|---|---|
| 1 | **draft prose** | `lessons/drafts/<stem>.md`, outside fences | it isn't — this is the filed line |
| 2 | **code fences in that draft** | same file, inside ``` fences | the fact is often a version, a flag, a limit *inside the command* |
| 3 | **duplicated code in a twin lesson** | another draft, or `lessons/challenges/**` | the twin's prose is rewritten, so a text search cannot find it. Found by **structure**, see §3 |
| 4 | **the ` ```visual ` block's `data:` and `prompt:`** | same draft | this is the **regeneration spec**: a correct image re-rendered from a stale spec silently regresses the fix |
| 5 | **that block's `purpose:` and `alt:`** | same draft | `alt` is the only thing a screen-reader user is taught, and it **paraphrases** — it spells "two hundred" where the spec says "200" |
| 6 | **the authored `visual-src` HTML** | `lessons/assets/<stem>/vNN-*.html` | it carries BOTH the rendered markup and a copy of the spec in an `<!-- -->` comment; fix both |
| 7 | **the rendered image** | `vNN-*.png` / `.webp` beside it | **it is a binary. No grep will ever find it.** See §4 |
| 8 | **the brief** | `lessons/briefs/*.brief.yaml` **and** `manifest.json` | `hook`, `concept_spec`, `the_tradeoff`, `flow.recap`, `flow.forward_hook`. Two copies, and the manifest is the one the export reads |
| 9 | **quiz `prompt` / `label` / `feedback` / `explanation`** | `manifest.json` (inline, never a `*.quiz.yaml`) | prose nobody re-reads, on a **graded** surface. The audit's single most common fallout site |
| 10 | **challenge `starter` / `solution` / `tests.json` / acceptance** | `lessons/challenges/<lesson>/<id>/` | it is *executed*, so a stale value here is a failing grade, not a wrong sentence |
| 11 | **the facts + research entries** | `lessons/facts/*.facts.md`, `lessons/research/*.research.yaml`, and their `manifest.json` copies | the grounding record is what the NEXT correction will be checked against; leaving it stale re-teaches the error |
| 12 | **`verified_on`** | on the research claim you just changed | a corrected claim carrying an old verification date is a lie about provenance |
| 13 | **course-level text** | `course.yaml`, `README.md`, `000-cover.md`, `modules/*/module.yaml`, `branding/banner.html` | the cover is the first thing read and the last thing edited |
| 14 | **later lessons that recap the claim** | any draft after this one | `flow.recap` exists precisely to restate earlier facts |
| 15 | **the exported tree** | `content/academy/courses/<slug>/**` | it is a *copy*. Fixing the source and not re-exporting ships the old text |

## 2. The protocol

```bash
SKILL=...   # skills/content-gen

# 1. PLAN — never fix first. The ledger is the work list.
python3 "$SKILL/tools/fix_sweep.py" plan content/courses/<id> \
    --claim "200 pulls per 6 hours" \
    --also  "own two hundred" \
    --to    "the vendor's current published limit" \
    --id    fix-docker-hub-pull-cap

# 2. Fix every listed surface. Re-render every listed image.
python3 "$SKILL/tools/render_visuals.py" render content/courses/<id>

# 3. CHECK — exits 1 while any surface still matches, or any render is stale.
python3 "$SKILL/tools/fix_sweep.py" check content/courses/<id>

# 4. CLOSE — flips status: open -> closed, and only when clean.
python3 "$SKILL/tools/fix_sweep.py" close content/courses/<id> --fix fix-docker-hub-pull-cap
```

`plan` writes `content/courses/<id>/fixes/<fix-id>.yaml`: every hit grouped by surface class, the
rendered assets hanging off each hit HTML, and a `review:` list of things a machine cannot settle.
`validate_course.py fixes` **HARD-fails any ledger still `status: open`**, so the sweep cannot be
abandoned halfway — which is exactly how it was abandoned before.

**Sweep the atom, not the sentence.** `frozen_facts` are already atomic by rule
(`lesson-brief-schema.md` §G), and that is the right granularity here too. On the real Docker
lesson, `--claim "200 pulls per 6 hours"` finds 8 surfaces; `--claim "200 pulls"` finds 11,
because the shipped figure writes `200 pulls / 6 h` and the regeneration prompt writes
`meter labeled "200 pulls /`. Use `--also` for the phrasings that are not substrings of each
other — above all the alt text, which spells numbers out.

**Never insert an unsourced specific while fixing.** A third of the audit's fallout is a *new*
claim the fix invented to fill the hole it made: a "twenty minutes" that nothing measured, an
"effectively unlimited" that replaced a correct, sourced figure. If the correct value is not in
hand, the honest fix removes the claim.

## 3. Twins are found by structure, not by text

A snippet duplicated into a later lesson has different prose around it, rewritten comments, and
different indentation. Grep cannot see it. `fix_sweep` normalises every code fence in the course
(strip the language's line comments and `/* */`, strip all whitespace) and hashes it; two fences
with the same hash are the same code however they are dressed. Challenge `starter`/`solution`
files are hashed as whole-file fences for the same reason — that is where a lab's code most often
gets a second life.

Origin fences are the ones that literally carry the claim, if any do; otherwise every substantial
fence (≥80 normalised chars, ≥3 lines) in a file the sweep already hit. `cargo build` is in every
lesson and reporting it is noise, not a finding.

A twin is always a **warning**, never a failure: identical structure is often correct duplication.
It is listed so a human says so, out loud, once.

## 4. The image rule (the one that actually bites)

Six shipped images taught retracted models because an image is a binary and nobody greps a PNG.

The only reliable signal is provenance: **a rendered asset is generated FROM its HTML source, so a
correctly re-rendered image is newer than the HTML it came from.** `fix_sweep check` therefore
fails while any listed render is older than its source:

```
lessons/assets/m05-l2-m06-l2/v04-diagram.png is OLDER than
lessons/assets/m05-l2-m06-l2/v04-diagram.html — the shipped image still teaches the
retracted model; re-run render_visuals.py render
```

Two consequences worth internalising:

- **Editing the HTML and not re-rendering is now a gate failure**, not a thing you were supposed
  to remember.
- **Re-rendering without fixing the `<!-- spec -->` comment is still wrong**, and the sweep lists
  that comment as its own surface (class `visual-spec`). The audit found rendered cards corrected
  to a new lineage while the spec comments driving the *next* regeneration still narrated the old
  one. The image was right and one command from being wrong again.

## 5. When the old text is right somewhere

A literal can be correct in one place and wrong in another: a history lesson that quotes the old
figure on purpose, a changelog that must carry it. `check` re-sweeps the whole course, so those
hits would keep the sweep open forever, and a gate that cannot be closed gets deleted. Add the
path (or `path:line`) to the ledger by hand:

```yaml
exempt:
  - lessons/drafts/m02-l1-history.md
```

It is reported on every run as `exempt by hand: … the old text is correct here`. Never silent, and
never a way to close a sweep you did not do — an exemption is a claim about *that* file, written
down, that the next reviewer can argue with.

## 6. What the tool cannot decide (`review:`)

Two rows come back as by-hand checks because no literal can settle them:

- **A visual whose spec matched but whose `alt:`/`purpose:` did not.** Alt text paraphrases; it may
  be correct, or it may still teach the old model in different words. Read it.
- **A lesson that matched but whose quiz did not.** Quiz feedback is where a corrected fact most
  often survives, and a quiz that says nothing about the claim is either fine or the single worst
  place to leave it wrong — a graded surface teaching the retracted model.

## 7. The rule

> **A fix is not applied at a line. It is applied to a claim, across every rendering of that
> claim, and it is not done until the images agree with the prose.**

A correction that ships to one of fifteen surfaces has not fixed the course; it has made the
course inconsistent with itself, which is strictly worse than the original error, because now the
learner cannot tell which one to believe.
