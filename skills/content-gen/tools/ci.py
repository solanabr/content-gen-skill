#!/usr/bin/env python3
"""ci.py — lean CI for the whole course suite (stdlib-only).

  Tier 0  pins      the skill's OWN version pins are fresh, single-sourced, and rendered
                    into verify/Dockerfile (pin_refresh.py). This tier exists because the
                    Dockerfile silently drifted a major version behind the content it
                    verifies; an anti-staleness system needs its own staleness gate.
  Tier 1  gates     tool selftests + validate_course all (incl. drafts) on every
                    course found, + writer-style facts/tells on every draft when
                    the writer-style skill is resolvable
  Tier 2  fixtures  golden bad-manifests must trip their expected flags
  Tier 3  metrics   deterministic per-draft metrics table (words, visuals, walls,
                    time-to-first-do) — the text-block-aesthetics dashboard
  Tier 4  smoke     collect per-lesson verify commands; list them (default) or
                    execute the allowlisted ones with --run-smoke
  Tier 5  verify    compile/run every fenced code block the courses ship
                    (verify_code.py). A real compile/run FAILURE fails the tier;
                    a SKIP (toolchain needs the pinned container) is reported, not
                    failed. Set VERIFY_ENV=docker to run against the pinned image.
  Tier 6  challenge THE PLATFORM CONTRACT: for every coding challenge, the SOLUTION passes
                    every tests.json case and the STARTER fails at least one
                    (verify_challenges.py). This is the one rule the Academy actually
                    executes on every PR, and it was not a CI tier at all.
  Tier 7  blocks    compile every rust/typescript block against the course's DECLARED deps
                    (verify_blocks.py), which verify_code.py has never done for those three
                    languages. Heavy (npm install / cargo build): opt in with --run-blocks.

    python3 ci.py                     # tiers 0-7 (smoke = list only, blocks = listed)
    python3 ci.py --tiers 1,3         # subset
    python3 ci.py --run-smoke         # tier 4 executes allowlisted commands
    python3 ci.py --run-blocks        # tier 7 actually compiles
    python3 ci.py --strict            # SKIP IS NOT PASS: any skipped tier fails

`--strict` exists because this repo learned the hard way that a SKIP counted as green is how
unverified content ships. Under --strict a tier that could not run is a failure, so "GREEN"
always means "everything was actually checked".

Exit 0 = all green; 1 = any failure. Courses discovered under the skill's
examples/ and the repo's content/courses/.
"""
from __future__ import annotations

import argparse
import copy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validate_course as vc                      # noqa: E402
import verify_code as vcode                        # noqa: E402
import verify_challenges as vchal                  # noqa: E402
import verify_blocks as vblocks                    # noqa: E402
import pin_refresh                                 # noqa: E402
from course_lib import load_manifest, flatten_lessons  # noqa: E402

REPO = HERE.parent.parent.parent
# Seeds verify_code's bash tier-3 execution allowlist; kept here because tier 4 (brief verify
# commands) and bash tier 3 must never diverge on what counts as side-effect-free.
SMOKE_ALLOWLIST = {"python3", "python", "shasum", "sha256sum", "printf", "echo", "openssl"}

STRICT = False


def _skip(msg: str) -> bool:
    """A tier that could not run. Green normally, RED under --strict: SKIP is not PASS."""
    print(("FAIL" if STRICT else "skip") + f" - {msg}" + (" [--strict]" if STRICT else ""))
    return not STRICT


def course_dirs() -> list[Path]:
    dirs = []
    for base in (HERE.parent / "examples", REPO / "content" / "courses"):
        if base.is_dir():
            dirs += [d for d in sorted(base.iterdir()) if (d / "manifest.json").is_file()]
    return dirs


WRITER_STYLE_SKILL_NAME = "writer-style"       # the skill dir
WRITER_STYLE_PLUGIN_NAME = "writer-style-skill"  # the repo/plugin that ships it


