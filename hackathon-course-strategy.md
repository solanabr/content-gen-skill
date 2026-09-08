# Strategy memo — "Solana Hackathon Expert: Build a Winning Project"

Status: **v0.7, course shipped as draft PR** (2026-09-05 → 07). D1–D14 decided (Kaue’s answers folded in 09-06); charter v1.0 signed; outline-v2 approved; manifest emitted. Every proposal below
is a concrete default on the table, not a decision. Decisions land in the decision-log section at the
bottom and then flow into the charter/outline per `course-methodology.md`.

Owner questions this memo answers (from `hackathon-course-prompt.md` §mandate): (1) what "winning"
means per surface and which the course optimizes for; (2) journey-shaped vs skill-shaped; (3) how
central the agent tooling is; (4) assessment model + language; (5) what David uniquely knows.

---

## 0. What the surfaces look like today (live snapshot, 2026-09-05)

Walked live on 2026-09-05. These are **write-time probes**: Board A re-verifies every one before ship,
and the course writes them season-swappable ("as of the 2026 World's Fair season"), never "currently".

### Colosseum (global) — a venture competition, explicitly

- Current season: **Crypto World's Fair, hackathon Sep 14 to Oct 12 2026**, registration open, 835
  builders in the arena (2026-09-06 re-check; 690 on 09-05). Colosseum runs global hackathons
  **twice a year** (Apr–May, Sep–Oct) plus **Eternal**, a self-started four-week sprint in the
  windows between (Nov–Mar, Jun–Aug; paused at snapshot; US$25k semi-annual Eternal Award).
