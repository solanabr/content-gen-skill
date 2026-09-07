#!/usr/bin/env python3
"""
continuity.py — the half of the continuity gate that needs the TREE, not just the manifest.

`validate_course.py continuity` checks the declared ledger against itself (manifest-only,
HARD). This tool checks the ledger against the drafts the reader will actually read:

  paths    every declared opens/emits path that the COURSE ships must exist on disk
  scan     the call-site scan: for each provided symbol, find its real call sites in
           LATER lessons and flag shapes that disagree with the declared signature
  renames  a declared rename's old name still appearing in later code
  dry-run  run everything across a tree of courses and print the hit rate
  infer    emit a provisional ledger (JSON) derived from the drafts, for retrofit

    python3 continuity.py check    --course content/courses/<id>
    python3 continuity.py scan     --course content/courses/<id> [--infer]
    python3 continuity.py dry-run  --root content/courses
    python3 continuity.py infer    --course content/courses/<id> > ledger.json

EVERYTHING HERE IS ADVISORY, deliberately. `method/known-failure-modes.md` §1 is the
law this file was written under: three separate checkers in this repo have shipped a
substring match that fired on prose, on a comment, and once on the tool's own
documentation. So:

  * extraction is FENCE-SCOPED — only fenced blocks with a known code language, never
    the raw markdown, never a prose paragraph, never an output fence;
  * every fence is comment-stripped and string-stripped before a single identifier is
    matched, in one pass so `"https://x"` can never look like a `//` comment;
  * a call site is found STRUCTURALLY: a negative lookbehind rejects `obj.name(`, and a
    definition site is excluded by its own definition keyword, not by line position;
  * arity is a SPAN, so a default or optional parameter widens what counts as a correct
    call instead of manufacturing a false positive on every one of them;
  * and a mismatch is only reported when a real later CALL SITE disagrees — a name
    merely defined twice is not evidence of anything in a course that ships two
    unrelated programs.

Promote a rule here to HARD only after a --dry-run across the whole corpus shows a
false-positive rate near zero. A hard gate people learn to bypass is worse than an
advisory people read.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from course_lib import (  # noqa: E402
    CODE_SYMBOL_KINDS, load_manifest, course_ledgers, split_top_level,
)
from verify_code import extract_blocks  # noqa: E402  (the one fence extractor; §1)

ADV = "[advisory] "
HARD = "[HARD] "

# Languages whose fences carry callable code. A bash fence is commands, not calls, and
# is scanned only for `cmd:` symbols.
CODE_LANGS = {"rust", "typescript", "javascript", "python", "solidity"}
SHELL_LANGS = {"bash"}

# Generated files that live in lessons/drafts/ but are not lessons. 000-cover.md is
# emitted by scaffold_course.py and re-states the whole syllabus; scanning it would let
# the toolchain match its own scaffolding (§1, third rule).
NOT_A_LESSON = re.compile(r"^(000-cover|README|_)", re.I)

# Course-relative roots the COURSE ships. A path under one of these is checkable on disk;
# everything else in a ledger describes the READER's repo, which this tree cannot see.
SHIPPED_ROOTS = ("assets/", "lessons/challenges/", "branding/")

# Entry points and trait/framework hooks that every program defines under the same name
# with whatever shape its own framework dictates. Two lessons defining `main` or an
# Anchor instruction handler are not a rename; they are two programs.
FRAMEWORK_NAMES = {
    "main", "new", "default", "from", "into", "fmt", "drop", "clone", "next", "poll",
    "handler", "handle", "process_instruction", "entrypoint", "try_from", "setup",
    "test", "it", "describe", "before", "after", "run", "start", "stop", "init",
    "constructor", "render", "app", "page", "get", "post", "put", "delete", "use",
    "process", "execute", "build", "check", "validate", "verify", "load", "save",
}
MIN_IDENT_LEN = 4


# ── fence-scoped extraction ─────────────────────────────────────────────────────

def strip_noncode(code: str, lang: str) -> str:
    """Blank out comments and string CONTENTS, preserving length and line breaks.

    One pass, one state machine: strings are entered before comments are recognized, so
    a `//` inside a URL string and a `#` inside a TS template literal are both invisible
    to the identifier match that follows. Blanking (rather than deleting) keeps every
    offset and line number intact for reporting.

    The quote DELIMITERS survive on purpose. Blanking those too made a string argument
    vanish -- `toBaseUnits("1.50", DECIMALS)` then counted as ONE argument instead of
    two, turning every correct call of a helper that takes a string into a false
    positive. Measured on the corpus: that single character cost 20 of 93 hits."""
    hash_comments = lang in {"python", "bash", "toml", "yaml"}
    out = list(code)
    i, n = 0, len(code)
    state = ""       # "" | 'line' | 'block' | a quote char | 'tri'
    tri = ""
    while i < n:
        c = code[i]
        if state == "line":
            if c == "\n":
                state = ""
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block":
            if code.startswith("*/", i):
                out[i] = out[i + 1] = " "
                i += 2
                state = ""
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
        if state == "tri":
            if code.startswith(tri, i):
                for k in range(len(tri)):
                    out[i + k] = " "
                i += len(tri)
                state = ""
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
        if state in ('"', "'", "`"):
            if c == "\\":
                out[i] = " "
                if i + 1 < n and code[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if c == state:
                state = ""          # keep the closing delimiter
                i += 1
                continue
            if c != "\n":
                out[i] = " "
            i += 1
            continue
        # neutral
        if lang == "python" and (code.startswith('"""', i) or code.startswith("'''", i)):
            tri = code[i:i + 3]
            for k in range(3):
                out[i + k] = " "
            state, i = "tri", i + 3
            continue
        if code.startswith("//", i) and lang != "python":
            state = "line"
            continue
        if hash_comments and c == "#":
            state = "line"
            continue
        if code.startswith("/*", i) and lang != "python":
            state = "block"
            continue
        if c in '"\'`':
            state = c               # keep the opening delimiter
            i += 1
            continue
        i += 1
    return "".join(out)


