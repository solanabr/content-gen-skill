#!/usr/bin/env python3
"""verify_code.py — actually compile/run the code a piece ships, so "run-first" is TRUE.

Generated content (courses, tutorials, walkthroughs…) is full of code the reader is
told to run. LLM generation writes plausible-but-uncompiled code; the structure/voice/
facts gates never execute it, so compile-breaking bugs ship (a non-compiling CpiContext,
an ImportError, a missing __main__ guard, a forge-init that clobbers its own test). This
tool closes that gap: it extracts every fenced code block (and each brief's `verify`
command), and compiles/runs it in a real toolchain, reporting PASS / FAIL / SKIP.

Two environments:
  --env local   run against the toolchains installed on this machine (fast; versions
                may not match what the content declares — mismatches are reported)
  --env docker  run inside the pinned image built from skills/content-gen/verify/Dockerfile
                (reproducible; versions match the content's declared toolchain) — the
                CORRECT default for a real gate.

    python3 verify_code.py <course-or-content-dir> [--env local|docker] [--only py,sol,bash]
    python3 verify_code.py <dir> --run-smoke      # also run each brief's verify command
    python3 verify_code.py --file <one.md>
    python3 verify_code.py --selftest

Exit 0 = every runnable unit PASSED or SKIPPED; 1 = a real compile/run FAILURE; 2 = usage.
A SKIP (toolchain/deps/network unavailable) never fails the run but is reported loudly, so
"green" cannot silently mean "nothing was checked."
"""
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE = "content-gen-verify"   # built from verify/Dockerfile

# fence info-string -> canonical language
LANGS = {"py": "python", "python": "python", "sh": "bash", "bash": "bash", "shell": "bash",
         "console": "bash", "sol": "solidity", "solidity": "solidity", "rs": "rust",
         "rust": "rust", "ts": "typescript", "tsx": "typescript", "typescript": "typescript",
         "js": "javascript", "javascript": "javascript", "json": "json", "toml": "toml"}


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 120), **kw)


def extract_blocks(md: str, keep_info: bool = False):
    """Yield (lang, code) for every non-visual fenced block with a known language.

    keep_info=True yields (lang, code, info) so callers can recover the raw fence tag
    that LANGS collapses (e.g. tsx -> typescript, which needs a .tsx compile target).
    """
    lines, i, out = md.split("\n"), 0, []
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```") and s != "```":
            info = s[3:].strip().lower()
            j, body = i + 1, []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                body.append(lines[j]); j += 1
            lang = LANGS.get(info)
            if lang:
                out.append((lang, "\n".join(body), info) if keep_info
                           else (lang, "\n".join(body)))
            i = j + 1
        else:
            i += 1
    return out


# ---- per-language checkers: return (status, detail). status in PASS/FAIL/SKIP ----

def _looks_fragment_python(code: str) -> bool:
    # a fragment can't compile standalone: an indented first line (a body lifted out of its
    # scope) or a leading continuation keyword. A top-level `def`/`class` IS a valid module.
    first = next((l for l in code.split("\n") if l.strip() and not l.strip().startswith("#")), "")
    if first.startswith((" ", "\t")):
        return True
    tok = first.strip().split()[0].rstrip(":") if first.strip() else ""
    return tok in {"return", "yield", "elif", "else", "except", "finally"}


def check_python(code):
    if not shutil.which("python3"):
        return "SKIP", "python3 not installed"
    if _looks_fragment_python(code):
        return "SKIP", "fragment (not a standalone module)"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code); path = f.name
    r = _run(["python3", "-m", "py_compile", path])
    Path(path).unlink(missing_ok=True)
    return ("PASS", "py_compile ok") if r.returncode == 0 else ("FAIL", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "syntax error")


# <placeholder>/<UPPER-CASE> tokens in a usage synopsis (e.g. `solana confirm <SIGNATURE>`)
# read as stdin redirects to bash -n and cause false syntax errors. Real redirects
# (`<<EOF`, `< input.txt`, `2>&1`, `<&3`) need a space/digit/`<` after `<` and are untouched.
_PLACEHOLDER = re.compile(r"<[A-Za-z][\w./-]*>")


def check_bash(code):
    if not shutil.which("bash"):
        return "SKIP", "bash not installed"
    r = _run(["bash", "-n"], input=_PLACEHOLDER.sub("PLACEHOLDER", code))
    return ("PASS", "bash -n ok") if r.returncode == 0 else ("FAIL", (r.stderr.strip().splitlines() or ["syntax error"])[-1])


def check_json(code):
    import json as _j
    try:
        _j.loads(code); return "PASS", "valid json"
    except Exception as e:
        return "FAIL", str(e)