- Multi-chain ("open to builders across all blockchain ecosystems", ecosystem prize tracks: Solana,
  Ethereum, Hyperliquid, Base, Tempo, Arbitrum, Zcash, Robinhood Chain on the World's Fair page).
  **Solana is a track, not the field; the Accelerator is Solana-only** ("some form of Solana
  integration is required"). The "why Solana" lesson argues the chain choice for both the track and
  the accelerator. Tracks, prizes and judges for World's Fair publish Sept 14 (write-time probe).
- **Stated judging factors** (verbatim, seven): Founder + Market Fit · Insight · Product + Execution
  · Potential Market Size · Founder Communication · **Viability** · Traction (Eternal lists six, no
  Traction). Process: multiple internal rounds → shortlist → judge panel → **15-minute Zoom
  interview** for a smaller group → winners ~1 month after the deadline.
- **What the repo review is NOT about (verbatim spirit):** they want "significant work during the
  hackathon", by the team "rather than a third party", features "prioritized strategically"; and
  explicitly *not* language, framework, patterns or code quality. This is F1 in Colosseum's own
  words, and it goes in lesson 2. Teams are "judged only on the work completed between the
  competition's start and end dates"; pre-existing code must be disclosed. Weekly one-minute update
  videos are optional but "strongly recommended" (a narrative-capture rung, L9).
- **Submission portal asks for**: product name + description; chains/tools used; team backgrounds;
  team location; logo; GitHub repo (private allowed if hackathon@colosseum.com gets access); a
  **2–3 minute presentation video** ("one of the first resources judges review"); a **≤3 minute
  product-demo video**; **GTM strategy, demand validation, distribution plan**.
- Rules that disqualify: one submission per team and per person; new startups only (no prior raise
  / must disclose development history; misrepresentation = disqualification); team leader must
  complete the submission before the deadline.
- Prize that matters: select winners enter the **Accelerator with $250,000** from Colosseum's fund;
  74 portfolio startups so far. Unruggable's arc (honorable mention → honorable mention → track win →
  grand prize over 4 seasons) is a ready-made "winning is iterative" story, on their own site.
- Colosseum ships **Colosseum Copilot** itself (colosseum.com/copilot) for research across previous
  submissions. The kit's `ext/colosseum` skill wraps it.

### Superteam Earn (national / regional)

- earn.superteam.fun is **bounties / projects / grants**, 213k+ users, 2,680+ sponsors. (Corrected
  2026-09-06: `/hackathon` is 404 but **`/hackathon/all` "Hackathon Tracks" and per-season pages
  `/hackathon/frontier`, `/hackathon/cypherpunk` are live.**) The mechanism the dossier guessed at
  exists: **regional Superteams attach "side tracks" to each global season**, submitted separately
  from the Colosseum main tracks. Frontier: 54 side tracks, US$439,410, including **"Side Track
  Superteam Brasil", US$10,000 USDG**; Cypherpunk: 41 side tracks, US$341,750, incl. Superteam Brasil
  × Tangem, US$11,200. No World's Fair side track yet (probe).
- Brazilian seasonal hackathons appear on Earn as **region-scoped bounties** (Hackathon Universitária
  US$3,000, 1500/1000/500 USDG; Vibeathon Superteam × Replit US$3,000) with an `eligibility` custom
  form (deck link, MVP link, social post), a UTC deadline, and Telegram PoC. Vibeathon is *submitted*
  on Earn; Passo Fundo is submitted on the STBR platform and *paid* through Earn. So Earn is: the
  side-track surface of every global season, sometimes the submission surface, always the payout
  rail (Earn → USDG → Jupiter → Pix via 4P Finance, the "Do Earn ao Pix" guide), and the grants
  surface after ("Solana Foundation Brazil Grants", up to US$10,000 USDG).
- Route quirk: send learners to `superteam.fun/earn`; deep links with `/earn/` prefix 404 to a plain
  fetch.

### Seasonal / local — Solana × Cursor, Passo Fundo 2026 (the swappable worked example)

- Aug 31 to Sep 12 2026, two phases: **Phase 1 online** (minicourses, 1:1 mentoring, team formation,
  Aug 31–Sep 5) → **submission by Sep 9, 12:00** (leader sends **deck + video + repo** on the
  platform) → selection Sep 10 → **Phase 2 in person**, Pitch Day at UPF Parque Sep 12: **5-minute
  pitch, no questions**, same-day deliberation.
- Teams of 2–4, 18+, one team per person, at least one member physically present at the final.
- **Deliverables (2026-09-06):** a **10-slide deck** (capa, problema, solução, arquitetura, mercado
  TAM/SAM/SOM, equipe, próximos passos, CTA), a **demo video ≤3 min**, **one GitHub repo** (private
  OK with read access for @hackathon-pf). **Any missing item disqualifies.** Finalists may update
  until day 12. Theme is free; Cursor "incentivado". A "regulamento" is referenced but not linked
  (ask Kaue).
- **Rubric, 0–10 per criterion, mean ranks**: Execução técnica · Inovação · Impacto · Apresentação.
  Tie-break: technical execution. Phase 2: banca scores the 5-minute pitches, mean decides. Banca not
  named on the page (probe). Schedule includes Derick Nina, "Pitch e Modelo de Negócio" (Sept 4).
- The STBR platform index shows three concurrent editions (Vibeathon online, Passo Fundo, Hackathon
  Universitário) with one shared flow: register → build with the WhatsApp community → submit deck +
  demo video + repo → finalists pitch to a banca → "Como receber o prêmio" (Earn-to-Pix guide). This
  shared flow is what the seasonal module teaches; the edition is the swappable example.
- Prizes: US$ 3,000 total (1,500 / 900 / 450 / 150 honorable mention) + Apollo incubator mentoring
  and a possible incubation invite. Kauê is on the schedule (Sep 3, "Desenvolvimento em Solana").
- Framing on the page: "Não precisa ser expert", regional-market / agro challenges. The audience for
  seasonal is wider and less technical than Colosseum's.

### What the three rubrics have in common (this is the course's spine)

Every surface scores the same four things under different names: **the problem is real (impact /
insight / market)** · **the thing works (execution / product)** · **the story lands (presentation /
founder communication / video)** · **this team can carry it (founder-market fit / team)**. Colosseum
adds two that the others do not: **viability** and **traction**. A project built to clear
Colosseum's bar clears the other two; the reverse is not true. That asymmetry is proposal 1.

---

## 1. "Winning" per surface, and what the course optimizes for

**Proposal: optimize for the Colosseum bar; ship one package with two "adapters".**

- The learner builds ONE submission package to Colosseum's spec (the superset). Two short adapter
  lessons translate it: to a **seasonal** submission (deck + video + repo, 5-minute no-questions
  pitch, in-person logistics) and to an **Earn** listing/track (bounty-style, fast cycle, regional
  judges, payout mechanics).
- "Winning" is defined per surface in lesson 2 as a literal reading of each rubric, and the course
  teaches the learner to **re-derive it each season from the live page** (the fact-discipline rule
  becomes a learner skill).
- Default stays the owner's: one course, three surfaces, seasonal module optional. Restructure only
  if David wants to narrow (e.g. Colosseum + seasonal, Earn as a lesson rather than an adapter).

Resolved by research (2026-09-06): Earn is a real hackathon surface (regional side tracks on every
global season, plus region-scoped hackathon bounties) and the payout rail. The Earn adapter is a
lesson: "side track + regional bounty: submit the same package twice, correctly".

## 2. Journey-shaped vs skill-shaped

**Proposal: journey-shaped modules, skill-shaped lessons.**

- The module map mirrors the month (before the clock → week 1 → weeks 2–3 → week 4 → submit → after),
  because that is the real artifact ladder: each week's output is the next week's input, and the
  learner is most likely taking this course *during* a season.
- Each **lesson** is a self-contained skill with its own reusable artifact (an idea memo, an evidence
  pack, a scope card, a deck), so the course is still useful off-season and re-enterable mid-season
  ("I'm in week 3, I need the deck lesson").
- Rejected alternatives: pure journey (dies between seasons, punishes late entrants); pure discipline
  (research / build / pitch) loses the ladder, and the 1-month arc is the course's best hook.

## 3. How central is the agent tooling

**Proposal: tooling is the spine of the *build*, not the subject of the course.**

- Promise stays "leave with a submission-ready package for a real season", not "learn to hackathon
  with agents". Every build lesson runs through the kit (idea sprint, Colosseum research, scaffold,
  pitch deck, video), one setup lesson installs it, and the course states plainly that an agent
  team is how a 2–4 person team ships a demoable slice in two weeks in 2026.
