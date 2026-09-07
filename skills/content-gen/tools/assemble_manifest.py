#!/usr/bin/env python3
"""assemble_manifest.py — deterministically merge per-module brief fragments into one manifest.

The other half of the brief fan-out (`method/brief-fanout.md`): `scaffold_course.py emit` splits a
manifest into a course tree, and this merges module fragments back into a manifest. Writing N modules
of briefs in parallel means N agents, and an agent hand-merging JSON produces a file that looks right
and has silently lost a lesson. So the merge is a tool, not a prompt.

Merges <dir>/manifest.skeleton.json + every <dir>/briefs/<module-id>.lessons.json into
<dir>/manifest.json. The skeleton owns course/dag/glossary/concept_ledger/modules/cadence/assessment/
academy and the ORDER of module + lesson ids; each fragment owns the full lesson objects
(id/module/order/brief[/research]) for exactly one module. `module` and `order` are re-stamped from the
skeleton's declaration, so ordering cannot drift.

Structural mismatch is fatal by design: a missing, extra or duplicated lesson id exits 2 with
ASSEMBLE-FAIL rather than quietly assembling a short course.

    python3 assemble_manifest.py <course-dir>      # -> <course-dir>/manifest.json
    python3 assemble_manifest.py --selftest
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


class AssembleError(Exception):
    """A structural mismatch between the skeleton and the fragments."""


def _fail(msg: str):
    raise AssembleError(msg)


def assemble(course_dir: Path) -> dict:
    """Merge skeleton + fragments and write <dir>/manifest.json.

    Returns {"manifest": Path, "lessons": int, "modules": int}. Raises AssembleError on mismatch.
    """
    d = Path(course_dir)
    skpath = d / "manifest.skeleton.json"
    if not skpath.exists():
        _fail(f"no skeleton at {skpath}")
    try:
        sk = json.loads(skpath.read_text("utf-8"))
    except Exception as e:
        _fail(f"{skpath.name}: invalid JSON: {e}")

    # module order + the lesson-id order each module declares
    modules = sk.get("modules", [])
    if not modules:
        _fail("skeleton has no modules")
    declared = []  # (module_id, lesson_id) in course order
    for m in modules:
        mid = m.get("id")
        if not mid:
            _fail("skeleton has a module with no id")
        for lid in m.get("lessons", []):
            declared.append((mid, lid))
    declared_ids = [lid for _, lid in declared]
    if not declared_ids:
        _fail("skeleton declares no lessons")
    if len(declared_ids) != len(set(declared_ids)):
        dups = sorted({x for x in declared_ids if declared_ids.count(x) > 1})
        _fail(f"skeleton declares duplicate lesson id(s): {dups}")

    # gather fragments
    frag_dir = d / "briefs"
    frags = sorted(frag_dir.glob("*.lessons.json")) if frag_dir.exists() else []
    if not frags:
        _fail(f"no lesson fragments under {frag_dir}")
    by_id: dict = {}
    for f in frags:
        try:
            arr = json.loads(f.read_text("utf-8"))
        except Exception as e:
            _fail(f"{f.name}: invalid JSON: {e}")
        if not isinstance(arr, list):
            _fail(f"{f.name}: expected a JSON array of lesson objects")
        for les in arr:
            if not isinstance(les, dict):
                _fail(f"{f.name}: expected lesson objects, got {type(les).__name__}")
            lid = les.get("id")
            if not lid:
                _fail(f"{f.name}: a lesson object has no id")
            if lid in by_id:
                _fail(f"lesson id '{lid}' appears in two fragments")
            if "brief" not in les:
                _fail(f"lesson '{lid}' has no brief")
            by_id[lid] = les

    # reconcile against the skeleton
    missing = [lid for lid in declared_ids if lid not in by_id]
    extra = [lid for lid in by_id if lid not in set(declared_ids)]
    if missing:
        _fail(f"skeleton declares lessons with no fragment: {missing}")
    if extra:
        _fail(f"fragments contain lessons not declared by skeleton: {extra}")

    # assemble in course order, stamping order fields to match the declaration
    lessons = []
    per_module_counter: dict = {}
    for mid, lid in declared:
        les = by_id[lid]
        les["module"] = mid
        per_module_counter[mid] = per_module_counter.get(mid, 0) + 1
        les["order"] = per_module_counter[mid]
        lessons.append(les)

    out = dict(sk)
    out["lessons"] = lessons
    out.pop("_lesson_plan", None)  # skeleton-only helper key
    mpath = d / "manifest.json"
    mpath.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return {"manifest": mpath, "lessons": len(lessons), "modules": len(modules)}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    if len(argv) != 1 or argv[0].startswith("-"):
        print("usage: assemble_manifest.py <course-dir> | --selftest", file=sys.stderr)
        return 2
    try:
        res = assemble(Path(argv[0]))
    except AssembleError as e:
        print(f"ASSEMBLE-FAIL: {e}", file=sys.stderr)
        return 2
    print(f"OK: assembled {res['lessons']} lessons across {res['modules']} modules -> {res['manifest']}")
    return 0


# ---------------------------------------------------------------- selftest

def _fixture(d: Path, modules, frags) -> None:
    (d / "manifest.skeleton.json").write_text(json.dumps({
        "schema_version": 1,
        "course": {"id": "demo", "length_target": {"lessons": sum(len(m[1]) for m in modules)}},
        "modules": [{"id": mid, "title": mid, "lessons": list(lids)} for mid, lids in modules],
        "_lesson_plan": "should be dropped",
    }), "utf-8")
    (d / "briefs").mkdir(exist_ok=True)
    for name, arr in frags.items():
        (d / "briefs" / f"{name}.lessons.json").write_text(json.dumps(arr), "utf-8")


def _lesson(lid: str) -> dict:
    return {"id": lid, "module": "WRONG", "order": 99, "brief": {"id": lid, "title": lid}}


def selftest() -> int:
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("PASS" if cond else "FAIL") + " - " + msg)
        ok = ok and bool(cond)

    def err(modules, frags) -> str:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _fixture(d, modules, frags)
            try:
                assemble(d)
                return ""
            except AssembleError as e:
                return str(e)

    mods = [("m01", ["a", "b"]), ("m02", ["c"])]
    frags = {"m01": [_lesson("b"), _lesson("a")], "m02": [_lesson("c")]}

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _fixture(d, mods, frags)
        res = assemble(d)
        man = json.loads((d / "manifest.json").read_text("utf-8"))
        chk(res["lessons"] == 3 and res["modules"] == 2, "assembles every declared lesson")
        chk([l["id"] for l in man["lessons"]] == ["a", "b", "c"],
            "lessons land in skeleton order, not fragment order")
        chk([l["module"] for l in man["lessons"]] == ["m01", "m01", "m02"],
            "module is re-stamped from the skeleton")
        chk([l["order"] for l in man["lessons"]] == [1, 2, 1],
            "order is re-stamped 1-based within each module")
        chk("_lesson_plan" not in man, "skeleton-only helper keys are dropped")
        chk(man["course"]["id"] == "demo" and man["schema_version"] == 1,
            "skeleton keys survive the merge")
        # idempotent: re-assembling the same inputs yields the same bytes
        before = (d / "manifest.json").read_bytes()
        assemble(d)
        chk((d / "manifest.json").read_bytes() == before, "re-assembling is idempotent")

    chk("no fragment" in err(mods, {"m01": [_lesson("a"), _lesson("b")]}),
        "a lesson with no fragment is fatal")
    chk("not declared by skeleton" in err(mods, {**frags, "m03": [_lesson("zz")]}),
        "a fragment lesson the skeleton never declared is fatal")
    chk("two fragments" in err(mods, {**frags, "m03": [_lesson("a")]}),
        "the same lesson id in two fragments is fatal")
    chk("duplicate lesson id" in err([("m01", ["a", "a"]), ("m02", ["c"])], frags),
        "a skeleton that declares a duplicate id is fatal")
    chk("has no brief" in err(mods, {"m01": [{"id": "a"}, _lesson("b")], "m02": [_lesson("c")]}),
        "a lesson object with no brief is fatal")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _fixture(d, mods, frags)
        (d / "briefs" / "m01.lessons.json").write_text("{not json", "utf-8")
        try:
            assemble(d)
            chk(False, "invalid fragment JSON is fatal")
        except AssembleError as e:
            chk("invalid JSON" in str(e), "invalid fragment JSON is fatal")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _fixture(d, mods, frags)
        (d / "briefs" / "m01.lessons.json").write_text('{"id": "a"}', "utf-8")
        try:
            assemble(d)
            chk(False, "a fragment that is not an array is fatal")
        except AssembleError as e:
            chk("JSON array" in str(e), "a fragment that is not an array is fatal")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        try:
            assemble(d)
            chk(False, "a missing skeleton is fatal")
        except AssembleError as e:
            chk("no skeleton" in str(e), "a missing skeleton is fatal")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _fixture(d, mods, frags)
        for f in (d / "briefs").glob("*.json"):
            f.unlink()
        try:
            assemble(d)
            chk(False, "no fragments at all is fatal")
        except AssembleError as e:
            chk("no lesson fragments" in str(e), "no fragments at all is fatal")
    chk(main(["/nonexistent-course-dir-xyz"]) == 2, "CLI exits 2 on ASSEMBLE-FAIL")

    print("ASSEMBLE_MANIFEST SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
