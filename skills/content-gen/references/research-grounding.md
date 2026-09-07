# Research Grounding — externalized onto the Solana AI Kit

The architect decides **what** to teach, in **what order**, and which **APIs /
artifacts / numbers** a lesson asserts. That is the one layer only this skill
controls, so it must be **grounded against live sources, not training data** —
the Solana ecosystem moves faster than any model cutoff.

But the *specifics* of which tool to call are **not** pinned here. The Solana AI
Kit's own rule is **"reference skills instead of duplicating content"** — delegate
live lookups to MCPs/skills, keep embedded context minimal and referential, avoid
stale embedded knowledge. So this file is deliberately **thin**: it links to the
kit's canonical catalogs and tells the agent to **double-check the current surface
at runtime** rather than trust a list baked into a skill.

> Upstream source of truth: **https://github.com/solanabr/solana-ai-kit**
> (its README lists the current MCP / skill / agent set). When in doubt, read it.

## When the kit is absent (the degradation ladder)

The paths and commands below assume this skill runs **inside a solana-ai-kit
install**. Installed standalone (plugin-only), most of them will not exist. MUST
GROUND steps then degrade in order — never skip them, never fake them:

1. **Named MCPs present** (`solana-dev`, `context7`, `helius`, `surfpool`) → use
   them as mapped below.
2. **No MCPs** → WebSearch/WebFetch against official sources (solana.com/docs,
   anchor-lang.com, the SDK's repo). Record the URL as evidence.
3. **No network** → mark every affected claim `status: unverified`, list it in
   `open_questions`, and state in the handoff that the human accuracy gate is
   **blocking** for this piece. A claim verified only from model memory is
   `unverified` by definition.

## Where the current tooling actually lives (consult, don't trust this list — kit installs only)
- **`.claude/skills/skill-registry.json`** — the kit's opt-in catalog: every
  repo / skill / MCP with its install command, license, and safety caveats.
- **`.mcp.json`** (repo root) — the MCP servers actually wired up in this install.
- **`.claude/skills/ext/solana-new/cli/data/{solana-mcps,solana-skills}.json`** and
  **`.../navigate-skills/SKILL.md`** — vendored catalogs of MCPs and skills.
- **`.claude/agents/`** — the kit's research agents (`solana-researcher`,
  `solana-guide`).

If a needed entrypoint isn't wired up, that's a kit-maintenance step, not a
skill change: run **`/doctor`** (verify toolchain), **`/setup-mcp`** (keys), and
**`/update`** + **`/resync`** (refresh skills/MCPs).

## Grounding need → kit entrypoint (the *current* mapping; defer to catalogs above)

| `claim.kind` / need | Preferred entrypoint (kit name) | Notes |
|---|---|---|
| `concept`, `api` — Solana docs/spec (authoritative) | **`solana-dev`** MCP — official Solana MCP at `https://mcp.solana.com/mcp` | `Solana_Documentation_Search`, `get_documentation`, `list_sections`, `Solana_Expert__Ask_For_Help` |
| `api` — libraries/SDKs (Anchor, web3.js/kit, SPL) | **`context7`** MCP | resolve-library-id then query-docs |
| `code` — Rust program snippets a lesson ships | **`solana-dev`** `program_autofixer` | run until clean before freezing the snippet |
| `onchain-number` — rent, account sizes, priority fees | **`helius`** MCP | record exact value + unit + date in the claim's `value`; `recheck` is the RPC call itself |
| `cli-default` — what a command does with no flags | **`local-execution`** (run it) · `context7` | `recheck` is the literal command; paste its output into `evidence` |
| `version-pin` — a crate/npm/toolchain version an example builds against | **`context7`** · `local-execution` | keep in step with `references/pins.yaml`; `recheck` is `<tool> --version` or `npm view <pkg> version` |
| `protocol-param` — slot time, epoch length, a feature gate's activation state | **`helius`** (gate account probe) · `solana-dev` · SIMD text | these change on epoch boundaries, so the probe must read the cluster, not the docs |
| build/verify an artifact actually compiles/runs | **`surfpool`** MCP | local validator / mainnet-fork |
| deep / multi-source / "is this still true?" | **`deep-research`** skill · **`solana-researcher`** / **`solana-guide`** agents | for contested ordering or ecosystem claims |
| context hygiene / cross-lesson memory | **`context-mode`** (compress) · **`memsearch`** (persist) | keep grounded facts available across lessons |

## Dispatch is literal (the anti-hallucination rule)

"Ground against the kit" means actually CALLING the kit surfaces — spawning the
`solana-researcher`/`solana-guide` agents, invoking the `deep-research` skill,
querying the `solana-dev`/`context7`/`helius` MCPs — and recording which surface
answered in each claim's `mcp`/`evidence` fields. Emulating what the researcher
would say from model memory is the exact failure this layer exists to prevent.
Per lesson: at least one claim grounded through a kit surface, unless every
claim in the lesson is `local-execution` (you ran the command) — and the
research.yaml must show it.

## How the workflow uses this (SKILL.md steps 3, 6, 9)
- **Step 3 (map the DAG)** — MUST ground the dependency *order* and that named
  primitives exist/are current (esp. fast-moving areas: Token-2022 / extensions /
  transfer-hooks, `@solana/web3.js`↔`@solana/kit`, Anchor version macros, CU/fee
  APIs, MWA). Use `solana-dev` + `context7`; escalate contested ordering to
  `deep-research`.
- **Step 6 (sequence)** — MUST ground every concrete API/tool/number that will
  land in a brief.
- **Step 9 (research scaffolds)** — write each lesson's `research.yaml`: list the
  `claims[]` with a `kind`, set `source_priority` to **kit names from the table
  above** (not raw tool calls), verify, and freeze the result into `frozen_facts`
  (projected to `lessons/facts/<id>.facts.md`).

`source_priority` and `claim.mcp` use **kit names** (`solana-dev`, `context7`,
`helius`, `surfpool`, `deep-research`) so a course's research is reproducible and
tool-agnostic — if the kit swaps an implementation, the names still resolve via
the catalogs above. This is the same grounding surface writer-style's facts-first
pass uses, so the architect and the writer never disagree on sources.

## Honest scope
Grounding raises accuracy; it does not replace human review. A generated course's
technical claims still pass a **human accuracy gate** before publish (see
`quality-bar.md`).

**Grounding is a first verification, not a permanent one.** Every claim carries
`verified_on` and expires on a TTL set by its `kind` (`tools/course_lib.py` `TTL_DAYS`),
and every claim of a machine-readable kind carries a runnable `recheck` probe.
`tools/fact_freshness.py stale` is a blocking gate before publish and
`tools/academy_export.py` refuses a course with an expired claim. `kind` extends the set
above with `cli-default`, `version-pin`, and `protocol-param`; the re-check workflow, the
TTL evidence, and the one-correction-sweeps-every-site rule are in
[`../method/fact-recheck.md`](../method/fact-recheck.md). `cadence.release.freshness_policy`
is read by that gate and may only **shorten** the `onchain-number` TTL for the lessons it
scopes.


## Version freshness & atomic facts (hardening)

- **Ground versions live, at authoring time** (solana-dev / context7 / web), never from
  memory — a pinned version that was stale-from-memory ships a build-failing example
  (the `solana-program 2.2.0` incident). Record the source URL in the claim's `evidence`.
- **Every pinned version/command carries a freshness note** in the prose ("verify against
  current docs; tracks the Agave/Anchor release train"), because these rot within weeks.
- **`frozen_facts` used for the writer-style diff must be atomic** (see lesson-brief-schema
  §G): single verbatim values, not sentences or templated commands.