def lesson_files(course: Path) -> list[Path]:
    """The drafts a reader actually reads, in course order, generated files excluded."""
    d = course / "lessons" / "drafts"
    return [p for p in sorted(d.glob("*.md")) if not NOT_A_LESSON.match(p.stem)]


def fences(md: str, langs: set) -> list[tuple[str, str]]:
    """[(lang, comment/string-stripped code)] for the fences we are allowed to match in."""
    out = []
    for lang, code in extract_blocks(md):
        if lang in langs:
            out.append((lang, strip_noncode(code, lang)))
    return out


# ── definitions and call sites ──────────────────────────────────────────────────

# (pattern, is_arrow). `is_arrow` entries must additionally be followed by `=>` after
# their balanced parens -- without that post-condition, `const body = (await res.json())`
# reads as a one-parameter arrow function and every later `body()` becomes a false
# positive. Found in the corpus shakedown; it was 1 of 17 surviving hits.
_DEF_PATTERNS = {
    "rust": [(re.compile(r"(?m)^(?P<indent>[ \t]*)(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
                         r"(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+(?P<name>\w+)"
                         r"\s*(?:<[^>(]*>)?\s*\("), False)],
    "typescript": [(re.compile(r"(?m)^(?P<indent>[ \t]*)(?:export\s+)?(?:default\s+)?"
                               r"(?:async\s+)?function\s*\*?\s+(?P<name>\w+)\s*(?:<[^>(]*>)?\s*\("),
                    False),
                   (re.compile(r"(?m)^(?P<indent>[ \t]*)(?:export\s+)?(?:const|let|var)\s+"
                               r"(?P<name>\w+)\s*(?::[^=\n]+)?=\s*(?:async\s*)?\("), True)],
    "python": [(re.compile(r"(?m)^(?P<indent>[ \t]*)(?:async\s+)?def\s+(?P<name>\w+)\s*\("), False)],
    "solidity": [(re.compile(r"(?m)^(?P<indent>[ \t]*)function\s+(?P<name>\w+)\s*\("), False)],
}
_DEF_PATTERNS["javascript"] = _DEF_PATTERNS["typescript"]
_ARROW_TAIL = re.compile(r"^\s*(?::[^;=\n]*?)?=>")

_RECEIVERS = {"self", "&self", "&mut self", "mut self", "cls"}


def _balanced(code: str, open_at: int) -> tuple[str, int]:
    """The text between `code[open_at] == '('` and its matching ')', plus the end index."""
    depth, i, n = 0, open_at, len(code)
    while i < n:
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return code[open_at + 1:i], i
        i += 1
    return "", -1