def _plugin_version_key(p: Path) -> tuple[int, ...]:
    """Sort key for a plugin-cache version dir, so the newest install wins."""
    return tuple(int(s) if s.isdigit() else -1 for s in p.name.split("."))


def writer_style_dir() -> Path | None:
    """Locate the *installed* writer-style skill, or None if it isn't present.

    writer-style is an optional dep (SKILL.md ships a no-writer degradation path),
    so absence is a skip, not a failure. Per SKILL.md's contract we discover it by
    name at runtime — newest release, never a hardcoded absolute path. Order:
    explicit override, installed plugin, user/project skill, sibling dev checkout.
    """
    import os

    cand = [Path(p) for p in [os.environ.get("WRITER_STYLE_SKILL", "")] if p]

    # installed from a marketplace: ~/.claude/plugins/cache/<mkt>/<plugin>/<version>/
    cache = Path.home() / ".claude" / "plugins" / "cache"
    cand += sorted(
        cache.glob(f"*/{WRITER_STYLE_PLUGIN_NAME}/*/skills/{WRITER_STYLE_SKILL_NAME}"),
        key=lambda p: _plugin_version_key(p.parent.parent),
        reverse=True,
    )

    # installed as a user-level or project-level skill
    cand += [Path.home() / ".claude" / "skills" / WRITER_STYLE_SKILL_NAME,
             REPO / ".claude" / "skills" / WRITER_STYLE_SKILL_NAME]

    # dev layout: sibling checkout next to THIS repo (relative, so it isn't one dev's $HOME)
    cand += [REPO.parent / WRITER_STYLE_PLUGIN_NAME / "skills" / WRITER_STYLE_SKILL_NAME]

    for c in cand:
        if (c / "tools" / "validate_voice.py").is_file():
            return c
    return None


def t0_pins() -> bool:
    """The skill's own pins. See pin_refresh.py — this is the recursion guard."""
    rc = pin_refresh.check(do_probe=False, strict_sourcing=True)
    print(("PASS" if rc == 0 else "FAIL") + " - pins fresh, single-sourced, rendered")
    return rc == 0


def t1_gates() -> bool:
    ok = True
    r = subprocess.run([sys.executable, str(HERE / "test_tools.py")],
                       capture_output=True, text=True)
    print(("PASS" if r.returncode == 0 else "FAIL") + " - tool selftests")
    if r.returncode != 0:
        for line in (r.stdout + r.stderr).splitlines():
            if line.startswith("FAIL") or "Error" in line or "Traceback" in line:
                print(f"   {line[:120]}")
    ok = ok and r.returncode == 0

    for d in course_dirs():
        m = load_manifest(d)
        hard = False
        for name, fn in vc.CHECKS.items():
            # a few checks read the course TREE (open fix sweeps), not the manifest
            res = fn(d) if name in getattr(vc, "COURSE_DIR_CHECKS", ()) else fn(m)
            hard = hard or res["hard"]
            for f in res["flags"]:
                if f.startswith(vc.HARD):
                    print(f"   {d.name}/{name}: {f}")
        res = vc.check_drafts(d, m)
        hard = hard or res["hard"]
        for f in res["flags"]:
            if f.startswith(vc.HARD):
                print(f"   {d.name}/drafts: {f}")
        print(("PASS" if not hard else "FAIL") + f" - gate {d.name}")
        ok = ok and not hard

    w = writer_style_dir()
    if w is None:
        return _skip("writer-style not installed (or set WRITER_STYLE_SKILL); "
                     "facts/tells not checked") and ok
    vv = w / "tools" / "validate_voice.py"
    card = w / "profiles" / "kaue" / "kaue.card.yaml"
    for d in course_dirs():
        for draft in sorted((d / "lessons" / "drafts").glob("*.md")):
            facts = d / "lessons" / "facts" / (draft.stem + ".facts.md")
            if facts.is_file():
                r = subprocess.run([sys.executable, str(vv), "diff", "--facts", str(facts),
                                    "--styled", str(draft)], capture_output=True, text=True)
                print(("PASS" if r.returncode == 0 else "FAIL") + f" - facts {d.name}/{draft.name}")
                ok = ok and r.returncode == 0
            if card.is_file():
                r = subprocess.run([sys.executable, str(vv), "tells", "--file", str(draft),
                                    "--card", str(card)], capture_output=True, text=True)
                print(("PASS" if r.returncode == 0 else "FAIL") + f" - tells {d.name}/{draft.name}")
                ok = ok and r.returncode == 0
    return ok


