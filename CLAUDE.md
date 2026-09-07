# content-gen-skill — agent guide

This repo is a **Claude Code skill**, not an application. It contains no runtime service and no
deployable program: it is instructions, references, and a small stdlib-only Python toolchain
that together let an agent design and write educational Solana/Web3 content.

> The previous version of this file was a `solana-builder` Anchor/Rust configuration left over
> from another project. It described `anchor build`, mainnet deploys, and CU profiling, none of
> which exist here. If you are looking for those rules they live in the *parent* workspace's
> `CLAUDE.md` and `.claude/rules/`, which Claude Code loads automatically when this repo sits
> inside it.

## Three names, one thing

This trips up every new reader, so: nothing is misconfigured, and **nothing should be renamed.**

| Layer | Name | Where it is fixed |
|---|---|---|
| git repo / clone dir | `course-creator-skill` (local), `content-gen-skill` (remote) | `git remote -v` |
| the shipped skill | **`content-gen`** | `skills/content-gen/SKILL.md` frontmatter `name:` |
| the plugin | `content-gen-skill@solanabr` | `.claude-plugin/plugin.json`, `marketplace.json` |

The skill name is what an agent invokes; the plugin name is what `/plugin install` takes and is
**install-visible**, so renaming it breaks every existing install. The repo directory name is
historical. Read `skills/content-gen/` and ignore the rest of the naming.

## Layout

```
skills/content-gen/          THE SKILL. Everything else in the repo is support.
  SKILL.md                   entry point: scope, the 13-step course pipeline, tool invocation
  design-spine.md            pedagogical non-negotiables, always on
  lesson-brief-schema.md     the per-lesson brief contract (§H = quizzes + coding challenges)
  forms/FORMS.md + forms/*   the form router and one recipe per form
  patterns/*.md              course-scale structural archetypes, routed by outcome + audience
  routing/ROUTING.md         which pattern for which (outcome, audience)
  references/                the contracts and the pins (see below)
  method/                    how to author patterns / harden the router
  tools/                     stdlib-only Python (see the inventory below)
  verify/Dockerfile          the pinned verification container
  examples/                  three validator-green worked courses
  brand/                     Superteam Brazil styles for rendered visuals
courses-corpus/              7 analysed Solana courses (analysis only; raw scrapes gitignored)
forms-corpus/                8 analysed content forms (same)
commands/  agents/           /create-content, /architect-course, /validate-course + 2 subagents
content/  courses/           GENERATED OUTPUT. Gitignored. Not skill source.
```

## The pipeline, in one paragraph

`SKILL.md` routes the **form** first (course / tutorial / walkthrough / explainer / essay /
litepaper / slides / post). Courses then run backward design → prerequisite DAG → pattern
routing → sequencing → per-lesson briefs → research scaffolds → assessment → **validate and
emit** a `content/courses/<id>/` filesystem → write the lessons one at a time through the voice
seam → optionally author quizzes/coding challenges and project to the Academy publish tree.
Full step list with the docs each step loads: `skills/content-gen/SKILL.md`.

## Tool inventory (`skills/content-gen/tools/`)

Stdlib only. No third-party imports, no network at import time. Every tool exposes
`--selftest`, and `test_tools.py` runs all of them.

| Tool | Does |
|---|---|
| `course_lib.py` | shared: manifest load, lesson flatten, YAML emit, topo sort |
| `validate_course.py` | THE deterministic gate. `dag · briefs · ladder · capstone · outcomes · challenges · all` |
| `scaffold_course.py` | manifest → the `content/courses/<id>/` filesystem |
| `assemble_manifest.py` | build a manifest from authored parts |
| `verify_code.py` | compile/run every fenced block. Python, JSON, TOML, Solidity, and the three-tier bash checker |
| `verify_blocks.py` | compile rust/typescript blocks against the course's DECLARED deps, triaging fragment context from real defects |
| `verify_challenges.py` | THE platform contract: solution passes every test, starter fails at least one |
| `fact_freshness.py` | per-claim expiry (`report · stale · probes`). `stale` is the blocking publish gate; TTLs live per `kind` in `course_lib.TTL_DAYS` |
| `academy_export.py` | project a course into the Academy publish tree (`content/academy/`), read-only on the source. Refuses a past-TTL claim unless `--allow-stale` |
| `render_visuals.py` | render visual specs and the course banner |
| `quiz_*.py` | quiz authoring, layout and metrics |
| `dedash.py` | remove em-dashes from every reader-visible surface, repairing by syntactic role |
| `pin_refresh.py` | keep the skill's own version pins from rotting (`check · render · surfaces`) |
| `ci.py` | tiers 0–7 over every discovered course |
| `test_tools.py` | runs every tool's selftest; a tool with a selftest that is not registered is a HARD FAILURE |