def _arity_span(arglist: str) -> tuple[int, int | None]:
    parts = [p for p in split_top_level(arglist) if p and p.strip() not in _RECEIVERS]
    parts = [p for p in parts if not p.strip().startswith(("self", "&self", "&mut self"))]
    if not parts:
        return 0, 0
    varargs = any(p.startswith(("*", "...")) or p.endswith("...") for p in parts)
    fixed = [p for p in parts if not (p.startswith(("*", "...")) or p.endswith("..."))]
    req = 0
    for p in fixed:
        name = p.split(":")[0].strip()
        if "=" in p or name.endswith("?"):
            continue
        req += 1
    return req, (None if varargs else len(fixed))


def definitions(code: str, lang: str) -> list[dict]:
    """Top-level-ish function definitions in ONE stripped fence.

    Structural, never positional (§1): the definition keyword is matched at the start of
    a line and the argument list is read by balanced parens, so a trait method whose
    receiver is `&self` is counted without its receiver and a nested closure is never
    mistaken for the block's entry point."""
    out = []
    for pat, is_arrow in _DEF_PATTERNS.get(lang, []):
        for m in pat.finditer(code):
            op = code.find("(", m.end() - 1)
            if op < 0:
                continue
            args, end = _balanced(code, op)
            if end < 0:
                continue
            if is_arrow and not _ARROW_TAIL.match(code[end + 1:end + 80]):
                continue                       # a parenthesised expression, not an arrow fn
            lo, hi = _arity_span(args)
            out.append({"name": m.group("name"), "lo": lo, "hi": hi,
                        "args": args.strip(), "lang": lang,
                        "indent": len(m.group("indent"))})
    return out


def call_sites(code: str, name: str) -> list[dict]:
    """Real call sites of `name` in ONE stripped fence.

    The negative lookbehind is the whole defence against §1: `obj.name(`, `x_name(`, and
    `$name(` are not calls of this symbol. Definition sites are excluded by their own
    keyword rather than by where they sit in the block."""
    out = []
    pat = re.compile(r"(?<![\w.$])" + re.escape(name) + r"\s*\(")
    for m in pat.finditer(code):
        line_start = code.rfind("\n", 0, m.start()) + 1
        before = code[line_start:m.start()]
        if re.search(r"\b(fn|def|function|impl|trait|struct|enum|class)\s*$", before):
            continue
        if re.search(r"\b(const|let|var)\s+$", before):
            continue
        op = code.index("(", m.end() - 1)
        args, end = _balanced(code, op)
        if end < 0:
            continue
        nl = code.find("\n", m.start())
        out.append({"n": len([p for p in split_top_level(args) if p]),
                    "text": code[line_start:nl if nl > 0 else len(code)].strip()[:110]})
    return out


# ── the ledger, declared or inferred ────────────────────────────────────────────

def _lesson_index(manifest: dict, course: Path) -> list[tuple[str, Path | None]]:
    """(lesson_id, draft_path) in canonical MANIFEST order -- which is what "later" means.

    Drafts are named `<mNN>-<lN>-<lesson-id...>.md`, and the id half varies by course
    (some append a slug, some carry two module prefixes). So the join runs
    most-specific-first and CLAIMS each file exactly once:

      1. the stem ends with `-<id>`   (the documented shape)
      2. the stem contains `<id>`     (a course that appended a slug)
      3. the positional `mNN-lN` prefix

    Longest ids are matched first and a claimed file is never re-used, because
    `lid in stem` alone would let the lesson `vault` steal the file belonging to
    `anchor-vault` -- the trailing-component trap from known-failure-modes §7, which
    once produced 27 bogus modules by grouping on `parts[len-2]`."""
    files = lesson_files(course)
    unclaimed = list(files)
    order = [led["lesson"] for led in course_ledgers(manifest)]
    hit: dict[str, Path] = {}

    for lid in sorted(order, key=len, reverse=True):
        for p in unclaimed:
            if p.stem.endswith("-" + lid) or p.stem == lid:
                hit[lid] = p
                unclaimed.remove(p)
                break
    for lid in sorted([x for x in order if x not in hit], key=len, reverse=True):
        for p in unclaimed:
            if lid in p.stem:
                hit[lid] = p
                unclaimed.remove(p)
                break
    if len(hit) < len(order):
        by_prefix: dict[str, Path] = {}
        for p in unclaimed:
            parts = p.stem.split("-")
            if len(parts) >= 2:
                by_prefix.setdefault("-".join(parts[:2]), p)
        mods = [x.get("id") for x in manifest.get("modules", [])]
        for l in manifest.get("lessons", []):
            lid = l.get("id")
            if lid in hit or l.get("module") not in mods:
                continue
            key = f"m{mods.index(l['module']):02d}-l{l.get('order', 0)}"
            if key in by_prefix and by_prefix[key] in unclaimed:
                hit[lid] = by_prefix[key]
                unclaimed.remove(by_prefix[key])
    return [(lid, hit.get(lid)) for lid in order]