def t2_fixtures() -> bool:
    """Golden bad-manifests: each mutation must trip its expected flag substring."""
    def mut_id(m): m["modules"][0]["id"] = "Not Kebab"
    def mut_surface(m): m["lessons"][0]["research"] = {
        "claims": [{"id": "C1", "mcp": "trust-me-bro", "status": "verified"}]}
    def mut_artifact(m):
        m["lessons"][0]["brief"]["artifact"] = {"id": "a", "consumes": ["b"]}
        m["lessons"][1]["brief"]["artifact"] = {"id": "b"}
    def mut_signature(m): m["lessons"][0]["brief"]["hook"] = "like the Movie Review app"
    def mut_passive(m): m["lessons"][0]["brief"]["assessment"] = "watch the recording"
    def mut_capstone(m): m["assessment"]["capstone"]["requires_skills"] = ["never-taught"]

    fixtures = [
        ("non-kebab id", mut_id, vc.check_dag, "not kebab-case"),
        ("non-kit research surface", mut_surface, vc.check_research, "non-kit surface"),
        ("backward artifact edge", mut_artifact, vc.check_artifacts, "built later"),
        ("corpus signature", mut_signature, vc.check_briefs, "corpus signature"),
        ("passive assessment", mut_passive, vc.check_briefs, "passive"),
        ("untaught capstone skill", mut_capstone, vc.check_capstone, ""),
    ]
    ok = True
    for name, mut, check, needle in fixtures:
        m = copy.deepcopy(vc._good_manifest())
        mut(m)
        res = check(m)
        hit = res["hard"] and (not needle or any(needle in f for f in res["flags"]))
        print(("PASS" if hit else "FAIL") + f" - fixture: {name}")
        ok = ok and hit
    return ok


def t3_metrics() -> bool:
    print(f"{'draft':44} {'words':>5} {'vis':>3} {'types':>2} {'wall':>4} {'1st-do':>6}")
    for d in course_dirs():
        for draft in sorted((d / "lessons" / "drafts").glob("*.md")):
            mx = vc.draft_metrics(draft.read_text("utf-8"))
            first = mx["first_code_words"]
            print(f"{d.name + '/' + draft.stem:44} {mx['prose_words']:>5} "
                  f"{mx['visual_valid']:>3} {len(mx['visual_types']):>2} "
                  f"{mx['longest_wall']:>4} {str(first if first is not None else '-'):>6}")
    return True  # informational; the enforced thresholds live in tier 1's drafts gate


def t4_smoke(run: bool) -> bool:
    ok = True
    found = 0
    for d in course_dirs():
        m = load_manifest(d)
        for l in flatten_lessons(m):
            v = l.get("brief", {}).get("verify")
            if not isinstance(v, dict) or not v.get("command"):
                continue
            found += 1
            cmd = v["command"]
            expect = str(v.get("expect", ""))
            head = shlex.split(cmd.split("|")[0].strip())[0] if cmd.strip() else ""
            allowed = head in SMOKE_ALLOWLIST and "|" not in cmd.replace("| shasum", "").replace(
                "| python3", "").replace("| wc", "")
            # conservative: only single-purpose pipelines of allowlisted tools run
            parts_ok = all(shlex.split(seg.strip())[0] in SMOKE_ALLOWLIST | {"wc"}
                           for seg in cmd.split("|") if seg.strip())
            if run and parts_ok:
                r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=15)
                hit = r.returncode == 0 and (expect in r.stdout if expect else True)
                print(("PASS" if hit else "FAIL") + f" - smoke {l['id']}: {cmd[:60]}")
                ok = ok and hit
            else:
                status = "run-eligible" if parts_ok else "listed (needs live env)"
                print(f"   smoke {l['id']}: {cmd[:70]}  [{status}]")
    print(f"{'PASS' if ok else 'FAIL'} - smoke tier ({found} verify commands found)")
    return ok


