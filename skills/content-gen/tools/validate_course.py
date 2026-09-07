#!/usr/bin/env python3
"""
validate_course.py — the content-gen validator (deterministic, pre-emit gate).

Reads a course manifest (JSON) and runs structural checks. HARD failures break
the prerequisite-DAG walk or the writer-style handoff and must be fixed; ADVISORY
flags are smells a human weighs. Pedagogical *judgement* (is the hook felt? the
tradeoff real? the dominant_job correct?) is NOT here — that stays an LLM-judge
pass in references/quality-bar.md.

  dag       acyclicity, no-forward-deps, referential integrity of ids/skills
  briefs    per-lesson schema completeness, dominant_job enum, gated-on-doing, id uniqueness
  ladder    artifact-rung monotonicity, difficulty band, cadence coverage
  capstone  capstone requires only skills taught earlier
  outcomes  every terminal outcome has a proof and vice-versa; module traces resolve
  all       run everything; exit 1 if any HARD fired

    python validate_course.py all     --course courses/<slug>
    python validate_course.py dag     --manifest manifest.json
    python validate_course.py --selftest

Mirrors the writer-style skill's validator: pure-Python, stdlib-only, --selftest,
hard-vs-advisory split, exit codes (0 ok, 1 hard fail, 2 usage).
"""
from __future__ import annotations

import argparse
import re
import sys

from course_lib import (
    DOMINANT_JOBS, GUEST_ONLY_JOBS, ARTIFACT_LADDER, BRIEF_REQUIRED_KEYS,
    BRIEF_CORE_KEYS, BRIEF_BUILD_KEYS, LESSON_KINDS, ID_RE, count_prose_emdashes,
    KIT_SURFACES, VISUAL_TYPES, VISUAL_FIELDS,
    WEAK_BLOOM_VERBS, PASSIVE_ASSESSMENT_RE, CHALLENGE_LANGS, CHALLENGE_BUILD_TYPES,
    load_manifest, flatten_lessons, topo_sort,
)

HARD = "[HARD] "
ADV = "[advisory] "

# Course-lesson length band (words). The brief's est_length target must reach the
# floor — that number is what the writer writes to. Raise the whole band by editing
# this one constant; every course the skill emits inherits it.
LESSON_TARGET_MIN = 3000


def _result(name, flags):
    hard = any(f.startswith(HARD) for f in flags)
    return {"name": name, "hard": hard, "flags": flags or ["ok: clean"]}


# ── dag ─────────────────────────────────────────────────────────────────────────

def check_dag(m: dict) -> dict:
    flags: list[str] = []
    for kind, ids in (("course", [m.get("course", {}).get("id")]),
                      ("module", [mod.get("id") for mod in m.get("modules", [])]),
                      ("lesson", [l.get("id") for l in m.get("lessons", [])])):
        for _id in ids:
            if _id is not None and not ID_RE.match(str(_id)):
                flags.append(f"{HARD}{kind} id '{_id}' is not kebab-case [a-z0-9-] — ids become filesystem paths")
    dag = m.get("dag", {})
    nodes = list(dag.get("nodes", []))
    edges = [list(e) for e in dag.get("edges", [])]
    nodeset = set(nodes)

    for a, b in edges:
        if a not in nodeset or b not in nodeset:
            flags.append(f"{HARD}dag edge references unknown node: {[a, b]}")

    order, cycle = topo_sort(nodes, edges)
    if cycle:
        flags.append(f"{HARD}prerequisite DAG has a cycle among: {sorted(cycle)}")

    modules = m.get("modules", [])
    mod_ids = [mod["id"] for mod in modules]
    mod_order = {mid: i for i, mid in enumerate(mod_ids)}
    if len(set(mod_ids)) != len(mod_ids):
        flags.append(f"{HARD}duplicate module id(s): {sorted({x for x in mod_ids if mod_ids.count(x) > 1})}")

    # module-level referential integrity
    for mod in modules:
        for dep in mod.get("depends_on", []):
            if dep not in mod_order:
                flags.append(f"{HARD}module {mod['id']} depends_on unknown module: {dep}")
        for sk in mod.get("requires_skills", []) + mod.get("teaches_skills", []):
            if sk not in nodeset:
                flags.append(f"{HARD}module {mod['id']} references unknown skill node: {sk}")

    # earliest course-position at which each skill is taught (module granularity)
    skill_taught_at: dict[str, int] = {}
    for mod in modules:
        idx = mod_order[mod["id"]]
        for sk in mod.get("teaches_skills", []):
            skill_taught_at[sk] = min(skill_taught_at.get(sk, idx), idx)

    flat = flatten_lessons(m)
    lesson_pos = {l["id"]: i for i, l in enumerate(flat)}
    lesson_ids = set(lesson_pos)

    for i, l in enumerate(flat):
        brief = l.get("brief", {})
        l_mod_idx = mod_order.get(l.get("module"), 1_000_000)
        for pre in brief.get("prerequisites", []):
            if pre in lesson_ids:
                if lesson_pos[pre] >= i:
                    flags.append(f"{HARD}forward dependency: lesson {l['id']} requires {pre} taught later")
            elif pre in nodeset:
                at = skill_taught_at.get(pre)
                if at is None:
                    flags.append(f"{HARD}lesson {l['id']} requires skill never taught: {pre}")
                elif at > l_mod_idx:
                    flags.append(f"{HARD}forward dependency: lesson {l['id']} requires skill {pre} taught later")
            else:
                flags.append(f"{HARD}lesson {l['id']} prerequisite resolves to nothing (typo?): {pre}")
    return _result("dag", flags)


# ── academy plugins: quiz + coding-challenge specs (optional, additive) ─────────

def check_quiz_blocks(b: dict, lid: str) -> list[str]:
    """Per-brief structural validation of `quiz_blocks` (references/academy-schema.md).
    Scope is deliberately narrow: the things that must hold for ONE brief to be a
    well-formed document — stable unique ids, correctness keyed to a stable option id,
    and the single/multi correctness rule.

    The AUTHORING policy (option counts, feedback on every option, explanations,
    em-dashes) and every statistical property live in `check_quiz`, which sees the
    whole course. Duplicating them here would let the two disagree."""
    qbs = b.get("quiz_blocks")
    if qbs is None:
        return []
    if not isinstance(qbs, list):
        return [f"{HARD}brief {lid} quiz_blocks must be a list"]
    flags: list[str] = []
    for qi, qb in enumerate(qbs):
        where = f"{lid} quiz_blocks[{qi}]"
        questions = (qb or {}).get("questions") if isinstance(qb, dict) else None
        if not questions:
            flags.append(f"{HARD}brief {where} has no questions")
            continue
        seen_q: set[str] = set()
        for q in questions:
            q = q or {}
            qid = str(q.get("id", "")).strip()
            if not qid:
                flags.append(f"{HARD}brief {where} a question is missing its id")
            elif qid in seen_q:
                flags.append(f"{HARD}brief {where} duplicate question id '{qid}'")
            seen_q.add(qid)
            if not str(q.get("prompt", "")).strip():
                flags.append(f"{HARD}brief {where} q'{qid}' has no prompt")
            opts = q.get("options") or []
            if len(opts) < 2:
                flags.append(f"{HARD}brief {where} q'{qid}' needs ≥2 options "
                             f"(the authoring floor is 4 — see check_quiz)")
            oids = [str((o or {}).get("id", "")).strip() for o in opts]
            if any(not oid for oid in oids):
                flags.append(f"{HARD}brief {where} q'{qid}' has an option with no id "
                             f"(correctness is keyed to a stable id, never position)")
            if len(set(oids)) != len(oids):
                flags.append(f"{HARD}brief {where} q'{qid}' has duplicate option id(s)")
            n_correct = sum(1 for o in opts if (o or {}).get("correct") is True)
            multi = bool(q.get("multiSelect", False))
            if not multi and n_correct != 1:
                flags.append(f"{HARD}brief {where} q'{qid}' single-select must have exactly one "
                             f"correct option (has {n_correct})")
            if multi and n_correct < 1:
                flags.append(f"{HARD}brief {where} q'{qid}' multi-select needs ≥1 correct option")
    return flags