def infer_provides(course: Path, manifest: dict,
                   idx: list[tuple[str, Path | None]] | None = None) -> list[dict]:
    """A provisional per-lesson `provides` derived from the drafts, in course order.

    The retrofit path AND what makes a --dry-run over pre-ledger courses mean anything:
    it reads every code fence's own function definitions and treats them as that lesson's
    provided symbols, with the signature the fence actually shows. ONE implementation --
    `scan_symbols` builds its definition timeline from these same rows, so an inferred
    ledger and an inferred scan can never disagree."""
    rows = []
    for lid, path in (idx if idx is not None else _lesson_index(manifest, course)):
        provides = []
        if path is not None:
            seen: dict[tuple[str, str], dict] = {}
            for lang, code in fences(path.read_text("utf-8"), CODE_LANGS):
                for d in definitions(code, lang):
                    # the widest shape shown in this lesson wins: a lesson that shows a
                    # helper twice (sketch, then final) declares the final one.
                    prev = seen.get((lang, d["name"]))
                    if prev is None or (d["hi"] or 0) > (prev["hi"] or 0):
                        seen[(lang, d["name"])] = d
            for (lang, name), d in sorted(seen.items()):
                provides.append({"symbol": f"fn:{name}", "sig": f"({d['args']})",
                                 "lo": d["lo"], "hi": d["hi"], "lang": lang})
        rows.append({"lesson": lid, "draft": path.name if path else None,
                     "provides": provides})
    return rows


# ── checks ──────────────────────────────────────────────────────────────────────

def check_paths(course: Path, manifest: dict) -> list[str]:
    """Declared paths that the COURSE ships must exist on disk.

    Scope is deliberately narrow. Most `emits` paths live in the READER's repo, which this
    tree knows nothing about, so a path is checkable here only if the COURSE ships it:
    declared in `course.starter_assets`, or living under a course-shipped root
    (`assets/`, `lessons/challenges/`). Insisting the rest exist would flag every correct
    course, which is the miscalibration this whole gate is trying not to be."""
    flags, n = [], 0
    starters = [str(r).strip("/") for r in
                ((manifest.get("course", {}) or {}).get("starter_assets") or [])]
    for rel in starters:
        n += 1
        if not (course / rel).exists():
            flags.append(f"{HARD}course.starter_assets declares '{rel}', which the course does "
                         f"not ship — every lesson that opens it opens nothing")
    shipped = set(starters)
    for led in course_ledgers(manifest):
        for kind in ("opens", "emits"):
            for p in led[kind]:
                q = str(p).strip("/")
                if q not in shipped and not q.startswith(SHIPPED_ROOTS):
                    continue                    # the reader's tree, not ours
                n += 1
                if not (course / q).exists():
                    flags.append(f"{HARD}lesson {led['lesson']} {kind} '{q}', which the course "
                                 f"ships from its own tree — but it is not on disk")
    if not flags:
        flags.append(f"ok: {n} course-shipped path(s) present"
                     if n else "ok: no course-shipped paths declared (nothing on disk to check)")
    return flags


