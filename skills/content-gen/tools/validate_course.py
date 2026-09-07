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
  freshness per-claim expiry: verified_on present, nothing past its TTL, volatile kinds
            carry a runnable `recheck` probe (see method/fact-recheck.md)
  continuity  the reader's tree: nothing opened before it exists, no symbol that
              changes shape mid-course, no old name surviving a declared rename
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
    SYMBOL_KINDS, SYMBOL_RE, LEDGER_LEGACY_KEYS,
    load_manifest, flatten_lessons, topo_sort, course_ledgers,
    CLAIM_KINDS, RECHECK_REQUIRED_KINDS, RECHECK_ADVISORY_KINDS, TTL_DAYS,
    claim_freshness, claim_ttl, course_ttl_policy, parse_iso_date, today,
    undated_deadline, FRESHNESS_EPOCH,
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

        sk = b.get("skills")
        if sk is not None and (not isinstance(sk, list)
                               or any(not isinstance(x, str) or not x.strip() for x in sk)):
            flags.append(f"{HARD}brief {lid} skills must be a list of non-empty strings "
                         f"(DAG skill nodes or academy skill slugs): {sk!r}")

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

    flags += _skill_tag_advisory(m)
    return _result("briefs", flags)


# A module's lessons are allowed to share tags; a whole module sharing ONE array is the
# signature of nobody having set them. Floor of 3 because a 2-lesson module is a single
# pair — no signal, and the house rule is that a metric under its sample floor says so
# rather than firing anyway.
SKILL_TAG_IDENTICAL_MAX = 0.8
SKILL_TAG_MIN_LESSONS = 3


def _skill_tag_advisory(m: dict) -> list[str]:
    """ADVISORY when >80% of a module's lessons carry byte-identical skill tags.

    A lesson's `skills` are learner-facing: the Academy renders them as the labels on the
    lesson card. They used to be derived from `mod['teaches_skills']` alone, which made
    every lesson in a module identical BY CONSTRUCTION — measured at 79/79 modules across
    the ten shipped courses, and filed as an audit major when a 31-lesson Rust/TS/Docker
    course tagged its Docker-install lesson with a slug reading "Program Development".

    The tags are computed by importing `academy_export._skills_for`, the same function the
    export calls, so this gate and the emitted YAML can never disagree about what a lesson
    is tagged with. Setting `skills:` on the briefs is what clears the flag."""
    lessons = m.get("lessons", [])
    modules = m.get("modules", [])
    if not lessons or not modules:
        return []
    try:
        from academy_export import _academy_cfg, _skills_for
    except Exception:                                             # noqa: BLE001
        return []
    cfg = _academy_cfg(m, {})
    by_mod: dict[str, dict] = {mod["id"]: mod for mod in modules if "id" in mod}
    groups: dict[str, list[tuple]] = {}
    for l in lessons:
        mid = l.get("module")
        if mid not in by_mod:
            continue
        groups.setdefault(mid, []).append(
            tuple(_skills_for(l.get("brief", {}) or {}, by_mod[mid], cfg)))
    flags = []
    for mid, tags in groups.items():
        if len(tags) < SKILL_TAG_MIN_LESSONS:
            continue
        top = max(set(tags), key=tags.count)
        n = tags.count(top)
        if n / len(tags) > SKILL_TAG_IDENTICAL_MAX:
            flags.append(f"{ADV}module {mid}: {n} of {len(tags)} lessons carry byte-identical "
                         f"skill tags {list(top) or '[]'} — the signature of tags nobody set "
                         f"per lesson (they are derived from the MODULE unless a brief sets "
                         f"`skills:`). A lesson's tags name what THAT lesson teaches "
                         f"(lesson-brief-schema §C; quality-bar JUDGE row).")
    return flags


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