def check_quiz(m: dict) -> dict:
    """The course-wide quiz gate. Statistics and authoring policy, in one place.

    This replaces `check_quiz_distribution`, which HARD-failed ">50% of keys in one
    slot" and nothing else. That gate was satisfiable by instruction, and it was:
    `content/wave2/_briefs_emit.wf.js` told the model to seed each module's first
    answer at `mi % 3` and rotate forward. Every wave-2 course came out
    near-perfectly balanced on the marginal the gate measured, and near-perfectly
    PREDICTABLE on the sequence it did not — best order-1 Markov accuracy 85.4%,
    86.2%, 92.0%, 94.0% against 39.6% for an honest shuffle.

        THE LAW: when a statistical property must hold, COMPUTE IT IN A TOOL.
        Never ask for it in a prompt. A stronger instruction produces a different
        artifact, not randomness. Option order is assigned by
        `tools/quiz_layout.py permute`; hand-ordering is a gate failure.

    Every number here comes from `tools/quiz_metrics.py`, which is also what
    `quiz_layout.py report` prints, so the gate and the report cannot disagree.
    Severity maps straight across: metric ERROR -> HARD, metric WARN -> ADVISORY.

    A metric under its sample floor reports "INCONCLUSIVE, not passed" and names
    what it could not rule out. The old gate returned [] below n=6; that quiet pass
    is the failure mode this check exists to remove.

    Ledger asymmetry: an ABSENT layout ledger is advisory (the course simply has not
    been through `permute` yet, and the statistics above still judge it), but a
    DRIFTED or forged ledger is HARD — that is someone hand-ordering after the fact.
    """
    import quiz_metrics
    import quiz_layout

    rep = quiz_metrics.analyse(m)
    flags: list[str] = []
    for f in rep.findings:
        prefix = HARD if f.severity == quiz_metrics.ERROR else ADV
        flags.append(f"{prefix}quiz {f.metric}: {f.message}")

    if rep.questions:
        for dup in quiz_layout.check_addressing(m):
            flags.append(f"{HARD}quiz duplicate question address {dup} — question ids are not "
                         f"unique within a course, so the layout ledger is keyed on "
                         f"(courseId, lesson, block, question); this pair collides")
        problems = quiz_layout.verify(m)
        if problems and quiz_layout.LEDGER_KEY not in m:
            flags.append(f"{ADV}quiz layout: {problems[0]}")
        else:
            for p in problems:
                flags.append(f"{HARD}quiz layout: {p}")

    if not flags:
        flags.append(f"ok: {len(rep.questions)} quiz question(s), every metric clean")
    return _result("quiz", flags)


def check_quiz_files(course_dir) -> dict:
    """Quizzes ship INLINE in `lesson.yaml`. A standalone `*.quiz.yaml` lints green
    and the platform compiler silently drops it, so the lesson ships with no check
    at all — the worst possible failure, because nothing reports it."""
    from pathlib import Path as _P
    root = _P(course_dir)
    stray = sorted(p for p in root.rglob("*.quiz.yaml"))
    if not stray:
        return _result("quiz-files", ["ok: no standalone quiz files"])
    return _result("quiz-files", [
        f"{HARD}standalone quiz file {p.relative_to(root)} — quizzes are emitted INLINE as a "
        f"`type: quiz` block in lesson.yaml; a `*.quiz.yaml` lints green and is then silently "
        f"dropped by the platform compiler" for p in stray])


def check_coding_challenges(b: dict, lid: str) -> list[str]:
    """Validate a lesson brief's optional `coding_challenges` specs (references/academy-schema.md).
    Structural only — file existence is checked by check_challenges when a course dir is given.
    HARD: kebab unique id, language ∈ {rust,typescript}, buildType enum, starter/solution/tests refs."""
    ccs = b.get("coding_challenges")
    if ccs is None:
        return []
    if not isinstance(ccs, list):
        return [f"{HARD}brief {lid} coding_challenges must be a list"]
    flags: list[str] = []
    seen: set[str] = set()
    for ci, cc in enumerate(ccs):
        cc = cc or {}
        cid = str(cc.get("id", "")).strip()
        where = f"{lid} coding_challenges[{cid or ci}]"
        if not cid:
            flags.append(f"{HARD}brief {where} missing id")
        elif not ID_RE.match(cid):
            flags.append(f"{HARD}brief {where} id not kebab-case (it becomes an exercise dir name)")
        elif cid in seen:
            flags.append(f"{HARD}brief {where} duplicate challenge id")
        seen.add(cid)
        lang = cc.get("language")
        if lang not in CHALLENGE_LANGS:
            flags.append(f"{HARD}brief {where} language must be one of {sorted(CHALLENGE_LANGS)} "
                         f"(the Academy runner compiles only these): {lang!r}")
        bt = cc.get("buildType", "standard")
        if bt not in CHALLENGE_BUILD_TYPES:
            flags.append(f"{HARD}brief {where} buildType not in {sorted(CHALLENGE_BUILD_TYPES)}: {bt!r}")
        if bt == "buildable" and lang != "rust":
            flags.append(f"{ADV}brief {where} buildType 'buildable' is the Rust/Anchor mode; "
                         f"language is {lang!r}")
        for k in ("starter", "solution", "tests"):
            if not str(cc.get(k, "")).strip():
                flags.append(f"{HARD}brief {where} missing {k} file reference")
        if not cc.get("acceptance_criteria"):
            flags.append(f"{ADV}brief {where} has no acceptance_criteria")
    return flags


# ── briefs ──────────────────────────────────────────────────────────────────────

def check_briefs(m: dict) -> dict:
    flags: list[str] = []
    lessons = m.get("lessons", [])
    ids = [l["id"] for l in lessons]
    dups = sorted({x for x in ids if ids.count(x) > 1})
    if dups:
        flags.append(f"{HARD}duplicate lesson id(s): {dups}")

    if lessons:
        ordered = flatten_lessons(m)
        if ordered and ordered[0].get("brief", {}).get("dominant_job") != "motivate":
            flags.append(f"{ADV}first lesson '{ordered[0].get('id')}' is not a course opener "
                         f"(dominant_job motivate) — courses open with a welcome lesson that already puts code in the reader's hands (forms/course.md)")
    for l in lessons:
        b = l.get("brief", {})
        lid = l.get("id", "?")
        # absent / null / empty-string is "missing"; an empty LIST/DICT is allowed
        # (prerequisites=[] is legal for the first lesson; just_in_time may be {}).
        kind = b.get("kind", "build")
        if kind not in LESSON_KINDS:
            flags.append(f"{HARD}brief {lid} kind not in enum {sorted(LESSON_KINDS)}: {kind!r}")
            kind = "build"
        required = BRIEF_CORE_KEYS + (BRIEF_BUILD_KEYS if kind == "build" else [])
        missing = [k for k in required
                   if k not in b or b[k] is None or (isinstance(b[k], str) and not b[k].strip())]
        if missing:
            flags.append(f"{HARD}brief {lid} missing required key(s): {missing}")
        if not b.get("objectives"):
            flags.append(f"{HARD}brief {lid} has no objectives (need ≥1 measurable, Bloom-tagged)")

        job = b.get("dominant_job")
        if job not in DOMINANT_JOBS:
            flags.append(f"{HARD}brief {lid} dominant_job not in enum: {job!r}")
        elif job in GUEST_ONLY_JOBS:
            flags.append(f"{ADV}brief {lid} dominant_job '{job}' is a guest-only job — usually a guest, "
                         f"not a whole-lesson backbone (see lesson-brief-schema §D)")

        a = b.get("assessment", "")
        gate_txt = str(a.get("gate", "")) if isinstance(a, dict) else str(a or "")
        if not gate_txt.strip():
            flags.append(f"{HARD}brief {lid} has no assessment gate (must gate on doing)")
        elif PASSIVE_ASSESSMENT_RE.search(gate_txt) and not _has_doing_verb(gate_txt):
            flags.append(f"{HARD}brief {lid} assessment is passive (watch/read) — gate on DOING")
        if kind == "build" and not b.get("verify"):
            flags.append(f"{ADV}brief {lid} has no verify command (verify: {{command, expect}} — "
                         f"the one-line paste-and-see proof; feeds the CI smoke tier)")
        # corpus-signature blocklist (frozen; references/corpus-signatures.txt)
        import json as _json
        hay = _json.dumps({k: b.get(k) for k in ("title", "hook", "concept_spec",
                          "artifact_spec", "color")}, ensure_ascii=False).lower()
        for sig in _signatures():
            if sig in hay:
                flags.append(f"{HARD}brief {lid} carries corpus signature '{sig}' — learn the move, "
                             f"never reuse the artifact/phrase (forms/course.md §Corpus stance)")

        d = b.get("difficulty")
        if isinstance(d, int) and not (1 <= d <= 3):
            flags.append(f"{ADV}brief {lid} difficulty {d} out of 1-3")

        for obj in b.get("objectives", []):
            stmt = (obj or {}).get("statement", "").lower()
            if any(w in stmt for w in WEAK_BLOOM_VERBS):
                flags.append(f"{ADV}brief {lid} objective uses a weak verb (know/understand…): {stmt!r}")

        # est_length is the writer's length CONTRACT — a short target yields a short
        # lesson, so the rule lives here: course lessons target ~3000-4500 words.
        import re as _re
        el = str(b.get("est_length", ""))
        nums = [int(n.replace(",", "")) for n in _re.findall(r"[\d,]+", el) if n.strip(",")]
        target = max(nums) if nums else 0
        if el and target and target < LESSON_TARGET_MIN:
            flags.append(f"{ADV}brief {lid} est_length target ~{target}w is short for a course "
                         f"lesson — the writer writes to this number; course lessons run "
                         f"~{LESSON_TARGET_MIN}-4500w (forms/course.md). Raise the target.")

        # Optional Academy plugins (additive): validate their specs if present.
        # Course-wide quiz policy + statistics live in check_quiz, not here.
        flags += check_quiz_blocks(b, lid)
        flags += check_coding_challenges(b, lid)
    return _result("briefs", flags)


