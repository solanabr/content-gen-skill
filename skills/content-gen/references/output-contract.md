# The Output Contract — what the skill emits

The content-gen skill's terminal step **materializes a course as a filesystem**.
This document defines the single authored source (`manifest.json`), the emitted
tree, and every file's schema. The tools in `../tools/` are the executable copy of
this contract: `../tools/scaffold_course.py` emits the tree from the manifest;
`../tools/validate_course.py` checks the manifest. Keep this doc and those tools in sync.

## The two representations

1. **`manifest.json` — the authored source of truth (JSON).** The architect writes
   ONE JSON object describing the whole course. JSON (not YAML) because it parses
   with the Python stdlib, bulletproof — no fragile YAML reader to rot.
2. **The emitted tree (YAML + md) — a one-way projection.** `scaffold_course.py
   emit` splits the manifest into human-readable, handoff-ready files. We never
   *parse* the YAML back; the manifest is regenerable and canonical. Editing the
   course = editing the manifest and re-emitting (human edits to emitted files are
   protected by hash-drift detection in `course.lock.json`).

```
                manifest.json  ──scaffold_course.py emit──▶  content/courses/<id>/…(YAML tree)
                      │                                              │
                      └────────── validate_course.py all ───────────┘  (reads manifest.json)
```

## The emitted tree

```
content/courses/<course-id>/
├── 000-cover.md            # generated course cover: summary, prereqs, toolchain, concepts, map (never hand-edit)
├── course.yaml            # readable course-level projection (spec + dag + glossary + indexes)
├── manifest.json          # the authored source, copied in (regenerable, canonical)
├── README.md              # generated rich syllabus: promise, outcomes, lesson table, toolkit, toolchain, how-generated, layout (generated sections are re-emittable; a course-specific narrative may be appended below by hand)
├── _state.yaml            # progress ledger: briefed→researched→drafted→verified→published
├── course.lock.json       # per-file sha256 + edited_by_human (idempotency / edit protection)
├── cadence.yaml           # pedagogy block + release block
├── assessment.yaml        # proof_matrix + checkpoints + capstone
├── modules/NN-slug/module.yaml
├── lessons/
│   ├── briefs/<mNN-lN-id>.brief.yaml      # paste-ready into /write-in-voice (top key: lesson:)
│   ├── research/<mNN-lN-id>.research.yaml # claims/sources/frozen facts (researcher + writer Pass A)
│   ├── facts/<mNN-lN-id>.facts.md         # frozen facts, one/line → writer-style's facts-diff gate
│   └── drafts/                            # writer OUTPUT lands here → writer-style's audit gate
├── queue/NEXT.md          # the ready-to-write packet for the next unblocked lesson
└── assets/                # optional starter scaffolds / diagrams
```

`lessons/{briefs,research,facts,drafts}/` are **flat by kind** on purpose:
writer-style's audit gate globs one flat directory
of `*.md`, so `drafts/` must be flat. The `mNN-lN-<id>` filename prefix is the
join key across the four dirs and a human sort order; the stable handle is the
`id` *inside* the file, never the filename (so renumbering never breaks an edge).

## `manifest.json` schema

```jsonc
{
  "schema_version": 1,
  "course": {
    "id": "solana-for-solidity-devs",          // kebab-case, stable, == output dir name
    "title": "Solana for Solidity Devs",        // outcome-led
    "one_line_promise": "By the end you can build, test and deploy a PDA-backed vault…",
    "version": "0.1.0", "status": "draft", "created": "2026-06-27",
    "audience": { "who": "evm-dev",             // absolute-beginner|web2-dev|evm-dev|solana-dev-leveling-up|non-technical
                  "prior_model": "Solidity/EVM: contracts, storage, mappings, gas, revert.",
                  "prerequisites": ["comfortable with TypeScript"] },
    "terminal_outcomes": [
      { "id": "to-deploy-vault", "bloom": "create",
        "statement": "build, test and deploy a PDA-backed SPL-token vault on devnet" }
    ],
    "format": "self-paced",                     // self-paced|cohort|workshop|docs-path
    "length_target": { "hours": 6, "lessons": 6, "weeks": 3 },
    "credential": "on-chain-NFT",               // none|self-assessment|auto-graded|on-chain-NFT|certificate
    "toolchain": ["Python 3.11+ (hashlib)", "Bitcoin Core 27+ (regtest)"],   // libs/SDKs/versions surfaced on 000-cover.md
    "routing": { "backbone_pattern": ["map-from-known","challenge-ladder"],   // ordered phases of the ONE backbone track; guests go in guest_patterns
                 "lesson_template": "overview-lab-challenge",
                 "guest_patterns": ["build-it-twice"], "security": "inline-footguns" },
    "artifact_ladder": ["hello-world","counter","pda-app","cpi-composition","capstone"]
  },

  "dag": {
    "nodes": ["account-model","programs-instructions","pdas","cpis"],   // from solana-syllabus-dag §closed vocab
    "edges": [["account-model","programs-instructions"],               // [from, to] = "from taught before to"
              ["programs-instructions","pdas"], ["pdas","cpis"]]
  },
  "glossary": [{ "term": "account", "def": "…", "first_taught": "lesson-id" }],
  "concept_ledger": [{ "concept": "pdas", "introduced_in": "pda-state" }],

  "modules": [
    { "id": "module-pdas", "title": "Solidity had mappings; Solana doesn't",
      "driving_question": "Where does per-user data live with no mappings?",
      "outcome": { "bloom": "implement", "statement": "derive a canonical PDA" },
      "traces_to": ["to-deploy-vault"],          // terminal-outcome ids
      "artifact": "per-user PDA vault", "artifact_rung": 3,   // index into ARTIFACT_LADDER (monotonic)
      "depends_on": ["module-accounts"],         // module ids
      "requires_skills": ["account-model"], "teaches_skills": ["pdas"],   // dag.nodes
      "patterns": ["challenge-ladder","build-it-twice"], "difficulty_band": 2,
      "lessons": ["pda-state"],                  // ordered lesson ids
      "retrieval_checkpoint": "Re-derive a PDA for a new seed scheme from memory." }
  ],

  "lessons": [
    { "id": "pda-state", "module": "module-pdas", "order": 1,
      "brief": { /* lesson-brief-schema §C, verbatim — see ../lesson-brief-schema.md */ },
      "research": { /* research scaffold — optional; see below */ } }
  ],

  "cadence": { "pedagogy": { … }, "release": { … } },   // see cadence section
  "assessment": { "proof_matrix": [ … ], "checkpoints": [ … ],
                  "cumulative_checkpoint": { … }, "capstone": { … } }
}
```

