# The Handoff Contract — course spec & lesson-brief schema

This is the **interface between `content-gen` and `writer-style`.** The architect emits
these artifacts; the voice skill consumes the lesson briefs and writes the prose. Every field exists either
to constrain the structure or to feed the writer — nothing decorative.

The golden rule: **the brief specifies *what* is taught, in *what order*, and proven *how* — never *how it
sounds*.** Leave the prose, jokes, analogies, and rhythm to the voice skill. An over-specified brief
strangles the voice (see `design-spine.md` §10).

**`id` convention:** all `id` fields (course/module/lesson) are kebab-case, outcome-led, unique within a
course, and **stable across the handoff** — the voice skill references lessons by these ids. `depends_on`
and `prerequisites` are id edges, so a typo'd edge is caught as a HARD failure by `tools/validate_course.py dag`
(`references/quality-bar.md`, validation-procedure step 1); keep them canonical.

---

## A. Course Spec (one per course)

```yaml
course:
  title:                 # outcome-led, not topic-led ("Ship Your First Solana Program", not "Intro to Solana")
  one_line_promise:      # "By the end you can build, test, and deploy X"
  audience:
    who:                 # absolute-beginner | web2-dev | evm-dev | solana-dev-leveling-up | non-technical
    prior_model:         # what they already know that we map from/against
    prerequisites:       # hard prereqs (e.g. "comfortable with TypeScript"); keep minimal
  terminal_outcomes:     # the measurable, Bloom-tagged capabilities the whole course proves
    - {bloom: create, statement: "build, test and deploy a PDA-backed SPL-token vault with correct auth checks"}
  format:                # self-paced | cohort | workshop | docs-path
  length_target:         # hours / lessons / weeks (be honest; prefer tight over exhaustive)
  credential:            # none | self-assessment | auto-graded | on-chain-NFT | certificate
  backbone_pattern:      # ordered phases of the ONE backbone track (opener -> engine); guests never appear here
  lesson_template:       # the default lesson pattern (usually overview-lab-challenge)
  capstone:              # the terminal artifact + how it's assessed
  prerequisite_dag:      # ordered skill nodes (see solana-syllabus-dag.md); the spine of the sequence
  modules:               # ordered list of module ids -> see Module Spec
```

## B. Module Spec (one per module)

```yaml
module:
  id:
  title:                 # driving-question or artifact framed
  driving_question:      # "how do we let users stake SOL trustlessly?"
  outcome:               # Bloom-tagged module outcome (subset of terminal outcomes)
  artifact:              # the build this module produces (a rung on the artifact ladder)
  depends_on:            # module/skill ids that must precede it (DAG edge)
  patterns:              # the pattern(s) leaned on here (backbone + ≤1-2 guests)
  difficulty_band:       # 1-3; should ramp across the course (fading)
  lessons:               # ordered list of lesson ids -> see Lesson Brief
  retrieval_checkpoint:  # the spaced-retrieval / interleaving check that closes the module
```

## C. Lesson Brief (one per lesson) — THE handoff unit