def _has_doing_verb(s: str) -> bool:
    return bool(re.search(
        r"\b(build|write|deploy|derive|implement|test|pass|ship|fix|run|submit|create)\b", s, re.I))


# ── ladder ──────────────────────────────────────────────────────────────────────

def check_ladder(m: dict) -> dict:
    flags: list[str] = []
    modules = m.get("modules", [])
    prev_rung = -1
    prev_band = 0
    for mod in modules:
        rung = mod.get("artifact_rung")
        if rung is None:
            flags.append(f"{ADV}module {mod['id']} has no artifact_rung")
            continue
        if rung < prev_rung:
            flags.append(f"{HARD}artifact ladder goes backward at {mod['id']} (rung {rung} < {prev_rung})")
        prev_rung = max(prev_rung, rung)
        band = mod.get("difficulty_band", prev_band)
        if band < prev_band:
            flags.append(f"{ADV}difficulty band dips at {mod['id']} ({band} < {prev_band}) — confirm a deliberate plateau")
        prev_band = band

    # cadence coverage (advisory): every lesson appears in the release schedule
    rel = (m.get("cadence", {}) or {}).get("release", {}) or {}
    sched = rel.get("schedule", [])
    if sched:
        scheduled = {lid for wk in sched for lid in wk.get("publish", [])}
        all_l = {l["id"] for l in m.get("lessons", [])}
        miss = sorted(all_l - scheduled)
        if miss:
            flags.append(f"{ADV}lessons absent from the release schedule: {miss}")
    return _result("ladder", flags)


# ── capstone ────────────────────────────────────────────────────────────────────

def check_capstone(m: dict) -> dict:
    flags: list[str] = []
    cap = (m.get("assessment", {}) or {}).get("capstone", {}) or {}
    taught = set()
    for mod in m.get("modules", []):
        taught.update(mod.get("teaches_skills", []))
    for sk in cap.get("requires_skills", []):
        if sk not in taught:
            flags.append(f"{HARD}capstone requires a skill never taught: {sk}")
    if not cap:
        flags.append(f"{ADV}no capstone defined")
    return _result("capstone", flags)


# ── outcomes ────────────────────────────────────────────────────────────────────

def check_length(m: dict) -> dict:
    """length_target.lessons must match the real lesson count (the cover renders it,
    first thing a learner reads). Prevents a stale hand-set count (the '20 lessons' bug)."""
    flags = []
    lt = m.get("course", {}).get("length_target", {})
    declared = lt.get("lessons")
    actual = len(m.get("lessons", []))
    if declared is not None and actual and declared != actual:
        flags.append(f"{HARD}length_target.lessons={declared} but the course has {actual} lessons "
                     f"— the cover states this; set it to {actual} and recompute hours")
    return _result("length", flags)


def check_outcomes(m: dict) -> dict:
    flags: list[str] = []
    course = m.get("course", {})
    outcome_ids = {o["id"] for o in course.get("terminal_outcomes", []) if "id" in o}
    proofs = (m.get("assessment", {}) or {}).get("proof_matrix", []) or []
    proven = {p.get("outcome") for p in proofs}

    for oid in sorted(outcome_ids - proven):
        flags.append(f"{HARD}terminal outcome has no proof in assessment: {oid}")
    for pid in sorted(proven - outcome_ids):
        flags.append(f"{HARD}proof_matrix references unknown outcome: {pid}")

    for mod in m.get("modules", []):
        traces = mod.get("traces_to", [])
        if not traces:
            flags.append(f"{ADV}module {mod['id']} traces to no terminal outcome")
        for t in traces:
            if t not in outcome_ids:
                flags.append(f"{HARD}module {mod['id']} traces_to unknown outcome: {t}")
    return _result("outcomes", flags)


def _signatures() -> list[str]:
    """Frozen corpus-signature blocklist (lowercased), one per line, # comments."""
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "references" / "corpus-signatures.txt"
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text("utf-8").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            out.append(s.lower())
    return out


def _parse_visuals(text: str):
    """Parse ```visual blocks. Returns (blocks, defects): blocks = [{fields, line}],
    defects = fence irregularities (closing fence carrying prose, unclosed block)."""
    lines = text.split("\n")
    blocks, defects = [], []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```visual":
            start = i + 1
            j = start
            body = []
            closed = False
            while j < len(lines):
                s = lines[j].strip()
                if s.startswith("```"):
                    closed = True
                    if s != "```":
                        defects.append(f"line {j + 1}: visual closing fence carries prose "
                                       f"({s[:50]!a}) — the insert-only pass split a sentence")
                    break
                body.append(lines[j])
                j += 1
            if not closed:
                defects.append(f"line {start}: visual block never closed")
            fields = {}
            cur = None
            for s in body:
                import re as _re
                m2 = _re.match(r"^([a-z_]+):\s*(.*)$", s)
                if m2 and not s.startswith((" ", "\t")):
                    cur = m2.group(1)
                    fields[cur] = m2.group(2).strip().lstrip("|").strip()
                elif cur is not None and s.strip():
                    fields[cur] = (fields.get(cur, "") + " " + s.strip()).strip()
            blocks.append({"fields": fields, "line": start})
            i = j + 1
        else:
            i += 1
    return blocks, defects