def check_renames(course: Path, manifest: dict) -> list[str]:
    """A declared rename whose OLD name still appears in later lesson code.

    This is the `init_vault -> initialize` defect: the manifest half of the gate catches
    a later lesson that still *declares* the old symbol, and this half catches the far
    more common case -- the declaration was updated and the verbatim code below it was
    not."""
    flags, idx = [], _lesson_index(manifest, course)
    pos = {lid: i for i, (lid, _p) in enumerate(idx)}
    leds = course_ledgers(manifest)
    for led in leds:
        for r in led["renames"]:
            old = str(r.get("from") or "").split(":")[-1].strip()
            new = str(r.get("to") or "").split(":")[-1].strip()
            since = r.get("since_lesson") or led["lesson"]
            if not old or since not in pos:
                continue
            for lid, path in idx[pos[since]:]:
                if path is None:
                    continue
                hits = 0
                for lang, code in fences(path.read_text("utf-8"), CODE_LANGS | SHELL_LANGS):
                    hits += len(re.findall(r"(?<![\w.])" + re.escape(old) + r"(?![\w])", code))
                if hits:
                    flags.append(f"{ADV}lesson {lid}: '{old}' appears {hits}x in code fences after "
                                 f"it was renamed to '{new}' at {since} — verbatim code kept the "
                                 f"old name")
    return flags or ["ok: no declared renames survive into later code"]


def scan_symbols(course: Path, manifest: dict, use_inferred: bool = False,
                 verbose: bool = False) -> tuple[list[str], dict]:
    """THE CALL-SITE SCAN. Advisory.

    For every provided symbol with a known signature, find its real call sites in LATER
    lessons and report the ones whose argument count falls outside the span.

    Three discriminators, each of which removed a whole class of false positive when the
    scan was shaken down against the ten courses in `content/courses/`:

    1. **Same language.** A course that opens on a Python `def transfer(sender, receiver,
       amount)` and later writes an Anchor `transfer(cpi_ctx, amount)` is not renaming
       anything; those are two unrelated symbols that share a common English word.
    2. **Nearest PRECEDING definition, and never across a redefinition.** When a lesson
       re-defines a helper in its own fences, it has re-established the contract locally
       and its call sites are correct by construction. Comparing them to module 2's
       version reported a defect in the one place a reader could not possibly be
       confused.
    3. **A real later CALL SITE must disagree.** A name merely defined twice proves
       nothing in a course that ships two unrelated programs.

    Together these took the corpus from 93 hits (36.8% of inspected call sites) to a
    number a human can actually triage. Everything here stays ADVISORY regardless."""
    flags: list[str] = []
    idx = _lesson_index(manifest, course)
    leds = course_ledgers(manifest)
    stats = {"symbols": 0, "call_sites": 0, "mismatch": 0, "lessons": len(idx),
             "drafts": sum(1 for _l, p in idx if p is not None)}
    texts = {lid: (p.read_text("utf-8") if p else "") for lid, p in idx}

    # A definition timeline per (lang, name). `lang=None` means "declared in the ledger",
    # which is language-agnostic on purpose: the author said this symbol is THE symbol.
    timeline: dict[tuple[str | None, str], list[tuple[int, int, int | None]]] = {}
    for i, led in enumerate(leds):
        for p in led["provides"]:
            if p["error"] or p["kind"] not in CODE_SYMBOL_KINDS or p["lo"] is None:
                continue
            timeline.setdefault((None, p["name"]), []).append((i, p["lo"], p["hi"]))
    if not timeline and use_inferred:
        for i, row in enumerate(infer_provides(course, manifest, idx)):
            for p in row["provides"]:
                timeline.setdefault((p["lang"], p["symbol"].split(":", 1)[1]), []).append(
                    (i, p["lo"], p["hi"]))

    for (lang, name), defs in sorted(timeline.items(), key=lambda kv: (kv[0][1], kv[0][0] or "")):
        if len(name) < MIN_IDENT_LEN or name.lower() in FRAMEWORK_NAMES:
            continue
        stats["symbols"] += 1
        by_lesson = {}
        for i, lo, hi in defs:                     # widest shape a lesson shows wins
            prev = by_lesson.get(i)
            if prev is None or (hi or 0) > (prev[1] or 0):
                by_lesson[i] = (lo, hi)
        defined_at = sorted(by_lesson)
        for j in range(defined_at[0] + 1, len(idx)):
            later_id, later_path = idx[j]
            if later_path is None or j in by_lesson:
                continue                            # (2) the lesson re-established it
            prior = [k for k in defined_at if k < j]
            lo, hi = by_lesson[prior[-1]]
            src = idx[prior[-1]][0]
            for flang, code in fences(texts[later_id], CODE_LANGS):
                if lang is not None and flang != lang:
                    continue                        # (1) same language only
                for cs in call_sites(code, name):
                    stats["call_sites"] += 1
                    n = cs["n"]
                    if n < lo or (hi is not None and n > hi):
                        stats["mismatch"] += 1
                        span = f"{lo}" if lo == hi else f"{lo}..{hi if hi is not None else '*'}"
                        flags.append(f"{ADV}lesson {later_id} calls {name}() with {n} arg(s); "
                                     f"{src} defines it taking {span} — `{cs['text']}`")
    if verbose:
        flags.append(f"note: {stats['symbols']} symbol(s) tracked, "
                     f"{stats['call_sites']} later call site(s) inspected")
    return (flags or ["ok: every later call site matches the declared signature"]), stats


