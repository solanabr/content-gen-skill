# Handoff → course-creator-skill (from writer-style evolution R2, 2026-08-21)

Findings from the two course audits that belong to the course pipeline, not this skill. Ordered by
severity × cheapness. Sources: R1 btc-to-sol audit + R2 speedrun audit (working data, this dir).

**Status pass, 2026-09-07** (branch `chore/skill-staleness-hygiene`). Items 1 and 2 are done; the
rest are annotated with what is now available to fix them and what is still open. Measurements
below are from the ten courses under `content/courses/`.

---

1. ~~**Em-dash gate hole at the assessment layer**~~ **FIXED 2026-09-07.** The old `dedash.py`
   globbed `lessons/drafts/*.md` and nothing else. Re-measured on the full corpus: **794
   em-dashes in quiz text across six courses** (under-the-hood 261, mastering-anchor-v2 239,
   client-side-mastery 159, btc-to-sol 74, defi-rwa 40, speedrun 21), plus 2,248 more in other
   brief prose inside `manifest.json`, plus `course.yaml` / `module.yaml` / `README.md` / covers.
   `dedash.py` now walks every reader-visible surface — `drafts, briefs, course, modules, meta,
   readme, quiz` — selectable with `--surfaces`, previewable with `--dry-run`.
   Quiz text lives in `manifest.json`; it is repaired **without reserialising the file** (two of
   the ten shipped manifests do not round-trip through `json.dumps`, so reserialising would
   rewrite files this pass has no business touching). Keys that carry commands, paths or ids are
   never repaired, so `cargo test -- --nocapture` survives.

2. ~~**dedash.py's unconditional em-dash→comma mapping mints comma splices**~~ **FIXED
   2026-09-07.** Repair is now chosen by the dash's syntactic ROLE:

   | role | repair |
   |---|---|
   | sentence boundary (independent clause on **both** sides) | period + capitalise, or semicolon |
   | appositive pair (two *spaced* dashes) | comma pair, or parentheses |
   | list-introducing / label + gloss | colon (comma if the clause already has one) |
   | trailing fragment | comma |
   | numeric or `V0–V4` range | `-` or ` to ` |

   Where a role admits more than one correct repair the choice is seeded from the surrounding
   text: **deterministic and idempotent, but distributed**, so the fix does not replace the
   em-dash fingerprint with a comma-appositive one. The concern in the original item was real and
   is now a test (`dedash.py --selftest` asserts that repairs of the same sentence shape across
   twelve subjects produce both periods and semicolons).

   Four classifier bugs were found by dry-running against the real corpus and are now regression
   tests: parentheses nested into text that already had them; `ISA enum V0–V4` flattened to
   `V0, V4`; `<label> — <noun phrase containing a verb>` split into two sentences, the first of
   which was not one; and a second colon added to a clause that already had one.

3. **Cover template leaks another course's thesis as fact.** STILL OPEN — belongs to
   `scaffold_course.py` / the cover template, not to this branch. The gates it asks for
   (`"era"/"rung"/ladder language conditional on modules > 1`, `artifact_ladder length > 1`,
   cover time math asserted against `course.yaml`) are all `validate_course.py` checks and none
   exist yet.

4. **The fact layer has no automated floor.** STILL OPEN, and it is now the largest remaining
   gap: research/facts are the only stage of the pipeline with no executable gate. Everything
   around it has one — structure (`validate_course.py`), code (`verify_code.py`,
   `verify_blocks.py`), the platform contract (`verify_challenges.py`), and, as of this branch,
   the skill's own version claims (`pin_refresh.py`). Note the shape that worked for the last of
   those: numbers were moved out of prose and into `references/pins.yaml` so a checker could
   reach them. Frozen facts (`lessons/facts/*`) are already structured that way, so the same
   move is available — a checker that re-probes each frozen fact against its recorded source and
   fails on a TTL is a direct analogue of `pin_refresh.py check`.

5. **Parallel writer fanout leaves per-agent dialect strata.** STILL OPEN. Note that
   `dedash.py`'s surface walker (`SURFACES` in that file) already enumerates every place these
   fields live and already parses YAML values apart from keys, so a normalisation pass over
   `prompt` / `purpose` / `alt` has somewhere to hang.

6. **Incompletely-applied owner fixes.** STILL OPEN as a process item. The mechanical half is
   now cheaper: `verify_code.py`'s `extract_inline_commands()` shows the shape of a
   corpus-wide sweep for a *prose* pattern, which is what "sweep the corpus for the pattern, not
   just the file in view" needs.

7. **btc-to-sol audience model contradicts itself in shipped metadata.** STILL OPEN. A
   `validate_course.py` cross-check of `course.yaml who:` against the overview text.

---

## Added by the 2026-09-07 hygiene pass (not from the R2 audits)

8. ~~**The two best verifiers in the repo were not in CI.**~~ **FIXED.** `verify_challenges.py`
   (524 lines, proves the one contract the Academy executes on every PR) was not a CI tier at
   all, and `verify_blocks.py` (1,366 lines, 31 selftests, the only thing that actually compiles
   rust/ts lesson blocks) was referenced by nothing — not `SKILL.md`, not `test_tools.py`, not
   `ci.py`. They are now `ci.py` tiers 6 and 7. **Tier 6's first run found 25 broken coding
   challenges across five courses**, including `solana-client-side-mastery` at 0 PASS / 9 FAIL —
   every challenge in that course fails against the upstream grader. Tier 7 enumerates 904
   rust/ts blocks that no CI had ever compiled.

9. ~~**`bash -n` is a syntax check, and shipped four majors that parse fine.**~~ **FIXED.**
   `verify_code.py`'s bash checker is now three tiers: syntax, **surface currency** against
   `references/command-surfaces.yaml`, and optional execution. Tier 2 catches all four named
   defects, and a fifth that tier 3 discovered while being measured (`echo hi | openssl pkeyutl
   -sign -rawin` fails on OpenSSL 3 because a one-shot EdDSA signature needs a seekable input).
   Tier 3 stays opt-in: measured on the corpus, 14 of 865 bash blocks are execution-eligible and
   most of their failures are harness artifacts (a block referencing a file an earlier block
   created), so it is an instrument, not yet a gate.

10. ~~**The skill's own pins were prose, so nothing could check them.**~~ **FIXED.** They lived
    in the Dockerfile and in sentences, and had rotted a full major behind the content:
    `SOLANA=v2.1.0 / ANCHOR=0.31.1 / RUST=1.86.0 / BITCOIN=27.1` against an authoring machine
    running `solana-cli 3.1.10 / anchor-cli 1.1.2 / rustc 1.98.1 / Bitcoin Core 31.1.0`.
    `references/pins.yaml` is now the single source, the Dockerfile ARG block is generated from
    it, and `pin_refresh.py check` is CI tier 0. **pins.yaml carries its own TTL** — the guard
    against this fix rotting the way the thing it replaced did.

11. **`references/academy-schema.md` is stale and hardcodes versions.** STILL OPEN — the file
    was out of scope for this branch. It says "pinned 2026-07-30 from `academy-courses@main`"
    and hardcodes `anchor-lang 1.1.2` three times. The proposed patch is in the branch report;
    `pins.yaml` now carries `platform.challenge_runner_anchor_lang` for it to cite.