def draft_metrics(text: str) -> dict:
    """Deterministic per-draft metrics: prose words, longest uninterrupted prose wall
    (words + ending line), prose words before the first code / any fence, visual stats."""
    lines = text.split("\n")
    in_fence = False
    first_code = None
    first_fence = None
    prose = 0
    run = 0
    longest = 0
    longest_end = 0
    for idx, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("```"):
            if not in_fence:
                in_fence = True
                info = s[3:].strip()
                if first_fence is None:
                    first_fence = prose
                if first_code is None and info != "visual":
                    first_code = prose
                if run > longest:
                    longest, longest_end = run, idx - 1
                run = 0
            else:
                in_fence = False
            continue
        if in_fence:
            continue
        w = len(ln.split())
        prose += w
        run += w
    if run > longest:
        longest, longest_end = run, len(lines)
    blocks, defects = _parse_visuals(text)
    valid = [b for b in blocks
             if all(b["fields"].get(k, "").strip() for k in VISUAL_FIELDS)
             and b["fields"].get("type") in VISUAL_TYPES]
    return {"prose_words": prose, "longest_wall": longest, "wall_end_line": longest_end,
            "first_code_words": first_code, "first_fence_words": first_fence,
            "visual_blocks": len(blocks), "visual_valid": len(valid),
            "visual_types": sorted({b["fields"].get("type") for b in valid}),
            "visual_defects": defects,
            "visual_alts": [b["fields"].get("alt", "") for b in valid],
            "visual_titles": [b["fields"].get("title", "") for b in valid]}


# Dead-zone thresholds: calibrated against the house's own good drafts (~400w reads
# fine); the point is text-block aesthetics — long explanation is broken by the thing
# it explains — never a fixed rhythm. Deliberate plateaus survive the advisory.
WALL_ADVISORY = 450
WALL_HARD = 700
FIRST_DO_FLOOR = 300      # prose words before the first runnable fence (build lessons)
FIRST_DO_FLOOR_OPENER = 150
# Visual density scales with length: one parsing visual per ~this many prose words,
# floor of 2. A ratio, not a fixed rhythm — the point is that a long lesson earns
# more graphics, not that graphics land on a metronome. Tune the divisor to taste.
VISUAL_WORDS_PER = 600
VISUAL_FLOOR_MIN = 2


def visual_floor(prose_words: int) -> int:
    import math
    return max(VISUAL_FLOOR_MIN, math.ceil(prose_words / VISUAL_WORDS_PER))