```yaml
lesson:
  id:
  title:                 # outcome-led ("Store per-user state with a PDA")
  kind:                  # build (default) | concept — concept lessons drop artifact_spec/exercise_spec/fading
  objectives:            # measurable, Bloom-tagged; 1-3 max
    - {bloom: implement, statement: "derive a canonical PDA and write per-user account data"}
  prerequisites:         # lesson/skill ids (must already be taught — DAG check)
  skills:                # what THIS lesson teaches, as DAG skill nodes or academy skill slugs → the learner-facing tags on the lesson card. OMIT and the export derives them from the MODULE, which gives every lesson in that module the same array (validator ADVISORY at >80% identical).
  hook:                  # the FELT problem / exploit / demo that opens it  → feeds voice pain-first opener
  concept_spec:          # the idea(s) to teach + the worked example to build (one new element per pass)
  artifact_spec:         # exactly what the learner builds this lesson (the ladder rung / accretion)
  artifact:              # DERIVED VIEW of `ledger` below: {id, consumes: [earlier artifact ids], terminal: <reason>}
  ledger:                # REQUIRED for kind: build — the continuity contract (see §I)
    state_in:            #   one honest line: what is in the reader's tree as this lesson OPENS
    state_out:           #   one honest line: what is in it when the lesson CLOSES
    opens: []            #   course-relative paths this lesson tells the reader to open. MUST ALREADY EXIST.
    emits: []            #   course-relative paths this lesson creates
    provides: []         #   symbols defined here: "fn:derive_vault_pda" | {symbol:, sig: "(a, b)", terminal: <reason>}
    consumes: []         #   symbols from EARLIER lessons this lesson uses
    renames: []          #   [{from, to, since_lesson}] — from == to declares a SIGNATURE change
  verify:                # RECOMMENDED for build lessons: {command, expect} — the one-line paste-and-see proof (CI smoke tier)
  exercise_spec:         # the completion problem + the unguided challenge + acceptance criteria
  the_tradeoff:          # the cost / limit / "when not to use it"  → feeds voice always-name-the-tradeoff
  just_in_time:
    define:              # concepts to define at point of use (don't front-load)
    footguns:            # the specific traps to flag inline (NOTE/TIP/IMPORTANT)
  assessment:            # how mastery is proven (gate on doing); string or {gate, answer_shape} — answer_shape keeps the from-memory close a 30-second win
  difficulty: 1          # 1-3
  fading:                # where this sits on the worked→completion→solo schedule
  dominant_job:          # show-how | derive-why | demystify | economics | frame | sustain | motivate  ← VOICE ROUTER INPUT
  voice_notes:           # optional voice hints: guest craft, an audience-stakes angle, a real number to cite
  flow:                  # the narrative thread (REQUIRED for course lessons — quality-bar JUDGE row)
    recap:               # one line: where the course stands as this opens (call back the previous artifact)
    forward_hook:        # the cliffhanger/promise that closes the lesson and opens the next
  color:                 # 1-3 grounded trivia/history beats to weave in (named incidents, dated numbers) — never invented
  est_length:            # THE length contract — the writer writes to this number. Course lessons: ~3000-4500w (keystone topics higher). Validator flags targets below 3000.
  # ── OPTIONAL Academy plugins (additive; see §H and references/academy-schema.md) ──
  quiz_blocks:           # OPTIONAL: formative checks. A list of Academy quiz BLOCKS (each becomes one `type: quiz` block INLINE in lesson.yaml on export — never a standalone *.quiz.yaml). Never gates the lesson.
    - key:               #   kebab block key (e.g. check). Optional; defaults to check / check-N.
      questions:
        - id:            #   stable; correctness is keyed to this id, never option order. NEVER renamed after authoring.
          prompt:
          multiSelect:   #   default false → exactly ONE correct option. true only where the honest answer is a SET; then ≥5 options and 2 ≤ correct ≤ k-2.
          options:       #   ≥4, and exactly 5 when the mean label is ≤70 chars. Opaque ids o1…o5. `feedback` on EVERY option, the correct one included.
            - {id: o1, label: "...", correct: false, feedback: "why this one misses"}
            - {id: o2, label: "...", correct: true,  feedback: "why this one is right"}
            - {id: o3, label: "...", correct: false, feedback: "why this one misses"}
            - {id: o4, label: "...", correct: false, feedback: "why this one misses"}
            - {id: o5, label: "...", correct: false, feedback: "why this one misses"}
          #   DO NOT THINK ABOUT OPTION ORDER. Write the options in whatever order they occur
          #   to you; `tools/quiz_layout.py permute` assigns the final order from a hash and
          #   records it in a ledger. Hand-ordering is a gate failure (validate_course.py quiz).
          explanation:   #   REQUIRED. Shown after answering — the paragraph that teaches the point.
  coding_challenges:     # OPTIONAL: runnable exercises. Only for rust|typescript (the Academy runner compiles ONLY these). Bitcoin/CLI/Python/Solidity lessons take quizzes, not code blocks.
    - id:                #   kebab; becomes the exercise dir name on export
      language:          #   rust | typescript
      buildType:         #   standard (default) | buildable (Rust/Anchor compile-check with a hidden `mod verify` harness)
      title:             #   optional learner-facing title
      prompt:            #   optional what-to-do (the writer expands it; the file comments carry the real spec)
      starter:           #   course-relative path — e.g. lessons/challenges/<lesson-id>/<challenge-id>/starter.rs
      solution:          #   course-relative path (the reference; starter MUST fail its tests, solution MUST pass)
      tests:             #   course-relative path to tests.json ([{id,input,expectedOutput,description?}])
      hints: []          #   optional
      acceptance_criteria: []   # what "done" means (feeds the writer + validated non-empty)
      difficulty:        #   1-3
      bloom:             #   the Bloom verb the challenge exercises
```