- Why not the differentiator: **the dossier's tooling inventory is a superset of what the plugin
  install ships.** Verified 2026-09-06 in `solanabr/solana-ai-kit` (research digest §4): the plugin
  ships three GTM skills as local wrappers (symlinked into `plugin/skills/`), each "adapted from
  sendaifun/solana-new, telemetry removed": **`hackathon`** (track choice via live crowdedness,
  scannable description, <3-min demo script, submission checklist, grants after), **`idea-sprint`**
  (interview → crypto-necessity gate → 3 candidates → score /15 → go/no-go → `idea.md`),
  **`pitch-deck`** (audience-specific: hackathon judges = 5–7 slides, working demo, technical
  novelty, why-Solana), plus **`ext/colosseum`** = Colosseum Copilot (5,400+ projects, needs a PAT).
  The rest of the dossier's names (`validate-idea`, `competitive-landscape`, `defillama-research`,
  `marketing-video`, `roast-my-product`, `cso`, `submit-to-hackathon`, …) exist **only upstream in
  `ext/solana-new`**, reachable through the full install, with a hub warning never to run their
  telemetry preambles. Rule for briefs: **teach the three wrappers + Copilot by name; everything
  else is "a plain Claude Code workflow" unless phase-3 pins it.** A course whose identity is "the
  20 kit skills" rots with the kit.
