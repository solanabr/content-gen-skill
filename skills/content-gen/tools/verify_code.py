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
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
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


# ═════════════════════════════════════════════════════════════════════════════════
# bash: three tiers
#
#   tier 1  syntax     `bash -n`. Catches unbalanced quotes and broken control flow.
#   tier 2  currency   parse each line into (tool, subcommand, flags) and ask
#                      references/command-surfaces.yaml whether that surface still behaves the
#                      way the lesson assumes.
#   tier 3  execution  actually run the allowlisted side-effect-free commands.
#
# Tier 2 exists because tier 1 is blind to the defect class that actually shipped. An audit of a
# live course found four majors that were all commands which no longer run: `forge create`
# without --broadcast (a silent dry run on Foundry 1.x), `openssl dgst -<digest> -sign` against
# an Ed25519 key (OpenSSL 3 refuses), and Bitcoin Core's fee + wallet-loading defaults. All four
# are valid bash. `bash -n` returns 0 on every one of them.
# ═════════════════════════════════════════════════════════════════════════════════

_SURFACES_CACHE: dict = {}


def surfaces(path: Path | None = None) -> dict:
    """references/command-surfaces.yaml, parsed once. Missing/broken ledger -> {} (tier 2 is
    then a no-op that says so, never a crash and never a silent pass)."""
    p = path or (HERE.parent / "references" / "command-surfaces.yaml")
    key = str(p)
    if key not in _SURFACES_CACHE:
        try:
            from pin_refresh import load_yaml_file        # noqa: PLC0415
            _SURFACES_CACHE[key] = (load_yaml_file(p) or {}) if p.is_file() else {}
        except Exception as e:                            # noqa: BLE001
            print(f"verify_code: command-surfaces ledger unreadable ({e}); "
                  f"bash tier 2 disabled", file=sys.stderr)
            _SURFACES_CACHE[key] = {}
    return _SURFACES_CACHE[key]


_CONT = re.compile(r"\s*\\\s*$")
# `$ ` and `> ` are transcript prompts. `# ` is NOT included: in a markdown shell block a
# leading `#` is a comment far more often than a root prompt, and treating it as a prompt
# turns every comment into a bogus command.
_PROMPT = re.compile(r"^\s*(?:\$|>)\s+")


def _logical_lines(code: str):
    """(lineno, text) for each logical shell line: prompts stripped, `\\` continuations joined,
    `&&`/`;`/`|` split into their own commands, comments and heredoc bodies dropped."""
    out, buf, start = [], "", 0
    in_heredoc, hd_tag, continuing = False, "", False
    for n, raw in enumerate(code.split("\n"), 1):
        if in_heredoc:
            if raw.strip() == hd_tag:
                in_heredoc = False
            continue
        line = _PROMPT.sub("", raw)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            in_heredoc, hd_tag = True, m.group(1)
            line = line[:m.start()]
        line = re.sub(r"(^|\s)#.*$", r"\1", line).rstrip()
        if not line.strip():
            continue
        if continuing:                     # a wrapped line's indent is layout, not an argument
            line = line.lstrip()
        if _CONT.search(line):
            buf += _CONT.sub(" ", line)
            start = start or n
            continuing = True
            continue
        buf += line
        continuing = False
        for seg in re.split(r"&&|\|\||;|(?<![|&>])\|(?!\|)", buf):
            seg = seg.strip()
            if seg:
                out.append((start or n, seg))
        buf, start = "", 0
    if buf.strip():
        out.append((start or len(code.split("\n")), buf.strip()))
    return out


_ENV_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")


def parse_command(line: str):
    """(tool, subcommand, flags) for a shell command line, or None if there is no tool.

    Leading `sudo`/env assignments are peeled; the subcommand is the first non-flag word, and
    flags keep their `=value` stripped so `--rpc-url=x` and `--rpc-url x` compare equal."""
    try:
        toks = shlex.split(line, comments=True)
    except ValueError:                                     # unbalanced quote: tier 1's problem
        return None
    while toks and (toks[0] in ("sudo", "env", "command", "exec", "time", "nohup")
                    or _ENV_ASSIGN.match(toks[0])):
        toks = toks[1:]
    if not toks:
        return None
    tool = Path(toks[0]).name
    rest = toks[1:]
    sub = next((t for t in rest if not t.startswith("-")), None)
    flags = [t.split("=", 1)[0] for t in rest if t.startswith("-")]
    return tool, sub, flags