def check_freshness(m: dict, as_of=None) -> dict:
    """Per-claim expiry: the publish-time gate on facts that were true when written.

    `check_research` proves a claim was grounded ONCE. Nothing proved it was still true
    the day it shipped, and an audit of five generated courses found six defects that were
    all that same hole: rent constants matching no live cluster, a rent mechanism the
    runtime now rejects, a dead API taught as live, an archived repo called "the living
    reference". Every one was verified once and then trusted forever.

    HARD
      - status verified with no obtainable date  (after the backfill window closes)
      - any live claim past its TTL              ← forces a re-probe, not a silent re-ship
      - onchain-number / cli-default / protocol-param / version-pin with no `recheck`,
        because an un-runnable probe is not a probe
      - a per-claim `ttl_days` that LENGTHENS its kind default, or an unknown `kind`
    ADVISORY
      - past 0.75x TTL (schedule the re-probe before it ambushes a publish)
      - no `kind` (the claim inherits the volatile 30-day default)
      - an api/number claim citing a URL with no `recheck` (a cited URL is a free probe,
        and defect #4 was a cited URL that stopped resolving)
      - a research scaffold with frozen_facts and zero claims — the gate is SILENT there
        because nothing is declared, not because the facts are fresh. Eight of the ten
        courses in the corpus are in exactly that state.

    Dates and TTLs come from course_lib so this and `fact_freshness.py stale` and
    `academy_export.py` can never disagree about what "stale" means.
    """
    flags: list[str] = []
    as_of = as_of or today()
    deadline = undated_deadline()
    backfill_open = as_of < deadline
    pol = course_ttl_policy(m)
    if pol["declared"] and pol["days"] and pol["days"] > TTL_DAYS["onchain-number"]:
        flags.append(f"{ADV}cadence.release.freshness_policy asks for "
                     f"{pol['declared']}d on on-chain numbers but the kind default is "
                     f"{TTL_DAYS['onchain-number']}d — a policy may only shorten, so the "
                     f"default applies (course_lib.TTL_DAYS)")
    n_claims = 0
    for l in m.get("lessons", []) or []:
        lid = l.get("id", "?")
        r = l.get("research") or {}
        claims = [c for c in (r.get("claims") or []) if isinstance(c, dict)]
        if r and not claims and r.get("frozen_facts"):
            flags.append(f"{ADV}lesson {lid}: research scaffold declares "
                         f"{len(r['frozen_facts'])} frozen_fact(s) and ZERO claims — nothing "
                         f"here is on any expiry clock; promote the volatile ones to claims[]")
        for c in claims:
            n_claims += 1
            cid = c.get("id", "?")
            f = claim_freshness(c, as_of, policy=pol, lesson_id=lid)
            where = f"lesson {lid} claim {cid}"

            kind = c.get("kind")
            if kind is None:
                flags.append(f"{ADV}{where}: no kind — it inherits the volatile "
                             f"{f['ttl']}-day default; declare one of {sorted(CLAIM_KINDS)}")
            elif kind not in CLAIM_KINDS:
                flags.append(f"{HARD}{where}: unknown kind '{kind}' — the vocabulary is "
                             f"closed ({sorted(CLAIM_KINDS)})")

            own = c.get("ttl_days")
            if isinstance(own, int) and own > f["kind_ttl"]:
                flags.append(f"{HARD}{where}: ttl_days={own} lengthens the {kind} default of "
                             f"{f['kind_ttl']}d — a claim may only SHORTEN its kind's TTL")

            if f["provenance"] == "malformed":
                flags.append(f"{HARD}{where}: verified_on={c.get('verified_on')!r} is not an "
                             f"ISO YYYY-MM-DD date")
            elif f["live"] and f["undated"]:
                msg = (f"{where}: status={f['status']} with no verified_on and no dispatch date "
                       f"in evidence — 'verified' with no date is a mood, not a measurement")
                flags.append((f"{ADV}{msg}; backfill or re-probe before {deadline.isoformat()}"
                              if backfill_open else f"{HARD}{msg}"))

            if f["live"] and f["state"] == "stale":
                flags.append(f"{HARD}{where}: last verified {f['verified_on'] or 'never'} — "
                             f"{f['age_days']}d old against a {f['ttl']}d TTL for kind "
                             f"'{kind or 'unset'}'. Re-probe (fact_freshness.py probes) and "
                             f"update verified_on; do not re-ship it unread")
            elif f["live"] and f["state"] == "aging":
                flags.append(f"{ADV}{where}: {f['age_days']}d of a {f['ttl']}d TTL used — "
                             f"expires {f['days_left']}d from now; schedule the re-probe")

            if not f["recheck"]:
                if kind in RECHECK_REQUIRED_KINDS:
                    flags.append(f"{HARD}{where}: kind '{kind}' with no `recheck` — this value "
                                 f"is read off a machine, so record the exact re-runnable probe "
                                 f"(an RPC call, a curl, a --version), not prose")
                elif kind in RECHECK_ADVISORY_KINDS and f["urls"]:
                    flags.append(f"{ADV}{where}: cites {f['urls'][0]} and carries no `recheck` — "
                                 f"a cited URL is a free probe, and a cited URL that stopped "
                                 f"resolving is exactly how a dead API shipped as live")

    if not flags:
        return _result("freshness", [f"ok: {n_claims} claim(s), none past TTL as of "
                                     f"{as_of.isoformat()}"])
    return _result("freshness", flags)


def check_artifacts(m: dict) -> dict:
    """The accretion graph: 'the toolkit becomes the bot' as a checkable DAG.

    This is a VIEW over the continuity ledger, not a second system: it reads the
    `artifact:`-kind symbols out of `course_ledgers(m)`, which is where
    `brief.artifact.{id,consumes}` and `brief.ledger.{provides,consumes}` both land.
    One graph means a course can declare its ladder in either shape (or both) and
    the two checks can never disagree about what was built when."""
    flags: list[str] = []
    leds = course_ledgers(m)
    declared = []
    for i, led in enumerate(leds):
        for p in led["provides"]:
            if p["kind"] == "artifact":
                cons = [c["name"] for c in led["consumes"] if c["kind"] == "artifact"]
                declared.append((p["name"], led["lesson"], i, cons, p["terminal"]))
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


