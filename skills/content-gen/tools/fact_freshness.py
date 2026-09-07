#!/usr/bin/env python3
"""fact_freshness.py — per-claim expiry for a course's research scaffolds.

The skill grounds facts once, at authoring time, and then nothing ever looks again. An
audit of five generated courses found six shipped defects that were all the same defect:
a fact that was true when written and expired quietly. Rent constants matching no live
cluster, a rent mechanism the runtime now rejects, a dead API taught as live, an archived
repo called "the living reference". Each was verified once and then trusted forever.

This tool is the "look again" half. `lesson.research.claims[]` now carries `verified_on`,
a per-kind `ttl_days`, and a runnable `recheck` probe (vocabulary and defaults in
course_lib.py, evidence in method/fact-recheck.md); this reads them.

    report   what every claim's expiry looks like, per course, with a summary
    stale    ONLY the expired ones; exit 1 if there are any  ← the publish gate
    probes   the re-check dispatch list, ordered, with each claim's exact probe

    python3 fact_freshness.py report --course content/courses/<id>
    python3 fact_freshness.py stale  --course content/courses/<id>
    python3 fact_freshness.py probes --course content/courses/<id> --include-aging
    python3 fact_freshness.py --selftest

`--as-of YYYY-MM-DD` pins "today" (deterministic in tests and for asking "what would this
have said at publish time"). `--ttl kind=days` overrides a default for one run, which is
how the shipped TTL table was calibrated against the real corpus rather than guessed.

Reads the manifest as source of truth and RECONCILES against the on-disk
`lessons/research/*.research.yaml`, because a hand-edited scaffold is exactly where a
re-verification gets recorded. Divergence is reported, and `stale` is fail-closed: if
either copy says a claim is expired, it is expired.

Stdlib only. YAML comes in through pin_refresh.py's restricted reader — one YAML subset
in this toolchain, not two.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from course_lib import (  # noqa: E402
    AGING_FRACTION, CLAIM_KINDS, FRESHNESS_EPOCH, LIVE_CLAIM_STATUSES,
    RECHECK_ADVISORY_KINDS, RECHECK_REQUIRED_KINDS, TTL_DAYS, TTL_DEFAULT_DAYS,
    claim_freshness, course_ttl_policy, load_manifest, parse_iso_date, undated_deadline,
)
from pin_refresh import load_yaml  # noqa: E402

STATE_RANK = {"stale": 0, "aging": 1, "fresh": 2}


# ── loading ─────────────────────────────────────────────────────────────────────

_STEM_PREFIX = re.compile(r"^m\d+-l\d+[a-z]?-")


def _resolve_lesson(candidates: list[str], known: set[str]) -> str:
    """Best manifest lesson id for a research file.

    Scaffolded filenames are `m{NN}-l{N}-{lesson-id}.research.yaml`, and at least one course
    in the corpus copied that whole stem into `lesson_id` instead of the id. So try the
    declared id, then the filename, then both with the `mNN-lN-` prefix stripped. Anything
    still unmatched is reported as an orphan rather than dropped.
    """
    for c in candidates:
        if c in known:
            return c
    for c in candidates:
        s = _STEM_PREFIX.sub("", c)
        if s in known:
            return s
    return candidates[0]


def _research_from_disk(course_dir: Path, known: set[str]) -> dict[str, list[dict]]:
    """{lesson_id: [claim, ...]} harvested from lessons/research/*.research.yaml.
    A file this reader refuses is reported, never silently skipped."""
    out: dict[str, list[dict]] = {}
    rd = Path(course_dir) / "lessons" / "research"
    if not rd.is_dir():
        return out
    for f in sorted(rd.glob("*.yaml")):
        try:
            y = load_yaml(f.read_text("utf-8")) or {}
        except Exception as e:                                          # noqa: BLE001
            out.setdefault("!unreadable", []).append({"id": f.name, "claim": f"{type(e).__name__}: {e}"})
            continue
        r = (y.get("research") if isinstance(y, dict) else None) or y or {}
        if not isinstance(r, dict):
            continue
        stem = f.stem[:-9] if f.stem.endswith(".research") else f.stem
        lid = _resolve_lesson([str(x) for x in (r.get("lesson_id"), stem) if x], known)
        for c in (r.get("claims") or []):
            if isinstance(c, dict):
                out.setdefault(lid, []).append(c)
    return out


def collect(course_dir: str | Path | None, manifest_path: str | Path | None,
            as_of: _dt.date) -> dict:
    """One course's freshness rows, reconciled across manifest + on-disk research.

    Returns {course, rows[], lessons, lessons_with_research, vacuous[], drift[], unreadable[]}.
    A row is a `claim_freshness` dict plus lesson/source keys.
    """
    src = manifest_path or course_dir
    m = load_manifest(src)
    cid = (m.get("course") or {}).get("id") or Path(str(src)).name
    pol = course_ttl_policy(m)
    known = {str(l.get("id")) for l in (m.get("lessons") or [])}
    disk = _research_from_disk(Path(course_dir), known) if course_dir else {}
    unreadable = [c["id"] for c in disk.pop("!unreadable", [])]

    rows: list[dict] = []
    drift: list[str] = []
    vacuous: list[str] = []
    seen: set[tuple[str, str]] = set()
    n_lessons = 0
    n_research = 0

    for l in m.get("lessons", []) or []:
        n_lessons += 1
        lid = str(l.get("id") or "?")
        r = l.get("research") or {}
        if r:
            n_research += 1
        claims = [c for c in (r.get("claims") or []) if isinstance(c, dict)]
        on_disk = {str(c.get("id")): c for c in disk.get(lid, [])}
        for c in claims:
            row = claim_freshness(c, as_of, policy=pol, lesson_id=lid)
            row.update(lesson=lid, source="manifest")
            cid_ = str(c.get("id"))
            twin = on_disk.get(cid_)
            if twin is not None:
                trow = claim_freshness(twin, as_of, policy=pol, lesson_id=lid)
                if trow["verified_on"] != row["verified_on"]:
                    drift.append(f"{lid}/{cid_}: manifest verified_on={row['verified_on']} "
                                 f"but research.yaml says {trow['verified_on']}")
                # fail-closed: the more expired of the two wins
                if STATE_RANK[trow["state"]] < STATE_RANK[row["state"]]:
                    row["state"] = trow["state"]
                    row["source"] = "manifest+yaml(worse)"
            rows.append(row)
            seen.add((lid, cid_))
        # claims that exist only on disk are still shipped content
        for c in disk.get(lid, []):
            key = (lid, str(c.get("id")))
            if key in seen:
                continue
            row = claim_freshness(c, as_of, policy=pol, lesson_id=lid)
            row.update(lesson=lid, source="yaml-only")
            rows.append(row)
            seen.add(key)
        if r and not claims and not disk.get(lid):
            # A research scaffold with frozen_facts but no claims: the freshness gate has
            # nothing to check here, and green means "nothing was checked", not "all fresh".
            if r.get("frozen_facts"):
                vacuous.append(lid)
        disk.pop(lid, None)

    # research files whose lesson_id matches no manifest lesson. Those claims are real and
    # still expire; dropping them silently is how a fail-closed gate quietly fails open.
    for lid, claims in disk.items():
        for c in claims:
            row = claim_freshness(c, as_of, policy=pol, lesson_id=lid)
            row.update(lesson=lid, source="yaml-orphan")
            rows.append(row)
            drift.append(f"{lid}/{c.get('id')}: research.yaml lesson_id '{lid}' matches no "
                         f"lesson in the manifest — still counted, still expires")

    rows.sort(key=lambda r: (STATE_RANK[r["state"]], -r["age_days"], r["lesson"], r["id"]))
    return {"course": cid, "dir": str(course_dir or src), "rows": rows, "policy": pol,
            "lessons": n_lessons, "lessons_with_research": n_research,
            "vacuous": vacuous, "drift": drift, "unreadable": unreadable}


# ── rendering ───────────────────────────────────────────────────────────────────

def _tally(rows: list[dict]) -> dict:
    live = [r for r in rows if r["live"]]
    return {
        "claims": len(rows), "live": len(live),
        "stale": sum(1 for r in live if r["state"] == "stale"),
        "aging": sum(1 for r in live if r["state"] == "aging"),
        "fresh": sum(1 for r in live if r["state"] == "fresh"),
        "undated": sum(1 for r in live if r["undated"]),
        "no_kind": sum(1 for r in live if not r["kind"]),
        "missing_recheck": sum(1 for r in live
                               if r["kind"] in RECHECK_REQUIRED_KINDS and not r["recheck"]),
    }


def _line(r: dict) -> str:
    mark = {"stale": "STALE", "aging": "aging", "fresh": "fresh"}[r["state"]]
    when = r["verified_on"] or f"undated({FRESHNESS_EPOCH})"
    kind = r["kind"] or "?kind"
    return (f"  {mark:5}  {r['lesson']}/{r['id']:<4} {kind:<15} "
            f"{r['age_days']:>4}d / ttl {r['ttl']:<4} verified_on {when}")


def report(courses: list[dict], as_of: _dt.date, out_json: str | None = None) -> int:
    total = {k: 0 for k in ("claims", "live", "stale", "aging", "fresh", "undated",
                            "no_kind", "missing_recheck")}
    n_vacuous = 0
    for c in courses:
        t = _tally(c["rows"])
        for k in total:
            total[k] += t[k]
        n_vacuous += len(c["vacuous"])
        shipped = "" if t["live"] == t["claims"] else f" of {t['claims']}"
        head = (f"{c['course']}: {t['live']}{shipped} shipping claim(s) — {t['stale']} stale, "
                f"{t['aging']} aging, {t['fresh']} fresh  "
                f"({c['lessons_with_research']}/{c['lessons']} lessons carry a research scaffold)")
        print(head)
        for r in c["rows"]:
            if r["live"]:
                print(_line(r))
        for lid in c["vacuous"]:
            print(f"  ----   {lid}: research scaffold has frozen_facts but ZERO claims — "
                  f"nothing here is on any clock")
        for d in c["drift"]:
            print(f"  DRIFT  {d}")
        for u in c["unreadable"]:
            print(f"  ERROR  unreadable research file: {u}")
        print()

    print(f"as of {as_of.isoformat()}  (epoch {FRESHNESS_EPOCH}, undated claims harden "
          f"{undated_deadline().isoformat()})")
    print(f"TOTAL {total['live']} shipping claim(s) of {total['claims']} over "
          f"{len(courses)} course(s): {total['stale']} stale / {total['aging']} aging / "
          f"{total['fresh']} fresh  (non-shipping = refuted/unverified/gathering)")
    print(f"      {total['undated']} carry no verifiable date, {total['no_kind']} declare no kind, "
          f"{total['missing_recheck']} need a recheck probe and have none")
    if n_vacuous:
        print(f"      {n_vacuous} lesson(s) have a research scaffold with frozen_facts and no "
              f"claims — the gate is silent there BECAUSE NOTHING IS DECLARED, not because "
              f"the facts are fresh")
    if out_json:
        Path(out_json).write_text(json.dumps(
            {"as_of": as_of.isoformat(), "epoch": FRESHNESS_EPOCH, "total": total,
             "courses": courses}, indent=2, default=str), "utf-8")
        print(f"      wrote {out_json}")
    return 0


def stale(courses: list[dict], as_of: _dt.date) -> int:
    hits = [(c, r) for c in courses for r in c["rows"] if r["live"] and r["state"] == "stale"]
    if not hits:
        n = sum(len(c["rows"]) for c in courses)
        vac = sum(len(c["vacuous"]) for c in courses)
        print(f"fact-freshness: PASS — 0 of {n} claim(s) past TTL as of {as_of.isoformat()}")
        if vac:
            print(f"  note: {vac} lesson(s) declare frozen_facts and no claims; those facts are "
                  f"on no clock at all (fact_freshness.py report names them)")
        return 0
    print(f"fact-freshness: FAIL — {len(hits)} claim(s) past TTL as of {as_of.isoformat()}")
    for c, r in hits:
        print(f"  {c['course']}  " + _line(r).strip())
    print("\nRe-probe them (fact_freshness.py probes), then update verified_on. A publish that "
          "cannot wait uses academy_export.py --allow-stale, which stamps the staleness into "
          "the export summary instead of hiding it.")
    return 1


def probes(courses: list[dict], as_of: _dt.date, include_aging: bool = False) -> int:
    want = {"stale"} | ({"aging"} if include_aging else set())
    hits = [(c, r) for c in courses for r in c["rows"] if r["live"] and r["state"] in want]
    print(f"# fact re-check dispatch — {len(hits)} claim(s), as of {as_of.isoformat()}")
    print(f"# Work top-down. Dispatch each probe to the surface named in `mcp` "
          f"(references/research-grounding.md).")
    print(f"# A claim that comes back CHANGED triggers a full sweep of that value across the "
          f"course, not a single-line edit (method/fact-recheck.md).\n")
    if not hits:
        print("# nothing to re-check.")
        return 0
    for c, r in hits:
        print(f"{r['state'].upper():5} {c['course']}  {r['lesson']}/{r['id']}  "
              f"[{r['kind'] or '?kind'}]  age {r['age_days']}d of {r['ttl']}d")
        claim = str(r["claim"] or "").replace("\n", " ")
        print(f"  claim:   {claim[:160]}")
        print(f"  surface: {r['mcp'] or '(none recorded — pick one from research-grounding.md)'}")
        if r["recheck"]:
            print(f"  recheck: {r['recheck']}")
        elif r["kind"] in RECHECK_REQUIRED_KINDS:
            print(f"  recheck: !! MISSING — this kind cannot ship without a runnable probe")
        elif r["urls"]:
            print(f"  recheck: (none recorded) try: curl -sSI {r['urls'][0]}")
        else:
            print(f"  recheck: (none recorded)")
        print()
    return 0


# ── cli ─────────────────────────────────────────────────────────────────────────

def _apply_ttl_overrides(specs: list[str]) -> None:
    for s in specs or []:
        k, _, v = str(s).partition("=")
        k = k.strip()
        if k not in CLAIM_KINDS or not v.strip().isdigit():
            raise SystemExit(f"fact_freshness: bad --ttl {s!r}; want kind=days with kind in "
                             f"{sorted(CLAIM_KINDS)}")
        TTL_DAYS[k] = int(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="per-claim expiry for course research scaffolds")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("report", "stale", "probes"):
        p = sub.add_parser(name)
        p.add_argument("--course", action="append", default=[],
                       help="course dir (repeatable); reads manifest.json + lessons/research/")
        p.add_argument("--manifest", help="a bare manifest.json instead of a course dir")
        p.add_argument("--as-of", help="pin today as YYYY-MM-DD")
        p.add_argument("--ttl", action="append", default=[], metavar="KIND=DAYS",
                       help="override one kind's TTL for this run (calibration)")
        if name == "report":
            p.add_argument("--json", dest="out_json", help="also write the full table as JSON")
        if name == "probes":
            p.add_argument("--include-aging", action="store_true",
                           help="also list claims past 0.75x TTL")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd not in ("report", "stale", "probes"):
        ap.print_help()
        return 2

    as_of = parse_iso_date(a.as_of) if a.as_of else _dt.date.today()
    if a.as_of and not as_of:
        raise SystemExit(f"fact_freshness: --as-of must be YYYY-MM-DD, got {a.as_of!r}")
    _apply_ttl_overrides(a.ttl)

    if not a.course and not a.manifest:
        raise SystemExit("fact_freshness: need --course DIR (repeatable) or --manifest FILE")
    courses = [collect(d, None, as_of) for d in a.course]
    if a.manifest:
        courses.append(collect(None, a.manifest, as_of))

    if a.cmd == "report":
        return report(courses, as_of, a.out_json)
    if a.cmd == "stale":
        return stale(courses, as_of)
    return probes(courses, as_of, a.include_aging)


# ── selftest ────────────────────────────────────────────────────────────────────

def selftest() -> int:
    import tempfile
    ok = True

    def check(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    D = _dt.date
    NOW = D(2026, 9, 7)

    man = {
        "course": {"id": "demo"},
        "lessons": [
            {"id": "l1", "research": {"lesson_id": "l1", "claims": [
                {"id": "C1", "kind": "onchain-number", "status": "verified",
                 "verified_on": "2026-08-01", "recheck": "rpc getMinimumBalanceForRentExemption 165",
                 "claim": "ATA rent-exempt minimum", "mcp": "helius"},
                {"id": "C2", "kind": "concept", "status": "verified",
                 "verified_on": "2026-09-01", "claim": "DigiCash filed Chapter 11 in 1998"},
                {"id": "C3", "kind": "api", "status": "verified", "claim": "jup quote endpoint",
                 "evidence": "https://station.jup.ag/docs"},
            ]}},
            {"id": "l2", "research": {"lesson_id": "l2",
                                      "frozen_facts": ["890,880", "2,282,880"]}},
        ],
    }

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "demo"
        (root / "lessons" / "research").mkdir(parents=True)
        (root / "manifest.json").write_text(json.dumps(man), "utf-8")

        c = collect(root, None, NOW)
        by = {r["id"]: r for r in c["rows"]}
        check(len(c["rows"]) == 3, "collect finds every manifest claim")
        check(by["C1"]["state"] == "stale" and by["C1"]["age_days"] == 37,
              "a 37-day-old on-chain number is past its 14-day TTL")
        check(by["C2"]["state"] == "fresh", "a 6-day-old concept is fresh")
        check(by["C3"]["undated"] and by["C3"]["state"] == "fresh",
              "an undated claim starts at the epoch rather than failing on day one")
        check(c["vacuous"] == ["l2"],
              "a scaffold with frozen_facts and no claims is reported as vacuous, not as clean")
        check(_tally(c["rows"])["missing_recheck"] == 0, "C1 has its probe")

        check(stale([c], NOW) == 1, "stale exits non-zero when a claim is past TTL")
        check(stale([collect(root, None, D(2026, 8, 5))], D(2026, 8, 5)) == 0,
              "…and exits 0 four days after verification")
        check(probes([c], NOW) == 0, "probes always exits 0 — it is a worklist, not a gate")
        check(report([c], NOW) == 0, "report always exits 0")

        # on-disk research the manifest does not carry is still shipped content
        (root / "lessons" / "research" / "m00-l3.research.yaml").write_text(
            "research:\n  lesson_id: l1\n  claims:\n    - id: C9\n      kind: version-pin\n"
            "      status: verified\n      verified_on: \"2026-01-01\"\n"
            "      claim: \"anchor 0.31.1\"\n", "utf-8")
        c2 = collect(root, None, NOW)
        c9 = [r for r in c2["rows"] if r["id"] == "C9"]
        check(len(c9) == 1 and c9[0]["source"] == "yaml-only" and c9[0]["state"] == "stale",
              "a claim that exists only in research.yaml is still collected and still expires")

        # drift: the same claim id, two different dates -> reported, worse one wins
        (root / "lessons" / "research" / "m00-l1.research.yaml").write_text(
            "research:\n  lesson_id: l1\n  claims:\n    - id: C2\n      kind: concept\n"
            "      status: verified\n      verified_on: \"2020-01-01\"\n", "utf-8")
        c3 = collect(root, None, NOW)
        row_c2 = [r for r in c3["rows"] if r["id"] == "C2"][0]
        check(any("C2" in d for d in c3["drift"]), "manifest/yaml date drift is reported")
        check(row_c2["state"] == "stale",
              "reconciliation is fail-closed: the more expired copy wins")

        # a research file naming a lesson the manifest does not have is still counted
        (root / "lessons" / "research" / "ghost.research.yaml").write_text(
            "research:\n  lesson_id: not-a-lesson\n  claims:\n    - id: G1\n"
            "      kind: cli-default\n      status: verified\n"
            "      verified_on: \"2020-01-01\"\n      claim: \"solana config get\"\n", "utf-8")
        c4 = collect(root, None, NOW)
        g1 = [r for r in c4["rows"] if r["id"] == "G1"]
        check(len(g1) == 1 and g1[0]["source"] == "yaml-orphan" and g1[0]["state"] == "stale",
              "a research file naming an unknown lesson is counted, not silently dropped")
        check(any("matches no" in d for d in c4["drift"]), "…and the orphan is reported")

        # a research file this reader refuses is surfaced, not skipped
        (root / "lessons" / "research" / "bad.research.yaml").write_text(
            "research:\n  claims: {inline: mapping}\n", "utf-8")
        check(collect(root, None, NOW)["unreadable"] == ["bad.research.yaml"],
              "an unparseable research file is reported, never silently dropped")

    # ttl overrides drive the calibration sweeps
    before = TTL_DAYS["api"]
    _apply_ttl_overrides(["api=45"])
    check(TTL_DAYS["api"] == 45, "--ttl overrides a kind default")
    TTL_DAYS["api"] = before
    try:
        _apply_ttl_overrides(["nonsense=5"])
        check(False, "a bad --ttl kind is refused")
    except SystemExit:
        check(True, "a bad --ttl kind is refused")

    check(0 < AGING_FRACTION < 1 and TTL_DEFAULT_DAYS in TTL_DAYS.values(),
          "freshness constants are sane")
    check(RECHECK_ADVISORY_KINDS and LIVE_CLAIM_STATUSES == {"verified", "user-attested"},
          "shipping statuses are the ones that expire")

    print("\n" + ("FACT_FRESHNESS SELFTESTS PASSED" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