def t5_verify() -> bool:
    """Compile/run every fenced code block the courses ship. FAIL fails; SKIP is reported."""
    import os
    if os.environ.get("VERIFY_ENV") == "docker":
        ok = True
        for d in course_dirs():
            rc = vcode.run_docker(str(d), "")
            print(("PASS" if rc == 0 else "FAIL") + f" - verify(docker) {d.name}")
            ok = ok and rc == 0
        return ok
    harness = bool(os.environ.get("VERIFY_HARNESS"))
    ok = True
    for d in course_dirs():
        drafts = d / "lessons" / "drafts"
        rows = []
        for f in sorted(drafts.glob("*.md")):
            rows += vcode.verify_file(f)
        if harness:                                  # heavy: real anchor build + tsc, opt-in
            rows += vcode.run_harness(d)
        fails = [r for r in rows if r[2] == "FAIL"]
        skips = [r for r in rows if r[2] == "SKIP"]
        for fn, blk, _, det in fails:
            print(f"   FAIL {d.name}/{fn} {blk}: {det[:70]}")
        if harness:
            for fn, blk, st, det in rows:
                if blk in ("tsc", "anchor build"):
                    print(f"   {st} {d.name}/{fn}: {det[:70]}")
        n_pass = sum(1 for r in rows if r[2] == "PASS")
        print(("PASS" if not fails else "FAIL")
              + f" - verify {d.name} ({n_pass} PASS · {len(fails)} FAIL · {len(skips)} SKIP)")
        ok = ok and not fails
    print("   (SKIP = declared toolchain unavailable locally; VERIFY_ENV=docker for full coverage)")
    return ok


def t6_challenges() -> bool:
    """THE platform contract: solution passes every test, starter fails at least one.

    verify_challenges.py has proved this since it was written and was never a CI tier, so the
    single rule the Academy executes on every PR was the one rule CI did not check. A SKIP here
    means a toolchain was missing and the contract went UNPROVEN, which under --strict is a
    failure -- "SKIP is not PASS" is a law this repo learned the hard way.
    """
    ok, any_course = True, False
    for d in course_dirs():
        chs = vchal.discover(d)
        if not chs:
            continue
        any_course = True
        rows = [vchal.verify_one(c, d, skip_rust=False) for c in chs]
        fails = [r for r in rows if r["status"] == "FAIL"]
        skips = [r for r in rows if r["status"] == "SKIP"]
        for r in fails:
            print(f"   FAIL {d.name}/{r['tag'][:50]}: {r.get('why', '')[:70]}")
        n_pass = sum(1 for r in rows if r["status"] == "PASS")
        print(("PASS" if not fails else "FAIL")
              + f" - challenges {d.name} ({n_pass} PASS · {len(fails)} FAIL · {len(skips)} SKIP)")
        ok = ok and not fails
        if skips:
            reasons = sorted({(r.get("why") or "toolchain unavailable")[:60] for r in skips})
            ok = _skip(f"challenges {d.name}: {len(skips)} unproven ({'; '.join(reasons)})") and ok
    if not any_course:
        return _skip("no coding challenges found in any course")
    return ok