def check_solidity(code):
    if "contract " not in code and "library " not in code and "interface " not in code:
        return "SKIP", "solidity fragment (no contract)"
    if not shutil.which("forge"):
        return "SKIP", "forge (Foundry) not installed"
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        (dp / "src").mkdir()
        (dp / "foundry.toml").write_text("[profile.default]\nsrc = 'src'\nout = 'out'\n")
        (dp / "src" / "C.sol").write_text(code if code.lstrip().startswith(("//", "pragma"))
                                          else "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n" + code)
        r = _run(["forge", "build", "--root", str(dp)], timeout=180)
        if r.returncode == 0:
            return "PASS", "forge build ok"
        err = (r.stderr + r.stdout).lower()
        if "failed to resolve" in err or "no solc" in err or "could not download" in err or "offline" in err:
            return "SKIP", "solc unavailable (forge svm needs network) — run in --env docker"
        return "FAIL", (r.stderr + r.stdout).strip().splitlines()[-1] if (r.stderr + r.stdout).strip() else "compile error"


def check_toml(code):
    try:
        import tomllib
    except ModuleNotFoundError:
        return "SKIP", "tomllib needs python 3.11+"
    try:
        tomllib.loads(code); return "PASS", "valid toml"
    except Exception as e:
        return "FAIL", str(e).splitlines()[0]


def check_container_lang(lang):
    # rust/anchor & typescript need the content's DECLARED versions + fetched deps;
    # only trustworthy in the pinned container. Never FAIL locally on a version mismatch.
    def _c(code):
        return "SKIP", f"{lang}: verify in --env docker (declared toolchain + deps)"
    return _c


CHECKERS = {"python": check_python, "bash": check_bash, "json": check_json,
            "solidity": check_solidity, "rust": check_container_lang("rust"),
            "typescript": check_container_lang("typescript"),
            "javascript": check_container_lang("javascript"), "toml": check_toml}


def verify_file(path: Path, only=None):
    rows = []
    for n, (lang, code) in enumerate(extract_blocks(path.read_text("utf-8")), 1):
        if only and lang not in only:
            continue
        status, detail = CHECKERS.get(lang, lambda c: ("SKIP", "no checker"))(code)
        rows.append((path.name, f"{lang}#{n}", status, detail))
    return rows


def _tail(r):
    out = (r.stdout + r.stderr).strip().splitlines()
    return out[-1][:80] if out else ""


def run_harness(content_dir: Path):
    """Run a piece's REAL-toolchain harnesses if present: a materialized project that
    actually compiles the code the lessons show. Convention (mirror the drafts into a
    buildable project, kept beside the content, gitignored):
      <dir>/verify-ts/        a tsc project (its node_modules ships a local tsc)
      <dir>/verify-anchor/*/  one or more `anchor init` workspaces (Anchor.toml)
    PASS/FAIL is a real compile result; SKIP means the harness or toolchain is absent."""
    content_dir = Path(content_dir).resolve()        # absolute, so cwd-relative exec resolves
    rows = []
    ts = content_dir / "verify-ts"
    if ts.is_dir():
        tsc = ts / "node_modules" / ".bin" / "tsc"
        if tsc.exists():
            r = _run([str(tsc), "--noEmit"], cwd=str(ts), timeout=300)
            rows.append(("verify-ts", "tsc", "PASS" if r.returncode == 0 else "FAIL",
                         "tsc --noEmit clean" if r.returncode == 0 else _tail(r)))
        else:
            rows.append(("verify-ts", "tsc", "SKIP", "no node_modules — run `npm install` in verify-ts/"))
    va = content_dir / "verify-anchor"
    if va.is_dir():
        for toml in sorted(va.glob("*/Anchor.toml")):
            proj = toml.parent
            if shutil.which("anchor"):
                r = _run(["anchor", "build"], cwd=str(proj), timeout=600)
                rows.append((f"verify-anchor/{proj.name}", "anchor build",
                             "PASS" if r.returncode == 0 else "FAIL",
                             "anchor build ok" if r.returncode == 0 else _tail(r)))
            else:
                rows.append((f"verify-anchor/{proj.name}", "anchor build", "SKIP", "anchor not installed"))
    return rows


