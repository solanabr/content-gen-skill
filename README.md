# ContentGen (content-gen-skill)

Create **educational Solana/Web3 content in any form** — courses, tutorials,
walkthroughs, explainers, essays, litepapers, slide decks (text specs), and
tweets/threads/posts — from a topic + audience + notes. The default deliverable is **fully written text**,
finished with a tunable **visual-placeholder pass** (specs for charts, flowcharts,
diagrams — never images). Courses additionally emit a **validated filesystem** of
per-lesson briefs.

> The structural sibling of
> [`writer-style-skill`](https://github.com/solanabr/writer-style-skill):
> content-gen decides *what is taught, in what order, proven how* and writes its
> briefs; when writer-style is installed, prose goes through its voice router (the
> seam is the brief's `dominant_job` tag). Without it, content-gen writes the
> prose itself in a plain technical register.

## The eight forms

| Form | Ask it like | Deliverable |
|---|---|---|
| `tutorial` | "how do I build X" | full text, steps to a working artifact (+ `recipe` mode) |
| `walkthrough` | "explain this repo/protocol/tx" | full text, guided tour (`article`/`repo` subtypes) |
| `explainer` | "how does X work / primer on X" | full text, mechanism deep-dive |
| `essay` | "why X / write an opinion piece" | full text, thesis-driven (+ `expository` mode) |
| `litepaper` | "draft our litepaper" | versioned design-of-record text |
| `slides` | "make slides for my talk" | per-slide text spec + speaker notes (+ `workshop` mode) |
| `post` | "write a tweet/thread/TL;DR on X" | short text, `platform` sub-profiles |
| `course` | "design a curriculum for X" | `content/courses/<id>/` filesystem + lessons |

`/create-content "<ask>"` routes the form automatically (`--form`, `--visuals
none|light|rich`, `--brief-only` to stop at structure). Courses run
`/architect-course` and gate on `/validate-course`.

## Three names, one thing

Before anything else, because it costs every new reader ten minutes: the repo, the skill and
the plugin have three different names, and **none of them should be renamed.**

| Layer | Name | Fixed in |
|---|---|---|
| clone directory | `course-creator-skill` (historical) | your filesystem |
| git remote | `content-gen-skill` | `git remote -v` |
| the skill you invoke | **`content-gen`** | `skills/content-gen/SKILL.md` frontmatter |
| the plugin you install | `content-gen-skill@solanabr` | `.claude-plugin/plugin.json` |

The plugin name is install-visible — renaming it breaks every existing install — and the skill
name is what an agent actually routes on. Read `skills/content-gen/`; ignore the rest.

## Install

```bash
# as a Claude Code plugin (this repo hosts its own marketplace)
/plugin marketplace add solanabr/content-gen-skill
/plugin install content-gen-skill@solanabr

# or clone and use in-place (skills/, agents/, commands/ resolve relatively)
git clone https://github.com/solanabr/content-gen-skill
```

Optional companion: install the latest release of
[`writer-style-skill`](https://github.com/solanabr/writer-style-skill) for
voice-written prose — ContentGen detects it at runtime and falls back to a plain
technical register without it.

## The pipeline

```
        topic + audience + notes
                 │
        route the form (forms/FORMS.md)
                 │
   outcome → ground claims → brief (dominant_job)
                 │
        write full text ──── writer-style installed? → /write-in-voice
                 │
   visual-placeholder pass (insert-only, density-budgeted)
                 │
   content/<slug>/            content/courses/<id>/  (course form:
   brief.yaml + <slug>.md      validate_course.py gate, briefs,
                               per-lesson drafts, _state.yaml)
```

## How it works — three layers + a form router
1. **Design spine** (`design-spine.md`) — pedagogical non-negotiables, always on.
2. **Pattern layer** (`patterns/*.md`) — course-scale structural archetypes,
   routed by **outcome + audience** (`routing/ROUTING.md`), never by topic.
3. **Domain DAG** (`references/solana-syllabus-dag.md`) — the Solana prerequisite
   graph the sequence may never violate.
4. **Form router** (`forms/FORMS.md`) — which pipeline runs at all; per-form
   recipes in `forms/<form>.md`.

## Grounding
DAG order, API names, artifacts, and numbers are verified **against live sources
at design time** (`references/research-grounding.md`) — the Solana AI Kit's MCPs
when present, with an explicit degradation ladder (web sources → `unverified` +
blocking human gate) when not. Generated content always passes a human accuracy
review before publish.

## Runnable-code verification
Any code this skill writes, in a course or a tutorial or a walkthrough or anywhere,
is **compiled and run before the piece is "done."** Facts, structure, and voice gates
never execute code, so LLM-generated code that merely *looks* right ships broken (a
non-compiling `CpiContext`, an `ImportError`, a missing `__main__` guard). The
`tools/verify_code.py` gate closes that:

```bash
# compile/run every fenced code block a piece ships
python3 skills/content-gen/tools/verify_code.py content/courses/<id>            # local toolchains
python3 skills/content-gen/tools/verify_code.py content/courses/<id> --harness  # + real anchor build + tsc
python3 skills/content-gen/tools/verify_code.py content/<slug> --run-smoke      # + each brief's verify cmd
python3 skills/content-gen/tools/verify_code.py content/courses/<id> --bash-tiers   # per-tier bash verdicts
python3 skills/content-gen/tools/verify_code.py content/courses/<id> --exec-bash    # bash tier 3 on
python3 skills/content-gen/tools/verify_blocks.py content/courses/<id> --lang ts    # really compile TS
python3 skills/content-gen/tools/verify_blocks.py content/courses/<id> --lang rust  # really compile Rust
VERIFY_ENV=docker python3 skills/content-gen/tools/ci.py --tiers 5              # pinned, version-matched
VERIFY_HARNESS=1 python3 skills/content-gen/tools/ci.py --tiers 5               # CI: run the harnesses too
python3 skills/content-gen/tools/ci.py --run-blocks --strict                    # nothing left unchecked
```

- **Three-tier bash checking.** `bash -n` is a *syntax* check, and an audit of a shipped course
  found four majors that were valid bash and simply no longer run: `forge create` without
  `--broadcast` (a silent dry run on Foundry 1.x <!-- pins-ok: names the major whose default changed, not a pin -->), `openssl dgst -<digest> -sign` against an
  Ed25519 key (OpenSSL 3 refuses), and Bitcoin Core's fee and wallet-loading defaults. So bash
  is checked in three tiers — **syntax**, then **surface currency** against the evidenced
  ledger in `references/command-surfaces.yaml`, then optional **execution** of
  side-effect-free commands (`--exec-bash`). Prose-embedded commands (backticked, in a
  sentence) are checked too; nothing checked those before.
- **Rust and TypeScript are compiled by `verify_blocks.py`, not here.** `verify_code.py`
  returns `SKIP` for rust/ts/js in *every* environment, container included, so its green for
  those languages was always vacuous. `verify_blocks.py` compiles them against the course's
  **declared** deps and triages missing-fragment-context errors apart from real defects.
- **Real materialized harnesses.** A piece can ship a `verify-ts/` (a `tsc` project) and
  `verify-anchor/*/` (`anchor init` workspaces) beside it: the lesson code assembled into
  an actually-buildable project. `--harness` runs `tsc --noEmit` and `anchor build` against
  them, so the exact code the reader copies is compiler-checked, not just per-block linted.
- **Pinned, version-matched toolchain.** `verify/Dockerfile` installs anchor, forge,
  cargo, solana, node, and python at the versions in `references/pins.yaml`, which is the
  single source of truth for every number this skill asserts. The Dockerfile's `ARG` block is
  **generated** from it, and `pin_refresh.py check` (CI tier 0) fails when the two drift, when
  a doc contradicts the pins, or when pins.yaml passes its own TTL.
- **`FAIL` blocks done; `SKIP` never silently passes.** A `FAIL` is a real compile or run
  break. A `SKIP` means something could not be checked, and `ci.py --strict` turns every SKIP
  into a failure, so "green" can never mean "nothing was checked."
- **Wired into CI as tiers 5, 6 and 7** (`ci.py`) and documented as a hard step in
  `forms/course.md`. It applies to every form, because any form can ship code.

## Academy quizzes, coding challenges & publishing

Two optional, **additive** interactive plugins can enrich any course lesson, matching the
Superteam Academy platform (`solanabr/academy-courses`) so a finished course can be published
there. A lesson brief may carry:

- **`quiz_blocks`** — formative multiple-choice checks with per-option feedback and an
  explanation. Language-agnostic, and they never gate the lesson (`design-spine.md` §6.1).
- **`coding_challenges`** — runnable **Rust/TypeScript** exercises (the platform runner compiles
  only those two). The grade is the test run: the solution must pass every `tests.json` case and
  the starter must fail at least one.

```bash
# validate the specs + that every challenge's starter/solution/tests file exists
python3 skills/content-gen/tools/validate_course.py challenges --course content/courses/<id>
# project the course into the Academy publish tree (course.yaml + per-lesson lesson.yaml blocks + files)
python3 skills/content-gen/tools/academy_export.py emit --course content/courses/<id> --out content/academy/courses/<slug>
# PROVE the contract in a real toolchain (tsc+node for TS; cargo check vs anchor-lang for buildable Rust)
python3 skills/content-gen/tools/verify_challenges.py content/courses/<id>
```

The platform contract is pinned in `references/academy-schema.md`; authoring is documented in
`lesson-brief-schema.md` §H. The export is one-way — it reads the course read-only and writes only
under `content/academy/`, so the source course is never mutated.

## Quick start

```bash
python3 skills/content-gen/tools/test_tools.py        # stdlib-only selftests

# small forms: one command, finished text out
#   /create-content "tutorial: escrow with Anchor for evm devs"

# courses: architect → validate → emit → write
python3 skills/content-gen/tools/validate_course.py all --manifest manifest.json
python3 skills/content-gen/tools/scaffold_course.py emit --manifest manifest.json --out content/courses/<id>
python3 skills/content-gen/tools/validate_course.py all --course content/courses/<id>
```

Three worked, validator-green example courses ship under
`skills/content-gen/examples/`: `walking-skeleton/`, `solidity-to-solana/`, and
`solana-security-audit/`.

## The deterministic gate (`validate_course.py`, course form)
HARD = breaks the prerequisite-DAG walk or the writer handoff; ADVISORY = a smell
to weigh. Subcommands: `dag` · `briefs` · `ladder` · `capstone` · `outcomes` ·
`challenges` · `all`. Lessons carry `kind: build|concept` — concept lessons drop the build triad.
There is intentionally **no "course score"**; pedagogical quality is a human/agent
judgement (`references/quality-bar.md`). Non-course forms gate on their form-file
checklist.

## Staying current

Everything above only works if the skill's own numbers are true. They live in one file:

```bash
python3 skills/content-gen/tools/pin_refresh.py check --probe  # TTL + Dockerfile + docs + local drift
python3 skills/content-gen/tools/pin_refresh.py render         # pins.yaml -> the Dockerfile ARG block
python3 skills/content-gen/tools/pin_refresh.py surfaces       # re-probe the command-surface ledger
```

- `references/pins.yaml` is the **only** place a version number is authored. Docs that
  contradict it fail CI tier 0; docs that legitimately differ are allowlisted *in the same
  file*, with a reason.
- It carries `pinned_on` + `ttl_days` and **fails once it expires**. That is deliberate: the
  previous, prose-based pins drifted a full major version behind the content they gate
  (`SOLANA=v2.1.0` while the authoring machine ran `solana-cli 3.1.10`), <!-- pins-ok: the historical drift this guard exists to prevent -->
  and an anti-staleness system with no expiry rots exactly the same way.
- `references/command-surfaces.yaml` records CLI surfaces that moved. Every rule carries
  `evidence:` naming how the claim was established — a local probe, a local run, or a vendor
  doc. Rules from memory are not accepted.

## Repo layout
```
skills/content-gen/           the skill (SKILL.md, design-spine, forms/, patterns/, routing/, references/, method/, tools/, examples/)
courses-corpus/               7 Solana courses analyzed (PATTERNS.md + per-course META.md; raw scrapes gitignored)
forms-corpus/                 8 content forms analyzed (PATTERNS.md + per-form FORM.md/catalog.md; raw gitignored)
commands/                     /create-content, /architect-course, /validate-course
agents/                       content-composer, course-architect
.claude-plugin/plugin.json    plugin manifest
content/                      generated non-course output + content/academy/ publish projection (gitignored)
courses/                      generated course output (gitignored)
```

## License
MIT — Superteam Brazil. The `dominant_job` taxonomy and brief schemas are kept in
lockstep with `writer-style-skill` — always resolve the **latest installed release** at runtime; never pin its internal paths or profile files.