---

## D. `dominant_job` → voice-skill routing (the critical integration)

The craft names below mirror the writer-style release and may evolve there; the binding
contract is the `dominant_job` enum, resolved against the **installed** writer-style at
runtime. The architect classifies each lesson's **dominant job** and writes it into the brief. The voice skill's
router (the `writer-style` skill's own router, `profiles/<profile>/ROUTING.md` as of writer-style
v1.2.0 — locate via that skill's install, never a hardcoded relative path) consumes it directly —
so the architecture decides the routing, and the writer never has to guess.

| Lesson's dominant job | `dominant_job` | Voice craft the brief should trigger |
|---|---|---|
| Show how a documented thing works, step-by-step (most labs/tutorials) | `show-how` | **Helius** (expository backbone) |
| Derive *why* a contested/intricate design is right | `derive-why` | **Vitalik** |
| Demystify one hyped/misframed thing by collapsing it ("X is just Y") | `demystify` | **Hotz** — *as a single-position guest over a Helius/spine backbone, never a whole-lesson Hotz backbone; extra-careful on security* |
| Make economics / tokenomics / value-flows legible | `economics` | **Hayes** (*if the lesson is also a mechanism derivation, tag `derive-why` instead → Vitalik backbone + Hayes guest; derivation wins*) |
| Frame a broad/contestable thesis or the ecosystem up front | `frame` | **Balaji** — *opener-guest only, never a whole-lesson backbone* |
| Sustain a long / cold-audience / intimidating lesson (abandonment risk) | `sustain` | **Hayes** (engagement & stamina) |
| Motivation / "why this matters" / course-opener | `motivate` | **Kaue's spine carries it** (no craft backbone) |
| Diagnose/fix a documented failure (debugging, security walkthrough) | `show-how` (+note) | **Helius**, guest Vitalik/Hotz per the voice router |

Rules of thumb the architect should honor so the handoff is clean:
- **Openers and "why it matters" beats → `motivate`** (spine-only; don't over-craft).
- **Security exploit-then-patch lessons → `show-how`** with a `voice_notes` flag "security: be wary of Hotz
  reductive collapse" (mirrors the voice router's security caution).
- **A lesson whose real job is *derivation* is `derive-why`, even if it's technical** (don't default every
  technical lesson to `show-how`).
- **`frame` and `demystify` are guest jobs, never backbones** — the voice skill uses Balaji and Hotz only
  as single-position guests. Tag them only when that guest move genuinely *leads* the lesson; the writer
  carries the body in Helius/Vitalik/spine.
- **`sustain` ≠ `economics`** — use `sustain` for long, non-economic, cold-audience lessons at abandonment
  risk (Hayes's engagement craft); use `economics` only for real value-flow/tokenomics content.
- **One dominant job per lesson.** If a lesson is genuinely two jobs, that's a signal to split it.

---

## E. Minimal worked example (one filled lesson brief)

```yaml
lesson:
  id: pdas-per-user-state
  title: "Store per-user state with a PDA"
  objectives:
    - {bloom: explain, statement: "explain why Solana has no mappings and how PDAs replace them"}
    - {bloom: implement, statement: "derive a canonical PDA and write per-user account data"}
  prerequisites: [accounts-and-rent, your-first-program, the-counter]
  hook: "In Solidity you'd reach for mapping(address => Data). Solana has no mappings. So where does per-user data live?"
  concept_spec: "PDAs as program-owned, deterministically-derived accounts; find_program_address; canonical bump. Build by extending the running counter to one account PER user."
  artifact_spec: "Upgrade the counter program so each user gets their own counter PDA, seeded by their pubkey."
  exercise_spec: "Completion: fill in the seeds array (TODO). Solo: add a second PDA keyed by a string label. Accept: two users get distinct, recoverable accounts; test passes."
  the_tradeoff: "Deterministic + no key to manage, BUT you must store or recompute the bump, and a sloppy seed scheme is an exploit (collision / spoofing)."
  just_in_time:
    define: [program-derived-address, canonical-bump, seeds]
    footguns: ["using a non-canonical bump", "user-controlled seeds without validation"]
  assessment: "anchor test: two distinct users write and read back their own counter; reinit attempt fails."
  difficulty: 2
  fading: "worked derivation shown; completion problem for seeds; solo for the second PDA"
  dominant_job: derive-why
  voice_notes: "contested 'why no mappings' — Vitalik craft over spine; a real devnet number for account size/rent is a good seam."
  est_length: "1200 words / ~12 min"
```

This brief is **voice-ready**: it hands the writer a felt hook, a named trade-off, a concrete artifact with
real numbers, and a `dominant_job` that routes the craft — and stops there, leaving the prose to Kaue.

---

## F. Content Brief — the non-course forms (tutorial, walkthrough, explainer, essay, litepaper, slides, post)

The same seam, one unit instead of a filesystem. Core keys are shared with §C; each form adds its own
(defined in `forms/<form>.md`). A `post` fills this inline and skips the file.

```yaml
content:
  id:                    # kebab-case slug; also the content/<form-plural>/<slug>/ dir name
  form:                  # tutorial | walkthrough | explainer | essay | litepaper | slides | post
  title:                 # outcome-led
  audience: {who:, prior_model:}
  objective:             # ONE measurable, Bloom-tagged statement
    {bloom:, statement:}
  hook:                  # the felt problem that opens it
  concept_spec:          # the idea(s) taught + the concrete example that carries them
  the_tradeoff:          # the cost / limit / "when not to use it"
  dominant_job:          # same enum + routing as §D
  est_length:            # words / slides / thread units
  visuals: light         # none | light | rich (see references/visual-placeholders.md)
  deliverable: full-text # full-text (default) | brief-only
  frozen_facts: []       # grounded claims the text must carry verbatim
  # + the form's extra keys — see forms/<form>.md
```

Emitted alongside the piece as `content/<form-plural>/<slug>/brief.yaml` (threads: `content/threads/<slug>/`; except unsaved posts). The §D
`dominant_job` routing applies unchanged — this is what keeps a tutorial, an essay, and a
course lesson consistent when they pass through the same voice.


## G. Fact & recap discipline (hardening)

- **`frozen_facts` are ATOMIC.** One verbatim value per line — a version, id, number, port,
  or a single exact command — each appearing verbatim once in the prose. NEVER a
  multi-clause sentence, a multi-version mention, or a templated command with placeholders
  (`<program_name>`, generic `MyType`): the writer-style facts diff checks every extracted
  token and a templated/multi-value fact false-fails. Keep the rich prose in the draft;
  keep the checkable atoms in `frozen_facts`.
- **`flow.recap` is honest.** It calls back only what the previous lesson genuinely did or
  built. A recap that invents a prior experience breaks the spine; the writer must open on
  the real previous artifact/step.
- **Every claim carries an expiry.** `lesson.research.claims[]` takes `verified_on` (ISO
  date, HARD-required when `status: verified`), an optional `ttl_days` that may only
  SHORTEN its kind's default, and a `recheck` holding the exact re-runnable probe. The
  `kind` vocabulary is closed: `concept | number | api | code | onchain-number |
  cli-default | version-pin | protocol-param`. Defaults live once in
  `tools/course_lib.py` (`TTL_DAYS`); the workflow is `method/fact-recheck.md`; the gates
  are `validate_course.py freshness`, `fact_freshness.py stale`, and `academy_export.py`,
  which refuses to publish a past-TTL claim without `--allow-stale`.
- **A `frozen_fact` that can change is a `claim`.** The facts file is a diff target for the
  writer, not an expiry ledger — nothing in `frozen_facts` is on any clock. A version, a
  rent figure, an endpoint, or a CLI default belongs in `claims[]` WITH a `recheck`, and
  may then also be frozen. Eight of the ten courses in the corpus froze volatile numbers
  and declared zero claims, which is precisely why the rent constants shipped wrong.


## H. Academy plugins — quizzes & coding challenges (optional, additive)

`quiz_blocks` and `coding_challenges` are the two **interactive plugins** the Superteam Academy
platform runs (`references/academy-schema.md`). They are OPTIONAL — a brief without them is unchanged,
and adding them never rewrites existing lessons. `tools/academy_export.py` projects them into a
publishable Academy course; `tools/validate_course.py` validates the specs (`check_briefs` +
`check_challenges`); `tools/verify_challenges.py` proves the runtime contract.

- **Quizzes are formative — they never gate.** Only `assessment` gates the lesson (design-spine §6/§6.1).
  **Artifacts gate; quizzes check.** A quiz gives immediate per-option feedback on understanding and
  awards nothing. Quizzes are language-agnostic — a Bitcoin, EVM, or CLI lesson still earns one.
  **Emit them INLINE**: a `quiz_blocks` entry becomes a `type: quiz` block inside `lesson.yaml`. A
  standalone `*.quiz.yaml` lints green and is then silently dropped by the platform compiler, so the
  lesson ships with no check and nothing reports it. `validate_course.py quiz` HARD-fails one.
- **The authoring policy** (all HARD in `validate_course.py quiz`; full rationale in
  references/academy-schema.md §Quiz):
  - **≥4 options, and exactly 5 when the mean option label is ≤70 characters.** Short labels are cheap;
    a 3-option question with one-line options is close to a coin flip.
  - **`multiSelect: true` wherever the honest answer is a set.** No cap and no quota — but never convert
    a single-answer question to multiSelect just to add difficulty. Its floor is 5 options with
    2 ≤ correct ≤ k−2, so neither "all of them" nor "exactly one" is a guess that works.
  - **`feedback` on EVERY option, the correct one included**, and an `explanation` on every question.
    The correct option's feedback is where the "yes, and here is why that is the distinction" lands.
  - **Opaque ids `o1…o5`**, so nothing implies id order is display order. Ids are NEVER renamed after
    authoring: correctness, translations, and the layout ledger all bind on them.
  - **Distractors are REAL misconceptions**, parallel to the answer in length and register. Never joke
    options, never a giveaway-long correct label: the gate scores a content-blind learner's actual
    strategies (longest, shortest, only-hedged, only-one-without-an-absolute, most-prompt-overlap) and
    HARD-fails any that beats chance.
- **DO NOT THINK ABOUT OPTION ORDER.** Write the options in whatever order they occur to you.
  `tools/quiz_layout.py permute` assigns the final order from
  `sha256(salt | courseId | lessonSlug | blockKey | questionId)` and records it in a ledger;
  `validate_course.py quiz` HARD-fails a ledger that drifted. Hand-ordering is a gate failure.
  This is the branch's governing law: **when a statistical property must hold, compute it in a tool;
  never ask for it in a prompt.** The previous version of this section asked authors to "vary the
  correct slot", and the wave-2 generator turned that into a per-lesson a→b→c rotation whose marginal
  was perfect and whose *sequence* was 85-94% predictable.
- **Coding challenges are runnable and RUST/TYPESCRIPT ONLY** (the Academy sandbox compiles only these).
  Author them where the lesson's real code is client-side Solana TS or a Rust/Anchor program. The **starter
  must fail** its tests and the **solution must pass** — that contract is the grade, so keep the solution
  the real, working code. The challenge code lives in FILES under `lessons/challenges/<lesson-id>/
  <challenge-id>/` (starter/solution + tests.json); the brief only points at them. Three test modes exist —
  TS (boolean expression over `result = fn(input)`), Rust `standard` (value compare), and Rust `buildable`
  (compiles ⇒ pass, enforced by a hidden `mod verify` harness). See `references/academy-schema.md`.

---

## I. The continuity ledger (`lesson.ledger`) — what the reader's tree actually holds

An independent audit of five courses this skill generated found the same defect in **every
one of them**: a later lesson presumes an artifact the earlier lessons never produced, or
produced under a different name. Four lessons in one course open on starter scaffolds the
course never ships (`swap.js`, `toolkit/vault`, `bot/`, `opsbot.py`). A payments course
claims a gasless path "lives inside the txreq app already"; it was never mounted. One course
renames `init_vault` to `initialize` mid-way and later verbatim code keeps calling the old
name. Another grows a helper from 2 arguments to 3 at `m02-l2`, and two later labs still call
it with 2 — both crash before any transaction reaches the network.

Every one was found by a human reading the course end to end. **None was catchable by any
check this skill shipped**, because `artifact_spec` is prose and prose is not a graph.

The ledger is that graph. It is REQUIRED on `kind: build` lessons.

### The fields

| field | what it holds | what it stops |
|---|---|---|
| `state_in` | one honest line: what is in the reader's tree as the lesson OPENS | a `flow.recap` that invents a prior experience |
| `state_out` | the same line for the close | the next lesson's `state_in` disagreeing with it |
| `opens` | course-relative paths this lesson tells the reader to open — **they must already exist** | `cd toolkit/vault` on a scaffold nobody shipped |
| `emits` | course-relative paths this lesson creates | the same, from the other side |
| `provides` | symbols defined here | a capstone that needs a pool no lesson creates |
| `consumes` | symbols from EARLIER lessons used here | using a helper before it is written |
| `renames` | `[{from, to, since_lesson}]` | later code that kept the old name |

**`opens` means MUST-ALREADY-EXIST.** That is the whole distinction from `emits`, and it is
what makes the check possible: a lesson listing the same path in both is telling the reader
to run a file it has not written yet, which is a HARD failure. If the course genuinely ships
the scaffold, declare it in `course.starter_assets` and the check passes.

### Symbol grammar

Every symbol is `<kind>:<name>`, from a closed set — an unrecognized kind is a HARD failure,
because a typo'd kind silently disables every rule that depends on it:

```
fn:derive_vault_pda      type:VaultConfig     const:VAULT_SEED     ix:initialize
cmd:npm run mint         file:scripts/mint.ts env:HELIUS_API_KEY   account:vault-pda
artifact:anchor-vault    ← the bridge kind; see below
```

A `provides` entry may be a bare string or a dict carrying the signature:

```yaml
provides:
  - fn:derive_vault_pda                                    # no signature declared
  - {symbol: "fn:mint", sig: "(conn, payer, amount)"}      # arity 3
  - {symbol: "fn:send", sig: "(payer, ixs, opts = {})"}    # arity 2..3 — a default widens the span
  - {symbol: "fn:teardown", terminal: "debug aid; nothing downstream needs it"}
```

Declare `sig` wherever a later lesson calls the symbol. It is what lets
`tools/continuity.py scan` compare real call sites against the shape you promised.

### Renames, and the same-name signature change

```yaml
renames:
  - {from: "fn:init_vault", to: "fn:initialize", since_lesson: m03-l2}
  - {from: "fn:resolveAta", to: "fn:resolveAta", since_lesson: m02-l2}   # same name, new shape
```

`from == to` declares a **re-signature**: the name did not move, only its arguments did. It
licenses the signature-drift rule and nothing else. Any lesson at or after `since_lesson`
that still declares the OLD name is a HARD failure.

### `artifact` is a VIEW over this, not a second system

`brief.artifact.{id, consumes}` is read as `artifact:<id>` in the same graph, so the accretion
ladder and the symbol ledger are one DAG. A course may declare its rungs in either shape (or
both) and the two checks can never disagree about what was built when.
`validate_course.py artifacts` owns the `artifact:` edges; `validate_course.py continuity`
owns everything else, so each flag is printed exactly once.

### What checks it

- **`validate_course.py continuity`** — manifest-only, HARD, in `CHECKS` (so `all` and CI
  tier 1 pick it up). A *missing* ledger is ADVISORY, never HARD: the ledger is new, ten real
  courses predate it, and a gate that fails all ten on its first run is one people learn to
  bypass. What is HARD is a ledger that **contradicts itself** — which every defect above
  becomes, the moment the lesson says out loud what it expects to find.
- **`tools/continuity.py`** — the half that needs the tree: shipped-path existence, the
  rename scan over later code fences, and the call-site scan. **All advisory.** See that
  file's header for the fence-scoping discipline it is written under
  (`method/known-failure-modes.md` §1).