# ── continuity ─────────────────────────────────────────────────────────────────

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "is", "are", "was",
         "with", "that", "this", "it", "its", "for", "from", "you", "your", "has", "have",
         "one", "two", "but", "not", "now", "still", "only", "just", "already", "plus",
         "com", "para", "que", "uma", "seu", "sua", "dos", "das", "por", "como", "mas"}


def _tokens(s: str) -> set:
    return {t for t in re.split(r"[^a-z0-9_./-]+", s.lower()) if len(t) >= 3 and t not in _STOP}


def _norm_path(p: str) -> str:
    p = str(p).strip().strip("`").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def _path_covered(p: str, emitted: set) -> bool:
    """Is `p` satisfied by something already in the reader's tree?

    Directory-tolerant in BOTH directions on purpose: `cd toolkit/vault` is covered by
    an earlier `emits: toolkit/vault/Anchor.toml`, and `opens: src/lib.rs` is covered by
    an earlier `emits: src/`. Being generous here costs a missed flag; being strict
    would manufacture a HARD failure on every correctly-built course that named a
    directory instead of a file."""
    if p in emitted:
        return True
    return any(e.startswith(p + "/") or p.startswith(e + "/") for e in emitted)


def _rename_key(s: str) -> tuple:
    """(kind_or_None, name) for a rename side. The kind prefix is optional here --
    a rename reads naturally as `init_vault -> initialize`, and forcing `fn:` on both
    sides buys nothing the name alone does not already identify."""
    s = str(s or "").strip()
    m = SYMBOL_RE.match(s)
    if m and m.group(1) in SYMBOL_KINDS:
        return (m.group(1), m.group(2).strip())
    return (None, s)


def _matches_rename(sym: dict, key: tuple) -> bool:
    kind, name = key
    return sym["name"] == name and (kind is None or sym["kind"] == kind)