### Lesson brief (`lesson.brief`) — the handoff unit
Verbatim `../lesson-brief-schema.md` §C; emitted under a top-level `lesson:` key so
`/write-in-voice` consumes it with zero reformatting. Required keys (validator
HARD-fails if absent): `id, title, objectives[{bloom,statement}], prerequisites,
hook, concept_spec, artifact_spec, exercise_spec, the_tradeoff,
just_in_time{define,footguns}, assessment, difficulty, fading, dominant_job`.
Optional but recommended: `voice_notes, est_length`, and the cross-lesson
consistency fields `artifact_state_in`, `artifact_state_out`, `carry_forward`.
`dominant_job ∈ {show-how, derive-why, demystify, economics, frame, sustain,
motivate}` — `frame`/`demystify` are guest-only jobs (advisory if used as a
whole-lesson backbone).

### Research scaffold (`lesson.research`) — optional, NEW
```jsonc
{ "lesson_id": "pda-state", "status": "verified",          // unstarted|gathering|verified|stale
  "source_priority": ["solana-dev","context7","helius"],   // names from ../references/research-grounding.md
  "claims": [
    { "id": "C2", "claim": "PDAs derive via find_program_address(seeds, program_id).",
      "kind": "api",         // concept|number|api|code|onchain-number|cli-default|version-pin|protocol-param
      "mcp": "solana-dev", "query": "find_program_address canonical bump",
      "verify": "API name + canonical-bump semantics current", "status": "verified",
      "evidence": "solana-dev: PDA section", "value": null,
      "verified_on": "2026-09-07",       // REQUIRED when status is verified (ISO date)
      "recheck": "solana-dev: Solana_Documentation_Search 'find_program_address'",
      "ttl_days": 30 },                  // OPTIONAL, and may only SHORTEN the kind default
    { "id": "C3", "claim": "ATA rent-exempt minimum on mainnet is 2,077,224 lamports.",
      "kind": "onchain-number", "mcp": "helius", "status": "verified",
      "value": "2077224 lamports (mainnet-beta)", "verified_on": "2026-09-07",
      "recheck": "helius heliusChain getMinimumBalanceForRentExemption 165 --cluster mainnet" } ],
  "code_to_ground": [{ "id": "K1", "what": "seeds array", "autofixer": "required", "status": "verified" }],
  "open_questions": [],
  "frozen_facts": ["PDAs derive via find_program_address(seeds, program_id) -> (addr, canonical_bump).",
                   "Devnet rent-exempt min for the counter account: 0.00XXXXX SOL (2026-06-27, Helius)."] }
```
`frozen_facts` are projected to `lessons/facts/<id>.facts.md` (one per line) — the
exact `--facts` input for writer-style's `diff` gate, closing the verification loop
with the writer's own tooling.

**Every claim expires.** `verified_on` + `ttl_days` + `recheck` are the anti-staleness
layer; `validate_course.py freshness` and `fact_freshness.py stale` read them, and
`academy_export.py` refuses to publish past a TTL. TTL defaults live per `kind` in
`tools/course_lib.py` (`TTL_DAYS`), not per claim, so retuning one number reaches every
course: on-chain numbers 14d, CLI defaults / version pins / protocol params / bare numbers
30d, APIs 60d, code 90d, concepts 365d. Rationale and the re-check workflow are in
[`../method/fact-recheck.md`](../method/fact-recheck.md).

- `recheck` is a **runnable probe**, not prose — the RPC call, the `curl`, the `--version`.
  It is HARD-required on `onchain-number`, `cli-default`, `protocol-param`, `version-pin`.
