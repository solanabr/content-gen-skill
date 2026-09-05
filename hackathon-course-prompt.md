# BRIEF FOR THE AGENT BUILDING "Solana Hackathon Expert: Build a Winning Project" (with David · from Kaue's build agent, 2026-08-31)

You are building a course for Superteam Academy (solanabr/academy-courses) that walks a learner
through the FULL lifecycle of a winning hackathon project across the ~1-month arc of a Solana
hackathon: from team formation and ideation, through market research, validation, product
strategy, an agent-tooling-powered build sprint, GTM and deck/demo-video craft, to the actual
submission — **Colosseum for the global season, Superteam Earn for national tracks, plus an
OPTIONAL seasonal-hackathon module** (reference instance: Solana × Cursor Passo Fundo 2026,
https://hackathon.superteam.com.br/h/solana-cursor-passo-fundo-2026). The global hackathon is a
startup competition more than a code contest — so the course owes real lessons on brainstorming,
market research, validation, product strategy, GTM, and deck building, not just shipping code.

Nothing exists yet. You run the full pipeline in the companion **`course-methodology.md`** (read
it completely first — it is the method behind the three shipped courses), with the raw-material
dossier **`hackathon-course-resources.md`** as your phase-2 starting inventory. This brief covers
what those don't: how to work with David, and where he has explicit strategic latitude.

## MODEL

Run on Claude Fable 5 (/model fable) — the voice baseline of every shipped course; subagents
inherit the session model. If you switch models mid-course, record the seam for the boards.

## DAVID'S MANDATE: STRATEGIST FIRST, THEN EXPERT-IN-THE-LOOP

Unlike the sibling handoffs, the owner explicitly wants David to **explore and strategize how to
best do this course** before committing to a shape. So your FIRST deliverable is not a charter —
it is a **strategy memo you build WITH David** answering:

1. What does "winning" mean per surface (Colosseum global vs Earn national vs seasonal), and
   which does the course optimize for? (One course serving all three, with the seasonal module
   optional, is the owner's default — David may restructure.)
2. Journey-shaped vs skill-shaped: does the course mirror the 1-month calendar (week-by-week
   modules) or organize by discipline (research/build/pitch)? The artifact ladder differs
   radically between the two. The dossier sketches the journey shape as the hypothesis.
3. How much of the course IS the agent tooling? The solana-ai-kit skills map 1:1 onto the
   journey (dossier §tooling) — the course could teach "hackathoning with an agent team" as its
   core differentiator, or keep tooling as one module. David's call.
4. The assessment model + course language (dossier flags both — decide with Kaue early; they
   gate the outline).
5. What David uniquely knows: his hackathon war stories, judging-side insight, what separates
   the winners he's seen from the rest. Capture these as sourced facts AND as the per-lesson
   "human seam" material the writer-style method requires.

Run it as working sessions with concrete proposals on the table — never a blank page. Everything
decided goes into the pipeline's durable artifacts (charter, decision-log, research digest), not
chat history. After the memo: proceed phase by phase per the methodology (research → outline →
briefs → write → boards → visuals → export → PR), bringing David back at outline review and at
Board A time.

## FACT DISCIPLINE FOR A PLATFORM-PROCESS COURSE

The hazard here isn't hallucinated syntax — it's **stale platform mechanics**. Hackathon
platforms change flows, criteria, and dates every season. Rules:

- Every platform claim (registration flow, judging rubric, submission format, deadlines,
  prize/accelerator structure) is verified LIVE during research and re-verified by Board A —
  walk the actual sites (Colosseum, earn.superteam.fun, hackathon.superteam.com.br), screenshot
  the state, date the claim.
- Write season-specific facts as swappable: the seasonal module especially should teach "how to
  read THIS season's page" as a skill, with the current season as the worked example — so the
  course survives its own next season. De-anchor dated claims ("as of the 2026 season") rather
  than writing "currently".
- Past-winner analysis comes from queryable data (colosseum-copilot's 5,400+ project corpus),
  not from memory. Numbers about prizes, past winners, and market sizes are exactly the class of
  confidently-precise false claims the wave's fact-check layer exists for — source every one.
- David's experiential claims are facts too — attribute them to him by name in the digest.

## VOICE: BUILD DAVID'S PROFILE FIRST

Clone **https://github.com/solanabr/writer-style-skill** as a sibling checkout and run the
**persona-builder** (`/new-persona`) on a corpus of David's own long-form writing (guides, posts,
docs — NOT tweets; tweet-density calibrated into a course reads as cosplay). Make-or-break
properties (see `skills/writer-style/method/primary-profile.md`): idiolect at the right dose per
register, and the naturalness floor (uneven texture; a human seam in every passage; perfectly
groomed prose is the biggest AI-tell). Validate with `tools/validate_voice.py` + a blind A/B with
David judging. Thin corpus → blend `david X / helius Y` and grow his share. This course's
register can carry more energy than the protocol courses — it's a competition course — but the
dosage discipline still applies: hype at the edges, calm clean bodies.

## STRUCTURE HYPOTHESES (session-1 material — David reshapes freely)

The dossier's journey skeleton: Week-0 (how winners win, from the data + team formation +
choosing your surface) → Week-1 (ideation, market research, validation sprint) → Weeks-2/3
(agent-powered build sprint to a demoable slice, narrative capture as you go) → Week-4 (GTM,
deck, demo video, submission mechanics per platform, judging optics) → optional seasonal module
(swappable season page, sponsor-track strategy, local-to-global compounding) → post-hackathon
(accelerator, grants, Earn, next season). Artifact ladder candidate: one project carried through
the whole course — idea memo → validation evidence pack → scoped MVP on devnet → deck + video →
a submission-ready package for each surface. Scale: tighter than the wave-2 protocol monsters —
btc-to-sol's single-digit-module scale is the right neighborhood for v1.

## PIPELINE, GATES, TRAPS

All in `course-methodology.md` — the 12 phases, verification doctrine (incl. the
challenge-executor contract if TS challenges are used), quiz length-tell, visual/banner/export
machinery, CI pre-flight, and the operational rules (session-limit resume mechanics, journal
recovery, additive-exporter diffs, em-dash policy). Follow it phase by phase; every gate exists
because its absence shipped a real defect. Reading list before phase 1: the methodology doc;
`skills/content-gen/references/quality-bar.md` + `academy-schema.md`; 3-4 full lessons each from
`courses/btc-to-sol-evolution` (live on main) and `mastering-anchor-v2` (PR #44); payments'
(PR #48) export tree as the cleanest CI-accepted example. Ask Kaue for the gitignored
`content/wave2/` workflow-script pack or re-author from the methodology doc.

## INCREMENTING WITH DAVID'S IDEAS

(1) Platform/experience FACTS → research digest, attributed, dated; sweep the corpus if they
correct something written. (2) SCOPE/STRUCTURE calls → decision-log + outline amendment BEFORE
the affected briefs are written. (3) VOICE → pack update + re-validate. (4) Content ideas → the
artifact-ladder test (what does it consume/produce, where does it sit on the difficulty curve)
rather than bolt-ons. Nothing is "out of scope" by default: log it, place it, or park it in the
expansion memo with a reason.

Questions → Kaue (Superteam Brazil). References: solanabr/academy-courses PRs #44 + #48,
courses/btc-to-sol-evolution on main; toolchain PR #2 on this repo. — Kaue's agent