def check_continuity(m: dict) -> dict:
    """The continuity gate: a lesson may not open on an artifact no earlier lesson
    produced, and a symbol may not change shape behind the reader's back.

    Every rule here is MANIFEST-ONLY -- it reads the declared ledger and nothing else.
    The rules that need the tree (do the paths exist? does later verbatim code still
    call the old name?) live in `continuity.py`, which is advisory.

    CALIBRATION. A missing ledger is ADVISORY, never HARD. The ledger is new; ten real
    courses predate it, and a gate that fails all ten on its first run is one people
    learn to bypass rather than one they fix. What IS hard is a ledger that contradicts
    itself -- because every defect this gate was built for (four lessons opening on
    scaffolds the course never ships, a helper that grew an argument mid-course, a
    capstone requiring a pool nobody created) is a contradiction, not an omission, the
    moment the lesson says out loud what it expects to find."""
    flags: list[str] = []
    leds = course_ledgers(m)
    if not leds:
        return _result("continuity", ["ok: no lessons"])
    lesson_at = {led["lesson"]: i for i, led in enumerate(leds)}
    starter = {_norm_path(p) for p in (m.get("course", {}).get("starter_assets") or [])}

    # 0. malformed declarations. A typo'd kind silently disables every rule below it,
    #    so it is HARD rather than a quiet drop ("ids are contracts").
    for led in leds:
        for e in led["provides"] + led["consumes"]:
            if e["error"]:
                flags.append(f"{HARD}lesson {led['lesson']} ledger: {e['error']}")
        for k in led["legacy"]:
            flags.append(f"{ADV}lesson {led['lesson']} carries '{k}' — documented in "
                         f"references/output-contract.md but never implemented; it is now "
                         f"{LEDGER_LEGACY_KEYS[k]}")

    declared_any = any(l["declared"] for l in leds)

    # 1. renames: resolve the lesson, then forbid the old name at/after it.
    renames = []          # (from_key, to_key, since_index, declaring_lesson)
    for led in leds:
        for r in led["renames"]:
            frm, to = _rename_key(r.get("from")), _rename_key(r.get("to"))
            since = r.get("since_lesson") or led["lesson"]
            if not frm[1] or not to[1]:
                flags.append(f"{HARD}lesson {led['lesson']} rename needs both from and to: {r!r}")
                continue
            if since not in lesson_at:
                flags.append(f"{HARD}lesson {led['lesson']} rename since_lesson '{since}' "
                             f"resolves to no lesson (typo?)")
                continue
            renames.append((frm, to, lesson_at[since], led["lesson"]))

    for frm, to, since_i, at_lesson in renames:
        if frm == to:
            # from == to is a RE-SIGNATURE, not a rename: the name is unchanged and only
            # its shape moved. It licenses the signature-drift rule below and nothing
            # else -- forbidding the "old" name here would forbid the new one too.
            continue
        for j, led in enumerate(leds):
            if j < since_i:
                continue
            for e in led["provides"] + led["consumes"]:
                if _matches_rename(e, frm):
                    flags.append(f"{HARD}lesson {led['lesson']} still uses '{e['symbol']}' after it "
                                 f"was renamed to '{to[1]}' at {leds[since_i]['lesson']} "
                                 f"(declared in {at_lesson}) — later code must use the new name")
        if not any(_matches_rename(e, to)
                   for led in leds[since_i:] for e in led["provides"]):
            flags.append(f"{ADV}rename '{frm[1]}' -> '{to[1]}' (from {at_lesson}): nothing provides "
                         f"the new name at or after {leds[since_i]['lesson']}")

    # 2. symbols: consumed must be provided EARLIER.
    provided_at: dict[str, list[tuple[int, dict]]] = {}
    for i, led in enumerate(leds):
        for p in led["provides"]:
            if p["error"]:
                continue
            provided_at.setdefault(p["symbol"], []).append((i, p))

    consumed_syms: set = set()
    for i, led in enumerate(leds):
        for c in led["consumes"]:
            # `artifact:` edges are check_artifacts' half of this same graph. One graph,
            # two views, and each flag printed exactly once.
            if c["error"] or c["kind"] == "artifact":
                continue
            where = provided_at.get(c["symbol"])
            if not where:
                flags.append(f"{HARD}lesson {led['lesson']} consumes '{c['symbol']}' that no lesson "
                             f"provides — the reader is asked to use something the course never built")
            elif min(w[0] for w in where) >= i:
                first = leds[min(w[0] for w in where)]["lesson"]
                flags.append(f"{HARD}lesson {led['lesson']} consumes '{c['symbol']}' first provided "
                             f"in {first}, which comes later — continuity runs forward only")
            else:
                consumed_syms.add(c["symbol"])

    # 3. signature drift: the same name, two shapes, nobody told the reader.
    renamed_names = {k[1] for r in renames for k in (r[0], r[1])}
    for sym, where in provided_at.items():
        if sym.startswith("artifact:"):
            continue                                  # check_artifacts owns duplicate rungs
        spans = {(p["lo"], p["hi"]) for _i, p in where if p["lo"] is not None}
        if len(spans) > 1 and sym.split(":", 1)[-1] not in renamed_names:
            lessons = ", ".join(leds[i]["lesson"] for i, _p in where)
            flags.append(f"{HARD}'{sym}' is provided with {len(spans)} different signatures "
                         f"({sorted(spans)}) across {lessons} — a symbol that changes shape "
                         f"mid-course needs a renames: entry, or the later call sites break")
        elif len(where) > 1 and len(spans) <= 1:
            flags.append(f"{ADV}'{sym}' is provided by {len(where)} lessons "
                         f"({', '.join(leds[i]['lesson'] for i, _p in where)}) — provide once, "
                         f"consume after")

    # 4. paths: a lesson may only OPEN what already exists.
    emitted: set = set()
    for i, led in enumerate(leds):
        own_emits = {_norm_path(p) for p in led["emits"]}
        own_emits |= {_norm_path(p["name"]) for p in led["provides"] if p["kind"] == "file"}
        opens = [_norm_path(p) for p in led["opens"]]
        opens += [_norm_path(c["name"]) for c in led["consumes"] if c["kind"] == "file"]
        for p in opens:
            if p in own_emits:
                flags.append(f"{HARD}lesson {led['lesson']} opens '{p}' and also emits it — the reader "
                             f"is told to run a file this lesson has not written yet. Ship it in "
                             f"course.starter_assets, or open on the previous lesson's artifact")
            elif not _path_covered(p, emitted | starter):
                flags.append(f"{HARD}lesson {led['lesson']} opens '{p}', which no earlier lesson emits "
                             f"and course.starter_assets does not ship")
        emitted |= own_emits

    # 5. ADVISORY: a rung nothing downstream picks up.
    last = len(leds) - 1
    for i, led in enumerate(leds):
        for p in led["provides"]:
            if p["error"] or p["kind"] == "artifact":
                continue   # artifact rungs are check_artifacts' half of the same graph
            if p["symbol"] not in consumed_syms and not p["terminal"] and i < last:
                flags.append(f"{ADV}'{p['symbol']}' ({led['lesson']}) is consumed by nothing "
                             f"downstream — wire it in, or mark it terminal: <reason>")

    # 6. ADVISORY: the prose seam. state_in of N should describe state_out of N-1.
    for i in range(1, len(leds)):
        a, b = leds[i - 1]["state_out"], leds[i]["state_in"]
        if not a or not b:
            continue
        ta, tb = _tokens(a), _tokens(b)
        if not ta or not tb:
            continue
        overlap = len(ta & tb) / min(len(ta), len(tb))
        if overlap < 0.2:
            flags.append(f"{ADV}lesson {leds[i]['lesson']} state_in shares {overlap:.0%} of its "
                         f"vocabulary with {leds[i-1]['lesson']} state_out — one of the two is "
                         f"describing a tree the other did not leave behind")

    # 7. coverage. ADVISORY by design; see the docstring.
    missing = [l["lesson"] for l in leds if l["kind"] == "build" and not l["declared"]]
    if missing and declared_any:
        flags.append(f"{ADV}{len(missing)}/{len(leds)} build lesson(s) carry no ledger: "
                     f"{', '.join(missing[:6])}{' …' if len(missing) > 6 else ''} — the gate can "
                     f"only check what a lesson declares")
    elif missing:
        return _result("continuity", flags + [f"ok: no continuity ledger declared "
                                              f"({len(missing)} build lesson(s) undeclared)"])
    return _result("continuity", flags)


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