def _rule_applies(rule: dict, line: str, block: str) -> bool:
    ctx = rule.get("when_block_matches")
    if ctx and not re.search(ctx, block):
        return False
    unless = rule.get("unless_line_matches")
    return not (unless and re.search(unless, line))


def _fmt(rule: dict, head: str) -> str:
    why = " ".join(str(rule.get("because", "")).split())
    fix = rule.get("fix")
    return f"{head}: {why}" + (f"  FIX: {fix}" if fix else "")


def check_bash_surfaces(code: str, ledger: dict | None = None):
    """Tier 2. Returns (status, detail) over the whole block: FAIL on any `severity: fail`
    rule, PASS if the block used ledger tools cleanly, SKIP if it used none."""
    led = (ledger if ledger is not None else surfaces()).get("tools") or {}
    if not led:
        return "SKIP", "no command-surfaces ledger"
    fails, warns, touched = [], [], False
    lines = _logical_lines(code)
    seen_before = ""
    for _n, line in lines:
        parsed = parse_command(line)
        if not parsed:
            seen_before += "\n" + line
            continue
        tool, sub, flags = parsed
        spec = led.get(tool)
        if spec is None:
            seen_before += "\n" + line
            continue
        touched = True
        subs = (spec.get("subcommands") or {})
        scopes = [(f"{tool}", spec)] + ([(f"{tool} {sub}", subs[sub])] if sub in subs else [])

        for rule in spec.get("removed_subcommands") or []:
            if rule.get("name") == sub and _rule_applies(rule, line, code):
                (fails if rule.get("severity", "fail") == "fail" else warns).append(
                    _fmt(rule, f"`{tool} {sub}` was removed in {rule.get('since', '?')}"))

        for head, sc in scopes:
            if not isinstance(sc, dict):
                continue
            for rule in sc.get("requires_flags") or []:
                flag = rule.get("flag")
                if flag and flag not in flags and _rule_applies(rule, line, code):
                    (fails if rule.get("severity", "fail") == "fail" else warns).append(
                        _fmt(rule, f"`{head}` is missing {flag}"))
            for rule in sc.get("forbidden_flags") or []:
                flag = rule.get("flag")
                if flag and flag in flags and _rule_applies(rule, line, code):
                    (fails if rule.get("severity", "fail") == "fail" else warns).append(
                        _fmt(rule, f"`{head}` uses removed flag {flag}"))
            for rule in sc.get("forbidden_flag_combos") or []:
                need = rule.get("flags") or []
                any_of = rule.get("with_any") or []
                if all(f in flags for f in need) and (not any_of or any(f in flags for f in any_of)) \
                        and _rule_applies(rule, line, code):
                    hit = [f for f in any_of if f in flags] or need
                    (fails if rule.get("severity", "fail") == "fail" else warns).append(
                        _fmt(rule, f"`{head}` combines {' + '.join(need + hit)}"))
            pre = sc.get("requires_preceding")
            if pre and _rule_applies(sc, line, code) and not re.search(pre, seen_before):
                (fails if sc.get("severity", "fail") == "fail" else warns).append(
                    _fmt(sc, f"`{head}` runs with nothing matching /{pre}/ before it"))
        seen_before += "\n" + line

    if fails:
        return "FAIL", " | ".join(fails)
    if warns:
        return "WARN", " | ".join(warns)
    return ("PASS", "surfaces current") if touched else ("SKIP", "no ledger tool used")


# Tier 3 executes only commands that cannot touch the machine: no network, no writes, no
# state. ci.py's SMOKE_ALLOWLIST is the seed; a tool earns a place here by being provably
# side-effect-free in the forms below, never by being "probably fine".
EXEC_ALLOWLIST = {"echo", "printf", "true", "false", "test", "["}
EXEC_ALLOWLIST_READONLY = {"python3", "python", "shasum", "sha256sum", "wc", "sort", "uniq",
                           "head", "tail", "cut", "tr", "seq", "basename", "dirname", "date",
                           "openssl", "jq", "bc", "expr"}