## CI

```bash
python3 skills/content-gen/tools/ci.py              # tiers 0-7
python3 skills/content-gen/tools/ci.py --strict     # SKIP IS NOT PASS
python3 skills/content-gen/tools/ci.py --run-blocks # tier 7 actually compiles (npm + cargo)
```

| Tier | What it proves |
|---|---|
| 0 pins | the skill's own pins are fresh, single-sourced and rendered into the Dockerfile |
| 1 gates | every tool's selftest + `validate_course` on every course + writer-style facts/tells |
| 2 fixtures | golden bad manifests still trip their expected flags |
| 3 metrics | per-draft aesthetics dashboard (informational) |
| 4 smoke | per-lesson `verify` commands; `--run-smoke` executes the allowlisted ones |
| 5 verify | every fenced code block compiles/runs (`verify_code.py`) |
| 6 challenge | the Academy runtime contract (`verify_challenges.py`) |
| 7 blocks | rust/ts blocks compile against declared deps (`verify_blocks.py`) |

`--strict` exists because a SKIP counted as green is how unverified content ships. Under
`--strict`, a tier that could not run fails the build.

## Rules that actually bite

- **Pins are data, not prose.** Every version number the skill asserts lives in
  `skills/content-gen/references/pins.yaml`. The Dockerfile's `ARG` block is *generated* from
  it (`pin_refresh.py render`); hand-editing it is reverted by CI tier 0. pins.yaml carries a
  TTL and fails the build when it expires. This exists because the hand-maintained version
  drifted a full major behind the content it verifies.
- **A tool with a selftest must be in `test_tools.py`'s `REGISTERED`.** An unregistered tool
  with a selftest fails the build. Five working selftests were once run by nothing.
- **`SKIP` is never `PASS`.** Any checker that cannot run must say so loudly and be failable
  under `--strict`.
- **Never claim a command works without running it.** `references/command-surfaces.yaml` records
  CLI surfaces that moved, and every rule in it must carry `evidence:` naming how the claim was
  established. A rule sourced from memory is worse than no rule.
- **`content/` and `courses/` are generated output and gitignored.** Never commit them, never
  treat them as skill source.
- **Grounding is mandatory for technical claims.** `references/research-grounding.md` has the
  degradation ladder. Never silently mark a claim verified from memory.
- **The em-dash is house-banned in generated prose** (`dedash.py`), including quiz text,
  `course.yaml` descriptions, module metadata and covers.
- **`writer-style` is an optional runtime dependency.** Discover the newest installed release by
  name; never hardcode its path, version or profile files. Absent, this skill writes plain
  technical prose itself.

## Branch workflow

`git checkout -b <type>/<scope>-<description>-<DD-MM-YYYY>`. Do not add Claude co-authorship
trailers to commits.

## Before you finish a branch

- [ ] `python3 skills/content-gen/tools/test_tools.py` passes
- [ ] `python3 skills/content-gen/tools/ci.py` — no new failures vs the branch point
- [ ] any tool you added is in `test_tools.py`'s `REGISTERED`
- [ ] any version number you wrote is in `pins.yaml`, or allowlisted in it with a reason
- [ ] any CLI surface claim you made carries `evidence:` in `command-surfaces.yaml`
- [ ] ripple check: `README.md`, `SKILL.md`, the relevant `references/*.md`