def check_fixes(course_dir) -> dict:
    """No course exports mid-sweep (method/fix-protocol.md).

    A correction is not finished when the filed line is fixed. It is finished when every
    surface carrying the claim is fixed and every image rebuilt from a corrected source.
    The round-2 audit measured the gap: **~17% of its findings were fallout from round-1
    fixes** that landed at one line and missed the twin passage, the quiz feedback, the
    alt text, the `visual-src` markup and the `<!-- spec -->` comment — headlined by six
    shipped images still teaching models the prose beside them had retracted.

    `fix_sweep.py plan` writes `fixes/<id>.yaml`; `fix_sweep.py close` flips it to
    `status: closed` only when every listed surface is clean AND every listed render is
    younger than its HTML source. Anything still `open` is HARD here, so the sweep cannot
    be forgotten halfway — which is exactly how it was forgotten before."""
    from pathlib import Path as _P
    root = _P(course_dir)
    try:
        import fix_sweep
    except Exception as e:                                        # noqa: BLE001
        return _result("fixes", [f"{ADV}fix_sweep unavailable ({e}) — open fix sweeps "
                                 f"cannot be checked"])
    ledgers = fix_sweep.open_ledgers(root)
    if not ledgers:
        return _result("fixes", ["ok: no fix sweeps recorded"])
    flags: list[str] = []
    closed = 0
    for p, d in ledgers:
        fix = d.get("fix") or {}
        fid = fix.get("id", p.stem)
        if fix.get("status") == "closed":
            closed += 1
            continue
        try:
            fails, _warns = fix_sweep.verify(root, d)
        except Exception as e:                                    # noqa: BLE001
            fails = [f"ledger could not be verified: {type(e).__name__}: {e}"]
        detail = f"; {len(fails)} surface(s) still unfixed: {fails[0]}" if fails else \
                 "; every surface is clean — run `fix_sweep.py close` to close it"
        flags.append(f"{HARD}fix sweep '{fid}' is still open (fixes/{p.name}){detail}")
    if not flags:
        flags.append(f"ok: {closed} fix sweep(s), all closed")
    return _result("fixes", flags)


CHECKS = {"dag": check_dag, "briefs": check_briefs, "quiz": check_quiz, "ladder": check_ladder,
          "capstone": check_capstone, "outcomes": check_outcomes,
          "research": check_research, "freshness": check_freshness,
          "artifacts": check_artifacts, "continuity": check_continuity,
          "length": check_length, "fixes": check_fixes}

# Checks that read the course TREE, not the manifest. They live in CHECKS so `all` and the
# subcommand list pick them up for free; every runner passes a course dir for these names
# and a manifest for the rest.
COURSE_DIR_CHECKS = {"fixes"}


# ── runner ──────────────────────────────────────────────────────────────────────

def _print(res: dict) -> None:
    mark = "FAIL" if res["hard"] else "ok"
    print(f"[{mark}] {res['name']}")
    for f in res["flags"]:
        print("   - " + f)