_EXEC_DENY = re.compile(r"[><]|\brm\b|\bmv\b|\bcp\b|\bcurl\b|\bwget\b|\bgit\b|\bsudo\b|"
                        r"\bnpm\b|\bcargo\b|\bdocker\b|`|\$\(")


def bash_execution_eligible(code: str) -> tuple[bool, str]:
    """Is every command in the block side-effect-free enough to actually run? Conservative by
    construction: one unrecognised head, one redirect, one substitution -> not eligible."""
    lines = _logical_lines(code)
    if not lines:
        return False, "nothing to run"
    allow = EXEC_ALLOWLIST | EXEC_ALLOWLIST_READONLY
    for _n, line in lines:
        if _EXEC_DENY.search(line):
            return False, "writes/network/substitution"
        p = parse_command(line)
        if not p:
            return False, "unparseable"
        if p[0] not in allow:
            return False, f"`{p[0]}` not on the execution allowlist"
    return True, "eligible"


def check_bash_exec(code: str, timeout: int = 15):
    """Tier 3. Runs the block when every command is allowlisted. Off by default (--exec-bash)."""
    okay, why = bash_execution_eligible(code)
    if not okay:
        return "SKIP", f"not execution-eligible ({why})"
    if not shutil.which("bash"):
        return "SKIP", "bash not installed"
    try:
        r = _run(["bash", "-euo", "pipefail", "-c", code], timeout=timeout)
    except subprocess.TimeoutExpired:
        return "FAIL", f"timed out after {timeout}s"
    if r.returncode == 0:
        return "PASS", "ran clean"
    tail = (r.stderr.strip() or r.stdout.strip() or "non-zero exit").splitlines()[-1]
    return "FAIL", f"exit {r.returncode}: {tail[:120]}"


# tier 3 is opt-in until it has been measured on the shipped corpus; see the module docstring.
BASH_EXEC = False


def check_bash(code):
    """Tier 1 then tier 2 (then tier 3 when enabled). The worst status wins, and the detail
    always says which tier spoke, so a FAIL is never ambiguous about what it means."""
    if not shutil.which("bash"):
        return "SKIP", "bash not installed"
    r = _run(["bash", "-n"], input=_PLACEHOLDER.sub("PLACEHOLDER", code))
    if r.returncode != 0:
        return "FAIL", "syntax: " + (r.stderr.strip().splitlines() or ["syntax error"])[-1]

    st2, d2 = check_bash_surfaces(code)
    if st2 == "FAIL":
        return "FAIL", "surface: " + d2
    if BASH_EXEC:
        st3, d3 = check_bash_exec(code)
        if st3 == "FAIL":
            return "FAIL", "exec: " + d3
        if st3 == "PASS":
            return "PASS", ("bash -n + surfaces + exec ok" if st2 == "PASS"
                            else f"bash -n + exec ok; surface warn: {d2}")
    if st2 == "WARN":
        return "PASS", "bash -n ok; surface warn: " + d2
    return "PASS", "bash -n ok" + (" + surfaces current" if st2 == "PASS" else "")


# ── prose-embedded commands ─────────────────────────────────────────────────────
# Nothing checked these. A course's most-copied command is often the one in a sentence
# ("run `forge create src/C.sol:C --rpc-url $RPC`"), never in a fence.
_INLINE = re.compile(r"`([^`\n]{2,300})`")