# ── commands ────────────────────────────────────────────────────────────────────

def _emit(title: str, flags: list[str]) -> bool:
    hard = any(f.startswith(HARD) for f in flags)
    print(f"[{'FAIL' if hard else 'ok'}] {title}")
    for f in flags:
        print("   - " + f)
    return hard


def cmd_check(course: Path, infer: bool, verbose: bool) -> int:
    m = load_manifest(course)
    hard = _emit("continuity/paths", check_paths(course, m))
    hard |= _emit("continuity/renames", check_renames(course, m))
    flags, _st = scan_symbols(course, m, use_inferred=infer, verbose=verbose)
    hard |= _emit("continuity/call-sites", flags)
    print(f"\nGATE: {'FAIL (hard)' if hard else 'PASS'}")
    return 1 if hard else 0


def cmd_dry_run(root: Path, infer: bool) -> int:
    """The shakedown. Prints one row per course so a miscalibrated rule is visible as a
    rule that fires everywhere, which is what miscalibration looks like."""
    courses = sorted(p for p in root.iterdir() if (p / "manifest.json").is_file())
    print(f"{'course':36} {'drafts':>7} {'syms':>5} {'calls':>6} {'hits':>5}  verdict")
    tot = {"courses": 0, "fired": 0, "hits": 0, "calls": 0, "skipped": 0}
    detail: list[tuple[str, list[str]]] = []
    for c in courses:
        m = load_manifest(c)
        flags, st = scan_symbols(c, m, use_inferred=infer)
        hits = st["mismatch"]
        tot["courses"] += 1
        tot["hits"] += hits
        tot["calls"] += st["call_sites"]
        # SKIP IS NOT PASS (known-failure-modes §2): a course with no drafts on this
        # branch proved nothing and must never drain into the clean count.
        if not st["drafts"]:
            tot["skipped"] += 1
            verdict = "NOT RUN (no drafts)"
        else:
            tot["fired"] += 1 if hits else 0
            verdict = "FIRES" if hits else "clean"
        print(f"{c.name:36} {st['drafts']:>7} {st['symbols']:>5} {st['call_sites']:>6} "
              f"{hits:>5}  {verdict}")
        if hits:
            detail.append((c.name, [f for f in flags if f.startswith(ADV)]))
    rate = f" ({tot['hits'] / tot['calls']:.2%})" if tot["calls"] else ""
    ran = tot["courses"] - tot["skipped"]
    print(f"\n{tot['fired']}/{ran} scanned course(s) fire ({tot['skipped']} not run); "
          f"{tot['hits']} hit(s) over {tot['calls']} inspected call site(s){rate}")
    for name, fl in detail:
        print(f"\n--- {name} ({len(fl)} hit(s))")
        for f in fl[:40]:
            print("   " + f)
        if len(fl) > 40:
            print(f"   … {len(fl) - 40} more")
    return 0


def cmd_infer(course: Path) -> int:
    m = load_manifest(course)
    print(json.dumps(infer_provides(course, m), indent=2))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────────