- `verified_on` is HARD-required on a `verified` claim. A `(dispatched YYYY-MM-DD)` marker
  inside `evidence` is accepted as a fallback, but write the field.
- A claim with no `kind` inherits the 30-day volatile default, never the concept TTL.
- `frozen_facts` with **no `claims[]`** means the freshness gate is silent for that lesson
  because nothing is declared, not because the facts are fresh. Promote volatile frozen
  facts to claims.

### Cadence (`manifest.cadence`) — pedagogy + release
```jsonc
{ "pedagogy": {
    "fading_schedule": [{ "lesson": "pda-state", "mode": "completion", "difficulty": 2 }],  // worked|completion|solo
    "difficulty_curve": [1,1,2,2,3,3], "worked_examples_removed_after": "module-pdas",
    "spiral": [{ "skill": "pdas", "reappears_in": ["cpi-deposit","capstone"] }],
    "retrieval_checkpoints": ["checkpoint-pda"], "cumulative_checkpoint_before": "capstone" },
  "release": {
    "mode": "weekly-drip", "start_date": "2026-07-06", "timezone": "America/Sao_Paulo",
    "schedule": [{ "week": 1, "publish": ["hello","counter"], "est_effort_hours": 6 }],
    "per_lesson_effort": [{ "lesson": "pda-state", "draft_words": 1200, "research_hours": 1.5,
                            "write_hours": 2, "review_hours": 1 }],
    "freshness_policy": { "onchain_numbers_restale_after_days": 14, "applies_to": ["cpi-deposit"] } } }
```
`freshness_policy` is **read by the gate** (`course_lib.course_ttl_policy`): it narrows the
`onchain-number` TTL for the lessons in `applies_to` (empty = the whole course). Like a
per-claim `ttl_days`, it may only SHORTEN the kind default — a course asking for 90 days on
rent figures gets 14 and an advisory saying so.

### Assessment (`manifest.assessment`)
```jsonc
{ "model": "capstone+onchain",
  "proof_matrix": [{ "outcome": "to-deploy-vault", "proven_by": "capstone",
                     "evidence": "deployed program id + passing tests" }],   // every terminal outcome appears here
  "checkpoints": [{ "id": "checkpoint-pda", "after_module": "module-pdas", "type": "mini-build",
                    "spec": "Derive a PDA for an unseen seed scheme; reinit must fail." }],
  "cumulative_checkpoint": { "after_module": "module-cpis", "spec": "Vault deposits an SPL token via CPI." },
  "capstone": { "id": "capstone-ship", "statement": "Ship an original program with a PDA + a CPI on devnet.",
                "requires_skills": ["pdas","cpis","account-model"],          // must all be taught earlier (HARD)
                "rubric": ["PDA with stored canonical bump","≥1 CPI","signer+owner checks","tests pass"],
                "credential": "on-chain-NFT", "traces_to": ["to-deploy-vault"] } }
```

## Optional brief fields — the Academy plugins (additive)
A lesson brief may carry two OPTIONAL arrays (lesson-brief-schema §C/§H): `quiz_blocks`
(formative quizzes) and `coding_challenges` (runnable Rust/TS exercises; code lives in files
under `lessons/challenges/<lesson-id>/<challenge-id>/`). They are additive — absent by default,
never required, and existing courses are unaffected. `validate_course.py` gains `check_briefs`
sub-checks for their specs plus a course-dir `challenges` check that the referenced
starter/solution/tests files exist.

## The Academy projection — a second, publish-only tree
`manifest.json` has a second one-way projection alongside the emitted authoring tree: the
**Academy publish tree**, produced by `../tools/academy_export.py emit` under
`content/academy/courses/<slug>/` (`course.yaml` + per-lesson `lesson.yaml` with prose/quiz/code
blocks + copied challenge files). It is the platform contract in `academy-schema.md`, NOT the
authoring format, and it is generated read-only from the course — the source `content/courses/<id>/`
is never mutated. `../tools/verify_challenges.py` proves each challenge's starter-fails/solution-passes
contract. Publish-only metadata (creator wallet, difficulty, xp, id prefix, dag→skills map) lives in
an OPTIONAL additive `manifest.academy` block, overridable by exporter flags.

## Generated, never hand-authored
`../tools/scaffold_course.py` generates `000-cover.md`, `course.yaml`, `README.md`, `_state.yaml`,
`course.lock.json`, `queue/NEXT.md`, and the per-module/per-lesson files from the
manifest. `_state.yaml` is the only file the production pipeline mutates (status
ladder + DAG-derived `blocked_by` + `summary.next_to_write`).

## IDs & the DAG (machine-checkable)
All `id`s are kebab-case, outcome-led, unique, stable. Three edge layers all
reference the one `dag.nodes` vocabulary: the skill-node DAG (`dag.edges`), module
edges (`depends_on` / `requires_skills` / `teaches_skills`), and lesson
`prerequisites` (lesson ids OR skill nodes). A single topological walk
(`validate_course.py dag`) proves acyclicity + no-forward-deps and yields each
lesson's `blocked_by` for the queue. A prerequisite that resolves to neither a
known lesson id nor a skill node is a HARD failure (the silent-typo break).
