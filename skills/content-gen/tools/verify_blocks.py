#!/usr/bin/env python3
"""Compile every rust/typescript block in a course's drafts against the course's DECLARED deps.

Why this exists: `verify_code.py`'s rust/typescript checkers return SKIP unconditionally (in
every env, container included), so "0 FAILs" for those languages has always been vacuous. This
tool actually compiles them.

The hard part is not compiling — it is telling a CONTENT bug apart from a HARNESS artifact.
Lesson code blocks are usually fragments: a struct excerpt, a handler body, a snippet whose
imports were shown three paragraphs earlier. Compiling those naively yields mass failures that
say nothing about the content. So every block is classified and every diagnostic is triaged:

    unresolved names/imports  -> SKIP  (the fragment's context is missing, not wrong)
    everything else           -> FAIL  (a real defect in what the lesson teaches)

That rule is the whole point. A block may only FAIL on something the reader would also hit.

  python3 verify_blocks.py <course-dir> --lang ts
  python3 verify_blocks.py <course-dir> --lang rust --json report.json
  python3 verify_blocks.py --selftest

Exit 0 = no FAILs (SKIPs are fine and reported loudly); 1 = at least one real failure; 2 = usage.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verify_code import extract_blocks  # noqa: E402  (single source of truth for fence parsing)

# Version pins: the range to install for a package a block imports. Anything not listed
# installs at "latest", which is honest for a course that does not pin it either.
TS_PINS = {
    "@solana/kit": "^7",
    "@solana/react": "^7",
    "typescript": "5.9.2",
}
# Packages that ship no types of their own: without these every use is a TS7016 SKIP, which
# would quietly hide real type errors in the surrounding lesson code.
TS_TYPES_FOR = {"express": "@types/express", "cors": "@types/cors", "ws": "@types/ws",
                "react": "@types/react", "react-dom": "@types/react-dom"}

# gather() prepends this to blocks whose fence tag was `tsx` (extract_blocks collapses the tag
# to "typescript"); the writer strips it and compiles those blocks as .tsx with JSX enabled.
TSX_MARK = "//tsx\n"
RUST_PINS = {
    "anchor_lang": ("anchor-lang", "=2.0.0-rc.1"),
    "anchor_spl": ("anchor-spl", "=2.0.0-rc.1"),
    "bytemuck": ("bytemuck", "1.25.2"),
    "litesvm": ("litesvm", "0.11.0"),
    "solana_sdk": ("solana-sdk", "3.1.10"),
    "solana_program": ("solana-program", "3.1.10"),
    "spl_token": ("spl-token", "8.0.0"),
    "spl_token_2022": ("spl-token-2022", "10.0.0"),
}
# Crates whose default feature set is not what the macro expansions need. `derive` gives
# bytemuck the Pod/Zeroable derives that #[zero_copy] emits; `min_const_generics` lets those
# derives cover arrays longer than 32, which account layouts routinely are.
RUST_FEATURES = {"bytemuck": ["derive", "min_const_generics"]}
# Crates named by macro EXPANSIONS rather than by any lesson's `use` line. They belong to the
# framework, so the dependency-resolution fallback must never strip them.
RUST_MACRO_DEPS = {"bytemuck", "wincode"}
# Crates that ship inside anchor-lang's prelude and must never become their own dependency.
RUST_NOT_CRATES = {"crate", "self", "super", "std", "core", "alloc"}


def _rust_dep_line(crate: str, ver: str, git_src: dict, course_feats: dict = None) -> str:
    """One [dependencies] line: a git inline table, a features table, or a plain version."""
    if crate in git_src:
        return f"{crate} = {git_src[crate]}"
    feats = sorted(set(RUST_FEATURES.get(crate, []))
                   | set((course_feats or {}).get(crate, [])))
    if feats:
        return f'{crate} = {{ version = "{ver}", features = [{", ".join(chr(34) + f + chr(34) for f in feats)}] }}'
    return f'{crate} = "{ver}"'
# Crates whose version defines what "correct" means. Their pins are never relaxed by the
# dependency-resolution fallback, and the resolved version is asserted after the warm build.
ANCHOR_PINNED = {"anchor-lang", "anchor-spl", "wincode"}

# ---- diagnostic triage -------------------------------------------------------------------
# A diagnostic matching these is a MISSING-CONTEXT signal: the fragment referenced something
# the lesson established elsewhere. Never a content bug -> SKIP.
TS_UNRESOLVED = re.compile(
    r"error TS(2304|2307|2552|2503|2686|2580|2792|7016|18004)\b"  # cannot find name/module/shorthand
)
# Diagnostics that only exist because THIS harness compiles with `strict`. The course may not;
# reporting them as failures would hold the content to a standard it never claimed. Surfaced
# separately as advisories so they inform the boards without blocking a gate.
TS_ADVISORY = re.compile(r"error TS(7005|7006|7008|7031|7034)\b")     # implicit-any family
# Parse-level failures, in either language.
SYNTAX_ERR = re.compile(r"error TS1\d{3}\b|error: expected|error: unexpected|is not followed by an item"
                        r"|error: mismatched closing|error\[E0584\]")
RUST_UNRESOLVED = re.compile(
    r"error\[E(0432|0433|0412|0425|0405|0422|0531|0603)\]"    # unresolved import/name/type/trait
    r"|cannot find (\w+ )?(type|value|function|macro|struct|trait|attribute)"
    r"|failed to resolve"
    r"|use of undeclared"
    r"|error\[E0583\]"          # `mod x;` whose file the snippet never ships
    # E0423 "expected value, found macro `line`": the fragment's own binding (`for line in …`)
    # lives in the prose above it, so the bare name falls through to a std macro of the same
    # name. That is a missing binding wearing a confusing hat, not a defect.
    r"|error\[E0423\]: expected value, found macro"
)
# Inference that the removed context would have supplied. Only ever applied to blocks THIS TOOL
# wrapped: `let (k, v) = pair.split_once('=')` cannot be typed once `pair` is gone, and rustc
# reports the consequence (E0282) rather than the cause. In a self-contained block the same
# diagnostic is the author's to fix, so `standalone` never gets this discount.
WRAPPED_INFERENCE = re.compile(r"error\[E028[23]\]|type annotations needed")


def classify_ts(code: str) -> str:
    """standalone (already a module) | fragment (needs wrapping).

    A trailing comma outranks an import line: lessons print "add this to the array" snippets that
    open with the import you need and end mid-list. Those are splices, not modules, and holding
    them to module syntax reports the lesson's formatting as a code defect.
    """
    if code.rstrip().endswith((",", "+", "&&", "||", "=>", "(", "[")):
        return "fragment"
    if re.search(r"^\s*(import|export)\s", code, re.M):
        return "standalone"
    return "fragment"


RUST_FIELD = re.compile(r"^\s*(?:pub\s+)?[\w_]+\s*:\s*[^;=]+,\s*(?://.*)?$")
# One enum variant per line: `Pending,` · `BadConfig(serde_json::Error),` · `Probe { url: String },`
# The trailing comma is load-bearing — it is what keeps match arms (`Some(x) => y,`) out.
RUST_VARIANT = re.compile(
    r"^\s*[A-Z]\w*(\s*\((?:[^()]|\([^()]*\))*\))?(\s*\{[^{}]*\})?\s*,\s*(?://.*)?$")


def classify_rust(code: str) -> str:
    """standalone | item | fields | variants | assoc | method | body.

    `fields` and `method` exist because the naive split gets them catastrophically wrong: a bare
    field list (`pub owner: Address,` …) lifted out of a struct is not a statement sequence, and
    wrapping it in a function yields "visibility `pub` is not followed by an item" — a harness
    artifact that was the single largest failure class before this existed. Likewise a method body
    using `self` needs an impl to live in, not a free function. `variants` is the same shape one
    level over: an enum grows by the variant the way a struct grows by the field, and a lesson
    that prints only the new variant is showing an edit, not a broken item.
    """
    if re.search(r"^\s*(use\s+anchor_lang|declare_id!|fn\s+main\s*\()", code, re.M):
        return "standalone"
    meaningful = [l for l in code.split("\n")
                  if l.strip() and not l.strip().startswith(("//", "#["))]
    if not meaningful:
        return "body"
    if all(RUST_FIELD.match(l) for l in meaningful):
        return "fields"
    if all(RUST_VARIANT.match(l) for l in meaningful):
        return "variants"
    first = meaningful[0].lstrip()
    if re.match(r"(pub\s+(struct|enum|fn|mod|const|static|type|trait|use)|struct\s|enum\s|impl\s"
                r"|trait\s|fn\s|mod\s|use\s|const\s|static\s|type\s)", first) \
            or code.lstrip().startswith("#["):
        # A method printed without the `impl` that owns it is still an item — but wrapping it at
        # item level makes rustc reject `self`. Give it an impl to live in instead. Only a block
        # whose FIRST item is that bare fn qualifies: a `trait` declaration also holds
        # `fn f(&self)` signatures, and forcing one into an impl produces "trait is not supported
        # in `impl`s", a syntax complaint about a block whose syntax is perfect.
        if re.match(r"(pub(\([^)]*\))?\s+)?fn\s", first) \
                and re.search(r"fn\s+\w+\s*(<[^>]*>)?\s*\([^)]*\bself\b", code) \
                and not re.search(r"\bimpl\b", code):
            return "assoc"
        return "item"
    if re.search(r"\bself\b", code):
        return "method"
    return "body"


TS_DECL = re.compile(r"\b(?:const|let|var|function|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)")


def ts_preamble(all_imports: dict, code: str = "", defaults: dict = None) -> str:
    """Re-import, for a fragment, the symbols it references and does not define itself.

    A fragment that says `address(...)` without an import line is normal lesson prose, not a
    bug — the import was shown earlier. Replaying the course's own import map lets such a
    fragment type-check for real instead of drowning in TS2304.

    It must be narrow, though: importing every symbol the course ever imports collides with the
    fragment's own declarations (a lesson that defines `type Ledger` next to a course module that
    exports `Ledger` yields TS2300) and invents failures that belong to the harness, not the text.
    So import only what this block actually mentions and has not declared or imported already.
    """
    if not code:
        return ""
    declared = set(TS_DECL.findall(code))
    for syms in re.findall(r"import\s*\{([^}]*)\}\s*from", code):
        for s in syms.split(","):
            declared.add(s.strip().split(" as ")[-1].strip())
    referenced = set(re.findall(r"[A-Za-z_$][\w$]*", code))
    lines, used = [], set(declared)
    for sym, mod in sorted((defaults or {}).items()):
        if sym in referenced and sym not in used:
            used.add(sym)
            lines.append(f"import {sym} from {mod!r};")
    for mod, syms in sorted(all_imports.items()):
        keep = sorted(s for s in syms if s in referenced and s not in used)
        if keep:
            used.update(keep)
            lines.append(f"import {{ {', '.join(keep)} }} from {mod!r};")
    return "\n".join(lines)


# `npm i @solana/kit@6.10.0 @solana-program/token@0.14.0` — the versions a reader actually types.
NPM_INSTALL = re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:i|install|add)\b([^\n`]*)")
NPM_SPEC = re.compile(r"(@?[\w.-]+(?:/[\w.-]+)?)@(\^?~?[\w.\-]+)")


def harvest_ts_pins(blocks, md_texts) -> dict:
    """Package -> version, taken from the course's own install lines.

    Guessing versions is how a harness invents failures: pinning @solana/kit ^7 for a course
    that deliberately teaches 6.10.0 (to satisfy @solana/pay's peer range) type-checks v6 code
    against a v7 API and reports the difference as the course's bug. Read the pins instead.
    Where a package is taught at several versions (a real per-workspace split), the most
    frequently taught one wins and the split is returned for reporting.
    """
    counts = {}
    for text in md_texts:
        for tail in NPM_INSTALL.findall(text):
            for pkg, ver in NPM_SPEC.findall(tail):
                if ver in ("latest",):
                    continue
                counts.setdefault(pkg, {}).setdefault(ver, 0)
                counts[pkg][ver] += 1
    pins, splits = {}, {}
    for pkg, vers in counts.items():
        best = max(vers.items(), key=lambda kv: kv[1])[0]
        pins[pkg] = best
        if len(vers) > 1:
            splits[pkg] = dict(vers)
    return pins, splits


CARGO_DEP = re.compile(r"^\s*([a-z][a-z0-9_-]*)\s*=\s*\"([=^~]?\d[\w.\-]*)\"\s*$", re.M)
CARGO_DEP_TABLE = re.compile(r"^\s*([a-z][a-z0-9_-]*)\s*=\s*\{[^}]*?version\s*=\s*\"([=^~]?\d[\w.\-]*)\"", re.M)


def crate_name(name: str, _cache={}) -> str:
    """The name crates.io actually publishes for `name`, or "" when nothing does.

    Two jobs in one lookup. First, existence: cargo names only ONE missing package per attempt,
    so a course that `use`s six of its own workspace crates would need six full resolution rounds
    to converge; pre-filtering collapses that to zero. Second, SPELLING: `use serde_json::` names
    a module path, and dash-for-underscore guessing invents `serde-json`, which cargo refuses
    outright ("no matching package found") — one wrong guess used to take the entire dependency
    graph down with it, dropping the course's real crates and turning every block that needed one
    into a cascade of invented failures. crates.io normalises the lookup and answers with the
    published spelling, so ask it.

    Network trouble is not evidence of absence: fall back to the dash guess and let cargo decide.
    """
    if name in _cache:
        return _cache[name]
    guess = name.replace("_", "-")
    try:
        import urllib.request
        req = urllib.request.Request(f"https://crates.io/api/v1/crates/{name}",
                                     headers={"User-Agent": "content-gen-verify/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8"))
            _cache[name] = (body.get("crate") or {}).get("name") or guess
    except Exception as e:
        _cache[name] = "" if "404" in str(e) else guess
    return _cache[name]


def _missing_from_cargo_errors(text: str) -> set:
    """Package names cargo reported as unresolvable, across cargo's error dialects.

    The newest one puts the name on a CONTINUATION line:

        error: no matching package found
        searched package name: `serde-json`
        perhaps you meant:      serde_json

    Missing that shape is expensive out of all proportion to its size: the drop-and-retry loop
    never fires, resolution "fails for an unknown reason", and the run falls back to the framework
    floor — discarding every crate the course actually teaches. Blocks then fail on cascades
    (`no method named context`, `no function named parse`) that no reader would ever see.
    """
    found = set(re.findall(r"no matching package (?:named )?`([^`]+)`", text))
    found |= set(re.findall(r"could not find `([^`]+)` in registry", text))
    found |= set(re.findall(r"no matching package found\s*\n\s*searched package name:\s*`?([^`\s]+)`?",
                            text))
    return found


# `anchor-lang = { git = "https://github.com/otter-sec/anchor.git", branch = "anchor-next" }`
CARGO_GIT = re.compile(
    r"^\s*([a-z][a-z0-9_-]*)\s*=\s*\{[^}]*?git\s*=\s*\"([^\"]+)\"([^}]*)\}", re.M)


def harvest_rust_crates(blocks, taught: dict) -> set:
    """Which crates the harness must depend on for these blocks to mean anything.

    Three sources of noise this filters, each of which cost a run before it existed:
      * `use ProbeState::*;` inside a fn imports an ENUM, not a crate. Crate names in a path are
        lowercase; an uppercase head is always a type in scope.
      * `mod engine;` makes the following `use engine::` a file in the reader's own crate. Left
        alone, the harness adds whatever stranger's crate holds that name on crates.io and lets it
        answer for the lesson's module.
      * a crate the course DECLARES and then calls by path only (`reqwest::blocking::Client`,
        never `use reqwest::`) is as real a dependency as any import. Both signals are required,
        which keeps out the pins a lesson merely quotes to be read — sqlx, in this course's
        "read three real-world dependency lines" exercise — and never installs.
    """
    crates, paths, local_mods = set(), set(), set()
    for _f, _n, code, _k in blocks:
        crates |= set(re.findall(r"^\s*use\s+([a-z][\w]*)\s*::", code, re.M))
        paths |= set(re.findall(r"(?<![\w:.])([a-z][a-z0-9_]{2,})::", code))
        local_mods |= set(re.findall(r"^\s*(?:pub\s+)?mod\s+([a-z][\w]*)\s*[;{]", code, re.M))
    crates |= {c for c in taught if c.replace("-", "_") in paths}
    return crates - RUST_NOT_CRATES - local_mods - {m.replace("_", "-") for m in local_mods}


def harvest_rust_git(md_texts) -> dict:
    """Crate -> inline table string, for deps the course sources from git rather than crates.io.

    This matters more than it looks: mastering-anchor-v2 declares
    `git otter-sec/anchor, branch anchor-next`, and that build differs from crates.io 2.0.0-rc.1 in
    at least one place that changes verdicts (`Address` in a wincode struct compiles on the branch
    and not on the release). Verifying against the registry version would report correct lessons
    as broken.
    """
    out = {}
    for text in md_texts:
        for lang, code in extract_blocks(text):
            if lang != "toml":
                continue
            for crate, url, rest in CARGO_GIT.findall(code):
                branch = re.search(r"branch\s*=\s*\"([^\"]+)\"", rest)
                rev = re.search(r"rev\s*=\s*\"([^\"]+)\"", rest)
                spec = f'{{ git = "{url}"'
                if branch:
                    spec += f', branch = "{branch.group(1)}"'
                if rev:
                    spec += f', rev = "{rev.group(1)}"'
                out.setdefault(crate.replace("-v2", ""), spec + " }")
    return out


def _ver_key(v: str):
    """'4.6' -> (4, 6). Sorts version strings numerically for the tie-break below."""
    return tuple(int(p) for p in re.findall(r"\d+", v)[:4])


def harvest_rust_pins(md_texts) -> dict:
    """Crate -> version, read from the Cargo.toml blocks the course prints.

    Ties go to the HIGHER version. Courses quote old pins as teaching material — this one prints
    `clap = "2.33.1"` in a "read three real-world dependency lines" exercise and
    `clap = { version = "4.6", features = ["derive"] }` as the line the reader actually adds, one
    mention each. First-seen wins would check the reader's clap-4 derive code against clap 2, where
    `Parser` does not exist, and report the lesson as broken.
    """
    counts = {}
    for text in md_texts:
        for lang, code in extract_blocks(text):
            if lang != "toml":
                continue
            for rx in (CARGO_DEP, CARGO_DEP_TABLE):
                for crate, ver in rx.findall(code):
                    counts.setdefault(crate, {}).setdefault(ver, 0)
                    counts[crate][ver] += 1
    return {c: max(v.items(), key=lambda kv: (kv[1], _ver_key(kv[0])))[0]
            for c, v in counts.items()}


# `clap = { version = "4.6", features = ["derive"] }` — the feature list on one dependency line.
CARGO_FEATURES = re.compile(
    r"^\s*([a-z][a-z0-9_-]*)\s*=\s*\{([^}]*)\}", re.M | re.S)


def harvest_rust_features(md_texts, pins: dict) -> dict:
    """Crate -> [features], from the course's own dependency lines.

    A pin without its features checks different code than the reader compiles: `clap = "4.6"`
    with no `derive` makes `#[derive(Parser)]` an unresolved macro, `serde` without `derive`
    does the same to `Serialize`, and both land as SKIPs that quietly retire real verification.
    Only lines carrying the winning version count, so a counter-example pin cannot donate its
    features. `default-features = false` is deliberately ignored: the harness wants the largest
    surface the course names anywhere, not the smallest one workspace happens to need.
    """
    out = {}
    for text in md_texts:
        for lang, code in extract_blocks(text):
            if lang != "toml":
                continue
            for crate, body in CARGO_FEATURES.findall(code):
                ver = re.search(r"version\s*=\s*\"([=^~]?\d[\w.\-]*)\"", body)
                if crate in pins and ver and ver.group(1) != pins[crate]:
                    continue
                feats = re.search(r"features\s*=\s*\[([^\]]*)\]", body)
                if feats:
                    out.setdefault(crate, set()).update(
                        f.strip().strip("\"'") for f in feats.group(1).split(",")
                        if f.strip().strip("\"'") and not f.strip().startswith("#"))
    return {k: sorted(v) for k, v in out.items() if v}


# A string literal holding an angle-bracketed instruction: declare_id!("<your program id>"),
# pubkey!("<paste your generated pubkey>"). Generics never appear inside quotes, so this cannot
# collide with real type parameters.
PLACEHOLDER = re.compile(r"""["'][^"'\n]*<[^"'>\n]+>[^"'\n]*["']""")
# A bare ellipsis where an expression/body belongs: `{ ... }` / `[ ... ]`. A spread always names
# its operand (`...foo`), so an ellipsis alone can never be real code — it is the author eliding.
ELLIPSIS_HOLE = re.compile(r"[\{\[]\s*\.\.\.\s*[\}\]]")


def has_placeholder(code: str) -> str:
    """'' or a reason: the block asks the reader to paste something before it can build."""
    m = PLACEHOLDER.search(code)
    if m:
        return (f"block contains an intentional reader placeholder {m.group(0)[:40]} — "
                "uncompilable by design")
    if ELLIPSIS_HOLE.search(code):
        return "block elides a body with a bare `...` — uncompilable by design"
    return ""


def unbalanced(code: str) -> str:
    """'' if delimiters balance, else a short reason.

    Lessons routinely split one function across two fenced blocks with prose between them: the
    first opens a brace the second closes. Half a construct cannot be compiled by anyone, so
    these are reported as SKIP rather than presented as syntax errors in the course's code.
    """
    for open_c, close_c, what in (("{", "}", "braces"), ("(", ")", "parens"), ("[", "]", "brackets")):
        a, b = code.count(open_c), code.count(close_c)
        if a != b:
            return f"block is half of a construct split across prose ({what} {a}/{b})"
    return ""


def _spec_name(spec: str) -> str:
    """'@solana/kit@^7' -> '@solana/kit'; 'express@latest' -> 'express'."""
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec


def _missing_from_npm_errors(text: str) -> set:
    """Package names npm reported as unavailable, across npm error dialects.

    npm <=10: `404 '<spec>' is not in this registry`
    npm >=11: `404  The requested resource '<spec>' could not be found or you do not
    have permission to access it.` — one shape for both unpublished names and
    invalid ones (e.g. the publish-lesson placeholder '@YOUR_NPM_USERNAME/pkg',
    which npm 11 rejects for capital letters before any registry lookup).
    """
    found = set(re.findall(r"404\s+'(\S+)' is not in this registry", text))
    found |= set(re.findall(r"404\s+The requested resource '(\S+)' could not be found", text))
    return {_spec_name(s) for s in found} - {""}


def _tsc(tsc: Path, work: Path, srcdir: str, project="tsconfig.json") -> dict:
    """Run tsc over one source dir; return {filename: [diagnostic, ...]}."""
    r = subprocess.run([str(tsc), "-p", project], cwd=work,
                       capture_output=True, text=True, timeout=1800)
    out = {}
    for line in (r.stdout + r.stderr).splitlines():
        m = re.match(rf"{srcdir}/(b\d+\.tsx?)\((\d+),(\d+)\):\s*(error TS\d+:.*)", line.strip())
        if m:
            out.setdefault(m.group(1), []).append(m.group(4))
    return out


def _split_imports(text: str):
    """(import lines, everything else) — handles multi-line brace imports."""
    imports, rest, buf = [], [], None
    for line in text.split("\n"):
        if buf is not None:
            buf.append(line)
            if "from" in line or line.strip().endswith(";"):
                imports.append("\n".join(buf)); buf = None
            continue
        s = line.strip()
        if s.startswith("import ") or s.startswith("import{"):
            if "from" in s or s.endswith(";"):
                imports.append(line)
            else:
                buf = [line]
        else:
            rest.append(line)
    if buf:
        imports.extend(buf)
    seen, uniq = set(), []
    for i in imports:
        if i.strip() not in seen:
            seen.add(i.strip()); uniq.append(i)
    return uniq, rest


def _ts_replay(prior_codes, code: str) -> str:
    """One module holding a lesson's earlier blocks plus this one: imports hoisted and
    de-duplicated, statements inside an async fn so top-level await stays legal."""
    imports, rest = _split_imports("\n".join(list(prior_codes) + [code]))
    return ("\n".join(imports) + "\nexport {};\nasync function __block(): Promise<void> {\n"
            + "\n".join(rest) + "\n}\nvoid __block;")


# Named imports, tolerating `type` and a default import in front:
#   import { A } from 'm' · import type { A } from 'm' · import express, { A } from 'm'
TS_NAMED_IMPORT = re.compile(
    r"import\s+(?:type\s+)?(?:[A-Za-z_$][\w$]*\s*,\s*)?\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
TS_DEFAULT_IMPORT = re.compile(
    r"import\s+(?:type\s+)?([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\})?\s*from\s*['\"]([^'\"]+)['\"]")


def collect_ts_imports(blocks) -> dict:
    """module -> {symbols} across every TS block in the course.

    Missing a form here is expensive: an unharvested `Request`/`Response` from express lets the
    bare names bind to the DOM globals instead, and the resulting `req.query does not exist`
    reads like a content bug when it is purely a harness miss.
    """
    out = {}
    for _f, _n, code, _k in blocks:
        for syms, mod in TS_NAMED_IMPORT.findall(code):
            clean = set()
            for s in syms.split(","):
                s = s.strip()
                if s.startswith("type "):
                    s = s[5:].strip()
                s = s.split(" as ")[0].strip()
                if s and re.match(r"^[A-Za-z_$][\w$]*$", s):
                    clean.add(s)
            if clean:
                out.setdefault(mod, set()).update(clean)
    return out


def collect_ts_defaults(blocks) -> dict:
    """symbol -> module for default imports (`import express from 'express'`)."""
    out = {}
    for _f, _n, code, _k in blocks:
        for sym, mod in TS_DEFAULT_IMPORT.findall(code):
            out.setdefault(sym, mod)
    return out


# Some blocks are SUPPOSED not to compile: a deliberately vulnerable snippet whose rejection is the
# lesson, a scaffold with a TODO the reader fills in, the V1 "before" in a migration module. Mark
# them in the markdown and the harness stops re-reporting them every round:
#     <!-- verify: expect-fail the V2 default rejects bare `dup`; that rejection is the lesson -->
EXPECT_FAIL = re.compile(r"<!--\s*verify:\s*expect-fail\s*(.*?)\s*-->", re.I)


def expect_fail_map(course: Path, lang: str) -> dict:
    """{(draft name, block index): reason} for blocks annotated as expected failures."""
    want = {"ts": ("typescript", "ts", "tsx"), "rust": ("rust", "rs")}[lang]
    out = {}
    for path in sorted((course / "lessons" / "drafts").glob("*.md")):
        lines, n, pending = path.read_text("utf-8").split("\n"), 0, None
        for line in lines:
            s = line.strip()
            m = EXPECT_FAIL.search(s)
            if m:
                pending = m.group(1) or "declared expect-fail"
                continue
            if s.startswith("```") and s != "```":
                info = s[3:].strip().lower()
                if info in want:
                    n += 1
                    if pending:
                        out[(path.name, n)] = pending
                if info:
                    pending = None
        # a marker only applies to the next fenced block; blanks between them are fine
    return out


def apply_expectations(rows, expect: dict):
    """FAIL on a marked block becomes EXPECTED; PASS on one becomes a FAIL worth knowing about."""
    for r in rows:
        key = (r["file"], r["block"])
        if key not in expect:
            continue
        why = expect[key]
        if r["status"] == "FAIL":
            r["status"], r["detail"] = "EXPECTED", f"expected failure — {why}"
        elif r["status"] == "PASS":
            r["status"] = "FAIL"
            r["detail"] = (f"marked expect-fail ({why}) but it COMPILES — the annotation or the "
                           f"lesson's claim is now wrong")
    return rows


def gather(course: Path, lang: str):
    """[(draft_name, block_index, code, kind)] for one language across a course's drafts."""
    drafts = sorted((course / "lessons" / "drafts").glob("*.md"))
    want = {"ts": "typescript", "rust": "rust"}[lang]
    out = []
    for d in drafts:
        n = 0
        for blang, code, info in extract_blocks(d.read_text("utf-8"), keep_info=True):
            if blang != want:
                continue
            n += 1
            kind = classify_ts(code) if lang == "ts" else classify_rust(code)
            if lang == "ts" and info == "tsx":
                code = TSX_MARK + code
            out.append((d.name, n, code, kind))
    return out


# ---- TypeScript --------------------------------------------------------------------------

def run_ts(course: Path, blocks, work: Path, verbose=False):
    pkgs = set()
    for _f, _n, code, _k in blocks:
        for mod in re.findall(r"from\s*['\"]([^'\"]+)['\"]", code):
            if mod.startswith("."):
                continue
            parts = mod.split("/")
            pkgs.add("/".join(parts[:2]) if mod.startswith("@") else parts[0])
    pkgs.discard("node:crypto")
    pkgs = {p for p in pkgs if not p.startswith("node:")}

    work.mkdir(parents=True, exist_ok=True)
    src = work / "src"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir()

    md_texts = [p.read_text("utf-8") for p in sorted((course / "lessons" / "drafts").glob("*.md"))]
    pins, splits = harvest_ts_pins(blocks, md_texts)
    if pins:
        print(f"[ts] using the course's own pins: "
              + ", ".join(f"{k}@{v}" for k, v in sorted(pins.items()) if k in pkgs), flush=True)
    for pkg, vers in sorted(splits.items()):
        if pkg in pkgs:
            print(f"[ts] NOTE {pkg} is taught at several versions {vers} (per-workspace split); "
                  f"checking against {pins[pkg]}", flush=True)

    peer_conflict = None
    if not (work / "node_modules").exists():
        specs = [f"{p}@{pins.get(p) or TS_PINS.get(p, 'latest')}" for p in sorted(pkgs)]
        specs += [TS_TYPES_FOR[p] for p in sorted(pkgs) if p in TS_TYPES_FOR]
        print(f"[ts] installing {len(specs)} packages: {' '.join(specs)}", flush=True)
        (work / "package.json").write_text(json.dumps({"name": "block-harness", "private": True,
                                                       "type": "module"}, indent=2))
        head = ["npm", "install", "--no-audit", "--no-fund",
                f"typescript@{TS_PINS['typescript']}", "@types/node"]
        # A course builds its own local artifacts (transfer-kit, verifier, …) and imports them
        # by bare name. Those are not registry packages; drop any 404 and retry, so imports of
        # them fall through to TS2307 -> SKIP instead of killing the whole run.
        base, dropped = head + specs, []
        for _ in range(4):
            r = subprocess.run(base, cwd=work, capture_output=True, text=True, timeout=900)
            if r.returncode == 0:
                break
            missing = _missing_from_npm_errors(r.stderr + r.stdout)
            if not missing:
                break
            dropped += sorted(missing)
            base = [s for s in base if _spec_name(s) not in missing]
            print(f"[ts] not on npm (course-local artifacts), dropping: {', '.join(sorted(missing))}",
                  flush=True)
        if r.returncode != 0:
            errs = [l for l in (r.stderr + r.stdout).splitlines() if "npm error" in l]
            blob = "\n".join(errs)
            # A peer-dependency conflict is not a harness problem — it means the course's OWN
            # declared dependency set does not co-install. Record it, then force the install so
            # the type-check can still run against what the reader would actually end up with.
            if "ERESOLVE" in blob:
                peer_conflict = " ".join(l.replace("npm error", "").strip()
                                         for l in errs if "peer" in l or "Found:" in l
                                         or "Could not resolve" in l)[:400]
                print(f"[ts] PEER CONFLICT (recorded as a finding): {peer_conflict}", flush=True)
                r = subprocess.run(base + ["--legacy-peer-deps"], cwd=work,
                                   capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                tail = "\n".join(errs[-6:])[:600] or (r.stderr or r.stdout)[-600:]
                return None, f"npm install failed:\n{tail}"

    (work / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "target": "ES2022", "module": "ESNext", "moduleResolution": "bundler",
            "strict": True, "noEmit": True, "skipLibCheck": True,
            "types": ["node"], "allowJs": False, "esModuleInterop": True,
            "jsx": "react-jsx",
        },
        "include": ["src/**/*.ts", "src/**/*.tsx"],
    }, indent=2))

    imports = collect_ts_imports(blocks)
    defaults = collect_ts_defaults(blocks)
    index, pre_rows = {}, []
    for i, (f, n, code, kind) in enumerate(blocks):
        tsx = code.startswith(TSX_MARK)
        if tsx:
            code = code[len(TSX_MARK):]
        why = has_placeholder(code) or unbalanced(code)
        if why:
            pre_rows.append({"file": f, "block": n, "kind": kind, "status": "SKIP", "detail": why})
            continue
        name = f"b{i:04d}.tsx" if tsx else f"b{i:04d}.ts"
        index[name] = (f, n, kind)
        if kind == "standalone":
            body = code
        else:
            # A fragment is statements lifted out of a function: replay just the imports this
            # block needs, then give the statements a function to live in so top-level await
            # stays legal.
            pre = ts_preamble(imports, code, defaults)
            body = f"{pre}\nexport {{}};\nasync function __block(): Promise<void> {{\n{code}\n}}\nvoid __block;"
        (src / name).write_text(body)

    tsc = work / "node_modules" / ".bin" / "tsc"
    diags = _tsc(tsc, work, "src")

    # Pass 2 — replay the lesson. Many blocks marked "standalone" are really continuations:
    # block 5 uses the `app` that block 1 created. Recompile each unresolved block with its
    # predecessors from the same draft prepended. UPGRADE-ONLY: a clean pass-2 promotes SKIP to
    # PASS; anything else keeps the pass-1 verdict, because a diagnostic in the replayed context
    # cannot be safely attributed to THIS block.
    retry = {}
    for name, (f, n, kind) in index.items():
        errs = diags.get(name, [])
        if not errs or verdict(f, n, kind, errs, TS_UNRESOLVED)["status"] != "SKIP":
            continue
        prior = [c for (pf, pn, c, _k) in blocks if pf == f and pn < n]
        if prior:
            retry[name] = _ts_replay(prior, next(c for (pf, pn, c, _k) in blocks
                                                 if pf == f and pn == n))
    if retry:
        src2 = work / "src2"
        if src2.exists():
            shutil.rmtree(src2)
        src2.mkdir()
        for name, body in retry.items():
            (src2 / name).write_text(body)
        (work / "tsconfig2.json").write_text(json.dumps({
            "extends": "./tsconfig.json", "include": ["src2/**/*.ts", "src2/**/*.tsx"],
        }, indent=2))
        d2 = _tsc(tsc, work, "src2", project="tsconfig2.json")
        promoted = 0
        for name in retry:
            if not d2.get(name):
                diags[name] = []
                promoted += 1
        print(f"[ts] lesson-replay promoted {promoted}/{len(retry)} unresolved blocks to a real check",
              flush=True)

    rows = list(pre_rows)
    if peer_conflict:
        # Only a real content defect if every package involved was pinned BY THE COURSE. If the
        # harness had to reach for `latest` on any of them, the conflict may be its own doing.
        unpinned = sorted(p for p in pkgs if p not in pins)
        real = not unpinned
        rows.append({"file": "<dependency set>", "block": 0, "kind": "install",
                     "status": "FAIL" if real else "WARN",
                     "detail": ("the course's own pins do not co-install: " if real else
                                f"deps did not co-install, but {len(unpinned)} package(s) had no "
                                f"course pin so the harness used latest ({', '.join(unpinned[:6])}): ")
                               + peer_conflict,
                     "errors": [peer_conflict]})
    for name, (f, n, kind) in index.items():
        errs = diags.get(name, [])
        rows.append(verdict(f, n, kind, errs, TS_UNRESOLVED, TS_ADVISORY))
    return rows, None


# ---- Rust --------------------------------------------------------------------------------

RUST_BARE_PREAMBLE = "#![allow(unused, dead_code, unexpected_cfgs)]\n"
RUST_ITEM_PREAMBLE = RUST_BARE_PREAMBLE + "use anchor_lang::prelude::*;\n"

# Anchor's prelude exports a ONE-parameter `Result<T>` that shadows `std::result::Result`. Inject
# it into a block that is not anchor code — a plain-Rust scratch file, a Pinocchio handler — and
# every honest `Result<T, E>` in it becomes "type alias takes 1 generic argument but 2 were
# supplied". So only add the prelude when the block actually reaches for anchor.
RUST_ANCHOR_MARKER = re.compile(
    r"#\[(account|program|event|derive\(Accounts|error_code|instruction)"
    r"|\b(Context|Signer|SystemAccount|UncheckedAccount|InterfaceAccount|declare_id|emit!"
    r"|require(_eq|_gte|_keys_eq)?!|msg!|InitSpace|Address|Pod(U64|U32|U16)|Slab|BorshAccount)\b"
    r"|\banchor_lang\b|\banchor_spl\b"
    r"|->\s*Result<[^,>]*>")           # anchor's one-parameter Result alias
# Module 9 compares anchor against raw Pinocchio/native. That code has its own `Signer` and its own
# `Result<T, E>`, so an anchor marker can fire on it by coincidence; these signals are decisive
# against, and are checked first. workers-rs is the same collision in a non-Solana course: a
# Cloudflare handler is `#[event(fetch)]` over `worker::{Request, Response, Context}`, every token
# of which the anchor markers above also claim. Inject the prelude there and anchor's `#[event]`
# macro answers for the worker crate's, rejecting a correct handler with "unknown `#[event]`
# mode — only `bytemuck` is accepted": a verdict about a framework the lesson never mentions.
RUST_NOT_ANCHOR = re.compile(r"\bProgramError\b|\bpinocchio\b|&'\w+\s+AccountInfo|\bentrypoint!"
                             r"|\bworker(_macros)?::|\buse\s+worker\b|#\[event\((fetch|scheduled|start)")


def rust_preamble(code: str) -> str:
    if RUST_NOT_ANCHOR.search(code):
        return RUST_BARE_PREAMBLE
    return RUST_ITEM_PREAMBLE if RUST_ANCHOR_MARKER.search(code) else RUST_BARE_PREAMBLE


def rust_wrap(kind: str, code: str) -> str:
    """The one source file this block gets compiled as: preamble, shell, code.

    The shell is a guess at the context the lesson removed, so it is built to be RECOGNISABLE
    when it guesses wrong — every synthetic name starts `__Block`, which verdict() discounts.
    """
    pre = rust_preamble(code)
    anchor = pre is RUST_ITEM_PREAMBLE
    # The error type is fabricated, so name it after the wrapper. A fragment lifted out of
    # `fn parse(..) -> Result<Config, String>` still says `return Err(format!(..))`, and one out
    # of an HTTP arm still says `send().await?`; against a guessed `()` both report a type error
    # the reader never sees. Naming it __BlockErr does not make those compile — it makes the
    # resulting diagnostic SAY it is about this harness's scaffolding. Anchor blocks keep anchor's
    # own Result: there the error type is not a guess, it is the framework's, and `?` against it
    # must stay checkable.
    err_decl = "" if anchor else "struct __BlockErr;\n"
    ret = "anchor_lang::Result<()>" if anchor else "std::result::Result<(), __BlockErr>"
    # Two contexts a fragment routinely loses, both cheap to restore and both otherwise fatal:
    # `.await` needs an async fn (E0728) and `continue`/`break` need a loop (E0268). The TS side
    # has always wrapped fragments in `async function` for exactly this reason. The loop is
    # conditional where async is not, because an unconditional loop would invent a second
    # iteration and with it E0382 moved-value errors that belong to no one.
    loop_open, loop_close = "", ""
    if re.search(r"\b(continue|break)\b", code) and not re.search(r"\b(loop|for|while)\b", code):
        loop_open, loop_close = "for __i in 0..1 {\n", "}\n"
    if kind == "standalone":
        body = RUST_BARE_PREAMBLE + code
    elif kind == "item":
        body = pre + code
    elif kind == "fields":
        body = pre + "pub struct __Block {\n" + code + "\n}\n"
    elif kind == "variants":
        body = pre + "pub enum __Block {\n" + code + "\n}\n"
    elif kind == "assoc":
        body = pre + "struct __Block;\nimpl __Block {\n" + code + "\n}\n"
    elif kind == "method":
        body = (pre + err_decl + "struct __Block;\nimpl __Block {\n"
                + f"async fn __block(&self) -> {ret} {{\n" + loop_open + code
                + "\n" + loop_close + "    Ok(())\n}\n}\n")
    else:
        body = (pre + err_decl + f"async fn __block() -> {ret} {{\n" + loop_open + code
                + "\n" + loop_close + "    Ok(())\n}\n")
    if "declare_id!" not in body and "#[program]" in body:
        body = body.replace("use anchor_lang::prelude::*;",
                            "use anchor_lang::prelude::*;\n"
                            'declare_id!("11111111111111111111111111111111");', 1)
    return body

# Rustc summary lines ("could not compile X due to 2 previous errors") carry no diagnostic of
# their own; counting them as findings both double-reports and, when the real diagnostics land
# in a form the parser misses, leaves a block FAILing with nothing to act on.
_CARGO_SUMMARY = re.compile(r"^(could not compile|aborting due to)")


def _cargo_errors(stdout: str):
    """Per-diagnostic error strings from `cargo check --message-format json`."""
    errs = []
    for line in stdout.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("reason") != "compiler-message":
            continue
        d = m.get("message") or {}
        if d.get("level") != "error":
            continue
        msg = (d.get("message") or "").strip()
        if not msg or _CARGO_SUMMARY.match(msg):
            continue
        code = ((d.get("code") or {}) or {}).get("code") or ""
        # The primary span's label carries the types. "mismatched types" alone is useless in a
        # report AND undecidable in triage: only the label says whether the mismatch is against
        # the reader's types or against `__BlockErr`, the return type this harness invented
        # ("expected `__BlockErr`, found `String`").
        label = next((s.get("label") for s in (d.get("spans") or [])
                      if s.get("is_primary") and s.get("label")), "")
        head = f"error[{code}]: {msg}" if code else f"error: {msg}"
        errs.append(f"{head} — {label}" if label else head)
    return errs


def run_rust(course: Path, blocks, work: Path, verbose=False):
    md_texts = [p.read_text("utf-8") for p in sorted((course / "lessons" / "drafts").glob("*.md"))]
    taught = harvest_rust_pins(md_texts)
    feats = harvest_rust_features(md_texts, taught)
    crates = harvest_rust_crates(blocks, taught)
    git_src = harvest_rust_git(md_texts)
    if git_src:
        print("[rust] course sources from git (using it, not crates.io): "
              + ", ".join(sorted(git_src)), flush=True)
    deps = {}
    for c in sorted(crates):
        name, ver = RUST_PINS.get(c, (crate_name(c) or c.replace("_", "-"), "*"))
        # The course's own Cargo.toml wins over this file's defaults — same reason as the npm
        # pins: checking against a version the course never names tests the wrong thing.
        deps[name] = taught.get(name, ver)
    deps.setdefault("anchor-lang", taught.get("anchor-lang", RUST_PINS["anchor_lang"][1]))
    # anchor-lang 2.x's #[program] expands to code that names ::wincode directly, so a crate
    # using the macro must depend on it even though no lesson `use`s it. Without this every
    # #[program] block fails to expand and buries the real diagnostics under cascade noise.
    deps.setdefault("wincode", taught.get("wincode", "0.5"))
    # Same class: #[zero_copy] / #[account(zero_copy)] expand to derives that name ::bytemuck.
    # Without the crate the Pod/Zeroable impls are never emitted, and every *use* of the struct
    # then reports `T: Pod is not satisfied` — a cascade that reads exactly like a real layout
    # bug. (The genuine layout bug, implicit padding, reports E0080 instead, and still does.)
    if any(re.search(r"#\[(account\([^)]*)?zero_copy", code) for _f, _n, code, _k in blocks):
        deps.setdefault("bytemuck", taught.get("bytemuck", RUST_PINS["bytemuck"][1]))
    absent = sorted(c for c in deps if not crate_name(c))
    for c in absent:
        deps.pop(c, None)
    if absent:
        print(f"[rust] not on crates.io (course-local artifacts, or wrong crate names — judge "
              f"each): {', '.join(absent)}", flush=True)
    if taught:
        print("[rust] course-taught pins: "
              + ", ".join(f"{k}={v}" for k, v in sorted(taught.items()) if k in deps), flush=True)
    if feats:
        print("[rust] course-taught features: "
              + ", ".join(f"{k}={v}" for k, v in sorted(feats.items()) if k in deps), flush=True)

    work.mkdir(parents=True, exist_ok=True)
    (work / "src").mkdir(exist_ok=True)
    dep_lines = "\n".join(_rust_dep_line(k, v, git_src, feats) for k, v in sorted(deps.items()))
    (work / "Cargo.toml").write_text(
        "[package]\nname = \"block-harness\"\nversion = \"0.0.0\"\nedition = \"2021\"\n"
        "\n[lib]\npath = \"src/lib.rs\"\n"
        f"\n[dependencies]\n{dep_lines}\n"
    )
    (work / "rust-toolchain.toml").write_text("[toolchain]\nchannel = \"1.89.0\"\n")

    # Warm the dependency graph once; every per-block check after this is incremental.
    # Three attempts, degrading deliberately: the course's declared pins first (what the reader
    # gets), then let cargo resolve, then anchor-lang alone. A wrong pin must not cost the run —
    # it becomes a reported finding while the blocks still get checked.
    (work / "src" / "lib.rs").write_text(RUST_ITEM_PREAMBLE)
    dep_note, notes, dropped, ds, last, warm_ok = None, [], [], dict(deps), "", False
    for _attempt in range(8):
        (work / "Cargo.toml").write_text(
            "[package]\nname = \"block-harness\"\nversion = \"0.0.0\"\nedition = \"2021\"\n"
            "\n[lib]\npath = \"src/lib.rs\"\n"
            "\n[dependencies]\n"
            + "\n".join(_rust_dep_line(k, v, git_src, feats) for k, v in sorted(ds.items())) + "\n"
        )
        print(f"[rust] warming {len(ds)} deps ({', '.join(sorted(ds))}) …", flush=True)
        warm = subprocess.run(["cargo", "check", "--quiet"], cwd=work,
                              capture_output=True, text=True, timeout=3600)
        if warm.returncode == 0:
            warm_ok = True
            break
        out, last = warm.stderr + warm.stdout, (warm.stderr or warm.stdout).strip()[-400:]
        # A course builds its own workspace crates (quarter-vault, cabinet-counter, …) and `use`s
        # them by name. Those are not registry crates; drop them and let blocks that need them
        # resolve to SKIP. Names that are NOT course artifacts but still missing are reported —
        # a lesson telling readers to depend on a crate that does not exist is a content bug.
        miss = set(_missing_from_cargo_errors(out))
        if miss:
            for m in miss:
                ds.pop(m, None)
            dropped += sorted(miss)
            continue
        # NEVER relax the framework pin. `anchor-lang = "*"` resolves to the latest STABLE (1.1.2),
        # because `*` excludes pre-releases — which silently swaps the oracle to Anchor 1.x and
        # then reports correct V2 code as broken ("bracket arguments must be the lifetime and
        # type", "missing lifetime specifier"). That inverts findings rather than losing them.
        keep = {k: v for k, v in ds.items() if k in ANCHOR_PINNED}
        if any(v != "*" for k, v in ds.items() if k not in ANCHOR_PINNED):
            notes.append("course-taught version pins did not resolve together; relaxed everything "
                         "except the framework pin to cargo-resolved versions")
            ds = {k: ("*" if k not in ANCHOR_PINNED else v) for k, v in ds.items()}
            ds.update(keep)
            continue
        # The floor is the framework PLUS its macro-expansion deps. Those are not any lesson's
        # imports — they are named by code the derives generate — so dropping them does not lose
        # a verdict, it inverts one: the derive stops expanding and every *use* of the type then
        # reports a missing trait impl that the reader would never see.
        floor = {"anchor-lang": deps.get("anchor-lang", RUST_PINS["anchor_lang"][1])}
        floor.update({k: v for k, v in ds.items() if k in RUST_MACRO_DEPS})
        if set(ds) != set(floor):
            notes.append("dependency graph unresolvable; fell back to the framework floor "
                         "(anchor-lang plus its macro-expansion deps)")
            ds = floor
            continue
        return None, "dependency graph failed to build at every fallback: " + last
    # Assert the oracle. Read what cargo ACTUALLY resolved, not what we asked for: a fallback,
    # a transitive requirement or a yanked version can substitute a different framework, and every
    # verdict in this run is only meaningful relative to the version that really compiled.
    lock = (work / "Cargo.lock")
    resolved = {}
    if lock.exists():
        txt = lock.read_text("utf-8")
        for blk in txt.split("[[package]]"):
            nm = re.search(r'^name = "([^"]+)"', blk, re.M)
            vs = re.search(r'^version = "([^"]+)"', blk, re.M)
            sc = re.search(r'^source = "([^"]+)"', blk, re.M)
            if nm and vs and nm.group(1) in ANCHOR_PINNED:
                resolved[nm.group(1)] = (vs.group(1), sc.group(1) if sc else "local")
    want = (deps.get("anchor-lang") or "").lstrip("=^~")
    got, src = resolved.get("anchor-lang", ("?", "?"))
    where = "git " + src.split("#")[-1][:12] if src.startswith("git+") else "crates.io"
    ok = "anchor-lang" in git_src or (want and got.startswith(want))
    print(f"[rust] ORACLE: anchor-lang {got} from {where} "
          f"({'matches' if ok else 'DOES NOT MATCH'} what the course declares)", flush=True)
    if "anchor-lang" in git_src and not src.startswith("git+"):
        return None, ("course declares anchor-lang from git but cargo resolved the crates.io "
                      "release; refusing to judge against a different build")
    if warm_ok and not ok:
        return None, (f"resolved anchor-lang {got} but the course targets {want}; refusing to judge "
                      f"V2 code against a different framework major")

    if not warm_ok:
        # Refusing to continue is the point: when cargo cannot resolve the graph it emits no
        # compiler messages at all, and "no errors parsed" would silently score every block PASS.
        # A harness that cannot build must fail loudly, never green.
        return None, ("dependency graph never built, so no block could be compiled; refusing to "
                      "report PASS for unchecked code. Last cargo error:\n" + last)
    if dropped or absent:
        gone = sorted(set(dropped) | set(absent))
        notes.append("referenced but absent from crates.io: " + ", ".join(gone))
    if notes:
        dep_note = "; ".join(notes)

    rows = []
    if dep_note:
        # WARN, not FAIL: the harness resolves a dependency set the course never states in full,
        # so a resolution failure here is at least as likely to be this file's guess as the
        # course's error. It is a lead for the boards, not a verdict on the content.
        rows.append({"file": "<dependency set>", "block": 0, "kind": "deps",
                     "status": "WARN", "detail": dep_note, "errors": [dep_note]})
    for i, (f, n, code, kind) in enumerate(blocks):
        why = has_placeholder(code) or unbalanced(code)
        if why:
            rows.append({"file": f, "block": n, "kind": kind, "status": "SKIP", "detail": why})
            if verbose:
                print(f"  {f} #{n} [{kind}] -> SKIP ({why})", flush=True)
            continue
        (work / "src" / "lib.rs").write_text(rust_wrap(kind, code))
        r = subprocess.run(["cargo", "check", "--message-format", "json"],
                           cwd=work, capture_output=True, text=True, timeout=600)
        errs = _cargo_errors(r.stdout)
        if r.returncode != 0 and not errs:
            # Nonzero with nothing parsed means cargo failed outside compilation. Never PASS.
            rows.append({"file": f, "block": n, "kind": kind, "status": "SKIP",
                         "detail": "cargo failed without emitting diagnostics (harness problem): "
                                   + (r.stderr or "").strip()[-160:]})
        else:
            rows.append(verdict(f, n, kind, errs, RUST_UNRESOLVED))
        if verbose:
            print(f"  {f} #{n} [{kind}] -> {rows[-1]['status']}", flush=True)
    return rows, None


# ---- shared ------------------------------------------------------------------------------

def verdict(f, n, kind, errs, unresolved_re, advisory_re=None):
    """Triage a block's diagnostics into PASS / FAIL / WARN / SKIP.

    Ordering matters: a block only FAILs on a diagnostic that is neither missing context nor an
    artifact of a stricter compiler setting than the course claims.
    """
    row = {"file": f, "block": n, "kind": kind}
    if not errs:
        return {**row, "status": "PASS", "detail": "compiles"}
    # A syntax error inside a block THIS TOOL wrapped is far more likely to be the wrapper's
    # fault than the author's: the snippet was a partial object literal or argument list and the
    # synthesized shell was the wrong one. Only a self-contained block is held to syntax.
    if kind not in ("standalone",):
        syntax = [e for e in errs if SYNTAX_ERR.search(e)]
        if syntax:
            return {**row, "status": "SKIP",
                    "detail": f"snippet did not survive harness wrapping ({kind}): {syntax[0][:150]}"}
        infer = [e for e in errs if WRAPPED_INFERENCE.search(e)]
        if infer:
            errs = [e for e in errs if e not in infer]
            if not errs:
                return {**row, "status": "SKIP",
                        "detail": "inference needs context the fragment does not carry: "
                                  + infer[0][:150]}
    # Any complaint about the synthesized `__Block` type is by definition about scaffolding this
    # tool invented (a method body wrapped in an empty struct), never about the lesson's code.
    if any("__Block" in e for e in errs):
        return {**row, "status": "SKIP",
                "detail": "diagnostic is about the harness's synthetic wrapper type: "
                          + next(e for e in errs if "__Block" in e)[:150]}
    rest = [e for e in errs if not unresolved_re.search(e)]
    advisory = [e for e in rest if advisory_re and advisory_re.search(e)]
    real = [e for e in rest if e not in advisory]
    if real:
        return {**row, "status": "FAIL", "detail": real[0][:300], "errors": real[:10]}
    if advisory:
        return {**row, "status": "WARN", "detail": advisory[0][:300], "errors": advisory[:10]}
    return {**row, "status": "SKIP",
            "detail": f"unresolved context only ({len(errs)} diag): {errs[0][:180]}"}


def report(rows, lang):
    P = [r for r in rows if r["status"] == "PASS"]
    F = [r for r in rows if r["status"] == "FAIL"]
    W = [r for r in rows if r["status"] == "WARN"]
    S = [r for r in rows if r["status"] == "SKIP"]
    X = [r for r in rows if r["status"] == "EXPECTED"]
    if F:
        print(f"\n=== {len(F)} REAL FAILURES ({lang}) ===")
        for r in F:
            print(f"  {r['file']} #{r['block']} [{r['kind']}]  {r['detail']}")
    if W:
        print(f"\n=== {len(W)} ADVISORY (strict-mode only; course may not claim strict) ===")
        for r in W[:12]:
            print(f"  {r['file']} #{r['block']} [{r['kind']}]  {r['detail'][:140]}")
        if len(W) > 12:
            print(f"  … and {len(W) - 12} more")
    if S:
        print(f"\n=== {len(S)} SKIP (fragment context missing — not content bugs) ===")
        for r in S[:15]:
            print(f"  {r['file']} #{r['block']} [{r['kind']}]  {r['detail'][:140]}")
        if len(S) > 15:
            print(f"  … and {len(S) - 15} more")
    print(f"\nverify_blocks[{lang}]: {len(P)} PASS · {len(F)} FAIL · {len(W)} WARN · {len(S)} SKIP"
          + (f" · {len(X)} EXPECTED-FAIL" if X else "")
          + f" (of {len(rows)} blocks)")
    return 1 if F else 0


def selftest() -> int:
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("ok   " if c else "FAIL ") + m)
        ok = ok and c

    chk(classify_ts("import { a } from 'b';\nconst x = a();") == "standalone", "ts import -> standalone")
    chk(classify_ts("const x = address('foo');") == "fragment", "ts bare stmt -> fragment")
    chk(classify_rust("use anchor_lang::prelude::*;\nfn main() {}") == "standalone", "rust use -> standalone")
    chk(classify_rust("#[account]\npub struct V { pub a: u64 }") == "item", "rust attr -> item")
    chk(classify_rust("let x = 1;\nmsg!(\"{}\", x);") == "body", "rust stmts -> body")
    chk(classify_rust("    pub owner: Address,\n    pub credit: u64,") == "fields",
        "rust bare field list -> fields (was the biggest false-FAIL class)")
    chk(classify_rust("self.credit = self.credit.checked_add(x)?;") == "method",
        "rust self-using body -> method")
    chk(classify_rust("pub fn go() -> Result<()> { Ok(()) }") == "item", "rust pub fn -> item")
    chk(classify_rust("pub fn credit(&self) -> u64 { self.credit }") == "assoc",
        "rust bare method with self -> assoc (needs an impl, not item level)")
    chk(classify_rust("impl V {\n pub fn credit(&self) -> u64 { self.credit }\n}") == "item",
        "rust method already inside impl stays item")
    chk(classify_rust("pub trait ProbeSource {\n    fn next_latency(&mut self) -> Option<u64>;\n}")
        == "item", "rust trait declaration stays item (an impl wrapper would reject its own fns)")
    chk(classify_rust("    #[error(\"config rejected: {0}\")]\n    BadConfig(serde_json::Error),")
        == "variants", "rust bare enum variant -> variants (an enum grows the way a struct does)")
    chk(classify_rust("    Pending,\n    Up,\n    Down,") == "variants", "rust plain variant list")
    chk(classify_rust("match x {\n    Some((k, v)) => (k, v),\n    None => return,\n}") != "variants",
        "match arms are not variants (the trailing comma alone must not decide)")
    chk(has_placeholder("export const c = { ... };") != "", "bare object ellipsis -> placeholder SKIP")
    chk(has_placeholder("const c = { ...defaults, a: 1 };") == "", "real spread is NOT a placeholder")
    ki = extract_blocks("```tsx\nexport function P() { return <div/> }\n```\n", keep_info=True)
    chk(ki and ki[0][0] == "typescript" and ki[0][2] == "tsx",
        "extract_blocks keep_info preserves the tsx fence tag")
    chk(extract_blocks("```ts\nconst a = 1;\n```\n") == [("typescript", "const a = 1;")],
        "extract_blocks default shape unchanged (2-tuples)")
    chk(_missing_from_npm_errors("npm error 404 'pulse-core@latest' is not in this registry")
        == {"pulse-core"}, "npm10 404 shape -> missing pkg")
    chk(_missing_from_npm_errors(
        "npm error 404  The requested resource '@YOUR_NPM_USERNAME/pulse-core@latest' could not "
        "be found or you do not have permission to access it.")
        == {"@YOUR_NPM_USERNAME/pulse-core"},
        "npm11 404 shape (incl. invalid placeholder names) -> missing pkg")
    chk(classify_ts("getInstruction({ a: 1 }),") == "fragment", "ts trailing-comma splice -> fragment")
    chk(classify_ts("import x from 'y';\nconst a = x();") == "standalone", "ts real module -> standalone")
    v = verdict("f.md", 1, "item", ["error: cannot find derive macro `Accounts` in this scope"],
                RUST_UNRESOLVED)
    chk(v["status"] == "SKIP", "rust missing derive macro -> SKIP")
    chk(rust_preamble("#[account]\npub struct V { pub a: u64 }") is RUST_ITEM_PREAMBLE,
        "anchor block gets the anchor prelude")
    chk(rust_preamble("pub trait G { fn c(&self) -> Result<(), String>; }") is RUST_BARE_PREAMBLE,
        "plain-Rust block does NOT get the prelude (it shadows Result<T,E>)")
    chk(rust_preamble("impl<'a> TryFrom<&'a [u8]> for W<'a> { type Error = ProgramError; }")
        is RUST_BARE_PREAMBLE, "pinocchio block does NOT get the anchor prelude")
    chk(rust_preamble("struct W<'a> { authority: &'a AccountInfo }\ntype E = ProgramError;")
        is RUST_BARE_PREAMBLE, "pinocchio 'Signer' lookalike does not force the anchor prelude")
    chk(rust_preamble("pub fn go(x: u64) -> Result<()> { Ok(()) }") is RUST_ITEM_PREAMBLE,
        "one-parameter Result<T> implies anchor's alias")
    rr = apply_expectations([{"file": "a.md", "block": 1, "status": "FAIL", "detail": "boom"}],
                            {("a.md", 1): "the rejection is the lesson"})
    chk(rr[0]["status"] == "EXPECTED", "declared expect-fail turns FAIL into EXPECTED")
    rr = apply_expectations([{"file": "a.md", "block": 1, "status": "PASS", "detail": "compiles"}],
                            {("a.md", 1): "the rejection is the lesson"})
    chk(rr[0]["status"] == "FAIL", "an expect-fail block that COMPILES is itself a failure")
    rr = apply_expectations([{"file": "b.md", "block": 2, "status": "FAIL", "detail": "boom"}],
                            {("a.md", 1): "x"})
    chk(rr[0]["status"] == "FAIL", "unmarked blocks are untouched")
    g = harvest_rust_git(['```toml\nanchor-lang = { git = "https://github.com/otter-sec/anchor.git", '
                          'branch = "anchor-next" }\n```'])
    chk(g.get("anchor-lang") == '{ git = "https://github.com/otter-sec/anchor.git", '
                                'branch = "anchor-next" }', "git dependency harvested verbatim")
    g = harvest_rust_git(['```toml\nanchor-spl-v2 = { git = "https://x/y.git", rev = "abc123" }\n```'])
    chk("anchor-spl" in g and 'rev = "abc123"' in g["anchor-spl"],
        "the -v2 crate-name suffix is normalised and rev is kept")
    bl = [("a.md", 1, "mod engine;\nuse engine::ProbeError;\nuse serde_json::Value;", "item"),
          ("a.md", 2, "use ProbeState::*;\nlet c = reqwest::blocking::Client::new();", "body")]
    cr = harvest_rust_crates(bl, {"reqwest": "0.13", "sqlx": "0.6.2"})
    chk("serde_json" in cr, "crate harvest: a plain import is a dependency")
    chk("reqwest" in cr, "crate harvest: declared by the course AND called by path -> dependency")
    chk("sqlx" not in cr, "crate harvest: a pin the course only quotes to be read is NOT installed")
    chk("engine" not in cr, "crate harvest: `mod engine;` means the reader's own file, not a crate")
    chk("ProbeState" not in cr, "crate harvest: `use ProbeState::*` imports an enum, not a crate")
    chk(_missing_from_cargo_errors("error: no matching package named `pulse-engine` found")
        == {"pulse-engine"}, "cargo: classic missing-package dialect")
    chk(_missing_from_cargo_errors(
        "error: no matching package found\n  searched package name: `serde-json`\n"
        "  perhaps you meant:      serde_json\n") == {"serde-json"},
        "cargo: continuation-line dialect (one miss used to collapse the whole graph)")
    p = harvest_rust_pins(['```toml\nclap = { version = "2.33.1", default-features = false }\n```',
                           '```toml\nclap = { version = "4.6", features = ["derive"] }\n```'])
    chk(p.get("clap") == "4.6", "pins: tie goes to the higher version, not the first seen")
    p = harvest_rust_pins(['```toml\ntokio = "1.53"\n```', '```toml\ntokio = "1.53"\n```',
                           '```toml\ntokio = "1.99"\n```'])
    chk(p.get("tokio") == "1.53", "pins: a clear count still beats a higher version")
    fe = harvest_rust_features(['```toml\nclap = { version = "2.33.1", features = ["suggestions"] }\n```',
                                '```toml\nclap = { version = "4.6", features = ["derive"] }\n```'],
                               {"clap": "4.6"})
    chk(fe.get("clap") == ["derive"],
        "features: only the winning version's features count (a quoted pin cannot donate its own)")
    fe = harvest_rust_features(['```toml\ntokio = { version = "1.53", features = ["macros", "time"] }\n```'],
                               {"tokio": "1.53"})
    chk(fe.get("tokio") == ["macros", "time"], "features: harvested from the course's own line")
    chk(_rust_dep_line("clap", "4.6", {}, {"clap": ["derive"]})
        == 'clap = { version = "4.6", features = ["derive"] }',
        "dep line carries the course's features (without derive, #[derive(Parser)] is a SKIP)")
    chk(has_placeholder('declare_id!("<your generated program id>");') != "",
        "reader placeholder detected -> not a content bug")
    chk(has_placeholder('let v: Vec<u8> = vec![]; let s = "ok";') == "",
        "real generics are not mistaken for placeholders")
    chk(unbalanced("async function main() {\n  const a = 1;") != "", "unbalanced half-block detected")
    chk(unbalanced("const a = { b: 1 };") == "", "balanced block accepted")
    v = verdict("f.md", 1, "fragment", ["error TS1005: '}' expected."], TS_UNRESOLVED, TS_ADVISORY)
    chk(v["status"] == "SKIP", "ts syntax error in a WRAPPED fragment -> SKIP (wrapper's fault)")
    v = verdict("f.md", 1, "standalone", ["error TS1005: '}' expected."], TS_UNRESOLVED, TS_ADVISORY)
    chk(v["status"] == "FAIL", "ts syntax error in a self-contained block -> FAIL (author's)")
    v = verdict("f.md", 1, "fragment", ["error TS2304: Cannot find name 'foo'."], TS_UNRESOLVED)
    chk(v["status"] == "SKIP", "ts unresolved name -> SKIP, not FAIL")
    v = verdict("f.md", 1, "fragment", ["error TS2345: Argument of type 'x' is not assignable."], TS_UNRESOLVED)
    chk(v["status"] == "FAIL", "ts type error -> FAIL")
    v = verdict("f.md", 1, "item", ["error[E0433]: failed to resolve: use of undeclared crate"], RUST_UNRESOLVED)
    chk(v["status"] == "SKIP", "rust unresolved crate -> SKIP")
    v = verdict("f.md", 1, "item", ["error[E0277]: the trait bound `V: Pod` is not satisfied"], RUST_UNRESOLVED)
    chk(v["status"] == "FAIL", "rust trait bound -> FAIL (this is the Pod question)")
    v = verdict("f.md", 1, "body", ["error[E0423]: expected value, found macro `line`"], RUST_UNRESOLVED)
    chk(v["status"] == "SKIP", "rust name shadowed by a std macro -> SKIP (the binding is missing)")
    v = verdict("f.md", 1, "body", ["error[E0282]: type annotations needed for `(&str, _)`"],
                RUST_UNRESOLVED)
    chk(v["status"] == "SKIP", "rust inference-needs-context in a wrapped block -> SKIP")
    v = verdict("f.md", 1, "standalone", ["error[E0282]: type annotations needed for `(&str, _)`"],
                RUST_UNRESOLVED)
    chk(v["status"] == "FAIL", "the same diagnostic in a self-contained block stays FAIL")
    v = verdict("f.md", 1, "body",
                ["error[E0308]: mismatched types — expected `__BlockErr`, found `String`"],
                RUST_UNRESOLVED)
    chk(v["status"] == "SKIP", "a mismatch against the harness's invented error type -> SKIP")
    v = verdict("f.md", 1, "body",
                ["error[E0308]: mismatched types — expected `u64`, found `&str`"], RUST_UNRESOLVED)
    chk(v["status"] == "FAIL", "a real type error in the SAME wrapper still FAILs")
    chk(rust_preamble("use worker::*;\n#[event(fetch)]\nasync fn fetch() -> Result<Response> {}")
        is RUST_BARE_PREAMBLE,
        "workers-rs block does NOT get the anchor prelude (anchor's #[event] would answer for it)")
    w = rust_wrap("body", "let resp = client.get(url).send().await?;")
    chk("async fn __block" in w, "an await fragment is wrapped in an ASYNC fn (E0728 was ours)")
    chk("for __i in 0..1" not in w, "a fragment with no continue/break gets no invented loop")
    w = rust_wrap("body", "let x = match j {\n    Ok(v) => v,\n    Err(e) => { continue; }\n};")
    chk("for __i in 0..1" in w and "async fn __block" in w,
        "a continue fragment gets a loop to continue out of (E0268 was ours)")
    w = rust_wrap("body", "for l in xs {\n    if l > 3 { continue; }\n}")
    chk("for __i in 0..1" not in w, "a fragment that brings its own loop is not double-wrapped")
    chk("struct __BlockErr;" in rust_wrap("body", "let a = 1;"),
        "a non-anchor body's error type is synthetic and NAMED so triage can spot it")
    chk("anchor_lang::Result<()>" in rust_wrap("body", "let signer: Signer = ctx.accounts.payer;"),
        "an anchor body keeps anchor's own Result (its error type is not a guess)")
    chk("pub enum __Block {" in rust_wrap("variants", "    Pending,\n    Up,"),
        "variants are wrapped in an enum, not a function")
    v = verdict("f.md", 1, "fragment", ["error TS7006: Parameter 'x' implicitly has an 'any' type."],
                TS_UNRESOLVED, TS_ADVISORY)
    chk(v["status"] == "WARN", "ts implicit-any -> WARN, not FAIL (harness forces strict)")
    v = verdict("f.md", 1, "fragment", ["error TS18004: No value exists in scope for 'reference'."],
                TS_UNRESOLVED, TS_ADVISORY)
    chk(v["status"] == "SKIP", "ts shorthand w/o value -> SKIP (defined in an earlier block)")
    # the narrowed preamble must not re-import a symbol the block declares itself (was a TS2300 storm)
    p = ts_preamble({"@solana/kit": {"address", "Ledger"}}, "type Ledger = {};\nconst a = address('x');")
    chk("Ledger" not in p and "address" in p, "preamble skips self-declared, keeps referenced")
    chk(ts_preamble({"@solana/kit": {"address"}}, "const x = 1;") == "", "preamble imports nothing unreferenced")
    imp = collect_ts_imports([("a.md", 1, "import { address, pipe } from '@solana/kit';", "standalone")])
    chk(imp == {"@solana/kit": {"address", "pipe"}}, "import harvest")
    imp = collect_ts_imports([("a.md", 1, "import express, { Request, Response } from 'express';", "s")])
    chk(imp == {"express": {"Request", "Response"}}, "import harvest: default + named")
    imp = collect_ts_imports([("a.md", 1, "import type { Request, NextFunction } from 'express';", "s")])
    chk(imp == {"express": {"Request", "NextFunction"}}, "import harvest: type-only")
    d = collect_ts_defaults([("a.md", 1, "import express from 'express';", "s")])
    chk(d == {"express": "express"}, "default-import harvest")
    p = ts_preamble({"express": {"Request"}}, "const app = express();\napp.get('/x', (r: Request) => {});",
                    {"express": "express"})
    chk("import express from 'express';" in p and "Request" in p, "preamble emits default + named")
    p = ts_preamble({"express": {"Request"}}, "app.get('/x', (r: Request) => {});", {"express": "express"})
    chk("import express" not in p, "preamble omits an unreferenced default import")
    pins, splits = harvest_ts_pins([], ["`npm i @solana/kit@6.10.0 @solana-program/token@0.14.0`\n"
                                        "`npm i @solana/kit@6.10.0`\n`npm i @solana/kit@^7`"])
    chk(pins.get("@solana/kit") == "6.10.0", "pins: most-taught version wins (6.10.0 over ^7)")
    chk(pins.get("@solana-program/token") == "0.14.0", "pins: scoped package harvested")
    chk("@solana/kit" in splits, "pins: per-workspace split is reported, not hidden")
    j = '\n'.join(['{"reason":"compiler-message","message":{"level":"error","message":"conflicting implementations","code":{"code":"E0119"}}}',
                   '{"reason":"compiler-message","message":{"level":"error","message":"could not compile `x` due to 2 previous errors"}}',
                   '{"reason":"compiler-message","message":{"level":"warning","message":"unused"}}'])
    e = _cargo_errors(j)
    chk(e == ["error[E0119]: conflicting implementations"], "cargo json: real error only, no summary/warning")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("course", nargs="?", help="course dir (reads lessons/drafts/*.md)")
    ap.add_argument("--lang", choices=["rust", "ts"], help="which language to compile")
    ap.add_argument("--work", help="harness dir (default: <course>/.verify-blocks-<lang>)")
    ap.add_argument("--json", help="write the full per-block report here")
    ap.add_argument("--only", help="only drafts whose name contains this substring")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.course or not a.lang:
        ap.error("need <course> and --lang (or --selftest)")

    course = Path(a.course).resolve()
    blocks = gather(course, a.lang)
    if a.only:
        blocks = [b for b in blocks if a.only in b[0]]
    if not blocks:
        print(f"no {a.lang} blocks in {course}")
        return 0
    kinds = {}
    for _f, _n, _c, k in blocks:
        kinds[k] = kinds.get(k, 0) + 1
    print(f"{len(blocks)} {a.lang} blocks in {course.name}: "
          + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))

    work = Path(a.work) if a.work else course / f".verify-blocks-{a.lang}"
    runner = run_ts if a.lang == "ts" else run_rust
    rows, err = runner(course, blocks, work, verbose=a.verbose)
    if err:
        print(f"harness could not run: {err}", file=sys.stderr)
        return 2
    expect = expect_fail_map(course, a.lang)
    if expect:
        rows = apply_expectations(rows, expect)
        print(f"{len(expect)} block(s) declared expect-fail; "
              f"{sum(1 for r in rows if r['status'] == 'EXPECTED')} behaved as declared")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=2))
        print(f"report -> {a.json}")
    return report(rows, a.lang)


if __name__ == "__main__":
    sys.exit(main())
