#!/usr/bin/env python3
"""pin_refresh.py — keep this skill's own version pins from rotting.

The skill verifies content against a pinned container. Nothing verified the PINS. They lived
in prose (verify/Dockerfile ARG lines, a "pinned 2026-07-30" sentence in academy-schema.md),
so they drifted a major version behind the content they gate: the Dockerfile installed
SOLANA=v2.1.0 / ANCHOR=0.31.1 / RUST=1.86.0 / BITCOIN=27.1 while the authoring machine ran
solana-cli 3.1.10, anchor-cli 1.1.2, rustc 1.98.1, Bitcoin Core 31.1.0.

references/pins.yaml is now the single source. This tool:

    check     exit 1 if pins.yaml is past its TTL, if verify/Dockerfile's generated ARG
              block disagrees with pins.yaml, or if a skill doc hardcodes a version of a
              governed tool outside the allowlist.  --probe also compares each pin against
              the locally installed tool and reports drift.
    render    rewrite the Dockerfile's generated ARG block from pins.yaml.
    surfaces  regenerate references/command-surfaces.yaml from live `--help` output.

    python3 pin_refresh.py check [--probe] [--json out.json]
    python3 pin_refresh.py render [--check]
    python3 pin_refresh.py surfaces [--out FILE]
    python3 pin_refresh.py --selftest

THE RECURSION GUARD is `check`'s TTL arm. An anti-staleness system with no expiry rots the
same way the thing it replaced did, so pins.yaml carries `pinned_on` + `ttl_days` and this
tool fails once they are in the past.

Stdlib only: pins.yaml and command-surfaces.yaml are parsed by the restricted YAML reader
below, which errors loudly on anything outside the subset it supports rather than guessing.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REPO = SKILL.parent.parent
PINS = SKILL / "references" / "pins.yaml"
SURFACES = SKILL / "references" / "command-surfaces.yaml"
DOCKERFILE = SKILL / "verify" / "Dockerfile"

GEN_START = "# >>> generated from references/pins.yaml by tools/pin_refresh.py render >>>"
GEN_END = "# <<< end generated block <<<"


# ─────────────────────────────────────────────────────────────────────────────────
# restricted YAML reader
# ─────────────────────────────────────────────────────────────────────────────────

class YamlError(ValueError):
    """Raised for YAML this reader deliberately refuses to guess at."""


_SCALAR_FLOW = re.compile(r"^\[(.*)\]$")


def _scalar(tok: str):
    t = tok.strip()
    if t == "" or t == "~" or t == "null":
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] == '"':
        # YAML double quotes process escapes, and the block-scalar pre-pass re-emits its
        # value as a JSON string, so \n must survive as a newline rather than as two chars.
        try:
            return json.loads(t)
        except ValueError:
            return t[1:-1]
    if len(t) >= 2 and t[0] == t[-1] and t[0] == "'":
        return t[1:-1]
    m = _SCALAR_FLOW.match(t)
    if m:
        inner = m.group(1).strip()
        return [] if not inner else [_scalar(x) for x in inner.split(",")]
    low = t.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return t


def _strip_comment(line: str) -> str:
    """Drop a trailing `#` comment that is not inside quotes."""
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            out.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _rows(text: str):
    """(indent, content, lineno) for every significant line."""
    rows = []
    for n, raw in enumerate(text.split("\n"), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        content = _strip_comment(raw)
        if not content.strip():
            continue
        rows.append((len(content) - len(content.lstrip(" ")), content.strip(), n))
    return rows


def _block_scalar(text_lines, start_idx, base_indent, style):
    """Consume a `|` / `>` block scalar starting after start_idx. Returns (value, next_idx).

    The body's indent is taken from its FIRST line (as YAML does), not from base_indent + 1 --
    getting that wrong shifts every line of every folded `because:` in the ledger by a space.
    """
    raw_body, i = [], start_idx
    while i < len(text_lines):
        raw = text_lines[i]
        if raw.strip() and (len(raw) - len(raw.lstrip(" "))) <= base_indent:
            break
        raw_body.append(raw)
        i += 1
    while raw_body and not raw_body[-1].strip():
        raw_body.pop()
    if not raw_body:
        return "", i
    body_indent = min(len(l) - len(l.lstrip(" ")) for l in raw_body if l.strip())
    body = [l[body_indent:] if len(l) > body_indent else "" for l in raw_body]
    if style == "|":
        return "\n".join(body), i
    # folded: blank line = paragraph break, otherwise join with a space
    paras, cur = [], []
    for ln in body:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            paras.append(" ".join(cur)); cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras), i


def load_yaml(text: str):
    """Parse the restricted YAML subset pins.yaml / command-surfaces.yaml are written in:
    nested maps, `- ` lists of scalars or maps, quoted/bare scalars, inline `[a, b]` flow
    lists, and `|` / `>` block scalars. Anything else raises YamlError instead of guessing."""
    raw_lines = text.split("\n")
    for n, ln in enumerate(raw_lines, 1):
        s = _strip_comment(ln).strip()
        if not s:
            continue
        if s.startswith("%") or re.search(r"(^|:\s|-\s)[&*]\w", s):
            raise YamlError(f"line {n}: anchors/aliases/directives are not supported: {s[:40]}")
        if s.startswith("{") or re.search(r":\s*\{", s):
            raise YamlError(f"line {n}: flow mappings are not supported: {s[:40]}")

    # expand block scalars into a pre-pass so the indent walker sees plain scalars
    resolved: dict[int, str] = {}
    i = 0
    while i < len(raw_lines):
        raw = raw_lines[i]
        s = _strip_comment(raw).rstrip()
        m = re.match(r"^(\s*)(-\s+)?([^:#]+):\s*([|>])[-+]?\s*$", s)
        if m:
            ind = len(m.group(1)) + (len(m.group(2)) if m.group(2) else 0)
            val, nxt = _block_scalar(raw_lines, i + 1, ind, m.group(4))
            resolved[i] = m.group(1) + (m.group(2) or "") + m.group(3) + ": " + json.dumps(val)
            for k in range(i + 1, nxt):
                resolved[k] = ""
            i = nxt
            continue
        i += 1
    lines = [resolved.get(n, ln) for n, ln in enumerate(raw_lines)]

    rows = _rows("\n".join(lines))
    pos = 0

    def parse(indent: int):
        nonlocal pos
        if pos >= len(rows):
            return None
        if rows[pos][1].startswith("- "):
            out = []
            while pos < len(rows) and rows[pos][0] == indent and rows[pos][1].startswith("- "):
                ind, content, _ = rows[pos]
                item = content[2:].strip()
                pos += 1
                if ":" in item and not item.startswith(("\"", "'")):
                    k, _, v = item.partition(":")
                    node = {k.strip(): _scalar(v) if v.strip() else None}
                    child_ind = ind + 2
                    if not v.strip() and pos < len(rows) and rows[pos][0] > child_ind:
                        node[k.strip()] = parse(rows[pos][0])
                    while pos < len(rows) and rows[pos][0] == child_ind and \
                            not rows[pos][1].startswith("- "):
                        k2, _, v2 = rows[pos][1].partition(":")
                        pos += 1
                        if v2.strip():
                            node[k2.strip()] = _scalar(v2)
                        elif pos < len(rows) and rows[pos][0] > child_ind:
                            node[k2.strip()] = parse(rows[pos][0])
                        else:
                            node[k2.strip()] = None
                    out.append(node)
                else:
                    out.append(_scalar(item))
            return out
        out = {}
        while pos < len(rows) and rows[pos][0] == indent:
            ind, content, ln = rows[pos]
            if content.startswith("- "):
                break
            if ":" not in content:
                raise YamlError(f"line {ln}: expected `key: value`, got {content[:40]!r}")
            k, _, v = content.partition(":")
            pos += 1
            if v.strip():
                out[k.strip()] = _scalar(v)
            elif pos < len(rows) and rows[pos][0] > ind:
                out[k.strip()] = parse(rows[pos][0])
            elif pos < len(rows) and rows[pos][0] == ind and rows[pos][1].startswith("- "):
                out[k.strip()] = parse(ind)
            else:
                out[k.strip()] = None
        return out

    return parse(rows[0][0]) if rows else {}


def load_yaml_file(path: Path):
    return load_yaml(Path(path).read_text("utf-8"))


def pins() -> dict:
    return load_yaml_file(PINS)


# ─────────────────────────────────────────────────────────────────────────────────
# render: pins.yaml -> Dockerfile ARG block
# ─────────────────────────────────────────────────────────────────────────────────

def arg_block(p: dict) -> str:
    lines = [GEN_START,
             f"# pinned_on: {p['pinned_on']}  ttl_days: {p['ttl_days']}  "
             f"(edit references/pins.yaml, then: python3 tools/pin_refresh.py render)"]
    for name, spec in (p.get("toolchain") or {}).items():
        arg = (spec or {}).get("docker_arg")
        if not arg:
            continue
        src = (spec or {}).get("source", "")
        lines.append(f"ARG {arg}={spec['pin']}" + (f"   # {name} ({src})" if src else ""))
    lines.append(GEN_END)
    return "\n".join(lines)


def render(check_only: bool = False) -> int:
    p = pins()
    want = arg_block(p)
    text = DOCKERFILE.read_text("utf-8")
    if GEN_START in text and GEN_END in text:
        pre, rest = text.split(GEN_START, 1)
        _, post = rest.split(GEN_END, 1)
        new = pre + want + post
    else:
        raise SystemExit(f"pin_refresh: {DOCKERFILE} has no generated block "
                         f"(add the {GEN_START!r} / {GEN_END!r} markers)")
    if new == text:
        print("PASS - Dockerfile ARG block matches pins.yaml")
        return 0
    if check_only:
        print("FAIL - Dockerfile ARG block is out of sync with pins.yaml "
              "(run: python3 tools/pin_refresh.py render)")
        return 1
    DOCKERFILE.write_text(new, "utf-8")
    print(f"wrote {DOCKERFILE.relative_to(REPO)} ARG block from pins.yaml")
    return 0


# ─────────────────────────────────────────────────────────────────────────────────
# check
# ─────────────────────────────────────────────────────────────────────────────────

def _ttl(p: dict):
    on = _dt.date.fromisoformat(str(p["pinned_on"]))
    due = on + _dt.timedelta(days=int(p["ttl_days"]))
    return on, due, (due - _dt.date.today()).days


def probe(spec: dict) -> str | None:
    cmd = (spec or {}).get("probe")
    if not cmd:
        return None
    head = cmd.split()[0]
    if not shutil.which(head):
        return None
    try:
        r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    m = re.search(spec.get("probe_re", r"(\d+\.\d+\.\d+)"), r.stdout + r.stderr)
    return (spec.get("probe_prefix", "") + m.group(1)) if m else None


# a governed tool's name as it appears in prose, -> the pins.yaml toolchain key
DOC_TOOL_ALIASES = {
    "anchor": "anchor", "anchor-cli": "anchor", "anchor-lang": "anchor", "avm": "anchor",
    "solana": "solana", "solana-cli": "solana", "agave": "solana",
    "rust": "rust", "rustc": "rust", "cargo": "rust",
    "node": "node_major", "nodejs": "node_major",
    "bitcoin": "bitcoin", "bitcoind": "bitcoin", "bitcoin-core": "bitcoin",
    "foundry": "foundry", "forge": "foundry",
    "solidity": "solidity", "solc": "solidity",
}
_DOC_VER = re.compile(
    r"\b(" + "|".join(sorted(DOC_TOOL_ALIASES, key=len, reverse=True)) +
    r")\b[ @=/-]{0,3}v?(\d+(?:\.\d+){0,2})\b", re.I)

DOC_GLOBS = ("skills/content-gen/**/*.md", "skills/content-gen/**/*.yaml",
             "*.md", "commands/*.md", "agents/*.md")

# Per-LINE escape, for prose that names a version on purpose: a behaviour change tied to a
# major ("Foundry 1.x made forge create simulate by default"), or a historical value quoted to
# explain why a guard exists. Preferred over allowlisting a whole file, which would blind the
# check on exactly the docs people read most.
#     <!-- pins-ok: why -->   (markdown)      # pins-ok: why   (yaml / Dockerfile)
_PINS_OK = re.compile(r"pins-ok\b")


def _allowed(rel: str, tool: str, allowlist) -> bool:
    for entry in allowlist or []:
        if not isinstance(entry, dict):
            continue
        pat = entry.get("path", "")
        if not (fnmatch.fnmatch(rel, pat) or (pat.endswith("**") and rel.startswith(pat[:-2]))):
            continue
        tools = entry.get("tools")
        if not tools or tool in tools:
            return True
    return False


def scan_docs(p: dict, strict_sourcing: bool = True):
    """Every hardcoded version of a governed tool in a skill doc, outside the allowlist.

    `contradicts` is the sharp end: the doc states a version pins.yaml disagrees with, which
    is what shipped the stale Dockerfile. A non-contradicting hardcode is still reported --
    it is a number that will rot silently the next time the pin moves.
    """
    tc = p.get("toolchain") or {}
    allow = p.get("sourcing_allowlist") or []
    hits = []
    seen = set()
    for glob in DOC_GLOBS:
        for f in sorted(REPO.glob(glob)):
            if not f.is_file() or f in seen:
                continue
            seen.add(f)
            rel = str(f.relative_to(REPO))
            try:
                text = f.read_text("utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.split("\n"), 1):
                if _PINS_OK.search(line):
                    continue
                for m in _DOC_VER.finditer(line):
                    tool = DOC_TOOL_ALIASES[m.group(1).lower()]
                    if tool not in tc:
                        continue
                    if _allowed(rel, tool, allow):
                        continue
                    found = m.group(2)
                    pin = str(tc[tool]["pin"]).lstrip("v")
                    contradicts = not (pin.startswith(found) or found.startswith(pin))
                    if contradicts or strict_sourcing:
                        hits.append({"file": rel, "line": n, "tool": tool, "found": found,
                                     "pin": tc[tool]["pin"], "contradicts": contradicts,
                                     "text": line.strip()[:100]})
    return hits


def check(do_probe: bool = False, strict_sourcing: bool = True, json_out: str | None = None) -> int:
    p = pins()
    ok = True
    report: dict = {"pinned_on": str(p["pinned_on"]), "ttl_days": p["ttl_days"]}

    on, due, left = _ttl(p)
    fresh = left >= 0
    print(("PASS" if fresh else "FAIL") +
          f" - pins TTL: pinned {on}, due {due} ({left:+d} days)")
    report["ttl_days_left"] = left
    ok = ok and fresh
    if not fresh:
        print("   pins.yaml is past its TTL. Re-probe every tool, update `pin:`, then move "
              "`pinned_on`. Moving `pinned_on` alone is the failure mode this guard exists for.")

    ok = (render(check_only=True) == 0) and ok

    hits = scan_docs(p, strict_sourcing)
    contradicting = [h for h in hits if h["contradicts"]]
    for h in hits:
        tag = "CONTRADICTS" if h["contradicts"] else "unsourced"
        print(f"   {tag} {h['file']}:{h['line']} says {h['tool']} {h['found']} "
              f"(pins.yaml: {h['pin']})")
    bad = hits if strict_sourcing else contradicting
    print(("PASS" if not bad else "FAIL") +
          f" - doc version sourcing ({len(contradicting)} contradicting, "
          f"{len(hits) - len(contradicting)} unsourced)")
    report["doc_hits"] = hits
    ok = ok and not bad

    if do_probe:
        drift = []
        for name, spec in (p.get("toolchain") or {}).items():
            got = probe(spec)
            if got is None:
                print(f"   probe {name}: not installed here (skipped)")
                continue
            want = str(spec["pin"])
            if want == "stable":
                print(f"   probe {name}: channel `stable` resolved to {got} (informational)")
                continue
            if got != want:
                drift.append((name, want, got))
                print(f"   DRIFT {name}: pins.yaml {want}, locally installed {got}")
            else:
                print(f"   probe {name}: {got} matches")
        print(("PASS" if not drift else "FAIL") + f" - local toolchain drift ({len(drift)})")
        report["drift"] = drift
        ok = ok and not drift

    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=2), "utf-8")
    print("pin_refresh: " + ("GREEN" if ok else "RED"))
    return 0 if ok else 1


# ─────────────────────────────────────────────────────────────────────────────────
# surfaces: regenerate command-surfaces.yaml observations from live --help
# ─────────────────────────────────────────────────────────────────────────────────

def _help_text(argv: list[str]) -> str:
    if not shutil.which(argv[0]):
        return ""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    except Exception:
        return ""
    return r.stdout + r.stderr


def surfaces(out: Path | None = None) -> int:
    """Re-probe each ledger tool and refresh its `observed:` fields in place.

    This does NOT invent rules. It answers the one question a rule can go stale on: does the
    flag/subcommand this rule talks about still exist in the installed tool's --help? A rule
    whose flag has vanished is reported so a human can retire it.
    """
    out = out or SURFACES
    led = load_yaml_file(out)
    today = _dt.date.today().isoformat()
    lines = out.read_text("utf-8").split("\n")
    changed = 0

    def set_key(tool: str, key: str, value: str):
        """Rewrite `    <key>: ...` inside the `  <tool>:` block."""
        nonlocal changed
        start = next((i for i, l in enumerate(lines) if l.rstrip() == f"  {tool}:"), None)
        if start is None:
            return
        for i in range(start + 1, len(lines)):
            if lines[i].strip() and not lines[i].startswith("    "):
                break
            m = re.match(rf"^(    ){re.escape(key)}:\s*(.*)$", lines[i])
            if m:
                new = f"    {key}: {value}"
                if lines[i] != new:
                    lines[i] = new
                    changed += 1
                return

    for tool, spec in (led.get("tools") or {}).items():
        pr = (spec or {}).get("version_probe")
        ver = ""
        if pr:
            txt = _help_text(pr.split())
            m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)", txt)
            ver = m.group(1) if m else ""
        if ver:
            set_key(tool, "observed", f'"{ver}"')
            set_key(tool, "observed_on", f'"{today}"')
            print(f"  {tool}: observed {ver}")
        else:
            print(f"  {tool}: not installed here (observed left as-is)")
            continue
        help_txt = _help_text([tool, "--help"]) or _help_text([tool, "-help"])
        for sub, sspec in ((spec or {}).get("subcommands") or {}).items():
            sub_help = _help_text([tool, sub, "--help"]) or help_txt
            for rule in (sspec or {}).get("requires_flags") or []:
                flag = (rule or {}).get("flag")
                if flag and sub_help and flag not in sub_help:
                    print(f"  STALE? {tool} {sub}: `{flag}` no longer appears in --help")
    if changed:
        out.write_text("\n".join(lines), "utf-8")
    print(f"surfaces: {changed} field(s) refreshed in {out.name}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="keep the skill's own pins from rotting")
    ap.add_argument("cmd", nargs="?", choices=["check", "render", "surfaces"])
    ap.add_argument("--probe", action="store_true", help="check: also compare against local installs")
    ap.add_argument("--no-strict-sourcing", action="store_true",
                    help="check: fail only on docs that CONTRADICT pins.yaml")
    ap.add_argument("--check", action="store_true", help="render: report drift, do not write")
    ap.add_argument("--out", help="surfaces: ledger path")
    ap.add_argument("--json", help="check: write the machine report here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "check":
        return check(a.probe, not a.no_strict_sourcing, a.json)
    if a.cmd == "render":
        return render(a.check)
    if a.cmd == "surfaces":
        return surfaces(Path(a.out) if a.out else None)
    ap.print_help()
    return 2


def selftest() -> int:
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    # ── the restricted YAML reader ──
    y = load_yaml("a: 1\nb:\n  c: two\n  d: [x, y]\ne:\n  - 1\n  - 2\n")
    chk(y == {"a": 1, "b": {"c": "two", "d": ["x", "y"]}, "e": [1, 2]}, "yaml: nesting + flow list")
    y = load_yaml("l:\n  - name: a\n    v: 1\n  - name: b\n    v: 2\n")
    chk(y == {"l": [{"name": "a", "v": 1}, {"name": "b", "v": 2}]}, "yaml: list of maps")
    y = load_yaml('s: "1.2.3"\nt: true\nn: null\nf: 1.5\n')
    chk(y == {"s": "1.2.3", "t": True, "n": None, "f": 1.5}, "yaml: scalar types (quoted stays str)")
    y = load_yaml("k: >-\n  one\n  two\nafter: 1\n")
    chk(y["k"] == "one two" and y["after"] == 1, "yaml: folded block scalar")
    y = load_yaml("k: |\n  a\n  b\nafter: 1\n")
    chk(y["k"] == "a\nb" and y["after"] == 1, "yaml: literal block scalar")
    chk(load_yaml("a: 1 # note\n") == {"a": 1}, "yaml: trailing comment stripped")
    chk(load_yaml('a: "x # y"\n') == {"a": "x # y"}, "yaml: `#` inside quotes kept")
    for bad in ("a: {b: 1}\n", "a: &anc 1\n"):
        try:
            load_yaml(bad); chk(False, f"yaml: refuses {bad.strip()!r}")
        except YamlError:
            chk(True, f"yaml: refuses {bad.strip()!r}")

    # ── the real files parse, and carry what the rest of the tool depends on ──
    p = pins()
    chk(isinstance(p.get("toolchain"), dict) and "anchor" in p["toolchain"], "pins.yaml parses")
    chk(all("pin" in v for v in p["toolchain"].values()), "every toolchain entry has a pin")
    on, due, left = _ttl(p)
    chk(due > on, "TTL yields a due date after pinned_on")
    if SURFACES.is_file():
        s = load_yaml_file(SURFACES)
        chk(isinstance(s.get("tools"), dict) and s["tools"], "command-surfaces.yaml parses")

    # differential test: where a real YAML parser is available, our restricted reader must
    # agree with it on the two files we actually ship. Absent PyYAML this is skipped -- the
    # tools stay stdlib-only, this is an authoring-time cross-check.
    try:
        import yaml as _pyyaml  # noqa: PLC0415
    except ModuleNotFoundError:
        print("skip - PyYAML absent; differential parse cross-check not run")
    else:
        def _norm(o):
            if isinstance(o, dict):
                return {k: _norm(v) for k, v in o.items()}
            if isinstance(o, list):
                return [_norm(v) for v in o]
            return None if o is None else str(o).strip()
        for f in (PINS, SURFACES):
            if f.is_file():
                chk(_norm(load_yaml_file(f)) == _norm(_pyyaml.safe_load(f.read_text("utf-8"))),
                    f"restricted reader agrees with PyYAML on {f.name}")

    # ── render is a pure function of pins.yaml, and idempotent ──
    blk = arg_block(p)
    chk(blk.startswith(GEN_START) and blk.endswith(GEN_END), "arg block is delimited")
    chk(f"ARG ANCHOR={p['toolchain']['anchor']['pin']}" in blk, "arg block carries the anchor pin")
    chk(arg_block(p) == blk, "arg block render is deterministic")

    # ── the allowlist matches by glob and narrows by tool ──
    al = [{"path": "skills/content-gen/examples/**"},
          {"path": "skills/content-gen/references/academy-schema.md", "tools": ["anchor"]}]
    chk(_allowed("skills/content-gen/examples/x/course.yaml", "rust", al), "allowlist: ** glob")
    chk(_allowed("skills/content-gen/references/academy-schema.md", "anchor", al),
        "allowlist: tool-scoped entry allows its tool")
    chk(not _allowed("skills/content-gen/references/academy-schema.md", "solana", al),
        "allowlist: tool-scoped entry does NOT allow other tools")
    chk(not _allowed("skills/content-gen/SKILL.md", "anchor", al), "allowlist: unlisted path denied")

    # ── the doc scanner sees a stale hardcode ──
    hits = []
    for m in _DOC_VER.finditer("built against anchor 0.31.1 and solana v2.1.0"):
        hits.append((DOC_TOOL_ALIASES[m.group(1).lower()], m.group(2)))
    chk(("anchor", "0.31.1") in hits and ("solana", "2.1.0") in hits,
        "doc scanner extracts (tool, version) pairs")
    chk(not _DOC_VER.search("the 2026 rewrite of chapter 3"), "doc scanner ignores bare numbers")

    # end-to-end: a doc that contradicts pins.yaml must actually FAIL the scan, and the
    # allowlist must be able to exempt it. This is the arm that proves the check bites.
    import tempfile
    real_repo = REPO
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills" / "content-gen" / "references").mkdir(parents=True)
            stale = root / "skills" / "content-gen" / "references" / "stale.md"
            stale.write_text("built against anchor 0.31.1 and solana v2.1.0\n", "utf-8")
            globals()["REPO"] = root
            hits = scan_docs(p, strict_sourcing=True)
            bad = [h for h in hits if h["file"].endswith("stale.md")]
            chk(len(bad) == 2 and all(h["contradicts"] for h in bad),
                f"stale doc versions are found AND marked contradicting ({len(bad)})")
            p2 = dict(p)
            p2["sourcing_allowlist"] = [{"path": "skills/content-gen/references/stale.md"}]
            chk(not [h for h in scan_docs(p2, True) if h["file"].endswith("stale.md")],
                "the allowlist exempts a path end to end")
            stale.write_text(f"we pin anchor {p['toolchain']['anchor']['pin']}\n", "utf-8")
            agree = [h for h in scan_docs(p, True) if h["file"].endswith("stale.md")]
            chk(len(agree) == 1 and not agree[0]["contradicts"],
                "a doc that AGREES with pins.yaml is reported as unsourced, not contradicting")
            stale.write_text("Foundry 1.x changed it <!-- pins-ok: names a major, not a pin -->\n",
                             "utf-8")
            chk(not [h for h in scan_docs(p, True) if h["file"].endswith("stale.md")],
                "the per-line `pins-ok` escape exempts one line")
            stale.write_text("anchor 0.31.1 <!-- pins-ok -->\nanchor 0.31.1\n", "utf-8")
            chk(len([h for h in scan_docs(p, True) if h["file"].endswith("stale.md")]) == 1,
                "...and only that line, not the whole file")
    finally:
        globals()["REPO"] = real_repo

    print("\nPIN_REFRESH SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