def t7_blocks(run: bool) -> bool:
    """Compile every rust/typescript block against the course's DECLARED deps.

    verify_blocks.py is 1366 lines with 31 selftests and was referenced by nothing: not
    SKILL.md, not test_tools.py, not ci.py. It is the only thing in the repo that actually
    compiles rust and typescript lesson blocks -- verify_code.py returns SKIP for all three of
    those languages in every environment, container included.

    Heavy (npm install + cargo build per course), so execution is opt-in; the tier always
    reports what it WOULD run, and --strict turns "did not run" into a failure.
    """
    ok, found = True, 0
    have = {"ts": bool(shutil.which("npm")), "rust": bool(shutil.which("cargo"))}
    for d in course_dirs():
        drafts = d / "lessons" / "drafts"
        if not drafts.is_dir():
            continue
        for lang in ("ts", "rust"):
            blocks = vblocks.gather(d, lang)
            if not blocks:
                continue
            found += 1
            cmd = f"python3 tools/verify_blocks.py {d.name} --lang {lang}"
            if not run:
                print(f"   blocks {d.name} --lang {lang}: {len(blocks)} block(s)  [{cmd}]")
                ok = _skip(f"blocks {d.name}/{lang} not compiled (pass --run-blocks)") and ok
                continue
            if not have[lang]:
                ok = _skip(f"blocks {d.name}/{lang}: "
                           f"{'npm' if lang == 'ts' else 'cargo'} not installed") and ok
                continue
            r = subprocess.run([sys.executable, str(HERE / "verify_blocks.py"), str(d),
                                "--lang", lang], capture_output=True, text=True)
            tail = [l for l in r.stdout.splitlines() if "PASS" in l and "FAIL" in l]
            print(("PASS" if r.returncode == 0 else "FAIL")
                  + f" - blocks {d.name} --lang {lang}"
                  + (f" ({tail[-1].strip()})" if tail else ""))
            if r.returncode != 0:
                for line in r.stdout.splitlines():
                    if line.lstrip().startswith("FAIL"):
                        print(f"   {line.strip()[:120]}")
            ok = ok and r.returncode == 0
    if not found:
        return _skip("no rust/typescript blocks found in any course")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="lean CI for the course suite")
    ap.add_argument("--tiers", default="0,1,2,3,4,5,6,7")
    ap.add_argument("--run-smoke", action="store_true",
                    help="tier 4: execute the allowlisted brief verify commands")
    ap.add_argument("--run-blocks", action="store_true",
                    help="tier 7: actually compile rust/ts blocks (npm install + cargo build)")
    ap.add_argument("--exec-bash", action="store_true",
                    help="tier 5: enable bash tier 3 (run execution-allowlisted blocks)")
    ap.add_argument("--strict", action="store_true",
                    help="SKIP IS NOT PASS: any tier that could not run fails the build")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    globals()["STRICT"] = a.strict
    if a.exec_bash:
        vcode.BASH_EXEC = True
    tiers = {t.strip() for t in a.tiers.split(",")}
    ok = True
    if "0" in tiers:
        print("== tier 0: pins =="); ok = t0_pins() and ok
    if "1" in tiers:
        print("== tier 1: gates =="); ok = t1_gates() and ok
    if "2" in tiers:
        print("== tier 2: fixtures =="); ok = t2_fixtures() and ok
    if "3" in tiers:
        print("== tier 3: metrics =="); t3_metrics()
    if "4" in tiers:
        print("== tier 4: smoke =="); ok = t4_smoke(a.run_smoke) and ok
    if "5" in tiers:
        print("== tier 5: verify =="); ok = t5_verify() and ok
    if "6" in tiers:
        print("== tier 6: challenge contract =="); ok = t6_challenges() and ok
    if "7" in tiers:
        print("== tier 7: block compile =="); ok = t7_blocks(a.run_blocks) and ok
    print("\nCI: " + ("GREEN" if ok else "RED") + (" (--strict)" if a.strict else ""))
    return 0 if ok else 1


