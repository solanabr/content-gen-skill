# Solana Hackathon Expert — platforms, tooling, and topic dossier

Research raw material for the course. Everything here is a STARTING INVENTORY, not verified
course fact — phase-2 research must confirm each platform's current flow live (these platforms
change between hackathon seasons; the course itself should teach "check the current rules" as a
habit, the way the technical courses teach "derive it, never memorize it").

## The three submission surfaces the course must cover

1. **Colosseum** (global) — the Solana ecosystem's flagship hackathons. Functionally a startup
   competition: judged on product + market + team narrative, not just code; winners historically
   feed into an accelerator path. The course's startup arc (ideation → validation → GTM → deck)
   exists BECAUSE of this surface. Research to verify at write time: current season name/dates,
   registration + submission flow, judging criteria + rubric, team formation norms, prize/
   accelerator structure, past winners.
2. **Superteam Earn** (national/regional) — earn.superteam.fun; where Brazilian/national
   hackathon tracks and bounties get submitted. Different rhythm from Colosseum: bounty-style
   listings, regional judging, faster cycles. Verify: listing flow, submission format,
   eligibility, how national tracks relate to global seasons.
3. **Seasonal/local hackathons** (the OPTIONAL module) — example given by the owner:
   **Solana × Cursor — Passo Fundo 2026**: https://hackathon.superteam.com.br/h/solana-cursor-passo-fundo-2026.
   The module should be written so the season's SPECIFICS are swappable (a template lesson:
   "reading this season's page: format, prizes, sponsor tracks, local logistics") while the
   evergreen part (why seasonal hackathons are the best on-ramp; sponsor-track strategy; how a
   local win compounds into the global season) stays stable. Verify the linked page's format
   live at write time.

## The 1-month journey shape

The course mirrors the real arc of a Colosseum-style month. Natural module skeleton (hypothesis
for David to reshape):

- **Week 0 / before**: how winners actually win — study the record (see colosseum-copilot below:
  5,400+ past projects are queryable for winner patterns and gap analysis); team formation;
  choosing global vs national vs seasonal.
- **Week 1**: ideation + market research + validation sprint (idea → evidence, kill fast).
- **Week 2-3**: build sprint with agent tooling (scaffold → MVP → devnet; scope ruthlessly to a
  demoable slice), continuous narrative capture (screenshots, metrics, decisions — deck fuel).
- **Week 4**: GTM story, pitch deck, demo video, submission mechanics per platform, judging
  optics, post-submission (what happens after: accelerator, grants, Earn bounties, next season).

## The startup-competition arc (global = startup contest, not a code contest)

Topics the course owes real lessons on, each with a produced artifact for the ladder:

- Brainstorming/ideation with structure (problem-first vs capability-first; stealing from
  adjacent ecosystems; gap analysis against past winners).
- Market research: sizing honestly at hackathon speed; competitive landscape mapping; using
  on-chain + DeFi data as evidence (e.g. TVL/protocol traction) rather than vibes.
- Validation: what counts as evidence in 1 week (user interviews, waitlists, a fake-door test,
  on-chain comparables); the kill/pivot decision.
- Product strategy: the demoable-slice doctrine; what judges can evaluate in 3 minutes.
- GTM: launch narrative, distribution hypothesis, why-Solana/why-now.
- Deck building: the hackathon deck vs the investor deck; slide-by-slide anatomy; the demo video
  (script, recording, length discipline).
- The submission itself: per-platform mechanics, deadlines timezone math, common disqualifiers.

## Agent tooling to teach (the "build with agents" spine)

The solana-ai-kit ecosystem (solanabr) ships skills that map 1:1 onto the course's journey —
the course can literally teach working WITH these (verify current names/state in the kit at
write time):

- Ideation/validation: `find-next-crypto-idea`, `idea-sprint`, `validate-idea`,
  `competitive-landscape`, `defillama-research` (TVL-as-evidence).
- Hackathon intel: `colosseum-copilot` (query 5,400+ past projects: winner patterns, gaps,
  similar-project search), `hackathon` / `submit-to-hackathon` (submission prep, track choice,
  description optimization).
- Build: `scaffold-project`, `build-with-claude`, `build-defi-protocol` / `build-mobile` /
  `build-data-pipeline` (per idea shape), `debug-program`, `deploy-to-mainnet`.
- Ship & polish: `create-pitch-deck` / `pitch-deck`, `marketing-video` (Remotion),
  `roast-my-product`, `product-review`, `review-and-iterate`, `cso` (security pass before
  judges poke it).
- Plus the general Claude Code workflow the learner should internalize: plan mode, subagents,
  skills, MCP servers (Helius, solana-dev docs, Surfpool mainnet-fork testing).

Further-resources layer (verify live): Solana docs/cookbook, Anchor docs, create-solana-dapp,
Superteam BR community channels, Colosseum's own content (past winner breakdowns), grant paths
(Solana Foundation grants, Superteam instagrants) as the "after the hackathon" exits.

## Assessment-model question (flag for the charter session with Kaue)

This is a process/strategy course — code challenges fit only the build module. The Academy
platform auto-grades TypeScript challenges only; quizzes carry the rest. Decide early: quiz-heavy
assessment + a small number of TS challenges in the build module (e.g. a submission-payload
validator, a deck-outline linter) vs. purely quiz + artifact-based gates. The schema requires the
standard block types — check `references/academy-schema.md` before promising challenge counts.

## Language question (flag for the charter)

The seasonal module targets Brazilian hackathons; prior art: `btc-to-sol-evolution` shipped in
English, `pilula-solana-superteam` and `solana-speedrun` shipped PT-BR. Decide EN vs PT-BR vs
EN-with-PT-BR-seasonal-module with Kaue before the outline locks.
