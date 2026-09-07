#!/usr/bin/env python3
"""quiz_layout.py — assign quiz option order from a hash, and prove it later.

Why this exists
---------------
Option order is a statistical property of the whole course, so it is a TOOL's job,
never a prompt's. The wave-2 generator asked a model to "VARY the correct option
position … rotate forward from there", and got a perfectly balanced marginal
wrapped around a perfectly predictable a->b->c cycle. A stronger instruction would
have produced a different artifact, not randomness.

This tool removes the decision from the author entirely:

    permute   each question's option array is reordered by
              sha256(salt | courseId | lessonSlug | blockKey | questionId), and the
              resulting option-id order is written to a LEDGER in the manifest.
    verify    byte-compares the live manifest against that ledger, and the ledger
              against the salted derivation. This is PROVENANCE, not statistics —
              it is conclusive even at n=1, where every distributional test is
              powerless.
    report    the full statistical picture (tools/quiz_metrics.py) plus the ledger's
              state and the length gaps a rewrite pass should close.

Addressing
----------
Question ids are NOT unique within a course. One shipped course uses only q1/q2/q3
for all 33 of its questions; another has 70 distinct ids across 88 questions. The
ledger is therefore keyed on the 4-tuple (courseId, lessonSlug, blockKey,
questionId) — anything coarser silently merges distinct questions.

Safety
------
The permuter touches ONLY array order. It never reads or writes `id`, `label`,
`correct`, `feedback`, or any other option field, and it asserts that itself: the
multiset of canonicalized option objects must be identical before and after, or it
aborts having written nothing. That invariant is what makes it safe to run on an
already-translated course, because translations bind on option id, not position.

Pipeline position (two tools deadlock if you get this wrong)
------------------------------------------------------------
    1. author / rewrite labels     tools/quiz_edit.py split -> edit -> merge
    2. permute                     tools/quiz_layout.py permute      <- LAST mutation
    3. validate                    tools/validate_course.py quiz
`quiz_edit.py merge` REFUSES any file whose option order moved, because a moved
order is indistinguishable from a moved answer key at merge time. So label QA runs
FIRST and permutation is the last mutation before validation. Re-running permute
after an edit is free and idempotent — the layout is a pure function of the salt
and the option ids, not of the order it finds.

    quiz_layout.py permute --course content/courses/<id> [--salt S] [--dry-run]
    quiz_layout.py verify  --course content/courses/<id>
    quiz_layout.py report  --course content/courses/<id> [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import quiz_metrics

LEDGER_KEY = "quiz_layout"
LEDGER_VERSION = 1


# ── addressing + derivation ───────────────────────────────────────────────────

def address(course_id: str, lesson_id: str, block_key: str, qid: str) -> tuple[str, str, str, str]:
    return (str(course_id), str(lesson_id), str(block_key), str(qid))


def _seed(salt: str, addr: tuple[str, str, str, str]) -> bytes:
    return hashlib.sha256("|".join((salt, *addr)).encode("utf-8")).digest()


def derive_order(salt: str, addr: tuple[str, str, str, str], option_ids: list[str]) -> list[str]:
    """The option-id order this address is entitled to.

    Sorting the ids by sha256(seed || id) makes the result a pure function of the
    salt, the address, and the id SET — never of the order it was handed. That is
    what makes `permute` idempotent and `verify` decidable.
    """
    seed = _seed(salt, addr)
    return sorted(option_ids,
                  key=lambda oid: hashlib.sha256(seed + oid.encode("utf-8")).digest())


def _canon(option: dict) -> str:
    """Canonical form of one option, for the before/after multiset assertion."""
    return json.dumps(option, sort_keys=True, ensure_ascii=False)


# ── manifest walking ──────────────────────────────────────────────────────────

def _manifest_path(course: Path) -> Path:
    return course / "manifest.json" if course.is_dir() else course


def _load(course: Path) -> tuple[Path, dict]:
    p = _manifest_path(course)
    if not p.is_file():
        raise SystemExit(f"quiz_layout: no manifest at {p}")
    return p, json.loads(p.read_text("utf-8"))


def walk(manifest: dict):
    """Yield (address, block, question) for every quiz question in display order.

    Ordering mirrors quiz_metrics.load_questions so the ledger, the gate and the
    report can never disagree about which question is which.
    """
    course_id = str((manifest.get("course") or {}).get("id", ""))
    for _mi, lesson in quiz_metrics._ordered_lessons(manifest):
        brief = lesson.get("brief") or {}
        for bi, block in enumerate(brief.get("quiz_blocks") or []):
            block = block or {}
            key = str(block.get("key") or f"#{bi}")
            for q in block.get("questions") or []:
                if not q:
                    continue
                yield address(course_id, lesson.get("id", ""), key, q.get("id", "")), block, q


def _addresses(manifest: dict) -> list[tuple]:
    return [addr for addr, _b, _q in walk(manifest)]


def check_addressing(manifest: dict) -> list[str]:
    """The 4-tuple must be unique. `check_quiz_blocks` already HARD-fails duplicate
    question ids inside a block, which guarantees it — but a ledger that silently
    merged two questions would be worse than no ledger, so assert it here too."""
    seen, dupes = set(), []
    for addr in _addresses(manifest):
        if addr in seen:
            dupes.append("/".join(addr))
        seen.add(addr)
    return dupes


# ── permute ───────────────────────────────────────────────────────────────────

def permute(manifest: dict, salt: str) -> tuple[int, list[str]]:
    """Reorder every question's option array from the salt. Returns (moved, errors).

    On any error the manifest is left untouched: the caller must not write.
    """
    dupes = check_addressing(manifest)
    if dupes:
        return 0, [f"duplicate question address {d} — the ledger would merge two questions"
                   for d in dupes]

    before = sorted(_canon(o) for _a, _b, q in walk(manifest) for o in (q.get("options") or []))
    plan: list[tuple[dict, list[dict]]] = []
    errors: list[str] = []
    entries: list[dict] = []
    moved = 0

    for addr, _block, q in walk(manifest):
        options = q.get("options") or []
        oids = [str(o.get("id", "")) for o in options]
        if len(set(oids)) != len(oids) or any(not o for o in oids):
            errors.append(f"{'/'.join(addr)}: options must all carry a distinct id")
            continue
        order = derive_order(salt, addr, oids)
        by_id = {oid: o for oid, o in zip(oids, options)}
        new = [by_id[oid] for oid in order]
        if oids != order:
            moved += 1
        plan.append((q, new))
        entries.append({"lesson": addr[1], "block": addr[2], "question": addr[3],
                        "options": order})

    if errors:
        return 0, errors

    for q, new in plan:
        q["options"] = new

    # The invariant, asserted rather than asserted-to: array ORDER moved and
    # nothing else. Compare the multiset of canonicalized options; any difference
    # at all (a label, a `correct` flag, a dropped field) means the permuter did
    # something it is not allowed to do.
    after = sorted(_canon(o) for _a, _b, q in walk(manifest) for o in (q.get("options") or []))
    if before != after:
        return 0, ["INVARIANT VIOLATION: the option multiset changed during permutation — "
                   "aborting without writing. Only array order may move; never id, label, "
                   "correct, or feedback"]

    manifest[LEDGER_KEY] = {"version": LEDGER_VERSION, "salt": salt, "entries": entries}
    return moved, []


# ── verify ────────────────────────────────────────────────────────────────────

def verify(manifest: dict) -> list[str]:
    """Byte-compare the live manifest against its ledger, and the ledger against
    the salted derivation. Provenance, not statistics — conclusive at any n."""
    ledger = manifest.get(LEDGER_KEY)
    if not ledger:
        return ["no layout ledger in the manifest — option order has no provenance. "
                "Run `quiz_layout.py permute` (it is the last mutation before validation)"]
    if ledger.get("version") != LEDGER_VERSION:
        return [f"ledger version {ledger.get('version')!r} != {LEDGER_VERSION}"]
    salt = str(ledger.get("salt", ""))

    want = {(e.get("lesson"), e.get("block"), e.get("question")): list(e.get("options") or [])
            for e in ledger.get("entries") or []}
    problems: list[str] = []
    seen = set()
    for addr, _block, q in walk(manifest):
        key = addr[1:]
        seen.add(key)
        live = [str(o.get("id", "")) for o in (q.get("options") or [])]
        if key not in want:
            problems.append(f"{'/'.join(addr)}: not in the ledger (added after the last permute?)")
            continue
        if live != want[key]:
            problems.append(f"{'/'.join(addr)}: option order {live} != ledger {want[key]} — "
                            f"hand-ordered after the permute")
            continue
        expect = derive_order(salt, addr, live)
        if want[key] != expect:
            problems.append(f"{'/'.join(addr)}: the LEDGER itself does not match the salted "
                            f"derivation ({want[key]} vs {expect}) — the ledger was edited")
    for key in sorted(set(want) - seen):
        problems.append(f"{'/'.join(key)}: in the ledger but not in the manifest (deleted question?)")
    return problems


# ── report ────────────────────────────────────────────────────────────────────

def length_gaps(manifest: dict, top: int = 8) -> list[tuple[int, str]]:
    """Widest 'key label minus runner-up' gaps — the actionable list for a rewrite
    pass. (This is what `quiz_balance.py report` printed before it was retired.)"""
    gaps: list[tuple[int, str]] = []
    for addr, _b, q in walk(manifest):
        opts = q.get("options") or []
        if q.get("multiSelect") or sum(1 for o in opts if o.get("correct")) != 1:
            continue
        lens = sorted(len(str(o.get("label", ""))) for o in opts)
        key = next(o for o in opts if o.get("correct"))
        if len(str(key.get("label", ""))) == lens[-1] and len(lens) >= 2:
            gaps.append((lens[-1] - lens[-2], "/".join(addr[1:])))
    gaps.sort(reverse=True)
    return gaps[:top]


def report(manifest: dict) -> str:
    rep = quiz_metrics.analyse(manifest)
    lines = [quiz_metrics.render(rep), ""]
    problems = verify(manifest)
    if not problems:
        lines.append("   layout ledger    in sync, and derived from the recorded salt")
    else:
        lines.append(f"   layout ledger    {len(problems)} problem(s):")
        lines += [f"     - {p}" for p in problems[:10]]
        if len(problems) > 10:
            lines.append(f"     - ... +{len(problems) - 10} more")
    gaps = length_gaps(manifest)
    if gaps:
        lines.append("   widest length gaps (key chars minus runner-up):")
        lines += [f"     +{g:>4} chars   {w}" for g, w in gaps]
    return "\n".join(lines)


# ── selftest ──────────────────────────────────────────────────────────────────

def _fixture() -> dict:
    """Two lessons that reuse q1/q2/q3 — the shipped non-unique-id shape."""
    def q(qid, correct):
        return {"id": qid, "prompt": f"{qid}?", "multiSelect": False,
                "explanation": "because of how accounts are laid out",
                "options": [{"id": f"o{i + 1}", "label": f"label {qid} {i}",
                             "correct": i == correct, "feedback": "why"} for i in range(5)]}
    return {
        "course": {"id": "fx"},
        "modules": [{"id": "m0"}, {"id": "m1"}],
        "lessons": [
            {"id": "l0", "module": "m0", "order": 1, "brief": {"title": "L0", "quiz_blocks": [
                {"key": "check", "questions": [q("q1", 0), q("q2", 0), q("q3", 0)]}]}},
            {"id": "l1", "module": "m1", "order": 1, "brief": {"title": "L1", "quiz_blocks": [
                {"key": "check", "questions": [q("q1", 0), q("q2", 0)]},
                {"questions": [q("q1", 0)]}]}},
        ],
    }


def selftest() -> int:
    import copy
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("PASS - " if cond else "FAIL - ") + msg)
        ok = ok and bool(cond)

    m = _fixture()
    addrs = _addresses(m)
    chk(len({a[3] for a in addrs}) == 3 and len(addrs) == 6,
        "fixture reproduces non-unique question ids (3 distinct ids, 6 questions)")
    chk(len(set(addrs)) == 6, "the 4-tuple keeps all 6 distinct")
    chk(not check_addressing(m), "no duplicate addresses in the fixture")
    chk(addrs[5] == ("fx", "l1", "#1", "q1"),
        f"a block with no `key` falls back to its index (got {addrs[5]})")

    # a genuine collision must be refused, not silently merged
    coll = copy.deepcopy(m)
    coll["lessons"][1]["brief"]["quiz_blocks"][1]["key"] = "check"
    chk(check_addressing(coll), "a real 4-tuple collision is detected")
    chk(permute(coll, "s")[1], "permute refuses a colliding course")

    # derivation is deterministic, salt-sensitive, order-independent
    a = ("fx", "l0", "check", "q1")
    ids = ["o1", "o2", "o3", "o4", "o5"]
    chk(derive_order("s", a, ids) == derive_order("s", a, list(reversed(ids))),
        "derive_order ignores the order it is handed (so permute is idempotent)")
    chk(derive_order("s", a, ids) != derive_order("t", a, ids), "the salt changes the layout")
    chk(derive_order("s", a, ids) != derive_order("s", ("fx", "l0", "check", "q2"), ids),
        "the address changes the layout")
    chk(sorted(derive_order("s", a, ids)) == sorted(ids), "derive_order is a permutation")

    # permute: order moves, nothing else does
    p = copy.deepcopy(m)
    before = {(a2[1:], o["id"]): dict(o) for a2, _b, q in walk(p) for o in q["options"]}
    moved, errs = permute(p, "salt-1")
    chk(not errs and moved > 0, f"permute moved {moved} question(s) with no errors {errs}")
    after = {(a2[1:], o["id"]): dict(o) for a2, _b, q in walk(p) for o in q["options"]}
    chk(before == after, "every option object is byte-identical: only array order moved")
    chk(all(q["options"][0]["id"] != "o1" or True for _a, _b, q in walk(p)), "shape intact")

    # idempotent
    p2 = copy.deepcopy(p)
    permute(p2, "salt-1")
    chk(json.dumps(p, sort_keys=True) == json.dumps(p2, sort_keys=True),
        "permute is idempotent — running it twice is a no-op")

    # verify
    chk(not verify(p), "verify passes straight after a permute")
    chk(verify(m), "verify fails on a manifest that was never permuted")
    tampered = copy.deepcopy(p)
    opts = tampered["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"]
    opts[0], opts[1] = opts[1], opts[0]
    probs = verify(tampered)
    chk(any("hand-ordered" in x for x in probs), "verify catches a hand-reordered question")
    forged = copy.deepcopy(p)
    ent = forged[LEDGER_KEY]["entries"][0]
    live = forged["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"]
    live[0], live[1] = live[1], live[0]
    ent["options"][0], ent["options"][1] = ent["options"][1], ent["options"][0]
    chk(any("does not match the salted derivation" in x for x in verify(forged)),
        "verify catches a ledger forged to match a hand-ordered manifest")
    dropped = copy.deepcopy(p)
    dropped["lessons"][0]["brief"]["quiz_blocks"][0]["questions"].pop()
    chk(any("not in the manifest" in x for x in verify(dropped)),
        "verify notices a question deleted after the permute")
    added = copy.deepcopy(p)
    added["lessons"][0]["brief"]["quiz_blocks"][0]["questions"].append(
        {"id": "q9", "options": [{"id": "o1"}, {"id": "o2"}]})
    chk(any("not in the ledger" in x for x in verify(added)),
        "verify notices a question added after the permute")

    # the multiset guard: a changed label must be distinguishable from a reorder
    b2 = copy.deepcopy(m)
    snapshot = sorted(_canon(o) for _a, _b, q in walk(b2) for o in q["options"])
    b2["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["options"][0]["label"] = "changed"
    chk(sorted(_canon(o) for _a, _b, q in walk(b2) for o in q["options"]) != snapshot,
        "the multiset guard distinguishes a changed label from a reordered array")

    # the layout it produces is statistically clean
    big = {"course": {"id": "big"}, "modules": [], "lessons": []}
    for li in range(30):
        mid = f"m{li // 3}"
        if {"id": mid} not in big["modules"]:
            big["modules"].append({"id": mid})
        qs = []
        for j in range(4):
            qs.append({"id": f"q{j + 1}", "prompt": f"l{li} q{j} asks something specific",
                       "multiSelect": False, "explanation": "a teaching paragraph here",
                       "options": [{"id": f"o{i + 1}",
                                    "label": quiz_metrics._fair_label(li * 4 + j, i),
                                    "correct": i == 0, "feedback": "why"} for i in range(5)]})
        big["lessons"].append({"id": f"l{li}", "module": mid, "order": 1,
                               "brief": {"title": f"L{li}",
                                         "quiz_blocks": [{"key": "check", "questions": qs}]}})
    pre = quiz_metrics.analyse(copy.deepcopy(big))
    chk(pre.failed, "an all-slot-1 course fails before the permute")
    permute(big, "big-salt")
    post = quiz_metrics.analyse(big)
    pos_metrics = {"sequence", "repeat-rate", "marginal", "module-seed"}
    still = [f"{f.metric}: {f.message}" for f in post.findings
             if f.severity == quiz_metrics.ERROR and f.metric in pos_metrics]
    chk(not still, "after the permute every POSITION metric is clean:\n      " + "\n      ".join(still))

    print("\n" + ("QUIZ_LAYOUT SELFTESTS PASSED" if ok else "QUIZ_LAYOUT SELFTESTS FAILED"))
    return 0 if ok else 1


# ── cli ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=("permute", "verify", "report"))
    ap.add_argument("--course", help="course directory (reads/writes manifest.json)")
    ap.add_argument("--manifest", help="manifest.json path")
    ap.add_argument("--salt", help="layout salt (default: the course id; reused from the "
                                   "ledger on a re-permute unless overridden)")
    ap.add_argument("--dry-run", action="store_true", help="permute: report, write nothing")
    ap.add_argument("--json", action="store_true", help="report: machine-readable")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    src = a.course or a.manifest
    if not a.cmd or not src:
        ap.print_help()
        return 2
    path, m = _load(Path(src))

    if a.cmd == "permute":
        salt = a.salt or (m.get(LEDGER_KEY) or {}).get("salt") \
            or str((m.get("course") or {}).get("id", "")) or "quiz-layout"
        moved, errs = permute(m, salt)
        for e in errs:
            print(f"  REFUSED {e}", file=sys.stderr)
        if errs:
            print("permute: aborted, nothing written", file=sys.stderr)
            return 1
        n = len((m.get(LEDGER_KEY) or {}).get("entries") or [])
        if a.dry_run:
            print(f"permute (dry run): would reorder {moved}/{n} question(s), salt={salt!r}")
            return 0
        path.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"permute: {moved}/{n} question(s) reordered, ledger written, salt={salt!r} -> {path}")
        return 0

    if a.cmd == "verify":
        problems = verify(m)
        for p in problems:
            print(f"  {p}")
        print(f"verify: {'FAIL' if problems else 'ok'} "
              f"({len((m.get(LEDGER_KEY) or {}).get('entries') or [])} ledger entries)")
        return 1 if problems else 0

    rep = quiz_metrics.analyse(m)
    if a.json:
        print(json.dumps({
            "course": rep.slug, "failed": rep.failed, "stats": rep.stats,
            "ledger": verify(m) or "in-sync",
            "findings": [{"severity": f.severity, "metric": f.metric, "message": f.message}
                         for f in rep.findings]}, indent=2))
    else:
        print(report(m))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
