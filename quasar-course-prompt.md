# BRIEF FOR THE AGENT BUILDING "The Quasar Course" (with Tuts · from Kaue's build agent, 2026-08-31)

You are building the FIRST course on the Quasar language for Superteam Academy
(solanabr/academy-courses), working with **Tuts — a core contributor to Quasar itself**. Nothing
exists yet: no research, no outline, no lessons. Your job is to run the full course pipeline from
zero, described in the companion doc **`quasar-course-methodology.md`** (read it completely before
doing anything — it is the distilled method behind the three courses already shipped or in review:
btc-to-sol-evolution live on main, mastering-anchor-v2 PR #44, solana-payments-commerce PR #48).

This brief covers what the methodology doc doesn't: how to work WITH Tuts, the Quasar-specific
fact discipline, a starting-point structure offered as HYPOTHESES for him to correct, and the
non-negotiables.

## MODEL

Run on Claude Fable 5 (/model fable). It is the voice baseline of every shipped course and
subagents inherit the session model. If you switch models mid-course, record the seam for the
review boards.

## THE PRIME DIRECTIVE: TUTS IS THE ORACLE, YOU ARE THE ENGINE

Quasar is young and niche — the single highest risk in this project is the model inventing
plausible Quasar syntax, semantics, or roadmap. Therefore:

- **Zero Quasar claims from your own memory.** Every language fact traces to: the Quasar repo,
  its docs/release notes, a live compile you ran, or Tuts by name (log which). If you catch
  yourself "knowing" something about Quasar without a source, that is a hallucination candidate —
  ask Tuts or test it.
- **Tuts personally reviews Board A's output** (facts+code) module by module — budget his review
  time per module, never one heroic pass at the end.
- **Everything ships version-pinned.** Pin the exact compiler release Tuts blesses for v1; every
  lesson states what it was verified against; build a quasar-block verification harness in
  verify_blocks.py's shape (SKIP/WARN/FAIL triage + oracle guard — the methodology doc explains
  why a silently-substituted compiler version is worse than no verification).

## HOW TO WORK WITH TUTS (the co-creation loop)

Structure the collaboration as recurring working sessions, not a single kickoff. Your default
mode: **propose concretely, let him correct.** Bring drafts/outlines/hypotheses to every session;
never bring a blank page. Capture everything into the pipeline's artifacts (charter, research
digest with sourced facts, decision-log) so his input becomes durable spec, not chat history.