def selftest() -> int:
    ok = True

    def chk(c, msg):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + msg)
        ok = ok and c

    # --- strip_noncode: the §1 defences -----------------------------------------
    s = strip_noncode('const u = "https://x/y"; // real comment\nfoo(1)', "typescript")
    chk("https" not in s, "string contents are blanked")
    chk("real comment" not in s, "line comment is blanked")
    chk("foo(1)" in s, "code survives")
    chk(len(s) == len('const u = "https://x/y"; // real comment\nfoo(1)'),
        "blanking preserves offsets")
    s2 = strip_noncode('x = "a # b"  # gone\ny = 1', "python")
    chk("gone" not in s2 and "y = 1" in s2, "python: hash inside a string is not a comment")
    s3 = strip_noncode("/* block\n   comment */ code()", "rust")
    chk("block" not in s3 and "code()" in s3, "block comment is blanked across lines")
    s4 = strip_noncode('def f():\n    """doc with call(1,2,3)"""\n    return 1', "python")
    chk("doc with" not in s4, "python triple-quoted docstring is blanked")
    s5 = strip_noncode("let p = a // b;\n", "rust")
    chk("b;" not in s5, "rust // is a comment even next to code")

    # a checker must not match its own scaffolding: this module's own docstring
    # mentions `derive_vault_pda(` in prose. Fence scoping must make that invisible.
    md_selfdoc = "Some prose calling derive_vault_pda(a, b) inline.\n"
    chk(fences(md_selfdoc, CODE_LANGS) == [], "prose outside a fence is never scanned")

    # --- definitions -------------------------------------------------------------
    rs = definitions(strip_noncode(
        "pub fn derive_vault_pda(program_id: &Pubkey, owner: &Pubkey) -> (Pubkey, u8) {\n}\n"
        "impl V {\n    pub fn touch(&self, n: u64) {}\n}\n", "rust"), "rust")
    d = {x["name"]: x for x in rs}
    chk(d["derive_vault_pda"]["lo"] == 2, "rust: two-arg fn")
    chk(d["touch"]["lo"] == 1, "rust: &self receiver is not an argument")
    ts = definitions(strip_noncode(
        "export async function mint(conn, payer, amount = 1) {}\n"
        "export const helper = (a, b) => a + b;\n", "typescript"), "typescript")
    t = {x["name"]: x for x in ts}
    chk((t["mint"]["lo"], t["mint"]["hi"]) == (2, 3), "ts: a default widens the span")
    chk(t["helper"]["lo"] == 2, "ts: arrow function is a definition")
    notarrow = definitions(strip_noncode(
        "const body = (await post.json()) as Shape;\n"
        "const typed = (a: number): string => String(a);\n", "typescript"), "typescript")
    nn = {x["name"] for x in notarrow}
    chk("body" not in nn, "ts: a parenthesised expression is NOT an arrow definition")
    chk("typed" in nn, "ts: an arrow with a return type still is one")
    py = definitions(strip_noncode("def build(a, b, *rest):\n    pass\n", "python"), "python")
    chk((py[0]["lo"], py[0]["hi"]) == (2, None), "python: varargs is unbounded")

    # --- call sites --------------------------------------------------------------
    code = strip_noncode(
        "fn derive_vault_pda(a: u8) {}\n"          # definition, must be skipped
        "let x = derive_vault_pda(one, two);\n"    # 2 args
        "let y = ctx.derive_vault_pda(zzz);\n"     # a METHOD, not this symbol
        "let z = my_derive_vault_pda(q);\n",       # a different identifier
        "rust")
    cs = call_sites(code, "derive_vault_pda")
    chk(len(cs) == 1 and cs[0]["n"] == 2,
        "call_sites: skips the definition, the method call, and the prefixed name")
    nested = call_sites(strip_noncode("out = mint_token(a, f(b, c), [d, e]);", "rust"), "mint_token")
    chk(nested and nested[0]["n"] == 3, "call_sites: nested calls and literals count as one arg each")
    chk(call_sites(strip_noncode('log("mint_token(a, b)")', "rust"), "mint_token") == [],
        "call_sites: a call inside a string literal is not a call")

    # --- the end-to-end scan on a synthetic course -------------------------------
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        c = Path(td) / "course"
        (c / "lessons" / "drafts").mkdir(parents=True)
        (c / "lessons" / "drafts" / "m01-l1-a.md").write_text(
            "# A\n\n```rust\npub fn derive_vault_pda(id: &Pubkey, owner: &Pubkey) "
            "-> Pubkey { todo!() }\n```\n", "utf-8")
        (c / "lessons" / "drafts" / "m02-l1-b.md").write_text(
            "# B\n\n```rust\nlet p = derive_vault_pda(&ID, &owner);\n```\n", "utf-8")
        (c / "lessons" / "drafts" / "m03-l1-c.md").write_text(
            "# C\n\n```rust\nlet p = derive_vault_pda(&ID, &owner, seed);\n```\n", "utf-8")
        (c / "lessons" / "drafts" / "000-cover.md").write_text(
            "```rust\nderive_vault_pda()\n```\n", "utf-8")
        man = {"course": {"id": "course"},
               "modules": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
               "lessons": [
                   {"id": "a", "module": "m1", "order": 1, "brief": {"ledger": {"provides": [
                       {"symbol": "fn:derive_vault_pda", "sig": "(id, owner)"}]}}},
                   {"id": "b", "module": "m2", "order": 1, "brief": {"ledger": {"consumes": [
                       "fn:derive_vault_pda"]}}},
                   {"id": "c", "module": "m3", "order": 1, "brief": {"ledger": {"consumes": [
                       "fn:derive_vault_pda"]}}}]}
        (c / "manifest.json").write_text(json.dumps(man), "utf-8")
        flags, st = scan_symbols(c, man)
        chk(len(lesson_files(c)) == 3, "000-cover.md is not a lesson")
        chk(any("lesson c calls derive_vault_pda() with 3" in f for f in flags),
            "scan: the 3-arg call in a later lesson is flagged")
        chk(not any("lesson b calls" in f for f in flags),
            "scan: the correct 2-arg call is NOT flagged")
        chk(st["mismatch"] == 1, "scan: exactly one mismatch")

        # inference finds the same drift with no ledger authored at all
        bare = json.loads(json.dumps(man))
        for l in bare["lessons"]:
            l["brief"] = {}
        f2, s2 = scan_symbols(c, bare, use_inferred=True)
        chk(s2["mismatch"] == 1, "infer: the same drift is found from the drafts alone")

        # renames: the old name surviving in later code
        man2 = json.loads(json.dumps(man))
        man2["lessons"][1]["brief"] = {"ledger": {"renames": [
            {"from": "derive_vault_pda", "to": "vault_pda", "since_lesson": "b"}]}}
        rf = check_renames(c, man2)
        chk(any("appears" in f and "lesson c" in f for f in rf),
            "renames: the old name is caught in a later fence")

        # paths: a starter asset the course does not ship
        man3 = json.loads(json.dumps(man))
        man3["course"]["starter_assets"] = ["assets/swap.js"]
        chk(any(f.startswith(HARD) for f in check_paths(c, man3)),
            "paths: a declared starter asset missing on disk is HARD")
        (c / "assets").mkdir()
        (c / "assets" / "swap.js").write_text("//\n", "utf-8")
        chk(not any(f.startswith(HARD) for f in check_paths(c, man3)),
            "paths: present starter asset passes")
        man4 = json.loads(json.dumps(man))
        man4["lessons"][1]["brief"] = {"ledger": {"opens": ["assets/ghost.js"]}}
        chk(any("not on disk" in f for f in check_paths(c, man4)),
            "paths: a missing path under a course-shipped root is HARD")
        man4["lessons"][1]["brief"] = {"ledger": {"opens": ["src/reader/own/tree.ts"]}}
        chk(not any(f.startswith(HARD) for f in check_paths(c, man4)),
            "paths: a path in the READER's repo is not checked against our tree")

    print("\n" + ("CONTINUITY SELFTESTS PASSED" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="continuity: the tree half of the continuity gate")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("check", "scan", "renames", "paths", "infer"):
        p = sub.add_parser(name)
        p.add_argument("--course", required=True)
        p.add_argument("--infer", action="store_true",
                       help="fall back to symbols inferred from the drafts when no ledger is declared")
        p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("dry-run")
    p.add_argument("--root", required=True)
    p.add_argument("--infer", action="store_true", default=True)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.print_help()
        return 2
    if a.cmd == "dry-run":
        return cmd_dry_run(Path(a.root), a.infer)
    course = Path(a.course)
    m = load_manifest(course)
    if a.cmd == "check":
        return cmd_check(course, a.infer, a.verbose)
    if a.cmd == "infer":
        return cmd_infer(course)
    if a.cmd == "paths":
        return 1 if _emit("continuity/paths", check_paths(course, m)) else 0
    if a.cmd == "renames":
        return 1 if _emit("continuity/renames", check_renames(course, m)) else 0
    flags, _st = scan_symbols(course, m, use_inferred=a.infer, verbose=a.verbose)
    return 1 if _emit("continuity/call-sites", flags) else 0


if __name__ == "__main__":
    raise SystemExit(main())