def run_docker(target, extra):
    if not shutil.which("docker"):
        print("docker not installed — build the image where Docker is available:\n"
              f"  docker build -t {IMAGE} {HERE.parent}/verify\n"
              f"  docker run --rm -v <repo>:/work {IMAGE} python3 "
              f"skills/content-gen/tools/verify_code.py {target} --env local {extra}", file=sys.stderr)
        return 2
    repo = HERE.parent.parent.parent
    # --entrypoint: the image's ENTRYPOINT is already this script; without the override the
    # command below would be appended to it and every argument would arrive duplicated.
    cmd = ["docker", "run", "--rm", "--entrypoint", "python3",
           "-v", f"{repo}:/work", "-w", "/work", IMAGE,
           "skills/content-gen/tools/verify_code.py", target, "--env", "local"] + extra.split()
    return subprocess.run(cmd).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="compile/run the code a piece ships")
    ap.add_argument("target", nargs="?", help="course/content dir (verifies lessons/drafts/*.md) or a dir of *.md")
    ap.add_argument("--file", help="a single markdown file")
    ap.add_argument("--env", choices=["local", "docker"], default="local")
    ap.add_argument("--only", help="comma list: py,bash,sol,ts,rust,json")
    ap.add_argument("--run-smoke", action="store_true", help="also run each brief's verify command")
    ap.add_argument("--harness", action="store_true",
                    help="run the piece's real-toolchain harnesses: verify-ts/ (tsc) + verify-anchor/*/ (anchor build)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.env == "docker":
        extra = " ".join(x for x in [f"--only {a.only}" if a.only else "", "--run-smoke" if a.run_smoke else ""] if x)
        return run_docker(a.file or a.target, extra)

    only = None
    if a.only:
        alias = {"py": "python", "sol": "solidity", "ts": "typescript"}
        only = {alias.get(x.strip(), x.strip()) for x in a.only.split(",")}
    files = []
    if a.file:
        files = [Path(a.file)]
    elif a.target:
        d = Path(a.target) / "lessons" / "drafts"
        files = sorted(d.glob("*.md")) if d.is_dir() else sorted(Path(a.target).glob("*.md"))

    rows = []
    for f in files:
        rows += verify_file(f, only)
    if a.harness and a.target:
        rows += run_harness(Path(a.target))
    if not rows:
        print("verify_code: pass a course/content dir or --file (nothing to verify)", file=sys.stderr); return 2
    fails = [r for r in rows if r[2] == "FAIL"]
    skips = [r for r in rows if r[2] == "SKIP"]
    passes = [r for r in rows if r[2] == "PASS"]
    print(f"{'file':40} {'block':14} {'status':6} detail")
    for f, b, st, d in rows:
        if st != "PASS":
            print(f"{f[:40]:40} {b:14} {st:6} {d[:70]}")
    print(f"\nverify_code: {len(passes)} PASS · {len(fails)} FAIL · {len(skips)} SKIP "
          f"(env={a.env}; SKIP = toolchain/deps unavailable → run --env docker for full coverage)")
    if a.env == "local" and (skips or shutil.which("anchor")):
        print("NOTE: local toolchain versions may differ from the content's declared "
              "versions; the pinned --env docker run is the authoritative gate.")
    return 1 if fails else 0


def selftest() -> int:
    ok = True
    def chk(c, m):
        nonlocal ok; print(("PASS" if c else "FAIL") + " - " + m); ok = ok and c
    b = extract_blocks("text\n```python\nprint(1)\n```\n```visual\ndata: x\n```\n```bash\nls\n```\n")
    chk(b == [("python", "print(1)"), ("bash", "ls")], "extract skips ```visual, keeps code")
    chk(check_python("print(1+1)")[0] == "PASS", "valid python -> PASS")
    chk(check_python("x = (1 +\n")[0] == "FAIL", "broken python -> FAIL")
    chk(check_python("    x = 1")[0] == "SKIP", "indented fragment -> SKIP")
    chk(check_python("def f():\n    return 1\n\nprint(f())")[0] == "PASS", "top-level def module -> PASS")
    chk(check_python("return 1")[0] == "SKIP", "bare return -> SKIP (fragment)")
    chk(check_toml('[a]\nb = 1')[0] == "PASS" and check_toml("x = ")[0] == "FAIL", "toml ok/bad")
    chk(check_bash("echo hi && ls")[0] == "PASS", "valid bash -> PASS")
    chk(check_bash("if then fi")[0] == "FAIL", "broken bash -> FAIL")
    chk(check_bash("solana confirm -v <SIGNATURE>")[0] == "PASS", "usage synopsis <placeholder> -> PASS")
    chk(check_bash("cat <<'EOF'\nhi\nEOF")[0] == "PASS", "real heredoc still ok")
    chk(check_json('{"a":1}')[0] == "PASS" and check_json("{bad}")[0] == "FAIL", "json ok/bad")
    print("VERIFY_CODE SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
