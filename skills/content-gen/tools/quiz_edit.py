#!/usr/bin/env python3
"""Split a course's quizzes out of manifest.json for per-lesson editing, then merge back.

Why this exists: every quiz in a course lives in `manifest.json` under
`lessons[].brief.quiz_blocks`. That is ONE file, so a fan-out of per-lesson editors would
race on it. `split` writes one JSON file per lesson; `merge` folds them back and REFUSES any
file whose structure moved, so a rewrite pass can change wording and nothing else.

What `merge` will not accept, and why each one matters:

  - a question id changed        -> the layout ledger is keyed on it; a re-keyed question is
                                    a new question wearing an old one's answers
  - an option id changed/dropped -> correctness and translations both bind on option id
  - a `correct` flag moved       -> the answer key is not editorial
  - `multiSelect` flipped        -> it silently changes how the platform grades
  - a block key changed          -> it is part of the ledger address
  - the option ORDER moved       -> at merge time a reorder is indistinguishable from a moved
                                    key, and order is not an author's decision anyway

That last one sets the pipeline order, which is not optional:

    1. author / rewrite labels   quiz_edit.py split -> edit -> merge
    2. permute                   quiz_layout.py permute        <- LAST mutation
    3. validate                  validate_course.py quiz

Permute before merge and merge refuses the whole course. There is no reporting mode here:
`quiz_layout.py report` prints the statistics, the ledger state, and the length gaps.

  quiz_edit.py split  <course>            -> <course>/lessons/quizzes/<stem>.json
  quiz_edit.py merge  <course>            -> rewrites manifest.json in place
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _stem(lesson: dict, modules: list) -> str:
    """Mirror the draft stem so quiz files line up with drafts/ and assets/."""
    idx = {m["id"]: i for i, m in enumerate(modules)}
    mi = idx.get(lesson.get("module"), 99)
    return f"m{mi:02d}-l{lesson.get('order', 0)}-{lesson['id']}"


def _load(course: Path) -> tuple[Path, dict]:
    mp = course / "manifest.json"
    return mp, json.loads(mp.read_text("utf-8"))


def _single_select(q: dict) -> bool:
    opts = q.get("options", [])
    return (not q.get("multiSelect")) and len(opts) >= 2 and \
        sum(1 for o in opts if o.get("correct")) == 1


def shape(blocks) -> list:
    """Everything a rewrite pass may NOT move. `merge` compares this before and
    after and refuses the whole file on any difference.

    Ordering is inside the shape on purpose: option order is assigned by
    `quiz_layout.py permute` from a hash and recorded in a ledger, so a reordered
    file here means either a hand-edit or a permute run out of sequence. Both are
    refusals, and at merge time neither is distinguishable from a moved answer key.
    """
    return [[str((b or {}).get("key", "")),
             [(q.get("id"),
               bool(q.get("multiSelect", False)),
               tuple(o.get("id") for o in q.get("options", [])),
               tuple(bool(o.get("correct")) for o in q.get("options", [])))
              for q in (b or {}).get("questions", [])]]
            for b in blocks]


def cmd_split(course: Path) -> int:
    _, m = _load(course)
    out = course / "lessons" / "quizzes"
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for l in m.get("lessons", []):
        blocks = (l.get("brief", {}) or {}).get("quiz_blocks") or []
        if not blocks:
            continue
        (out / f"{_stem(l, m.get('modules', []))}.json").write_text(
            json.dumps({"lesson": l["id"], "quiz_blocks": blocks}, indent=2, ensure_ascii=False) + "\n",
            "utf-8")
        n += 1
    print(f"split: {n} lesson quiz file(s) -> {out}")
    return 0


def cmd_merge(course: Path) -> int:
    mp, m = _load(course)
    src = course / "lessons" / "quizzes"
    if not src.is_dir():
        print(f"merge: nothing at {src} (run split first)", file=sys.stderr)
        return 2
    by_id = {l["id"]: l for l in m.get("lessons", [])}
    merged = changed = 0
    problems: list[str] = []
    for f in sorted(src.glob("*.json")):
        doc = json.loads(f.read_text("utf-8"))
        l = by_id.get(doc.get("lesson"))
        if l is None:
            problems.append(f"{f.name}: unknown lesson id {doc.get('lesson')!r}")
            continue
        old = (l.get("brief", {}) or {}).get("quiz_blocks") or []
        new = doc.get("quiz_blocks") or []
        # Correctness and identity are structural, not editorial: a rewrite pass may
        # change wording only. If anything in shape() moved, refuse the whole file
        # rather than silently republish a quiz whose key, id, or order changed.
        if shape(old) != shape(new):
            problems.append(f"{f.name}: refusing — a block key, question id, option id, "
                            f"option ORDER, multiSelect flag, or `correct` flag changed. "
                            f"Only labels, feedback and explanations may be edited here; "
                            f"order is assigned by quiz_layout.py permute, which runs AFTER "
                            f"this merge")
            continue
        if old != new:
            changed += 1
        l["brief"]["quiz_blocks"] = new
        merged += 1
    for p in problems:
        print(f"  REFUSED {p}", file=sys.stderr)
    if problems:
        print(f"merge: aborted, {len(problems)} file(s) failed the correctness check", file=sys.stderr)
        return 1
    mp.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"merge: {merged} lesson(s) folded back, {changed} with edits -> {mp}")
    return 0


def selftest() -> int:
    ok = True

    def chk(c, msg):
        nonlocal ok
        print(("PASS - " if c else "FAIL - ") + msg)
        ok = ok and bool(c)

    q_ok = {"id": "q1", "multiSelect": False,
            "options": [{"id": "o1", "label": "x", "correct": True}, {"id": "o2", "label": "yy"}]}
    chk(_single_select(q_ok), "single-select detected")
    chk(not _single_select({"id": "q", "multiSelect": True, "options": q_ok["options"]}),
        "multiSelect excluded")
    chk(not _single_select({"id": "q", "options": [{"id": "o1", "label": "x", "correct": True},
                                                   {"id": "o2", "label": "y", "correct": True}]}),
        "two-correct excluded")
    chk(_stem({"id": "m01-l1", "module": "module-b", "order": 2},
              [{"id": "module-a"}, {"id": "module-b"}]) == "m01-l2-m01-l1",
        "stem uses positional module index")

    # the refusal invariant: what a rewrite pass may and may not move
    import copy
    base = [{"key": "check", "questions": [
        {"id": "q1", "multiSelect": False,
         "options": [{"id": "o1", "label": "alpha", "correct": True, "feedback": "yes"},
                     {"id": "o2", "label": "beta", "correct": False, "feedback": "no"},
                     {"id": "o3", "label": "gamma", "correct": False, "feedback": "no"},
                     {"id": "o4", "label": "delta", "correct": False, "feedback": "no"}],
         "explanation": "e"}]}]

    def moved(mutate) -> bool:
        b = copy.deepcopy(base)
        mutate(b)
        return shape(base) != shape(b)

    def edit_labels(b):
        b[0]["questions"][0]["options"][0]["label"] = "a completely rewritten label"
        b[0]["questions"][0]["options"][1]["feedback"] = "a better explanation of the miss"
        b[0]["questions"][0]["explanation"] = "a rewritten teaching paragraph"
    chk(not moved(edit_labels), "rewriting labels/feedback/explanation is ACCEPTED")

    for name, mut in [
        ("a re-keyed question id",
         lambda b: b[0]["questions"][0].__setitem__("id", "q1-v2")),
        ("a renamed option id",
         lambda b: b[0]["questions"][0]["options"][0].__setitem__("id", "a")),
        ("a moved `correct` flag",
         lambda b: (b[0]["questions"][0]["options"][0].__setitem__("correct", False),
                    b[0]["questions"][0]["options"][1].__setitem__("correct", True))),
        ("a flipped multiSelect",
         lambda b: b[0]["questions"][0].__setitem__("multiSelect", True)),
        ("a renamed block key", lambda b: b[0].__setitem__("key", "check-2")),
        ("a reordered option array", lambda b: b[0]["questions"][0]["options"].reverse()),
        ("a dropped option", lambda b: b[0]["questions"][0]["options"].pop()),
        ("a dropped question", lambda b: b[0]["questions"].pop()),
    ]:
        chk(moved(mut), f"{name} is REFUSED")

    print("QUIZ_EDIT SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=("split", "merge"))
    ap.add_argument("course", nargs="?")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.cmd or not a.course:
        ap.print_help()
        return 2
    course = Path(a.course)
    return {"split": cmd_split, "merge": cmd_merge}[a.cmd](course)


if __name__ == "__main__":
    sys.exit(main())