def check_drafts(course_dir, m: dict | None = None) -> dict:
    """Written-lesson gates (forms/course.md): >=2 PARSING visual blocks per lesson;
    no prose wall past the thresholds; code in hands early; no corpus signatures."""
    from pathlib import Path
    flags: list[str] = []
    d = Path(course_dir) / "lessons" / "drafts"
    drafts = sorted(d.glob("*.md")) if d.is_dir() else []
    if not drafts:
        return _result("drafts", ["ok: no drafts yet (gates apply as lessons get written)"])

    # stem -> (kind, is_opener) from the manifest, mirroring the scaffold's naming
    import re as _re
    stem_info = {}
    if m:
        mods = {mod["id"]: i for i, mod in enumerate(m.get("modules", []))}
        flat = flatten_lessons(m)
        for i, l in enumerate(flat):
            safe = _re.sub(r"[^a-z0-9-]", "-", str(l["id"]).lower()).strip("-") or "x"
            stem = f"m{mods.get(l.get('module'), 99):02d}-l{l.get('order', 0)}-{safe}"
            stem_info[stem] = {"kind": l.get("brief", {}).get("kind", "build"),
                               "opener": i == 0}

    import re as _re2
    sigs = _signatures()
    for p in drafts:
        if not _re2.match(r"m\d+-l\d", p.stem):
            continue  # not a lesson draft (e.g. 000-cover.md) — course-level, skip
        text = p.read_text("utf-8")
        # a lesson must open on its H1 title; anything before it is leaked editor/agent
        # scaffolding ("Returning the fixed lesson:", "I've identified...") — HARD.
        _first = next((ln for ln in text.split("\n") if ln.strip()), "")
        if not _first.startswith("# "):
            flags.append(f"{HARD}draft {p.name}: does not open on its H1 title — leaked "
                         f"editor/agent scaffolding before the title; strip everything above '# '")
        mx = draft_metrics(text)
        info = stem_info.get(p.stem, {})
        kind = info.get("kind", "build")
        opener = info.get("opener", False)

        # visual floor scales with length: max(2, ceil(prose_words / VISUAL_WORDS_PER))
        floor = visual_floor(mx["prose_words"])
        if mx["visual_valid"] < floor:
            broken = mx["visual_blocks"] - mx["visual_valid"]
            extra = f" ({broken} malformed/incomplete block(s) found)" if broken else ""
            flags.append(f"{HARD}draft {p.name}: {mx['visual_valid']} valid visual block(s){extra} — "
                         f"a {mx['prose_words']}-word lesson earns >={floor} that parse "
                         f"(1 per ~{VISUAL_WORDS_PER}w, floor {VISUAL_FLOOR_MIN}; "
                         f"type/title/purpose/data/prompt/alt; references/visual-placeholders.md)")
        for defect in mx["visual_defects"]:
            flags.append(f"{HARD}draft {p.name}: {defect}")
        if mx["visual_valid"] >= 2 and len(mx["visual_types"]) < 2:
            flags.append(f"{ADV}draft {p.name}: all visuals share one type "
                         f"({mx['visual_types']}) — two blocks, one visual idea; vary the kind")
        for alt, title in zip(mx["visual_alts"], mx["visual_titles"]):
            wc = len(alt.split())
            low = alt.lower()
            if (wc < 8 or wc > 30 or low == title.lower()
                    or low.startswith(("image of", "diagram of", "visual of", "illustration of"))):
                flags.append(f"{ADV}draft {p.name}: alt text weak ({alt[:50]!a}) — one 8-30 word "
                             f"sentence that stands in for the visual, not a label")
            # The alt becomes `![<alt>](assets/….png)`. A literal ']' — which Rust attribute
            # syntax like `#[account(borsh)]` carries — closes the alt early for a regex
            # markdown parser, so upstream never sees the image reference and fails the
            # PNG as an orphan file (gate-5). Name the attribute in prose instead.
            if "]" in alt or "[" in alt:
                flags.append(f"{HARD}draft {p.name}: alt text contains a square bracket "
                             f"({alt[:60]!a}) — it truncates the ![alt](...) reference upstream "
                             f"and the image is then reported as an orphan; write it without brackets")

        # text-block aesthetics: prose walls
        if mx["longest_wall"] > WALL_HARD:
            flags.append(f"{HARD}draft {p.name}: {mx['longest_wall']}-word prose wall ending line "
                         f"{mx['wall_end_line']} — break long explanation with the thing it explains "
                         f"(a runnable fence or a visual), never past {WALL_HARD} words")
        elif mx["longest_wall"] > WALL_ADVISORY:
            flags.append(f"{ADV}draft {p.name}: {mx['longest_wall']}-word prose run ends line "
                         f"{mx['wall_end_line']} — confirm the plateau is deliberate")

        # time-to-first-do (needs the manifest to know kind/opener)
        if stem_info:
            floor = FIRST_DO_FLOOR_OPENER if opener else FIRST_DO_FLOOR
            first = mx["first_code_words"] if kind == "build" else mx["first_fence_words"]
            if first is None or first > floor:
                where = "no runnable fence at all" if first is None else f"first at word {first}"
                flags.append(f"{HARD}draft {p.name}: {where} — put a do-element in the reader's "
                             f"hands inside the first {floor} words ({'opener' if opener else kind})")

        # corpus signatures in prose
        low = text.lower()
        for sig in sigs:
            if sig in low:
                flags.append(f"{HARD}draft {p.name}: corpus signature '{sig}' — "
                             f"learn the move, never reuse it (forms/course.md §Corpus stance)")

        # setup guardrail: a tool invoked with no install step in the draft is the
        # "command not found on the happy path" class the round-2 review caught (advisory).
        _TOOLS = {"anvil": "foundryup", "forge": "foundryup", "cast": "foundryup",
                  "cargo build-sbf": "rustup", "cargo new": "rustup", "anchor ": "avm",
                  "solana ": "release.anza.xyz", "solana-keygen": "release.anza.xyz",
                  "bitcoind": "bitcoin", "npx tsx": "npm install", "ts-node": "npm install"}
        # Look for the tool as an actual COMMAND, i.e. inside a shell fence and at the start of a
        # line (allowing $/# prompts and a leading env assignment). Two false-positive classes made
        # the prose-wide substring version useless: `"forge" in text` fires on "forgets"/"forgery",
        # and even with word boundaries `cast` is ordinary English in a zero-copy course ("byte
        # cast", "castable") — it flagged 25 of 30 anchor-v2 drafts for Foundry that is never used.
        _shell = []
        _in, _lang = False, ""
        for _ln in text.split("\n"):
            _s = _ln.strip()
            if _s.startswith("```"):
                if not _in:
                    _in, _lang = True, _s[3:].strip().lower()
                else:
                    _in, _lang = False, ""
                continue
            if _in and _lang in ("bash", "sh", "shell", "console", "zsh"):
                _shell.append(_ln)
        _cmds = "\n".join(_shell).lower()
        _low = text.lower()
        for tool, installer in _TOOLS.items():
            t = re.escape(tool.strip())
            m = re.search(rf"^[ \t]*(?:[$#][ \t]*)?(?:[A-Z_]+=\S+[ \t]+)*{t}\b", _cmds, re.M)
            if m and installer.lower() not in _low:
                flags.append(f"{ADV}draft {p.name}: invokes `{tool.strip()}` but shows no install step "
                             f"(expected `{installer}` or an install line) — beginners hit command-not-found")
                break

        # em-dash policy: the top AI tell — house ships essentially none. Counts prose +
        # visual-block specs, not code fences. tools/dedash.py drives this to 0.
        em = count_prose_emdashes(text)
        if em > 2:
            flags.append(f"{HARD}draft {p.name}: {em} em-dashes outside code — the em-dash is a top "
                         f"AI tell; run tools/dedash.py (house policy: essentially none)")
        elif em >= 1:
            flags.append(f"{ADV}draft {p.name}: {em} em-dash(es) outside code — run tools/dedash.py to clear")

        # depth bands (raised again 2026-07-06: foundational topics run long).
        # Advisory only + a wide band — the right length is topic-driven, not a target.
        words = mx["prose_words"]
        if words < 2400:
            flags.append(f"{ADV}draft {p.name}: {words} prose words — foundational course lessons "
                         f"run ~3000-4500 (more for keystone topics); this reads thin")
        elif words > 5500:
            flags.append(f"{ADV}draft {p.name}: {words} prose words — past ~5500; a lesson this long "
                         f"is usually two lessons — consider splitting, don't just cut explanation")

        # paragraph rhythm: prose must breathe — paragraphs vary from a 1-sentence
        # punch to a 4+-sentence developed run; uniform staccato reads stitched.
        paras = []
        cur = []
        fence = False
        for ln in text.split("\n"):
            s = ln.strip()
            if s.startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            if not s:
                if cur:
                    paras.append(" ".join(cur))
                    cur = []
            elif not s.startswith(("#", "-", "|", ">", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
                cur.append(s)
        if cur:
            paras.append(" ".join(cur))
        import re as _re2
        counts = [len([x for x in _re2.split(r"[.?]\s", p2) if x.strip()])
                  for p2 in paras if len(p2.split()) > 10]
        if counts:
            developed = sum(1 for c in counts if c >= 4)
            if developed == 0:
                flags.append(f"{ADV}draft {p.name}: no developed paragraph (4+ sentences) across "
                             f"{len(counts)} paragraphs — prose reads stitched; vary paragraph "
                             f"length from 1-sentence punches to 4-sentence runs")
            elif sum(counts) / len(counts) < 1.8:
                flags.append(f"{ADV}draft {p.name}: mean {sum(counts)/len(counts):.1f} sentences/"
                             f"paragraph — staccato; let some paragraphs develop")
    return _result("drafts", flags)


def check_research(m: dict) -> dict:
    """Kit dispatch is literal (research-grounding.md): a verified claim must cite a
    kit surface, and every briefed lesson carries a research scaffold.

    The missing-scaffold case was advisory until 2026-09-07. Advisory meant "the
    lesson was written from the model's memory and nobody recorded where anything
    came from", which is the same class of defect as an unrunnable code block: it
    ships, it reads fine, and it is wrong. Grounding is mandatory (SKILL.md step 9,
    quality-bar.md §5), so the gate now says so."""
    flags: list[str] = []
    for l in m.get("lessons", []):
        lid = l.get("id", "?")
        r = l.get("research")
        if not r:
            flags.append(f"{HARD}lesson {lid} has no research scaffold — SKILL.md step 9 is "
                         f"per-lesson and grounding is mandatory (references/research-grounding.md)")
            continue
        for c in r.get("claims", []):
            surf = str(c.get("mcp", ""))
            if c.get("status") == "verified" and surf not in KIT_SURFACES:
                flags.append(f"{HARD}lesson {lid} claim {c.get('id', '?')}: status=verified via "
                             f"non-kit surface '{surf}' — dispatch a kit surface and record it, or "
                             f"mark the claim unverified (research-grounding.md §Dispatch is literal)")
    return _result("research", flags)


def check_artifacts(m: dict) -> dict:
    """The accretion graph: 'the toolkit becomes the bot' as a checkable DAG.
    Structured artifact edges are optional; once any lesson declares one, edges must
    run forward and non-terminal artifacts should be consumed downstream."""
    flags: list[str] = []
    flat = flatten_lessons(m)
    declared = []
    for i, l in enumerate(flat):
        art = l.get("brief", {}).get("artifact")
        if isinstance(art, dict) and art.get("id"):
            declared.append((art["id"], l["id"], i, art.get("consumes") or [], art.get("terminal")))
    if not declared:
        return _result("artifacts", ["ok: no structured artifact graph (prose artifact_spec only)"])
    pos = {}
    for aid, lid, i, cons, term in declared:
        if aid in pos:
            flags.append(f"{HARD}duplicate artifact id '{aid}' (lesson {lid})")
        pos[aid] = i
    consumed = set()
    for aid, lid, i, cons, term in declared:
        for c in cons:
            if c not in pos:
                flags.append(f"{HARD}lesson {lid} artifact '{aid}' consumes unknown artifact '{c}'")
            elif pos[c] >= i:
                flags.append(f"{HARD}lesson {lid} artifact '{aid}' consumes '{c}' built later — "
                             f"accretion runs forward only")
            else:
                consumed.add(c)
    last = max(p for p in pos.values())
    for aid, lid, i, cons, term in declared:
        if aid not in consumed and not term and i < last:
            flags.append(f"{ADV}artifact '{aid}' ({lid}) is consumed by nothing downstream — wire it "
                         f"in or flag terminal: <reason> ('the toolkit becomes the bot')")
    return _result("artifacts", flags)


def check_challenges(course_dir, m: dict | None = None) -> dict:
    """Course-dir check (like check_drafts): every coding_challenge's starter/solution/tests
    file referenced by a brief must exist on disk, and tests.json must be a non-empty array of
    cases carrying an id + expectedOutput. Mirrors the Academy 'files must be present' +
    executable-tests rules (references/academy-schema.md). File existence needs the tree, so it
    lives here rather than in check_briefs (which is manifest-only)."""
    import json as _json
    from pathlib import Path as _P
    root = _P(course_dir)
    if m is None:
        try:
            m = load_manifest(course_dir)
        except SystemExit:
            return _result("challenges", ["ok: no manifest to resolve challenge files"])
    flags: list[str] = []
    n_seen = 0
    for l in m.get("lessons", []):
        lid = l.get("id", "?")
        for cc in (l.get("brief", {}) or {}).get("coding_challenges", []) or []:
            cc = cc or {}
            cid = cc.get("id", "?")
            n_seen += 1
            for k in ("starter", "solution", "tests"):
                rel = str(cc.get(k, "")).strip()
                if not rel:
                    continue  # missing ref already HARD in check_coding_challenges
                p = root / rel
                if not p.is_file():
                    flags.append(f"{HARD}challenge {lid}/{cid}: {k} file not found: {rel}")
                elif k == "tests":
                    try:
                        data = _json.loads(p.read_text("utf-8"))
                    except Exception as e:
                        flags.append(f"{HARD}challenge {lid}/{cid}: tests.json is not valid JSON ({e})")
                        continue
                    if not isinstance(data, list) or not data:
                        flags.append(f"{HARD}challenge {lid}/{cid}: tests.json must be a non-empty array")
                    elif any(("id" not in t or "expectedOutput" not in t) for t in data):
                        flags.append(f"{HARD}challenge {lid}/{cid}: every test case needs id + expectedOutput")
    if not flags:
        return _result("challenges", [f"ok: {n_seen} coding challenge(s), all files present" if n_seen
                                      else "ok: no coding challenges"])
    return _result("challenges", flags)


CHECKS = {"dag": check_dag, "briefs": check_briefs, "quiz": check_quiz, "ladder": check_ladder,
          "capstone": check_capstone, "outcomes": check_outcomes,
          "research": check_research, "artifacts": check_artifacts, "length": check_length}


# ── runner ──────────────────────────────────────────────────────────────────────

def _print(res: dict) -> None:
    mark = "FAIL" if res["hard"] else "ok"
    print(f"[{mark}] {res['name']}")
    for f in res["flags"]:
        print("   - " + f)


def run(m: dict, names: list[str]) -> int:
    any_hard = False
    for n in names:
        res = CHECKS[n](m)
        _print(res)
        any_hard = any_hard or res["hard"]
    print(f"\nGATE: {'FAIL (hard)' if any_hard else 'PASS'}")
    return 1 if any_hard else 0


def _good_manifest() -> dict:
    return {
        "schema_version": 1,
        "course": {
            "id": "demo", "title": "Demo",
            "terminal_outcomes": [{"id": "to-pda", "bloom": "create", "statement": "build a PDA app"}],
        },
        "dag": {"nodes": ["account-model", "programs-instructions", "pdas"],
                "edges": [["account-model", "programs-instructions"],
                          ["programs-instructions", "pdas"], ["account-model", "pdas"]]},
        "modules": [
            {"id": "m-accounts", "artifact_rung": 1, "difficulty_band": 1,
             "teaches_skills": ["account-model", "programs-instructions"],
             "requires_skills": [], "traces_to": ["to-pda"]},
            {"id": "m-pdas", "artifact_rung": 3, "difficulty_band": 2,
             "depends_on": ["m-accounts"], "teaches_skills": ["pdas"],
             "requires_skills": ["account-model"], "traces_to": ["to-pda"]},
        ],
        "lessons": [
            {"id": "the-counter", "module": "m-accounts", "order": 1, "brief": {
                "id": "the-counter", "title": "The counter",
                "objectives": [{"bloom": "implement", "statement": "write account state"}],
                "prerequisites": [], "hook": "h", "concept_spec": "c", "artifact_spec": "a",
                "exercise_spec": "e", "the_tradeoff": "t", "just_in_time": {"define": [], "footguns": []},
                "assessment": "anchor test passes", "difficulty": 1, "fading": "worked",
                "dominant_job": "show-how"}},
            {"id": "pda-state", "module": "m-pdas", "order": 1, "brief": {
                "id": "pda-state", "title": "PDA state",
                "objectives": [{"bloom": "implement", "statement": "derive a PDA"}],
                "prerequisites": ["the-counter", "account-model"], "hook": "h", "concept_spec": "c",
                "artifact_spec": "a", "exercise_spec": "e", "the_tradeoff": "t",
                "just_in_time": {"define": [], "footguns": []},
                "assessment": "test: two users get distinct PDAs", "difficulty": 2,
                "fading": "completion", "dominant_job": "derive-why"}},
        ],
        "assessment": {
            "proof_matrix": [{"outcome": "to-pda", "proven_by": "capstone"}],
            "capstone": {"id": "cap", "requires_skills": ["pdas", "account-model"]},
        },
        "cadence": {"release": {"schedule": [{"week": 1, "publish": ["the-counter", "pda-state"]}]}},
    }


def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    g = _good_manifest()
    check(not check_dag(g)["hard"], "good course: dag clean")
    check(not check_briefs(g)["hard"], "good course: briefs clean")

    # concept lesson: no build triad required, but bad kind is HARD
    import copy
    gc = copy.deepcopy(g)
    gc["lessons"][1]["brief"].update({"kind": "concept"})
    for k in ("artifact_spec", "exercise_spec", "fading"):
        gc["lessons"][1]["brief"].pop(k, None)
    check(not check_briefs(gc)["hard"], "concept lesson: build triad not required")
    gc["lessons"][1]["brief"]["kind"] = "video"
    check(any("kind not in enum" in f for f in check_briefs(gc)["flags"]),
          "bad kind is HARD")

    # non-kebab ids are HARD (they become filesystem paths)
    gi = copy.deepcopy(g)
    gi["modules"][0]["id"] = "../Evil Module"
    check(any("not kebab-case" in f for f in check_dag(gi)["flags"]),
          "non-kebab module id is HARD")
    check(not check_ladder(g)["hard"], "good course: ladder clean")
    check(not check_capstone(g)["hard"], "good course: capstone clean")
    check(not check_outcomes(g)["hard"], "good course: outcomes clean")

    # cycle
    c = _good_manifest()
    c["dag"]["edges"].append(["pdas", "account-model"])
    check(check_dag(c)["hard"], "cycle -> dag HARD")

    # forward dependency (lesson requires a later lesson)
    f = _good_manifest()
    f["lessons"][0]["brief"]["prerequisites"] = ["pda-state"]
    check(check_dag(f)["hard"], "forward lesson dep -> dag HARD")

    # dangling prerequisite
    d = _good_manifest()
    d["lessons"][1]["brief"]["prerequisites"] = ["ghost-lesson"]
    check(check_dag(d)["hard"], "dangling prereq -> dag HARD")

    # unknown skill node on a module
    u = _good_manifest()
    u["modules"][0]["teaches_skills"].append("ghost-skill")
    check(check_dag(u)["hard"], "unknown skill node -> dag HARD")

    # bad dominant_job enum
    j = _good_manifest()
    j["lessons"][0]["brief"]["dominant_job"] = "explain"
    check(check_briefs(j)["hard"], "bad dominant_job -> briefs HARD")

    # guest-only job as backbone -> advisory, not hard
    gj = _good_manifest()
    gj["lessons"][0]["brief"]["dominant_job"] = "frame"
    rj = check_briefs(gj)
    check(not rj["hard"] and any("guest-only" in x for x in rj["flags"]), "guest job as backbone -> advisory")

    # missing required brief key
    mk = _good_manifest()
    del mk["lessons"][0]["brief"]["hook"]
    check(check_briefs(mk)["hard"], "missing brief key -> briefs HARD")

    # passive assessment
    pa = _good_manifest()
    pa["lessons"][0]["brief"]["assessment"] = "watch the video walkthrough"
    check(check_briefs(pa)["hard"], "passive assessment -> briefs HARD")

    # duplicate lesson id
    dl = _good_manifest()
    dl["lessons"][1]["id"] = "the-counter"
    check(check_briefs(dl)["hard"], "duplicate lesson id -> briefs HARD")

    # ladder goes backward
    lb = _good_manifest()
    lb["modules"][1]["artifact_rung"] = 0
    check(check_ladder(lb)["hard"], "backward artifact rung -> ladder HARD")

    # capstone needs an untaught skill
    cs = _good_manifest()
    cs["assessment"]["capstone"]["requires_skills"] = ["cpis"]
    check(check_capstone(cs)["hard"], "untaught capstone skill -> capstone HARD")

    # orphan outcome
    oo = _good_manifest()
    oo["assessment"]["proof_matrix"] = []
    check(check_outcomes(oo)["hard"], "orphan outcome -> outcomes HARD")

    # module traces to unknown outcome
    mt = _good_manifest()
    mt["modules"][0]["traces_to"] = ["to-ghost"]
    check(check_outcomes(mt)["hard"], "module traces to unknown outcome -> outcomes HARD")

    # length_target.lessons must match actual count
    lc = _good_manifest(); lc["course"]["length_target"] = {"lessons": 99}
    check(check_length(lc)["hard"], "wrong length_target.lessons -> length HARD")

    # drafts visual floor
    import tempfile
    from pathlib import Path as _P
    with tempfile.TemporaryDirectory() as td:
        dd = _P(td) / "lessons" / "drafts"
        dd.mkdir(parents=True)
        VB = ("```visual\ntype: diagram\ntitle: t one\npurpose: p\ndata: d\nprompt: pr\n"
              "alt: a full sentence of at least eight words standing in\n```\n")
        VB2 = VB.replace("type: diagram", "type: chart").replace("t one", "t two")
        # ~640 prose words -> floor 2; two valid visuals must pass
        prose = ("word " * 80 + "\n\n```bash\nrun\n```\n\n") * 8   # fences break walls, early code
        (dd / "m00-l1-x.md").write_text("# T\n\n" + prose + VB, "utf-8")
        check(check_drafts(td)["hard"], "draft with 1 valid visual -> drafts HARD")
        (dd / "m00-l1-x.md").write_text("# T\n\n" + prose + VB + VB2, "utf-8")
        check(not check_drafts(td)["hard"], "draft with 2 valid visuals -> drafts clean")
        # empty visual blocks don't count toward the floor
        (dd / "m00-l1-x.md").write_text("# T\n\n" + prose + "```visual\n```\n```visual\n```\n", "utf-8")
        check(check_drafts(td)["hard"], "empty visual blocks don't satisfy the floor")
        # glued closing fence is a defect
        (dd / "m00-l1-x.md").write_text("# T\n\n" + prose + VB + VB2.replace("```\n", "``` glued prose\n", 1)
                                        .replace("```visual``` glued prose", "```visual"), "utf-8")
        # (rebuild simpler: valid + one glued block)
        glued = "```visual\ntype: chart\ntitle: t\npurpose: p\ndata: d\nprompt: pr\nalt: a full sentence of at least eight words here\n``` glued prose\n"
        (dd / "m00-l1-x.md").write_text("# T\n\n" + prose + VB + VB2 + glued, "utf-8")
        check(any("carries prose" in f for f in check_drafts(td)["flags"]),
              "glued closing fence flagged")
        (dd / "m00-l1-x.md").write_text("Returning the fixed lesson:\n\n# T\n\n" + prose + VB + VB2, "utf-8")
        check(any("H1 title" in f for f in check_drafts(td)["flags"]),
              "scaffolding before the H1 title -> drafts HARD")
        # prose wall past the hard cap
        (dd / "m00-l1-x.md").write_text("# T\n\n```bash\nrun\n```\n" + "word " * 720 + "\n" + VB + VB2, "utf-8")
        check(any("prose wall" in f for f in check_drafts(td)["flags"]),
              "700+ word prose wall -> drafts HARD")

    # research: a missing scaffold is HARD (promoted 2026-09-07 — grounding is mandatory)
    rg = _good_manifest()
    check(any("no research scaffold" in f for f in check_research(rg)["flags"])
          and check_research(rg)["hard"], "lesson with no research scaffold -> research HARD")
    for _l in rg["lessons"]:
        _l["research"] = {"claims": []}
    check(not check_research(rg)["hard"], "every lesson scaffolded -> research clean")
    # verified claim via non-kit surface
    rg["lessons"][0]["research"] = {"claims": [
        {"id": "C1", "mcp": "canonical-record", "status": "verified"}]}
    check(check_research(rg)["hard"], "verified claim via non-kit surface -> research HARD")
    rg["lessons"][0]["research"]["claims"][0]["mcp"] = "solana-researcher"
    check(not check_research(rg)["hard"], "kit surface -> research clean")

    # artifacts: forward consumption
    ag = _good_manifest()
    ag["lessons"][0]["brief"]["artifact"] = {"id": "tool-a", "consumes": ["tool-b"]}
    ag["lessons"][1]["brief"]["artifact"] = {"id": "tool-b", "consumes": []}
    check(check_artifacts(ag)["hard"], "artifact consuming a later artifact -> artifacts HARD")
    ag["lessons"][0]["brief"]["artifact"] = {"id": "tool-a", "consumes": []}
    ag["lessons"][1]["brief"]["artifact"] = {"id": "tool-b", "consumes": ["tool-a"]}
    check(not check_artifacts(ag)["hard"], "forward accretion graph -> artifacts clean")

    # corpus signature in a brief
    cg = _good_manifest()
    cg["lessons"][0]["brief"]["artifact_spec"] = "build a Restaurant Review app"
    check(any("corpus signature" in f for f in check_briefs(cg)["flags"]),
          "corpus signature in brief -> HARD")

    # short est_length target flags (the length rule)
    sl = _good_manifest()
    sl["lessons"][0]["brief"]["est_length"] = "1400 words / ~12 min"
    check(any("est_length target" in f for f in check_briefs(sl)["flags"]),
          "short est_length target -> briefs advisory")
    sl["lessons"][0]["brief"]["est_length"] = "3500-4500 words / ~32 min"
    check(not any("est_length target" in f for f in check_briefs(sl)["flags"]),
          "on-band est_length -> clean")

    # (cover is index-only; no course.overview narrative is rendered or required)

    # ── academy plugins: quiz_blocks + coding_challenges (optional, additive) ──
    # a good quiz block keeps briefs clean
    qg = _good_manifest()
    qg["lessons"][0]["brief"]["quiz_blocks"] = [{"questions": [
        {"id": "q1", "prompt": "Base unit of SOL?", "multiSelect": False,
         "options": [{"id": "o1", "label": "Gwei", "correct": False, "feedback": "Ethereum's."},
                     {"id": "o2", "label": "Lamport", "correct": True, "feedback": "Right."},
                     {"id": "o3", "label": "Satoshi", "correct": False, "feedback": "Bitcoin's."},
                     {"id": "o4", "label": "Wei", "correct": False, "feedback": "Ethereum's."}],
         "explanation": "One SOL is 1e9 lamports."}]}]
    check(not check_briefs(qg)["hard"], "good quiz_blocks -> briefs clean")
    # single-select with two correct is HARD
    q2 = copy.deepcopy(qg)
    q2["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"][0]["correct"] = True
    check(any("exactly one correct" in f for f in check_briefs(q2)["flags"]),
          "single-select with two correct -> briefs HARD")
    # a missing option id is HARD (correctness keyed to id)
    q3 = copy.deepcopy(qg)
    q3["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"][0].pop("id")
    check(check_briefs(q3)["hard"], "quiz option with no id -> briefs HARD")
    # course-wide policy is check_quiz's job, never check_briefs'
    check(not any("option" in f and "4" in f for f in check_briefs(qg)["flags"]),
          "check_briefs no longer duplicates the course-wide option-count policy")

    # ── the three quiz regression fixtures (the point of this whole workstream) ──
    # A shared question factory: 5 options, parallel labels whose LENGTH does not
    # depend on which one is correct, feedback everywhere, an explanation.
    import hashlib as _hl

    def _qz(qid, correct_at, k=5):
        base = ("the runtime charges rent-exempt lamports against the payer at creation "
                "and refunds them when the account closes")
        opts = []
        for i in range(k):
            n = 76 + int(_hl.sha256(f"{qid}|{i}".encode()).hexdigest(), 16) % 34
            opts.append({"id": f"o{i + 1}", "label": base[:n], "correct": i == correct_at,
                         "feedback": "why this option lands where it does"})
        return {"id": qid, "prompt": f"{qid}: which account pays the rent here?",
                "multiSelect": False, "options": opts,
                "explanation": "a paragraph that teaches the point after answering"}

    def _course_with(seq):
        """A 2-module manifest carrying `seq` as its single-select key positions."""
        mm = _good_manifest()
        per = 3
        blocks = [[], []]
        for i, pos in enumerate(seq):
            blocks[(i // per) % 2].append(_qz(f"q{i}", pos))
        for li in (0, 1):
            mm["lessons"][li]["brief"]["quiz_blocks"] = [{"key": "check", "questions": blocks[li]}]
            mm["lessons"][li]["research"] = {"claims": []}
        return mm

    ROT = [i % 3 for i in range(60)]        # the exact `mi % 3` artifact that shipped
    ONE = [0] * 60                          # the all-'A' failure the old gate was built for
    HASH = [int(_hl.sha256(f"fx|{i}".encode()).hexdigest(), 16) % 5 for i in range(60)]

    rot = check_quiz(_course_with(ROT))
    check(rot["hard"], "FIXTURE 1: a perfect a->b->c rotation -> quiz HARD")
    check(any("sequence" in f and f.startswith(HARD) for f in rot["flags"]),
          "FIXTURE 1: it fails on sequential exploitability (the old gate PASSED it)")
    one = check_quiz(_course_with(ONE))
    check(one["hard"], "FIXTURE 2: an all-one-slot sequence -> quiz HARD")
    check(any("marginal" in f and f.startswith(HARD) for f in one["flags"]),
          "FIXTURE 2: it fails on the marginal")
    hsh = check_quiz(_course_with(HASH))
    check(not hsh["hard"], "FIXTURE 3: a hash-balanced sequence -> quiz clean\n     "
          + "\n     ".join(f for f in hsh["flags"] if f.startswith(HARD)))

    # promotions to HARD (all four were advisory or absent before 2026-09-07)
    lg = _course_with(HASH)
    for blk in (lg["lessons"][0]["brief"]["quiz_blocks"][0]["questions"]
                + lg["lessons"][1]["brief"]["quiz_blocks"][0]["questions"]):
        for o in blk["options"]:
            if o["correct"]:
                o["label"] = o["label"] + " and a further clarifying clause that runs on"
            else:
                o["label"] = o["label"][:70]
    check(any("longest-correct" in f and f.startswith(HARD) for f in check_quiz(lg)["flags"]),
          "correct-is-longest -> HARD (was advisory; 4 courses shipped at 91-97% with GATE: PASS)")
    nf = _course_with(HASH)
    nf["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"][0].pop("feedback")
    check(any("quiz feedback" in f and f.startswith(HARD) for f in check_quiz(nf)["flags"]),
          "an option with no feedback -> HARD (every option, correct one included)")
    ne = _course_with(HASH)
    ne["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0].pop("explanation")
    check(any("quiz explanation" in f and f.startswith(HARD) for f in check_quiz(ne)["flags"]),
          "a question with no explanation -> HARD")
    fo = _course_with(HASH)
    for q in fo["lessons"][0]["brief"]["quiz_blocks"][0]["questions"]:
        q["options"] = q["options"][:3]
    check(any("option-count" in f and f.startswith(HARD) for f in check_quiz(fo)["flags"]),
          "fewer than 4 options -> HARD")
    ed = _course_with(HASH)
    ed["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["prompt"] = "an — em-dash"
    check(any("em-dash" in f and f.startswith(HARD) for f in check_quiz(ed)["flags"]),
          "an em-dash in quiz text -> HARD (794 ship across six courses today)")

    # the small-sample rule: under the floor a metric says so, it never passes quietly
    tiny = _good_manifest()
    tiny["lessons"][0]["brief"]["quiz_blocks"] = [{"key": "check",
                                                   "questions": [_qz("q1", 0), _qz("q2", 0)]}]
    tf = check_quiz(tiny)["flags"]
    check(any("INCONCLUSIVE, not passed" in f for f in tf),
          "under the sample floor -> INCONCLUSIVE, not a silent pass (the old gate returned [])")
    check(all("Cannot rule out:" in f for f in tf if "INCONCLUSIVE" in f),
          "each INCONCLUSIVE names what it could not rule out")

    # the layout ledger: absent is advisory, drifted is HARD
    import quiz_layout as _ql
    lm = _course_with(HASH)
    check(any("layout" in f and f.startswith(ADV) for f in check_quiz(lm)["flags"]),
          "no layout ledger -> advisory (the course has not been permuted yet)")
    _ql.permute(lm, "fixture-salt")
    check(not any("layout" in f for f in check_quiz(lm)["flags"]),
          "after permute the ledger verifies clean")
    lm["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"].reverse()
    check(any("layout" in f and f.startswith(HARD) for f in check_quiz(lm)["flags"]),
          "hand-ordering after the permute -> HARD")

    # standalone *.quiz.yaml is HARD (lints green, then the compiler drops it)
    with tempfile.TemporaryDirectory() as tq:
        check(not check_quiz_files(tq)["hard"], "no standalone quiz files -> clean")
        qd = _P(tq) / "lessons" / "intro"
        qd.mkdir(parents=True)
        (qd / "check.quiz.yaml").write_text("questions: []\n", "utf-8")
        check(check_quiz_files(tq)["hard"], "a standalone *.quiz.yaml -> quiz-files HARD")

    # a good coding_challenge SPEC keeps briefs clean (file existence checked separately)
    cg2 = _good_manifest()
    cg2["lessons"][0]["brief"]["coding_challenges"] = [{
        "id": "add-two", "language": "rust", "buildType": "standard",
        "starter": "lessons/challenges/the-counter/add-two/starter.rs",
        "solution": "lessons/challenges/the-counter/add-two/solution.rs",
        "tests": "lessons/challenges/the-counter/add-two/tests.json",
        "acceptance_criteria": ["adds two ints"]}]
    check(not check_briefs(cg2)["hard"], "good coding_challenge spec -> briefs clean")
    # bad language is HARD
    cb = copy.deepcopy(cg2)
    cb["lessons"][0]["brief"]["coding_challenges"][0]["language"] = "python"
    check(any("language must be one of" in f for f in check_briefs(cb)["flags"]),
          "coding_challenge language not rust/typescript -> briefs HARD")

    # check_challenges: missing files HARD, present files clean
    with tempfile.TemporaryDirectory() as td2:
        root = _P(td2)
        # manifest with one challenge referencing files under the course dir
        cm = _good_manifest()
        cm["lessons"][0]["brief"]["coding_challenges"] = cg2["lessons"][0]["brief"]["coding_challenges"]
        check(check_challenges(td2, cm)["hard"], "challenge with missing files -> challenges HARD")
        exdir = root / "lessons" / "challenges" / "the-counter" / "add-two"
        exdir.mkdir(parents=True)
        (exdir / "starter.rs").write_text("fn add(a:i64,b:i64)->i64{0}\n", "utf-8")
        (exdir / "solution.rs").write_text("fn add(a:i64,b:i64)->i64{a+b}\n", "utf-8")
        (exdir / "tests.json").write_text('[{"id":"t1","input":"2, 3","expectedOutput":"5"}]', "utf-8")
        check(not check_challenges(td2, cm)["hard"], "challenge with present files -> challenges clean")
        # a tests.json that isn't a non-empty array is HARD
        (exdir / "tests.json").write_text('[]', "utf-8")
        check(check_challenges(td2, cm)["hard"], "empty tests.json array -> challenges HARD")

    print("\n" + ("VALIDATOR SELFTESTS PASSED" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="content-gen validator")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in list(CHECKS) + ["drafts", "challenges", "all"]:
        p = sub.add_parser(name)
        p.add_argument("--course", help="course directory (reads manifest.json)")
        p.add_argument("--manifest", help="manifest.json path")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.print_help()
        return 2
    src = getattr(a, "course", None) or getattr(a, "manifest", None)
    if not src:
        print("course: pass --course <dir> or --manifest <file>", file=sys.stderr)
        return 2
    m = load_manifest(src)
    names = list(CHECKS) if a.cmd == "all" else ([] if a.cmd in ("drafts", "challenges") else [a.cmd])
    any_hard = False
    for n in names:
        res = CHECKS[n](m)
        _print(res)
        any_hard = any_hard or res["hard"]
    course_dir = getattr(a, "course", None)
    if course_dir and a.cmd in ("quiz", "all"):
        res = check_quiz_files(course_dir)
        _print(res)
        any_hard = any_hard or res["hard"]
    if course_dir and a.cmd in ("drafts", "all"):
        res = check_drafts(course_dir, m)
        _print(res)
        any_hard = any_hard or res["hard"]
    if course_dir and a.cmd in ("challenges", "all"):
        res = check_challenges(course_dir, m)
        _print(res)
        any_hard = any_hard or res["hard"]
    print(f"\nGATE: {'FAIL (hard)' if any_hard else 'PASS'}")
    return 1 if any_hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