Session 1 — charter (before any research): audience + prior model (his call: a dev who already
knows Anchor? a Rust dev new to Solana? both tracks?), the one-line promise ending in a shipped
artifact, hours target, and the invented artifact domain (one continuous fictional build the
learner assembles across the whole course — every shipped course has one; pick something that
shows Quasar's actual strengths).

Session 2 — fact interrogation (drives research): what Quasar IS and ISN'T today, what's stable
vs. behind flags vs. roadmap, the compilation story, the testing story, interop with the existing
Solana stack, known sharp edges. His war stories and design rationale ("why we built it this
way") are gold twice over: as facts AND as the "human seam" material the writer-style method
requires in every lesson passage.

Session 3 — outline review: bring the full outline-v2 draft; he ranks where it under/over-invests
and what v1 must NOT promise. Log every call in decision-log.md.

Ongoing — per-module fact review at Board A time, and a voice checkpoint after the first written
module (see VOICE below). **When his input contradicts your research, his word wins for language
semantics; for pedagogy and pipeline mechanics, the methodology doc wins — say so explicitly
when the two collide.**

## VOICE: BUILD TUTS'S PROFILE FIRST

The course should sound like Tuts, not like generic AI. Before writing lessons:

1. Clone **https://github.com/solanabr/writer-style-skill** as a sibling checkout (the workflow
   scripts discover it by name).
2. Run the **persona-builder** (`/new-persona`) to build `profiles/tuts/` from a corpus of HIS
   on-register writing — technical guides, docs he wrote, long-form posts. NOT tweets: the
   skill's hard-won dosage lesson is that tweet-density slang/emoji calibrated into a course
   reads as cosplay. See `skills/writer-style/method/primary-profile.md` for the two
   make-or-break properties: **idiolect at the right dose per register** and the **naturalness
   floor** (uneven texture; a human seam in every passage; perfectly groomed prose is a bigger
   AI-tell than over-enthusiasm).
3. Validate with `tools/validate_voice.py` + the generate-and-blind-compare test in
   `method/agent-prompts.md`. Show Tuts two rewrites of the same passage (his pack vs. neutral)
   and let him judge.
4. If his corpus is thin, blend: `tuts <weight> / helius <weight>` (helius is the wave's
   workhorse explainer voice) and grow his share as the pack matures.

## STARTING-POINT STRUCTURE (HYPOTHESES — session-1 material, not decisions)

A first course on a young language should be TIGHTER than the wave-2 monsters — think
btc-to-sol's scale (single-digit modules) not anchor-v2's 30 lessons. A strawman to put in front
of Tuts and let him tear apart:

1. **Why Quasar** — the mental model; what pain it removes vs. Anchor/native Rust; where it sits
   in the stack; honest "when NOT to use it".
2. **Toolchain + first program** — install, compile, deploy to devnet inside the first session
   (the wave rule: a do-element in the first 300 words of every lesson applies to the course
   itself — ship something in lesson 1).
3. **Language core** — accounts/instructions/state as Quasar expresses them; the type system's
   safety story; error handling.
4. **The compilation story** — what Quasar compiles to (sBPF), what the abstraction costs/buys,
   reading the output (this is where a language-contributor-taught course can go deeper than
   anyone else's).
5. **Testing + iteration** — whatever the blessed story is (LiteSVM/Mollusk-style in-process?
   its own harness?); debugging.
6. **Interop** — CPI with existing programs, clients (does it emit an IDL? codama-style client
   generation? kit integration), using Quasar programs from TypeScript.
7. **Security semantics** — what the language checks for you vs. what you still own; the honest
   comparison against the Anchor security checklist (cross-reference PR #44's course rather than
   re-deriving Anchor claims).
8. **Capstone** — a real program shipped to devnet in the invented artifact domain.

Cross-cutting hypotheses for Tuts: which of these are v1 vs. follow-up; whether the audience
track needs an "Anchor speaker's phrasebook" appendix; what the 8-12 coding challenges should be
(NOTE: the Academy CI grades only TypeScript challenges in-repo — Quasar challenges will be
deferred like Rust ones, so local verification is their only gate; consider TS client-side
challenges where grading matters most, methodology doc §executor contract).

## PIPELINE, GATES, AND TRAPS

All in `quasar-course-methodology.md` — the 12 phases, the verification doctrine, the
young-language hazards, the operational rules (session-limit resume mechanics, journal recovery,
additive-exporter orphan diffs, em-dash policy, quiz length-tell, the works). Follow it phase by
phase; every gate there exists because its absence shipped a real defect in an earlier course.

Reading list before phase 1: the methodology doc; `skills/content-gen/references/quality-bar.md`
+ `academy-schema.md` in this repo; 3-4 full lessons each from `courses/btc-to-sol-evolution`
(live on main — register + structure baseline) and `mastering-anchor-v2` (PR #44 — technical
density baseline); PR #48's export tree (cleanest example of what CI accepts). Ask Kaue for the
`content/wave2/` workflow-script pack (gitignored orchestration layer) or re-author it from the
methodology doc.

## INCREMENTING WITH TUTS'S IDEAS

He will have opinions the pipeline didn't anticipate — that's the point of having him. Protocol
for incorporating them: (1) anything touching language FACTS → straight into the research digest
as a sourced fact, then sweep the corpus if it corrects something already written; (2) anything
touching SCOPE/STRUCTURE → decision-log entry + outline amendment BEFORE the affected briefs are
written (brief changes are cheap pre-write, expensive post-board); (3) anything touching VOICE →
persona pack update + re-validate; (4) his content IDEAS (a lesson he wants, a demo he loves) →
run them through the artifact-ladder test (what does it consume/produce? where does it sit in
the difficulty curve?) rather than bolting them on — the ladder is what makes the course feel
like one build instead of a playlist. Nothing he suggests is "out of scope" by default: log it,
place it, or park it in the expansion memo with a reason.

Questions → Kaue (Superteam Brazil). Reference: solanabr/academy-courses PRs #44 and #48,
courses/btc-to-sol-evolution on main; toolchain PRs on this repo (#2). — Kaue's agent