def extract_inline_commands(md: str, ledger: dict | None = None):
    """Yield (lineno, command) for every backtick span whose first word is a ledger tool.

    Deliberately narrow. A backtick span is usually an identifier, a path, or a flag name; only
    spans that actually start with a known CLI are commands, and only those are checkable."""
    led = (ledger if ledger is not None else surfaces()).get("tools") or {}
    if not led:
        return []
    out, in_fence = [], False
    for n, line in enumerate(md.split("\n"), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _INLINE.finditer(line):
            span = m.group(1).strip()
            p = parse_command(span)
            if p and p[0] in led and (p[1] or p[2]):
                out.append((n, span))
    return out


def check_inline_commands(md: str, ledger: dict | None = None):
    """(status, detail) over a whole markdown file's prose-embedded commands."""
    cmds = extract_inline_commands(md, ledger)
    if not cmds:
        return "SKIP", "no prose-embedded ledger commands"
    fails = []
    for n, cmd in cmds:
        st, d = check_bash_surfaces(cmd, ledger)
        if st == "FAIL":
            fails.append(f"line {n}: {d}")
    if fails:
        return "FAIL", " | ".join(fails)
    return "PASS", f"{len(cmds)} prose command(s) current"


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
    """rust / typescript / javascript: this file does NOT compile them. verify_blocks.py does.

    The previous version of this function returned SKIP unconditionally in EVERY environment,
    `--env docker` included, while the docstring and the docs said the container was "the
    authoritative gate". It was not: those three languages were never compiled anywhere in this
    tool, so "0 FAILs" for them was vacuous no matter which env you ran.

    So it now says what is true, and names the tool that does the work. verify_blocks.py
    compiles rust and typescript blocks against the course's DECLARED deps and triages
    unresolved-name errors (missing fragment context) apart from real defects. ci.py runs it as
    tier 7. The SKIP text is the pointer, because a SKIP nobody can act on is how this stayed
    broken for so long.
    """
    def _c(code):
        return "SKIP", (f"{lang}: not compiled here — run tools/verify_blocks.py "
                        f"(ci.py tier 7) which builds it against the course's declared deps")
    return _c


CHECKERS = {"python": check_python, "bash": check_bash, "json": check_json,
            "solidity": check_solidity, "rust": check_container_lang("rust"),
            "typescript": check_container_lang("typescript"),
            "javascript": check_container_lang("javascript"), "toml": check_toml}


def verify_file(path: Path, only=None, inline: bool = True):
    md = path.read_text("utf-8")
    rows = []
    for n, (lang, code) in enumerate(extract_blocks(md), 1):
        if only and lang not in only:
            continue
        status, detail = CHECKERS.get(lang, lambda c: ("SKIP", "no checker"))(code)
        rows.append((path.name, f"{lang}#{n}", status, detail))
    if inline and (not only or "bash" in only):
        st, d = check_inline_commands(md)
        if st != "SKIP":
            rows.append((path.name, "inline-cmds", st, d))
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


def bash_tier_report(files) -> int:
    """Per-tier verdicts for every bash block across `files`.

    This is the instrument the tier-3 rollout is measured with: it reports how many blocks are
    execution-eligible and what happens when they run, WITHOUT letting tier 3 gate anything.
    Tier 3 stays opt-in until that number is known on the real corpus.
    """
    t1 = {"PASS": 0, "FAIL": 0}
    t2: dict = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
    t3: dict = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    findings, eligible, total = [], 0, 0
    for f in files:
        md = f.read_text("utf-8")
        for n, (lang, code) in enumerate(extract_blocks(md), 1):
            if lang != "bash":
                continue
            total += 1
            r = _run(["bash", "-n"], input=_PLACEHOLDER.sub("PLACEHOLDER", code))
            t1["PASS" if r.returncode == 0 else "FAIL"] += 1
            s2, d2 = check_bash_surfaces(code)
            t2[s2] = t2.get(s2, 0) + 1
            if s2 in ("FAIL", "WARN"):
                findings.append((f.name, f"bash#{n}", s2, d2))
            ok, why = bash_execution_eligible(code)
            if ok:
                eligible += 1
                s3, d3 = check_bash_exec(code)
                t3[s3] = t3.get(s3, 0) + 1
                if s3 == "FAIL":
                    findings.append((f.name, f"bash#{n}", "EXEC", d3))
            else:
                t3["SKIP"] += 1
        s, d = check_inline_commands(md)
        if s == "FAIL":
            findings.append((f.name, "inline", "FAIL", d))

    print(f"bash blocks: {total}   (tier 3 execution-eligible: {eligible})")
    print(f"  tier 1 syntax    PASS {t1['PASS']:4}  FAIL {t1['FAIL']:4}")
    print(f"  tier 2 surfaces  PASS {t2['PASS']:4}  FAIL {t2['FAIL']:4}  "
          f"WARN {t2['WARN']:4}  SKIP {t2['SKIP']:4}")
    print(f"  tier 3 exec      PASS {t3['PASS']:4}  FAIL {t3['FAIL']:4}  SKIP {t3['SKIP']:4}")
    if findings:
        print("\nfindings:")
        for fn, blk, st, d in findings:
            print(f"  {st:5} {fn[:38]:38} {blk:11} {d[:150]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="compile/run the code a piece ships")
    ap.add_argument("target", nargs="?", help="course/content dir (verifies lessons/drafts/*.md) or a dir of *.md")
    ap.add_argument("--file", help="a single markdown file")
    ap.add_argument("--env", choices=["local", "docker"], default="local")
    ap.add_argument("--only", help="comma list: py,bash,sol,ts,rust,json")
    ap.add_argument("--run-smoke", action="store_true", help="also run each brief's verify command")
    ap.add_argument("--harness", action="store_true",
                    help="run the piece's real-toolchain harnesses: verify-ts/ (tsc) + verify-anchor/*/ (anchor build)")
    ap.add_argument("--exec-bash", action="store_true",
                    help="bash tier 3: actually run the execution-allowlisted blocks (opt-in)")
    ap.add_argument("--no-inline", action="store_true",
                    help="skip the prose-embedded (backticked) command check")
    ap.add_argument("--bash-tiers", action="store_true",
                    help="report the per-tier bash verdict for every bash block, then exit")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.exec_bash:
        globals()["BASH_EXEC"] = True
    if a.env == "docker":
        extra = " ".join(x for x in [f"--only {a.only}" if a.only else "",
                                     "--run-smoke" if a.run_smoke else "",
                                     "--exec-bash" if a.exec_bash else ""] if x)
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

    if a.bash_tiers:
        return bash_tier_report(files)

    rows = []
    for f in files:
        rows += verify_file(f, only, inline=not a.no_inline)
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

    # ── bash tier 2: the line parser ────────────────────────────────────────────
    chk(parse_command("forge create src/C.sol:C --rpc-url $R --private-key $K")
        == ("forge", "create", ["--rpc-url", "--private-key"]), "parse: tool/sub/flags")
    chk(parse_command("sudo RUST_LOG=info bitcoind -regtest -daemon")
        == ("bitcoind", None, ["-regtest", "-daemon"]), "parse: peels sudo + env assignment")
    chk(parse_command("forge create C --rpc-url=$R")[2] == ["--rpc-url"],
        "parse: --flag=value normalises to --flag")
    chk(parse_command("$ solana balance") is None or parse_command("solana balance")
        == ("solana", "balance", []), "parse: plain subcommand")
    chk([l for _, l in _logical_lines("$ echo a && echo b")] == ["echo a", "echo b"],
        "logical lines: prompt stripped, && split")
    chk([l for _, l in _logical_lines("echo a \\\n  b\n# note\n")] == ["echo a b"],
        "logical lines: continuation joined, comment dropped")
    chk([l for _, l in _logical_lines("# forge create X\nls")] == ["ls"],
        "logical lines: a leading `#` is a comment, not a root prompt")
    hd = [l for _, l in _logical_lines("cat <<EOF\nforge create X\nEOF\necho done")]
    chk(hd == ["cat", "echo done"], "logical lines: heredoc body is data, not commands")

    # ── bash tier 2 vs the four defects that actually shipped ───────────────────
    # A ledger is only worth having if it fires on the real thing, so each of these is the
    # shape the audited course used. Every one of them passes `bash -n`.
    forge_bad = "forge create src/Counter.sol:Counter --rpc-url $RPC --private-key $PK"
    chk(_run(["bash", "-n"], input=forge_bad).returncode == 0, "defect 1 is valid bash (tier 1 blind)")
    chk(check_bash_surfaces(forge_bad)[0] == "FAIL", "defect 1: forge create without --broadcast -> FAIL")
    chk("--broadcast" in check_bash_surfaces(forge_bad)[1], "defect 1: the fix names --broadcast")
    chk(check_bash_surfaces(forge_bad + " --broadcast")[0] == "PASS", "defect 1: --broadcast clears it")

    ssl_bad = ("openssl genpkey -algorithm ed25519 -out key.pem\n"
               "openssl dgst -sha256 -sign key.pem -out sig.bin msg.bin")
    chk(_run(["bash", "-n"], input=ssl_bad).returncode == 0, "defect 2 is valid bash (tier 1 blind)")
    chk(check_bash_surfaces(ssl_bad)[0] == "FAIL", "defect 2: openssl dgst -sha256 -sign on Ed25519 -> FAIL")
    chk(check_bash_surfaces("openssl dgst -sha256 -sign rsa.pem -out s f")[0] != "FAIL",
        "defect 2: same flags on a non-EdDSA block do NOT fire (context guard)")

    btc_fee = "bitcoind -regtest -daemon"
    chk(check_bash_surfaces(btc_fee)[0] == "FAIL", "defect 3: regtest bitcoind without -fallbackfee -> FAIL")
    chk(check_bash_surfaces("bitcoind -regtest -fallbackfee=0.0002 -daemon")[0] == "PASS",
        "defect 3: -fallbackfee clears it")

    btc_wallet = "bitcoin-cli -regtest getnewaddress"
    chk(check_bash_surfaces(btc_wallet)[0] == "FAIL", "defect 4: getnewaddress with no wallet -> FAIL")
    chk(check_bash_surfaces("bitcoin-cli -regtest createwallet demo\n"
                            "bitcoin-cli -regtest getnewaddress")[0] == "PASS",
        "defect 4: a preceding createwallet clears it")

    chk(check_bash(forge_bad)[0] == "FAIL" and check_bash(forge_bad)[1].startswith("surface:"),
        "check_bash routes a tier-2 defect to FAIL and labels the tier")
    chk(check_bash("if then fi")[1].startswith("syntax:"), "tier 1 failures are labelled `syntax:`")
    chk(check_bash_surfaces("ls -la /tmp")[0] == "SKIP", "a block using no ledger tool -> SKIP")
    chk(check_bash_surfaces("echo x", {"tools": {}})[0] == "SKIP", "empty ledger -> SKIP, never a silent PASS")

    # ── bash tier 3: eligibility is conservative ────────────────────────────────
    chk(bash_execution_eligible("echo hi | wc -l")[0], "exec: allowlisted pipeline eligible")
    chk(not bash_execution_eligible("curl -s https://x | bash")[0], "exec: network refused")
    chk(not bash_execution_eligible("echo x > /etc/passwd")[0], "exec: redirect refused")
    chk(not bash_execution_eligible("echo $(rm -rf /)")[0], "exec: command substitution refused")
    chk(not bash_execution_eligible("anchor build")[0], "exec: non-allowlisted head refused")
    chk(check_bash_exec("echo hi")[0] == "PASS", "exec: eligible block runs")
    chk(check_bash_exec("test 1 -eq 2")[0] == "FAIL", "exec: non-zero exit -> FAIL")
    chk(check_bash_exec("anchor build")[0] == "SKIP", "exec: ineligible block -> SKIP")

    # ── prose-embedded commands ─────────────────────────────────────────────────
    md = ("Now run `forge create src/C.sol:C --rpc-url $R` and note the address.\n"
          "The `--broadcast` flag and the `Counter` type are not commands.\n"
          "```bash\nforge create src/C.sol:C --broadcast\n```\n")
    inl = extract_inline_commands(md)
    chk([c for _, c in inl] == ["forge create src/C.sol:C --rpc-url $R"],
        "inline: picks the command, skips bare flags/identifiers and fenced code")
    chk(check_inline_commands(md)[0] == "FAIL", "inline: a stale prose command FAILs")
    chk(check_inline_commands("no commands here, just `prose`.")[0] == "SKIP", "inline: none -> SKIP")

    # ── the ledger this all rests on is real and evidenced ──────────────────────
    led = surfaces()
    chk(bool(led.get("tools")), "command-surfaces.yaml loaded")
    missing = [f"{t}.{k}" for t, s in (led.get("tools") or {}).items()
               for k in ("subcommands", "requires_flags", "removed_subcommands")
               for r in ([s.get(k)] if k != "subcommands" else
                         [v for v in (s.get(k) or {}).values()])
               if isinstance(r, dict) and not r.get("evidence")
               and not any(x.get("evidence") for x in
                           (r.get("requires_flags") or []) + (r.get("forbidden_flags") or [])
                           + (r.get("forbidden_flag_combos") or []))]
    chk(not missing, f"every ledger rule carries evidence ({missing[:3]})")

    print("VERIFY_CODE SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