def selftest() -> int:
    """Guards writer-style discovery: order, fall-through, version sort, graceful skip."""
    import os
    import tempfile

    ok = True

    def chk(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    # version sort: numeric, so 1.10.0 beats 1.9.0 (a plain string sort gets this wrong)
    k = _plugin_version_key
    order = sorted([Path("a/1.9.0"), Path("a/1.10.0"), Path("a/1.2.0")], key=k, reverse=True)
    chk([p.name for p in order] == ["1.10.0", "1.9.0", "1.2.0"], "plugin version sort is numeric")
    chk(k(Path("a/1.0.0-beta")) < k(Path("a/1.0.0")), "prerelease sorts below release")

    prev = os.environ.pop("WRITER_STYLE_SKILL", None)
    home, repo = Path.home, REPO
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # an explicit, valid override wins outright
            fake = root / "override" / "skills" / "writer-style" / "tools"
            fake.mkdir(parents=True)
            (fake / "validate_voice.py").write_text("")
            os.environ["WRITER_STYLE_SKILL"] = str(fake.parent)
            chk(writer_style_dir() == fake.parent, "explicit override wins")

            # a bogus override degrades to discovery instead of hard-failing
            globals()["REPO"] = root / "repo"
            Path.home = staticmethod(lambda: root / "home")          # type: ignore[method-assign]
            os.environ["WRITER_STYLE_SKILL"] = str(root / "nope")
            chk(writer_style_dir() is None, "bogus override falls through")

            # sibling dev checkout is found relative to REPO, not to $HOME
            sib = root / "writer-style-skill" / "skills" / "writer-style" / "tools"
            sib.mkdir(parents=True)
            (sib / "validate_voice.py").write_text("")
            del os.environ["WRITER_STYLE_SKILL"]
            chk(writer_style_dir() == sib.parent, "sibling checkout found via REPO, not $HOME")

            # nothing anywhere -> None, so the gates skip rather than crash.
            # Nest one level down so REPO.parent has no sibling checkout either.
            globals()["REPO"] = root / "deep" / "elsewhere"
            chk(writer_style_dir() is None, "absent writer-style degrades to skip")
    finally:
        Path.home, globals()["REPO"] = home, repo                    # type: ignore[method-assign]
        os.environ.pop("WRITER_STYLE_SKILL", None)
        if prev is not None:
            os.environ["WRITER_STYLE_SKILL"] = prev

    # ── --strict: SKIP is not PASS ──
    # _skip() prints; capture it so the probe's own "FAIL - ... [--strict]" line does not read
    # as a real failure in test_tools.py output.
    import contextlib
    import io
    prev_strict = globals()["STRICT"]
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            globals()["STRICT"] = False
            lenient = _skip("probe")
            globals()["STRICT"] = True
            strict = _skip("probe")
        chk(lenient is True, "a skipped tier is green by default")
        chk(strict is False, "a skipped tier is RED under --strict")
        chk("[--strict]" in buf.getvalue(), "a strict-mode skip says why it failed")
    finally:
        globals()["STRICT"] = prev_strict

    # ── the two formerly-orphaned verifiers are reachable AND wired ──
    # Both were fully working and referenced by nothing. Importability is not the point; being
    # a tier is. These assertions are what stops either of them going orphan again.
    chk(callable(getattr(vchal, "verify_one", None)) and callable(getattr(vchal, "discover", None)),
        "verify_challenges' contract API is importable")
    chk(callable(getattr(vblocks, "gather", None)), "verify_blocks' block gatherer is importable")
    src = Path(__file__).read_text("utf-8")
    for name, tier in (("vchal.verify_one", "6"), ("vblocks.gather", "7"),
                       ("pin_refresh.check", "0")):
        chk(name in src, f"tier {tier} actually calls {name}")
    chk("t6_challenges" in src and "t7_blocks" in src and "t0_pins" in src,
        "tiers 0/6/7 are defined")
    for t in ("0", "6", "7"):
        chk(f'"{t}" in tiers' in src, f"tier {t} is dispatched from main()")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