def run(m: dict, names: list[str], course_dir=None) -> int:
    any_hard = False
    for n in names:
        if n in COURSE_DIR_CHECKS:
            if course_dir is None:
                continue                      # tree-only check; nothing to read from a manifest
            res = CHECKS[n](course_dir)
        else:
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

    # freshness: per-claim expiry (the anti-staleness gate)
    import datetime as _fdt
    NOW = _fdt.date(2026, 9, 20)          # inside the backfill window (epoch + 13d)
    LATER = _fdt.date(2026, 11, 1)        # past it (epoch + 55d)

    def _fresh(claim, when=NOW, extra=None):
        fm = _good_manifest()
        for _l in fm["lessons"]:
            _l["research"] = {"claims": []}
        fm["lessons"][0]["research"] = {"claims": [claim]}
        if extra:
            fm.update(extra)
        return check_freshness(fm, when)

    good = {"id": "C1", "kind": "onchain-number", "status": "verified",
            "verified_on": "2026-09-18", "mcp": "helius",
            "recheck": "rpc getMinimumBalanceForRentExemption 165"}
    check(not _fresh(good)["hard"], "dated, in-TTL, probeable claim -> freshness clean")

    stale_c = dict(good, verified_on="2026-08-01")
    r = _fresh(stale_c)
    check(r["hard"] and any("50d old against a 14d TTL" in f for f in r["flags"]),
          "a claim past its TTL -> freshness HARD (the publish gate)")

    aging_c = dict(good, verified_on="2026-09-08")
    r = _fresh(aging_c)
    check(not r["hard"] and any("TTL used" in f for f in r["flags"]),
          "past 0.75x TTL -> advisory, not hard")

    no_probe = {k: v for k, v in good.items() if k != "recheck"}
    r = _fresh(no_probe)
    check(r["hard"] and any("no `recheck`" in f for f in r["flags"]),
          "an on-chain number with no runnable probe -> freshness HARD")
    for _k in ("cli-default", "protocol-param", "version-pin"):
        check(_fresh(dict(no_probe, kind=_k))["hard"],
              f"kind '{_k}' with no recheck -> freshness HARD")

    undated = {k: v for k, v in good.items() if k != "verified_on"}
    r_in = _fresh(undated)
    check(not r_in["hard"] and any("no verified_on" in f for f in r_in["flags"]),
          "verified with no date, inside the backfill window -> advisory")
    r_out = _fresh(undated, LATER)
    check(r_out["hard"], "verified with no date, past the backfill window -> HARD")

    inferred = dict(undated, evidence="https://x/y (dispatched 2026-09-18)")
    check(not _fresh(inferred)["hard"] and
          not any("no verified_on" in f for f in _fresh(inferred)["flags"]),
          "a dispatch date in evidence satisfies the date requirement")

    check(_fresh(dict(good, verified_on="09/18/2026"))["hard"],
          "a non-ISO verified_on -> freshness HARD")
    check(_fresh(dict(good, kind="on-chain-number"))["hard"],
          "an unknown kind -> freshness HARD (closed vocabulary)")
    check(_fresh(dict(good, ttl_days=365))["hard"],
          "a per-claim ttl_days that lengthens the kind default -> freshness HARD")
    check(not _fresh(dict(good, ttl_days=7))["hard"],
          "a per-claim ttl_days that shortens is fine")

    url_api = {"id": "C1", "kind": "api", "status": "verified", "verified_on": "2026-09-18",
               "mcp": "solana-dev", "evidence": "https://station.jup.ag/docs/apis/swap-api"}
    r = _fresh(url_api)
    check(not r["hard"] and any("free probe" in f for f in r["flags"]),
          "an api claim citing a URL with no recheck -> advisory (defect #4's shape)")

    check(any("ZERO claims" in f for f in _fresh(
        good, NOW, {"lessons": [{"id": "x", "module": "m-accounts", "order": 1, "brief": {},
                                 "research": {"frozen_facts": ["890,880"]}}]})["flags"]),
        "frozen_facts with no claims -> advisory that the gate is silent, not that it passed")

    lax = {"cadence": {"release": {"schedule": [{"week": 1, "publish": ["the-counter"]}],
                                   "freshness_policy": {
                                       "onchain_numbers_restale_after_days": 90}}}}
    check(any("may only shorten" in f for f in _fresh(good, NOW, lax)["flags"]),
          "a freshness_policy longer than the kind default -> advisory that it is ignored")
    tight = {"cadence": {"release": {"schedule": [{"week": 1, "publish": ["the-counter"]}],
                                     "freshness_policy": {
                                         "onchain_numbers_restale_after_days": 1}}}}
    check(_fresh(good, NOW, tight)["hard"],
          "a freshness_policy shorter than the kind default DOES tighten the gate")

    check("freshness" in CHECKS and CHECKS["freshness"] is check_freshness,
          "freshness is registered in CHECKS")

    # artifacts: forward consumption
    ag = _good_manifest()
    ag["lessons"][0]["brief"]["artifact"] = {"id": "tool-a", "consumes": ["tool-b"]}
    ag["lessons"][1]["brief"]["artifact"] = {"id": "tool-b", "consumes": []}
    check(check_artifacts(ag)["hard"], "artifact consuming a later artifact -> artifacts HARD")
    ag["lessons"][0]["brief"]["artifact"] = {"id": "tool-a", "consumes": []}
    ag["lessons"][1]["brief"]["artifact"] = {"id": "tool-b", "consumes": ["tool-a"]}
    check(not check_artifacts(ag)["hard"], "forward accretion graph -> artifacts clean")

    # ── continuity ────────────────────────────────────────────────────────────
    def _cont(a: dict | None = None, b: dict | None = None, course: dict | None = None):
        g = _good_manifest()
        if a is not None:
            g["lessons"][0]["brief"]["ledger"] = a
        if b is not None:
            g["lessons"][1]["brief"]["ledger"] = b
        if course:
            g["course"].update(course)
        return check_continuity(g)

    # calibration: no ledger anywhere is never HARD -- ten real courses predate it
    check(not check_continuity(_good_manifest())["hard"],
          "no ledger declared -> continuity is not HARD (calibration)")
    check(any("no continuity ledger" in f for f in check_continuity(_good_manifest())["flags"]),
          "no ledger declared -> says so rather than claiming clean")

    # a lesson consuming a symbol nothing provides
    r = _cont(None, {"consumes": ["fn:derive_vault_pda"]})
    check(r["hard"] and any("no lesson provides" in f for f in r["flags"]),
          "consumes a symbol nobody provides -> continuity HARD")
    # provided EARLIER is fine; provided LATER is not
    check(not _cont({"provides": ["fn:derive_vault_pda"]},
                    {"consumes": ["fn:derive_vault_pda"]})["hard"],
          "consumes a symbol provided earlier -> clean")
    r = _cont({"consumes": ["fn:derive_vault_pda"]}, {"provides": ["fn:derive_vault_pda"]})
    check(r["hard"] and any("comes later" in f for f in r["flags"]),
          "consumes a symbol provided later -> continuity HARD")

    # opening a file no earlier lesson emits, and the starter-asset escape hatch
    r = _cont(None, {"opens": ["swap.js"]})
    check(r["hard"] and any("no earlier lesson emits" in f for f in r["flags"]),
          "opens a path nobody emits -> continuity HARD (the swap.js defect)")
    check(not _cont({"emits": ["swap.js"]}, {"opens": ["swap.js"]})["hard"],
          "opens a path an earlier lesson emits -> clean")
    check(not _cont(None, {"opens": ["swap.js"]}, {"starter_assets": ["swap.js"]})["hard"],
          "opens a declared course starter asset -> clean")
    check(not _cont({"emits": ["toolkit/vault/Anchor.toml"]}, {"opens": ["toolkit/vault"]})["hard"],
          "opens a directory an earlier lesson emitted into -> clean")
    r = _cont(None, {"opens": ["bot/main.py"], "emits": ["bot/main.py"]})
    check(r["hard"] and any("and also emits it" in f for f in r["flags"]),
          "told to run a file this same lesson writes -> continuity HARD")

    # signature drift with no rename declared
    r = _cont({"provides": [{"symbol": "fn:mint", "sig": "(a, b)"}]},
              {"provides": [{"symbol": "fn:mint", "sig": "(a, b, c)"}]})
    check(r["hard"] and any("different signatures" in f for f in r["flags"]),
          "same symbol, two signatures, no rename -> continuity HARD")
    r = _cont({"provides": [{"symbol": "fn:mint", "sig": "(a, b)"}]},
              {"provides": [{"symbol": "fn:mint", "sig": "(a, b, c)"}],
               "renames": [{"from": "fn:mint", "to": "fn:mint", "since_lesson": "pda-state"}]})
    check(not r["hard"], "a declared rename licenses the signature change")

    # the old name surviving a declared rename
    r = _cont({"provides": ["fn:init_vault"]},
              {"provides": ["fn:initialize"], "consumes": ["fn:init_vault"],
               "renames": [{"from": "fn:init_vault", "to": "fn:initialize",
                            "since_lesson": "pda-state"}]})
    check(r["hard"] and any("still uses" in f for f in r["flags"]),
          "old name used after a declared rename -> continuity HARD")
    r = _cont(None, {"renames": [{"from": "a", "to": "b", "since_lesson": "nope"}]})
    check(r["hard"] and any("resolves to no lesson" in f for f in r["flags"]),
          "rename since_lesson typo -> continuity HARD")

    # malformed declarations are HARD, not a silent hole
    r = _cont({"provides": ["derive_vault_pda"]})
    check(r["hard"] and any("<kind>:<name>" in f for f in r["flags"]),
          "a symbol with no kind prefix -> continuity HARD")
    r = _cont({"provides": ["func:x"]})
    check(r["hard"] and any("unknown symbol kind" in f for f in r["flags"]),
          "an unknown symbol kind -> continuity HARD")

    # advisories
    r = _cont({"provides": ["fn:helper"]}, {"provides": ["fn:other"]})
    check(not r["hard"] and any("consumed by nothing downstream" in f for f in r["flags"]),
          "a provides nobody consumes -> advisory")
    r = _cont({"state_out": "a counter program that builds and passes its tests"},
              {"state_in": "an empty directory, nothing written yet"})
    check(not r["hard"] and any("state_in shares" in f for f in r["flags"]),
          "state_in that does not describe the previous state_out -> advisory")
    r = _cont({"state_out": "a counter program that builds and passes its tests"},
              {"state_in": "the counter program from the previous lesson, tests passing"})
    check(not any("state_in shares" in f for f in r["flags"]),
          "an honest state_in seam -> no advisory")

    # the three fields output-contract.md documented and nothing ever implemented
    lg = _good_manifest()
    lg["lessons"][0]["brief"]["carry_forward"] = "the counter"
    r = check_continuity(lg)
    check(not r["hard"] and any("never implemented" in f for f in r["flags"]),
          "a brief written against the old output-contract fields is told where they went")

    # ONE graph: an artifact edge and a ledger edge are the same graph
    og = _good_manifest()
    og["lessons"][0]["brief"]["artifact"] = {"id": "counter", "consumes": []}
    og["lessons"][1]["brief"]["ledger"] = {"consumes": ["artifact:counter"],
                                           "provides": ["artifact:vault"]}
    check(not check_artifacts(og)["hard"] and not check_continuity(og)["hard"],
          "a ledger consuming an artifact declared the legacy way resolves (one graph)")
    og["lessons"][1]["brief"]["ledger"]["consumes"] = ["artifact:ghost"]
    check(check_artifacts(og)["hard"],
          "a ledger consuming an unknown artifact is caught by check_artifacts")

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

    # ── skills-tag advisory: identical tags across a module ──────────────────────
    st = _good_manifest()
    st["academy"] = {"skills_map": {"account-model": "account-model",
                                    "programs-instructions": "program-development",
                                    "pdas": "pdas"}, "default_skills": []}
    base = copy.deepcopy(st["lessons"][0])
    for i in (2, 3):                      # 3 lessons in m-accounts, none setting `skills`
        extra = copy.deepcopy(base)
        extra["id"] = f"the-counter-{i}"
        extra["order"] = i
        extra["brief"]["id"] = extra["id"]
        st["lessons"].append(extra)
    fl = check_briefs(st)["flags"]
    check(any("byte-identical skill tags" in f and f.startswith(ADV) for f in fl),
          "a module whose lessons all derive the same tags -> briefs ADVISORY")
    check(not check_briefs(st)["hard"], "the skills-tag flag is ADVISORY, never HARD")
    for j, sk in ((0, ["account-model"]), (2, ["programs-instructions"]), (3, ["pdas"])):
        st["lessons"][j]["brief"]["skills"] = sk
    check(not any("byte-identical skill tags" in f for f in check_briefs(st)["flags"]),
          "per-lesson brief `skills:` clears the flag")
    two = _good_manifest()               # 1 lesson per module: under the sample floor
    check(not any("byte-identical skill tags" in f for f in check_briefs(two)["flags"]),
          "a module under 3 lessons is not flagged (one pair is not a signal)")
    bs = _good_manifest()
    bs["lessons"][0]["brief"]["skills"] = "pdas"
    check(any("skills must be a list" in f for f in check_briefs(bs)["flags"]),
          "a scalar `skills` -> briefs HARD (it becomes a YAML array on the lesson card)")

    # ── fixes: no course exports mid-sweep ───────────────────────────────────────
    import fix_sweep as _fs
    with tempfile.TemporaryDirectory() as tf:
        c = _P(tf) / "content" / "courses" / "demo"
        (c / "lessons" / "drafts").mkdir(parents=True)
        check(not check_fixes(c)["hard"], "no fixes/ dir -> fixes check clean")
        (c / "lessons" / "drafts" / "m00-l1-x.md").write_text(
            "# T\n\nthe cap is 200 pulls per 6 hours.\n", "utf-8")
        _fs.cmd_plan(c, "200 pulls per 6 hours", "fix-cap", None, None, None)
        r = check_fixes(c)
        check(r["hard"] and any("still open" in f for f in r["flags"]),
              "an open fix sweep -> fixes HARD (the course cannot export mid-sweep)")
        check(any("still unfixed" in f for f in r["flags"]),
              "the HARD flag names a surface that is still wrong, not just the ledger")
        (c / "lessons" / "drafts" / "m00-l1-x.md").write_text(
            "# T\n\nthe cap is whatever the vendor publishes today.\n", "utf-8")
        check(check_fixes(c)["hard"],
              "text fixed but the ledger still open -> still HARD (close it deliberately)")
        check(_fs.cmd_check(c, "fix-cap", None, close=True) == 0, "close succeeds once clean")
        check(not check_fixes(c)["hard"], "a closed sweep -> fixes clean")
        check("fixes" in CHECKS and "fixes" in COURSE_DIR_CHECKS,
              "check_fixes is registered in CHECKS as a course-dir check")

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
    course_dir = getattr(a, "course", None)
    any_hard = False
    for n in names:
        if n in COURSE_DIR_CHECKS:
            if not course_dir:
                print(f"[skip] {n}: needs --course <dir> (it reads the course tree)")
                continue
            res = CHECKS[n](course_dir)
        else:
            res = CHECKS[n](m)
        _print(res)
        any_hard = any_hard or res["hard"]
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