- What the course *can* own: the **method** (the same four-criteria spine, the demoable-slice
  doctrine, the evidence pack), with tooling as the accelerant. Kit names are version-pinned facts
  with a freshness note, like an Anchor version.

## 4. Assessment model + language

**Proposal (assessment): quiz-led, artifact-gated, 3–4 honest TypeScript challenges.**

- Every lesson: scenario quiz (Academy grades it) + the lesson's artifact as the "do" element.
- TS challenges only where a pure function is the real skill, so grading is honest and deterministic:
  1. `validateSubmission(payload)` — checks a Colosseum-shaped payload for the required fields and
     the video-length / repo-access rules (submission module).
  2. `deadlineInLocal(deadlineUtcIso, tz)` — the timezone math that disqualifies real teams.
  3. `happyPathFits(steps[])` — the ≤7-step scope check (David's MVP worksheet, stance 15).
  4. `scoreAgainstRubric(rubric, scores)` — mean-of-criteria ranking with the Passo Fundo tie-break.
- `openEnded` reflections in the strategy lessons (ungraded by design). No Rust anywhere.
- Capstone = the submission-ready package; the credential moment is the learner's own package
  passing `validateSubmission` plus the deck/video artifacts checked in.

**Proposal (language): EN source, PT-BR overlay.** The repo now ships multi-language courses via
l10n overlays (`academy-courses` PR #51, merged; #53 used it for visão-geral). Author in English
(David's voice pack is calibrated on English), then overlay PT-BR for the seasonal module first and
the whole course when it earns it. Decide with Kaue before the outline locks.

## 5. What David uniquely knows (captured 2026-09-05, session 1)

Sourced facts, attributed to **David Potolski Lafetá** by name in the research digest, and the
human-seam material per lesson. Tag: `[david-2026-09-05]`. Attribution rules he set: **his judging
experience is on other chains and is NOT to be discussed** in the course (the *lessons* from it are
usable as his positions, the events are not); the SuiHubs win is his own story and is usable
(confirm with him whether to name the chain, see D8). Two third-party stories (Cloak, Bido) are his
recollection and are **write-time probes**: verify with Kaue / live sources before any number or
outcome is written.

| # | Fact (his words, condensed) | Kind | Lands in |
|---|---|---|---|
| F1 | Winners were always the ones with the most compelling presentation. It is not the best code or the most features; it is solving a problem that needs solving and selling that solution the right way. | stance, high | L2 (define winning), L11 (deck), course thesis |
| F2 | Winning products did not *look* AI-made (the obviously AI-generated frontend) and were functional: not 100% complete, but complete enough for a demo. | stance, high | L7 (demoable slice), L9 (polish pass) |
| F3 | Sometimes the pitch is worse than the product, and you lose on the pitch. If you believe in the idea, keep working and bring it to the next hackathon (check that season's rules on prior work). | stance + method | L14 (after the deadline); pairs with Colosseum's own Unruggable arc (4 seasons to a grand prize) |
| F4 | **His win at the SuiHubs hackathon, Dubai.** He did not expect it: the idea was "too simple" and he had not planned a good demo. He won because the idea matched exactly what the organizers were looking for at the time, and the pitch was good enough to sell it. | named anecdote (burn: once) | L2 (read the rubric: match what they are looking for) |
| F5 | **His worst mistake, last Colosseum edition:** too much focus on code, not enough planning of the presentation; realized near the end of the month. Should have planned the pitch from day 0 and kept improving it, and shown the project to more people for feedback. | named anecdote (burn: once) | L3 (day-0 plan) as the seam; drives structural change S1 below |
| F6 | The demos he remembers opened on emotional attachment in the first 20 seconds: a problem people face in their own lives (wallet hacked, talking to a scammer, signing a malicious contract), told specifically, with the feeling of impotence at not being able to do anything about it. | observation | L12 (the two videos) |
| F7 | Day-0 team needs a plan of action for the whole month. Someone must own competitor research (what they do right and wrong). Someone should go after adjacent projects as integration partners and sell them the idea; arriving at demo day with a few partners is an edge. | method | L3 (team + month plan), L5 (research role), L10 (GTM: partners) |
| F8 | Good hackathon ideas came from problems the team members, or people close to them, face day to day. | observation | L4 (ideation) |
| F9 | **Cloak**: a team of university students who won a track at a previous hackathon, got a large investment, and had a running company by graduation. **Probe result 2026-09-06 (digest §6):** Cloak placed **third in Cypherpunk's Stablecoin Track** (US$15k; Cointelegraph Brasil), four named founders with prior jobs (SonicSVM, Compute Labs, BTG Pactual), **US$250k Colosseum Accelerator pre-seed**, mainnet alpha; no page mentions a university. "Won a track" is REFUTED; students / larger raise UNCERTAIN. Ask Kaue before writing. | third-party story, PARTLY REFUTED | L16 (local win compounds) / L14, as "placed, then got funded", if Kaue confirms the rest |
| F10 | **Bido**: two friends with no idea for a project went to Superteam Brazil mentoring sessions and ended up in Silicon Valley with a US$ 2M investment. **Probe result:** no public trace under that name (5 searches, EN + PT). Needs exact name, founders, round, a public source and consent from Kaue. | third-party story, UNVERIFIED | L14 (after) / L16 only if verified |

Unanswered from the capture list (carry to session 2 or the outline review): what he accepts as
one-week validation evidence (F-pending, L6), and whether he has seen a seasonal win reach Colosseum
directly (F9/F10 partially answer it).

### Structural changes these facts force (logged as S1–S3, applied in §6)

- **S1 — the pitch is a living artifact from lesson 3, not a week-4 deliverable.** F5 is the
  course's central war story and it says the calendar shape in the dossier is exactly the trap: deck
  and pitch in week 4. So the ladder carries a **pitch draft from M1** that every module revises
  (v0 one-liner at L3 → v1 after validation at L6 → v2 after the slice at L9 → final at L11), and a
  **feedback loop** rung: show the pitch to N people per week, log what they did not get.
- **S2 — a "does it look real" polish pass is its own lesson beat (F2).** L9 gains an explicit
  anti-"AI-made" pass on the frontend and the demo path, before the roast/security pass.
- **S4 — one dedicated `concept-retrieval` lesson is mandatory (CATALOG §5, found in the register-bar
  pass 2026-09-06).** The memo's retrieval checkpoint after M2 becomes a real lesson: "Re-derive
  winning for a season you have never seen" (an unseen season page, the rubric brief, the evidence
  pack graded against it, cumulative quiz with ≥1 item per skill tag). Count becomes 5 modules /
  **15 lessons** + optional 2; D6 amended accordingly at outline review.
- **S3 — partners and competitors are roles, not topics (F7).** L3 assigns the competitor-research
  owner and the partnerships owner on day 0; L5 and L10 consume their outputs. GTM at L10 includes
  outreach to adjacent projects with the goal of naming partners on the deck.

## 6. Proposed shape (hypothesis for the outline; David reshapes)

Scale: **6 modules, 14 lessons + 1 optional module of 2** — btc-to-sol's neighborhood (7/15).

| Module (journey) | Lessons (skills) | Artifact rung |
|---|---|---|
| M1 Before the clock starts | 1 Opener: query the record (runs a Colosseum-corpus query in the first 150 words) · 2 Read the rubric: pick your surface, define winning (F1, F4) · 3 The team on day 0: the month plan, the competitor owner, the partnerships owner, **pitch v0** (F5, F7; S1, S3) | surface brief + team card + month plan + pitch v0 |
| M2 Week 1: idea to evidence | 4 Ideation with structure: problems you and yours actually have; gap vs past winners (F8) · 5 Market research at hackathon speed: the competitor owner's map, on-chain / DeFi data as evidence, not vibes (F7) · 6 The validation sprint and the kill/pivot call; **pitch v1 + first feedback round** (S1) | idea memo → competitor map → evidence pack → pitch v1 |
| M3 Weeks 2–3: the demoable slice | 7 Product strategy: scope to what a judge can evaluate in 3 minutes, complete enough for a demo (F2) · 8 Build sprint with an agent team (setup, scaffold, devnet) · 9 Capture the narrative while you build; the **"does it look real" pass** (F2; S2), then roast + security; **pitch v2 + second feedback round** (S1) | scope card → devnet demo slice → narrative log → pitch v2 |
| M4 Week 4: the story | 10 GTM: distribution hypothesis, why-Solana / why-now as a judged claim, **partner outreach with named partners on the deck** (F7; S3) · 11 The hackathon deck vs the investor deck; pitch final (F1) · 12 The two videos: the first 20 seconds are a felt problem (F6); demo ≤3 min | GTM one-pager + partner list → deck → videos |
| M5 Submit, then keep going | 13 Submission mechanics per surface: Colosseum portal, Earn listing, seasonal platform; deadline math; disqualifiers · 14 After the deadline: interview, accelerator, grants, Earn, and carrying a lost pitch into the next season (F3, F9, F10; Unruggable arc) (conclusion) | submission package (capstone) |
| M6 (optional) The seasonal hackathon | 15 Reading this season's page (Passo Fundo 2026 as the worked example) · 16 Sponsor tracks and how a local win compounds into the global season (F9, F10) | seasonal adapter |

Cadence: difficulty plateaus in M2 and M4 (research and writing skills), spikes in M3 (build) and
lesson 13 (mechanics). Retrieval checkpoint after M2 (re-derive the rubric for an unseen season page)
and before capstone (assemble the package from the rungs). The pitch thread (S1) is the spiral: it
reappears at L3, L6, L9, L11 and is the one artifact every module touches.

## 7. Timing

The World's Fair season closes **Oct 12 2026**. The pipeline will not ship a reviewed course by Sep 14,
so v1 targets the **next global season (~H1 2027)** and uses the World's Fair as a dated worked example
alongside Passo Fundo. If Kaue wants a partial drop during the season, the M4/M5 lessons (deck, video,
submission mechanics) are the ones a team mid-hackathon would pay for; flag as a scope decision.

## 8. Risks

- **Stale mechanics** (the brief's hazard): every §0 fact is a write-time probe; the course teaches
  "read the live page" as the skill.
- **Tooling drift**: kit skill names are pinned with a freshness note; no lesson promises a skill that
  phase-2 research did not find.
- **Voice extrapolation**: David's pack is calibrated on ~3.9k words of 2020 Medium prose with zero
  code blocks; `helius` carries the evidence layer at ~15%. A competition course can run warmer at the
  edges, but bodies stay calm. Validate with a blind A/B on lesson 1 before the parallel write.
- **Numbers**: prize amounts, builder counts, past-winner counts are exactly the confidently-precise
  claims the fact layer exists for. Source every one, date every one.

---

## Decision log (fills in during session 1)

| # | Decision | Chosen | Why | Date |
|---|---|---|---|---|
| D1 | Surface the course optimizes for | **Colosseum bar + two adapter lessons (seasonal, Earn)** | A package that clears Colosseum's superset rubric clears the other two; the reverse is false. | 2026-09-05 (David) |
| D2 | Journey vs skill shape | **Journey-shaped modules, skill-shaped lessons** | The month is the ladder and the hook; skill lessons keep it usable off-season and re-enterable mid-season. | 2026-09-05 (David) |
| D3 | Agent tooling centrality | **Spine of the build, not the subject** | Promise stays "submission-ready package"; kit inventory is smaller than the dossier claims, so names are pinned facts with freshness notes, never the identity. | 2026-09-05 (David) |
| D4 | Assessment model | **Quiz + artifact gates only; no coding challenges** | Process/strategy course; a TS challenge would grade a proxy, not the skill. `openEnded` reflections in strategy lessons; the capstone is the assembled package. §4's four TS challenge ideas are parked in the expansion memo. | 2026-09-05 (David) |
| D5 | Course language | **EN source now; PT-BR overlay later** (confirmed) | Voice pack is calibrated on English; repo supports overlays (academy-courses #51) but the app does not render them yet. "Start with english and create pt-br later." | 2026-09-06 (Kaue via David) |
| D6 | Scale (modules / lessons) | **5 core modules / 14 lessons + optional M6 of 2** (default, taken as accepted unless David objects at outline review) | btc-to-sol's neighborhood (7/15) per the brief; S1–S3 fit inside existing lessons without adding any. | 2026-09-06 |
| D7 | Seasonal module optional vs core | **Optional** (owner's default, kept under D1) | Seasonal is an adapter over the same package; F9/F10 give it its own payoff story. | 2026-09-06 |
| D8 | Naming the chain in David's win (F4) | **"A hackathon in Dubai"; chain not named** | His call: his own win is usable, the competing chain is not named in a Solana course. Writers must not add the chain back in. | 2026-09-06 (David) |
| D11 | Creator wallet | **`8kMziL5e3qEWhp1nQHEiYLRypymyBVTXNxgZXyQwhbSo`** | David's wallet; immutable once the course is created on-chain. | 2026-09-06 (David) |
| D12 | Worked-example domain | **"Fiado"** (corner-shop credit notebook → stablecoin-settled tab) | Day-to-day problem (F8), felt opener (F6), two-week slice, honest why-Solana. David re-reviews at outline review. | 2026-09-06 (David) |
| D15 | Voice validation, blind A/B on lesson 1 | **David preferred the plain-register draft (B) over the pack draft (A).** Reason (his words): "v2 has too much text in places where it didn't need. I want a version where it seems like someone wrote it instead of seeming like it was written without a person behind it." Plan: tune the pack (cut padding and meta-narration; keep a sparing, earned first person), then a second blind A/B on lesson 2. The plain draft of L1 stays as fallback. | Both drafts 3.2k words, 8 visuals, same facts; A had 24 first-person "I", 13 H2s and a qualification opener; B had 0 "I", 10 H2s. | 2026-09-06 (David) |
| D16 | Scope: Colosseum is the target; other hackathons are rehearsals | **Amends D1 and D7.** The course optimizes for Colosseum (twice a year; the goal is to prepare people for the next edition). Its seven judging factors are the spine; per-edition specifics (dates, prizes, tracks) are dated in prose. **No per-hackathon rubric tables** for seasonal or Earn surfaces: they are taught as rehearsals for the next Colosseum edition (what to reuse, what to test), not as parallel targets. The optional seasonal module collapses to ONE lesson ("Rehearse the season before the season"); L2 becomes "What winning means at Colosseum"; L7 re-derives a past Colosseum season; L14 is Colosseum's portal first with one rehearsal-surface section. Core count stays 15; total 16. | David (his words): "If we spend too much time on that the course will be outdated too soon. Let's focus more on the Colosseum since this one happens twice a year and our goal is to help people prepare to it. These other hackathons are just a preparation for this next Colosseum edition." | 2026-09-06 (David) |
| D17 | Voice validation, blind A/B round 2 (lesson 2) | **David picked the tuned pack (A) over the plain register.** Register for all 16 lessons = the david pack in course modes with the R1 calibration (`LESSONS.md`): no announcement stubs, no qualification opener, first person as receipt (≤8 per 3k words), 8–11 sections, low marker appetite. The R1 plain draft of L1 stays in `_ab/` as the tightness bar; L1 and L2 are rewritten under the tuned pack (L2 also to the D16 brief). | Round 2 forensics: A had 5 first-person "I", 11 sections, 0 announcement stubs; B had 0 / 10 / 0. The difference David felt is judgment and receipts, not markers. | 2026-09-06 (David) |
| D18 | Course shipped | **Draft PR opened 2026-09-07 on solanabr/academy-courses, branch `chore/course-solana-hackathon-expert-07-09-2026`** (16 lessons, 50 quiz items, 105 visuals, content-lint OK). WIP per D13 with a TODO for the past-winner example; World's Fair season facts to re-verify on Sept 14. | Boards A–D + three fixer passes + exported-tree cold read all green; reports in the authoring workspace `boards/`. | 2026-09-07 |
| D19 | Lesson length | **Cut every lesson to a guide: L1–L3 ≤1,500 words, the rest ≤2,000 (build and submit ≤2,400); 5–7 sections; why → do this (numbered) → done when → watch out → checkpoint → next; 3–4 visuals per lesson; duration 12 h.** | David, after reading the shipped draft: "people want a guide to follow but if the guide is too big they might lose interest." The 3,000+ word bar was the protocol courses' bar, not a hackathon guide's. Facts, artifacts, quizzes and voice unchanged. | 2026-09-08 (David) |
| D20 | Emphasis and commit policy | **Add bold and italics as a reading aid on every lesson** (bold the action and the number that matters in each step, the idea, the checkable object, the trap; italics for the judgment, the felt line, the answer shape; never whole sentences; no paragraph over 90 words without emphasis; split over 120). **No more force-pushes: every change is a new commit.** | David, reading PR #58 after the cut: "avoid having these big chunks of text without any bold or italic text"; "it grabs people's attention and helps them focus more". | 2026-09-08 (David) |
| D21 | Owner feedback round 2 (after reading the emphasized guide) | **(a) Plain language: no "rung", "rubric", "spec", "surface" jargon; (b) quote regulations from Colosseum ONLY, never from Passo Fundo / Vibeathon / Universitária / Earn listings (and no Portuguese fragments); (c) Checkpoint memory drills → a two-line takeaway (lesson 1 has none); (d) lesson 1 ships without a quiz and without the byline; (e) Kuka is not a judge, remove; (f) the Earn season API moved to superteam.fun/api/hackathon/<season> (use curl -sL); (g) Unruggable's four seasons are shown on colosseum.com/hackathon, not the company page; (h) ideation: a problem they have or had, not "that same week".** | David's read of the shipped guide, 2026-09-08. Facts corrected at the source first; drafts, quizzes and cards swept after. | 2026-09-08 (David) |
| D10 | Where the course PR lands | **`solanabr/academy-courses`, branch off fresh main, touch only `courses/solana-hackathon-expert/`, trackId 0 / trackLevel 0** | Elective lane per CATALOG.md addendum; PR #48's body is the template. | 2026-09-06 (David) |
| D9 | Third-party stories (Cloak, Bido) | **Tag by X handle only (x.com/cloak_ag, x.com/usebido); no founder names, no university, no raise figures beyond the public Colosseum US$250k for Cloak; Bido's raise stays unnumbered and attributed to David** | Kaue: "not really necessary to add so much personal info, just tag their X." Verified public facts only; the US$2M figure has no public source and is not written. | 2026-09-06 (Kaue via David) |
| D13 | Course PR status at open | **Draft / WIP** with a TODO for a Superteam Brasil past-winner deck or demo video Kaue will try to source | Kaue: "leave this as todo in the PR and leave the PR as wip." | 2026-09-06 (Kaue via David) |
| D14 | Kaue's answers to the remaining probes | Regulamento: link the Passo Fundo page only. Banca: unanswered, not named. Funnel numbers: unanswered, keep Cointelegraph. "Instagrants": outdated, link superteam.fun/earn/grants/solana-foundation-brazil-grants. Road to Colosseum for Brasil: link hackathon.superteam.com.br. World's Fair side track: expected to publish Sept 14. Wave-2 script pack: re-author if not present. | Answers in `questions-for-kaue.md`. | 2026-09-06 |
