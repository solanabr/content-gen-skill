#!/usr/bin/env python3
"""
fix_sweep.py — the executable half of `method/fix-protocol.md`.

A fact gets corrected at the line somebody filed, and the same claim survives in the
twin passage two lessons later, in the quiz feedback, in the image alt text, in the
`visual-src` HTML, in the `<!-- spec -->` comment a future re-render rebuilds from, and
in the exported copy. The round-2 audit measured that blast radius: **~17% of its
findings were fallout from round 1's fixes** — not bad fixes, narrow ones — headlined by
six shipped images still teaching models the corrected prose beside them retracted.

This tool turns "remember every surface" into machine-checkable state.

    fix_sweep.py plan  <course> --claim "<literal>"|<claim-id> [--also "<other phrasing>"]
                                [--id <fix-id>] [--to "<replacement>"] [--note "..."] [--export <dir>]
    fix_sweep.py check <course> [--fix <id>]      # exit 1 while the sweep is incomplete
    fix_sweep.py close <course> --fix <id>        # check, then flip status: open -> closed
    fix_sweep.py list  <course>
    fix_sweep.py --selftest

Sweep the ATOM, not the sentence (`lesson-brief-schema.md` §G already says frozen facts are
atomic). On the real Docker lesson, `--claim "200 pulls per 6 hours"` reaches 8 surfaces and
`--claim "200 pulls"` reaches 11, because the shipped figure writes `200 pulls / 6 h`. Use
`--also` for phrasings that are not substrings of each other — above all the alt text, which
spells numbers out. A hit that is genuinely correct where it stands goes in the ledger's
`exempt:` list, by hand, and is reported on every run.

`plan` writes `<course>/fixes/<fix-id>.yaml`: every hit, grouped by surface class, plus
the rendered assets that hang off each hit HTML source. `check` fails while

  * any surface still matches the old text (listed OR newly appeared), or
  * any listed rendered asset is OLDER than its HTML source.

That second rule is the specific fix for "six shipped images still teach the retracted
model": an image regenerated from a corrected HTML is younger than it; an untouched one
is not. A memory failure becomes a stat() call.

`validate_course.py`'s `check_fixes` HARD-fails any `fixes/*.yaml` still `status: open`,
so a course cannot reach the Academy export with an unclosed sweep.

Stdlib-only, deterministic, no network. Reads the course tree; writes only `fixes/`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from course_lib import to_yaml  # noqa: E402

# ── surface classes ─────────────────────────────────────────────────────────────
# The exhaustive list from method/fix-protocol.md. Everyone remembers the draft and
# forgets the rest, so the classes are named and ordered by how easily they are missed.
SURFACE_ORDER = [
    "draft-prose",      # the filed line, and the twin passage two lessons later
    "draft-code",       # code fences inside that draft
    "twin-code",        # the same snippet elsewhere, found by normalised fence hash
    "visual-spec",      # ```visual data:/prompt: + the <!-- spec --> comment a re-render rebuilds from
    "visual-meta",      # that block's purpose:/alt: (alt is what a screen reader is taught)
    "visual-src",       # the authored HTML's rendered markup
    "brief",            # hook / concept_spec / the_tradeoff / flow.recap / flow.forward_hook
    "quiz",             # prompt / label / feedback / explanation
    "challenge",        # starter / solution / tests.json / acceptance_criteria
    "facts",            # lessons/facts/*.facts.md
    "research",         # lessons/research/*.research.yaml (and its verified_on)
    "course-meta",      # course.yaml / module.yaml / README.md / cover / banner
    "export",           # content/academy/courses/<slug>/** if the course has been exported
]

TEXT_EXTS = {".md", ".markdown", ".yaml", ".yml", ".json", ".html", ".htm", ".txt",
             ".rs", ".ts", ".tsx", ".js", ".jsx", ".toml", ".sh", ".bash", ".py", ".css"}
RENDER_EXTS = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg", ".pdf")
SKIP_DIRS = {"node_modules", "target", "dist", "build", "__pycache__", "fixes",
             ".git", ".verify-blocks-ts", "verify-ts"}
MAX_BYTES = 2_000_000

# A duplicated snippet only counts as a twin above this normalised length: `cargo build`
# appears in every lesson and telling you so is noise, not a finding.
TWIN_MIN_CHARS = 80
TWIN_MIN_LINES = 3

# Line comments per fence language. Unknown languages strip nothing — two identical
# snippets still hash equal, and stripping `#` from Rust would eat `#[account]`.
_LINE_COMMENTS = {
    "rust": ("//",), "rs": ("//",), "ts": ("//",), "tsx": ("//",), "typescript": ("//",),
    "js": ("//",), "jsx": ("//",), "javascript": ("//",), "json": ("//",), "c": ("//",),
    "bash": ("#",), "sh": ("#",), "shell": ("#",), "console": ("#",), "zsh": ("#",),
    "python": ("#",), "py": ("#",), "toml": ("#",), "yaml": ("#",), "yml": ("#",),
    "sql": ("--",),
}
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_EXT_LANG = {".rs": "rust", ".ts": "ts", ".tsx": "tsx", ".js": "js", ".json": "json",
             ".py": "python", ".sh": "bash", ".toml": "toml", ".yaml": "yaml"}


# ── matching ────────────────────────────────────────────────────────────────────

def _canon(s: str) -> str:
    """Fold the typographic variants that make a literal grep miss its own claim."""
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("—", "-"), ("–", "-"), (" ", " ")):
        s = s.replace(a, b)
    return s


_TAG = re.compile(r"<[^>\n]{0,400}>")
_ENTITY = re.compile(r"&[a-zA-Z]{2,8};|&#\d{2,5};")


def _index(text: str, strip_markup: bool = False) -> tuple[str, list[int]]:
    """(normalised text, line-of-each-character).

    Normalised = canonicalised, casefolded, every whitespace run collapsed to one space.
    The parallel line list is what turns a match offset back into a file line, and
    collapsing across newlines is what finds a claim that YAML or HTML wrapped mid-phrase.

    `strip_markup` additionally replaces HTML tags/entities and markdown emphasis with a
    space, so `200 <strong>pulls</strong> / 6 h` matches the claim `200 pulls / 6 h`.
    """
    if strip_markup:
        # Replace with a space of the SAME length so line accounting stays exact.
        text = _TAG.sub(lambda m: " " * len(m.group(0)), text)
        text = _ENTITY.sub(lambda m: " " * len(m.group(0)), text)
        text = re.sub(r"[*_`]", " ", text)
    out: list[str] = []
    lines: list[int] = []
    ln = 1
    prev_space = True
    for ch in _canon(text):
        if ch == "\n":
            ln += 1
            ch = " "
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            lines.append(ln)
            prev_space = True
            continue
        out.append(ch.lower())
        lines.append(ln)
        prev_space = False
    return "".join(out), lines


def _needle(claim: str) -> str:
    n, _ = _index(claim)
    return n.strip()


def find_lines(text: str, claim) -> list[int]:
    """1-based line numbers where `claim` (a string, or any of a list) occurs, plain or
    through markup. The line reported is where the match STARTS, so a claim a YAML block
    or an HTML attribute wrapped mid-phrase still points at something you can open."""
    claims = [claim] if isinstance(claim, str) else list(claim)
    needles = [n for n in (_needle(c) for c in claims) if n]
    if not needles:
        return []
    hits: set[int] = set()
    for strip in (False, True):
        norm, lines = _index(text, strip_markup=strip)
        for needle in needles:
            start = norm.find(needle)
            while start != -1:
                hits.add(lines[start])
                start = norm.find(needle, start + 1)
    return sorted(hits)


# ── course walk ─────────────────────────────────────────────────────────────────

def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        parts = set(p.relative_to(root).parts[:-1])
        if parts & SKIP_DIRS or any(x.startswith(".") for x in p.relative_to(root).parts):
            continue
        yield p


def _classify_draft_line(draft_text: str) -> list[str]:
    """Per-line surface class for a draft: prose, code fence, or a ```visual field."""
    classes = []
    in_fence = False
    visual = False
    field = ""
    for ln in draft_text.split("\n"):
        s = ln.strip()
        if s.startswith("```"):
            if not in_fence:
                in_fence, visual, field = True, s[3:].strip().lower() == "visual", ""
            else:
                in_fence, visual, field = False, False, ""
            classes.append("draft-code" if not visual else "visual-spec")
            continue
        if in_fence and visual:
            m = re.match(r"^([a-z_]+):", s)
            if m:
                field = m.group(1)
            classes.append("visual-meta" if field in ("purpose", "alt", "title")
                           else "visual-spec")
        elif in_fence:
            classes.append("draft-code")
        else:
            classes.append("draft-prose")
    return classes


def _classify_html_line(html: str) -> list[str]:
    """`visual-spec` inside the <!-- ... --> regeneration comment, `visual-src` outside."""
    classes = []
    in_comment = False
    for ln in html.split("\n"):
        opened = "<!--" in ln
        closed = "-->" in ln
        classes.append("visual-spec" if (in_comment or opened) else "visual-src")
        if opened and not closed:
            in_comment = True
        elif closed:
            in_comment = False
    return classes


def _file_surface(rel: Path) -> str | None:
    """Default surface class for a course-relative path (drafts/HTML refine per line)."""
    parts = rel.parts
    name = rel.name
    if parts[:2] == ("lessons", "drafts"):
        return "course-meta" if re.match(r"^\d", name) else "draft-prose"
    if parts[:2] == ("lessons", "briefs"):
        return "brief"
    if parts[:2] == ("lessons", "facts"):
        return "facts"
    if parts[:2] == ("lessons", "research"):
        return "research"
    if parts[:2] == ("lessons", "assets"):
        return "visual-src" if rel.suffix in (".html", ".htm") else None
    if parts[:2] == ("lessons", "challenges"):
        return "challenge"
    if parts[:2] == ("lessons", "quizzes"):
        return "quiz"
    if parts[0] in ("modules", "branding", "boards", "queue"):
        return "course-meta"
    if len(parts) == 1 and name in ("course.yaml", "README.md", "assessment.yaml",
                                    "cadence.yaml", "_state.yaml"):
        return "course-meta"
    if name == "manifest.json":
        return None       # walked structurally instead — see scan_manifest
    return None


def scan_files(root: Path, claim, surface_prefix: str = "") -> list[dict]:
    """Every textual hit under `root`, classified by surface."""
    hits: list[dict] = []
    for p in _iter_files(root):
        if p.suffix.lower() not in TEXT_EXTS or p.stat().st_size > MAX_BYTES:
            continue
        rel = p.relative_to(root)
        base = _file_surface(rel) if not surface_prefix else surface_prefix
        if base is None:
            continue
        try:
            text = p.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = find_lines(text, claim)
        if not lines:
            continue
        src = text.split("\n")
        per_line = None
        if not surface_prefix and base == "draft-prose":
            per_line = _classify_draft_line(text)
        elif base == "visual-src":
            per_line = _classify_html_line(text)
        for ln in lines:
            surface = base
            if per_line and ln - 1 < len(per_line):
                surface = per_line[ln - 1]
                if surface_prefix:
                    surface = surface_prefix
            hits.append({"file": str(rel), "line": ln, "surface": surface,
                         "text": src[ln - 1].strip()[:160] if ln - 1 < len(src) else ""})
    return hits


# ── manifest walk (quiz + brief text lives in JSON, not on a line anyone greps) ──

def _json_paths(node, path="", out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            _json_paths(v, f"{path}.{k}" if path else str(k), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _json_paths(v, f"{path}[{i}]", out)
    elif isinstance(node, str):
        out.append((path, node))
    return out


def _manifest_surface(path: str) -> str:
    if "quiz_blocks" in path:
        return "quiz"
    if "coding_challenges" in path:
        return "challenge"
    if ".research" in path:
        return "research"
    if ".brief" in path:
        return "brief"
    return "course-meta"


def scan_manifest(course: Path, claim) -> list[dict]:
    p = course / "manifest.json"
    if not p.is_file():
        return []
    try:
        m = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    claims = [claim] if isinstance(claim, str) else list(claim)
    needles = [n for n in (_needle(c) for c in claims) if n]
    hits = []
    for jpath, val in _json_paths(m):
        nv = _needle(val)
        if any(n in nv for n in needles):
            hits.append({"file": f"manifest.json#{jpath}", "line": 0,
                         "surface": _manifest_surface(jpath),
                         "text": val.strip()[:160]})
    return hits


# ── twins: a duplicated snippet is found by STRUCTURE, not by text search ───────

def _norm_code(body: str, lang: str) -> str:
    lang = (lang or "").lower()
    body = _BLOCK_COMMENT.sub("", body) if lang in ("rust", "rs", "ts", "tsx", "js",
                                                    "typescript", "javascript", "c") else body
    marks = _LINE_COMMENTS.get(lang, ())
    kept = []
    for ln in body.split("\n"):
        s = ln
        for mk in marks:
            i = s.find(mk)
            if i != -1:
                s = s[:i]
        kept.append(s)
    return re.sub(r"\s+", "", "\n".join(kept))


def _fence_hash(body: str, lang: str) -> str:
    return hashlib.sha256(_norm_code(body, lang).encode("utf-8")).hexdigest()[:12]


def code_fences(root: Path) -> list[dict]:
    """Every code fence in the course's markdown, plus every challenge source file
    (a challenge IS one fence's worth of code, and is exactly where a snippet gets
    duplicated). Each carries the normalised-structure hash the twin check keys on."""
    out = []
    for p in _iter_files(root):
        rel = str(p.relative_to(root))
        if p.suffix.lower() == ".md" and p.stat().st_size <= MAX_BYTES:
            lines = p.read_text("utf-8").split("\n")
            i = 0
            while i < len(lines):
                s = lines[i].strip()
                if s.startswith("```") and len(s) > 3:
                    lang = s[3:].strip().lower()
                    j = i + 1
                    body = []
                    while j < len(lines) and not lines[j].strip().startswith("```"):
                        body.append(lines[j])
                        j += 1
                    if lang != "visual":
                        out.append({"file": rel, "line": i + 1, "lang": lang,
                                    "body": "\n".join(body),
                                    "hash": _fence_hash("\n".join(body), lang),
                                    "lines": len(body)})
                    i = j + 1
                    continue
                i += 1
        elif (p.suffix.lower() in _EXT_LANG and "challenges" in Path(rel).parts
              and p.stat().st_size <= MAX_BYTES):
            body = p.read_text("utf-8")
            lang = _EXT_LANG[p.suffix.lower()]
            out.append({"file": rel, "line": 1, "lang": lang, "body": body,
                        "hash": _fence_hash(body, lang), "lines": len(body.split("\n"))})
    return out


def find_twins(root: Path, claim, hit_files: set[str]) -> list[dict]:
    """Snippets that are STRUCTURALLY the same code as one the fix touches, elsewhere.

    A text search cannot find these: the twin's prose is different, its comments are
    rewritten, its whitespace moved. Normalised hashing (comments and whitespace
    stripped, then sha256) finds it by shape.

    Origin fences are the ones that literally carry the claim if any do; otherwise every
    substantial fence in a file the sweep already hit — the copy of that lab two lessons
    later is where the corrected line silently survives.
    """
    fences = code_fences(root)
    carrying = [f for f in fences if find_lines(f["body"], claim)]
    if carrying:
        origins = carrying
    else:
        origins = [f for f in fences
                   if f["file"] in hit_files
                   and len(_norm_code(f["body"], f["lang"])) >= TWIN_MIN_CHARS
                   and f["lines"] >= TWIN_MIN_LINES]
    okeys = {(f["file"], f["line"]) for f in origins}
    ohash = {f["hash"]: f for f in origins}
    out = []
    for f in fences:
        if (f["file"], f["line"]) in okeys or f["hash"] not in ohash:
            continue
        src = ohash[f["hash"]]
        out.append({"file": f["file"], "line": f["line"], "surface": "twin-code",
                    "text": f"structural twin of {src['file']}:{src['line']} "
                            f"({f['lang'] or 'text'}, hash {f['hash']})"})
    return out


# ── rendered assets: the mtime rule ─────────────────────────────────────────────

def assets_for(root: Path, hits: list[dict]) -> list[dict]:
    """Rendered images hanging off every HTML source the sweep touched.

    The image is generated FROM the HTML, so a correct fix leaves the render younger
    than its source. An untouched image is older, and that is checkable.
    """
    out = []
    seen: set[str] = set()
    for h in hits:
        f = h["file"].split("#")[0]
        if not f.lower().endswith((".html", ".htm")) or f in seen:
            continue
        seen.add(f)
        src = root / f
        rendered = [str((root / f).with_suffix(e).relative_to(root))
                    for e in RENDER_EXTS if (root / f).with_suffix(e).is_file()]
        if rendered and src.is_file():
            out.append({"html": f, "rendered": rendered})
    return out


# (the mtime comparison itself lives in `verify`, which owns the export-path resolver)


# ── ledger io ───────────────────────────────────────────────────────────────────

def _unquote(s: str):
    s = s.strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if s in ("true", "false"):
        return s == "true"
    if s == "null":
        return None
    if s in ("[]", "{}"):
        return [] if s == "[]" else {}
    if re.match(r"^-?\d+$", s):
        return int(s)
    return s


def read_yaml(text: str):
    """Minimal reader for exactly what `course_lib.to_yaml` emits (this file's ledgers):
    nested maps by two-space indent, lists of scalars, lists of maps. Not a YAML parser;
    the repo is stdlib-only and YAML is otherwise write-only here."""
    rows = [(len(l) - len(l.rstrip()) * 0 - len(l.lstrip(" ")), l.rstrip())
            for l in text.split("\n") if l.strip() and not l.lstrip().startswith("#")]
    pos = 0

    def block(indent: int):
        nonlocal pos
        if pos >= len(rows):
            return None
        if rows[pos][1].lstrip().startswith("- "):
            items = []
            while pos < len(rows):
                ind, raw = rows[pos]
                s = raw.lstrip()
                if ind != indent or not s.startswith("- "):
                    break
                rest = s[2:]
                if re.match(r"^[A-Za-z0-9_.-]+:", rest):
                    rows[pos] = (indent + 2, " " * (indent + 2) + rest)
                    items.append(block(indent + 2))
                else:
                    pos += 1
                    items.append(_unquote(rest))
            return items
        out = {}
        while pos < len(rows):
            ind, raw = rows[pos]
            if ind < indent:
                break
            s = raw.lstrip()
            if ind > indent or s.startswith("- "):
                break
            m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", s)
            if not m:
                pos += 1
                continue
            key, val = m.group(1), m.group(2)
            pos += 1
            if val.strip() == "":
                out[key] = block(indent + 2) if (pos < len(rows) and rows[pos][0] > indent) else None
            else:
                out[key] = _unquote(val)
        return out

    return block(0) or {}


def fixes_dir(course: Path) -> Path:
    return course / "fixes"


def load_ledger(path: Path) -> dict:
    return read_yaml(path.read_text("utf-8"))


def open_ledgers(course: Path) -> list[tuple[Path, dict]]:
    d = fixes_dir(course)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.yaml")):
        try:
            out.append((p, load_ledger(p)))
        except Exception as e:                                    # noqa: BLE001
            out.append((p, {"fix": {"id": p.stem, "status": "open",
                                    "claim": f"<unreadable ledger: {e}>"}}))
    return out


def _slug(s: str, n: int = 6) -> str:
    words = re.findall(r"[a-z0-9]+", s.lower())[:n]
    return "-".join(words)[:48].strip("-") or "claim"


# ── claim resolution ────────────────────────────────────────────────────────────

def resolve_claim(course: Path, claim: str) -> tuple[str, str | None]:
    """(literal text, claim id or None). A bare id resolves against the course's research
    claims and frozen facts, so a sweep can be opened from the grounding record."""
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", claim) or " " in claim:
        return claim, None
    p = course / "manifest.json"
    if p.is_file():
        try:
            m = json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            m = {}
        for l in m.get("lessons", []):
            for c in ((l.get("research") or {}).get("claims") or []):
                if str(c.get("id")) == claim and c.get("claim"):
                    return str(c["claim"]), claim
    for rp in sorted((course / "lessons" / "research").glob("*.yaml")) \
            if (course / "lessons" / "research").is_dir() else []:
        txt = rp.read_text("utf-8")
        m2 = re.search(rf"^\s*-\s+id:\s*{re.escape(claim)}\s*$\n\s*claim:\s*(.+)$",
                       txt, re.M)
        if m2:
            return _unquote(m2.group(1).strip()), claim
    return claim, None


# ── commands ────────────────────────────────────────────────────────────────────

def export_root(course: Path, explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_dir() else None
    slug = course.name
    p = course.parent.parent / "academy" / "courses" / slug
    if p.is_dir():
        return p
    mp = course / "manifest.json"
    if mp.is_file():
        try:
            slug2 = (json.loads(mp.read_text("utf-8")).get("academy") or {}).get("slug")
        except (json.JSONDecodeError, OSError):
            slug2 = None
        if slug2:
            p2 = course.parent.parent / "academy" / "courses" / slug2
            if p2.is_dir():
                return p2
    return None


def sweep(course: Path, claim, export: str | None = None) -> tuple[list[dict], list[dict]]:
    """(hits, assets) — the whole surface list for one claim (string, or claim+aliases)."""
    hits = scan_files(course, claim)
    hits += scan_manifest(course, claim)
    hit_files = {h["file"].split("#")[0] for h in hits}
    hits += find_twins(course, claim, hit_files)
    er = export_root(course, export)
    if er:
        for h in scan_files(er, claim, surface_prefix="export"):
            h["file"] = f"{er.name}::{h['file']}"
            hits.append(h)
    assets = assets_for(course, [h for h in hits if "::" not in h["file"]])
    if er:
        assets += [{"html": f"{er.name}::{a['html']}",
                    "rendered": [f"{er.name}::{r}" for r in a["rendered"]]}
                   for a in assets_for(er, [{"file": h["file"].split("::", 1)[1]}
                                            for h in hits if "::" in h["file"]])]
    return hits, assets


def _asset_path(course: Path, rel: str, export: str | None) -> Path:
    if "::" in rel:
        er = export_root(course, export)
        return (er or course) / rel.split("::", 1)[1]
    return course / rel


def review_rows(course: Path, claim, hits: list[dict]) -> list[dict]:
    """Surfaces a LITERAL sweep structurally cannot reach, next to ones it did reach.

    Two are worth naming because the audit found both repeatedly:

      * **alt text spells the number out.** The v04 block whose `data:` says "200 pulls
        per 6 hours" has an `alt:` reading "their own two hundred". No literal matches it,
        and alt text is the only thing a screen-reader user is taught. If a visual block
        was hit in one field and not in `alt:`/`purpose:`, say so.
      * **the quiz of a hit lesson was not hit.** Quiz feedback is where a corrected fact
        most often survives — it is prose nobody re-reads. If a lesson's draft matched and
        its `quiz_blocks` did not, that is a hand-check, not a pass.

    These are never failures: a machine cannot tell "the alt is a paraphrase, and correct"
    from "the alt still teaches the old model". It can tell you to look.
    """
    out: list[dict] = []
    hit_files = {h["file"].split("#")[0] for h in hits}
    for f in sorted(x for x in hit_files if x.endswith(".md") and "drafts" in x):
        p = course / f
        if not p.is_file():
            continue
        text = p.read_text("utf-8")
        blocks, _defects = _visual_blocks(text)
        for b in blocks:
            fields = b["fields"]
            spec_hit = any(find_lines(fields.get(k, ""), claim) for k in ("data", "prompt"))
            meta_hit = any(find_lines(fields.get(k, ""), claim) for k in ("alt", "purpose", "title"))
            if spec_hit and not meta_hit:
                out.append({"file": f, "line": b["line"],
                            "check": f"visual '{fields.get('title', '?')[:60]}': the spec "
                                     f"carries the claim but alt:/purpose: do not — alt text "
                                     f"often spells a number out; read it by hand"})
    # A draft stem is `m<mod>-l<order>-<lesson id>` (scaffold_course.py), and the id half
    # can itself look like `m06-l2`. Peel the position prefix rather than substring-matching:
    # on `m05-l2-m06-l2`, a naive `lid in stem` claims BOTH m05-l2 and m06-l2 own the file.
    hit_lessons = {re.sub(r"^m\d+-l\d+-", "", Path(f).stem) for f in hit_files if "drafts" in f}
    mp = course / "manifest.json"
    if mp.is_file() and hit_lessons:
        try:
            m = json.loads(mp.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            m = {}
        quiz_hit = {h["file"] for h in hits if h["surface"] == "quiz"}
        for i, l in enumerate(m.get("lessons", [])):
            lid = str(l.get("id", ""))
            if not (l.get("brief") or {}).get("quiz_blocks"):
                continue
            safe = re.sub(r"[^a-z0-9-]", "-", lid.lower()).strip("-")
            if not safe or safe not in hit_lessons:
                continue
            if any(f"lessons[{i}]." in q for q in quiz_hit):
                continue
            out.append({"file": f"manifest.json#lessons[{i}].brief.quiz_blocks", "line": 0,
                        "check": f"lesson {lid} matched but its quiz did not — quiz feedback "
                                 f"is where a corrected fact most often survives"})
    return out


def _visual_blocks(text: str):
    """```visual blocks as {fields, line}. Same parse as validate_course._parse_visuals;
    duplicated here only to keep this tool importable on its own."""
    lines = text.split("\n")
    blocks, defects = [], []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```visual":
            start, j, body = i + 1, i + 1, []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                body.append(lines[j])
                j += 1
            if j >= len(lines):
                defects.append(f"line {start}: visual block never closed")
            fields, cur = {}, None
            for s in body:
                m2 = re.match(r"^([a-z_]+):\s*(.*)$", s)
                if m2 and not s.startswith((" ", "\t")):
                    cur = m2.group(1)
                    fields[cur] = m2.group(2).strip().lstrip("|").strip()
                elif cur is not None and s.strip():
                    fields[cur] = (fields.get(cur, "") + " " + s.strip()).strip()
            blocks.append({"fields": fields, "line": start})
            i = j + 1
        else:
            i += 1
    return blocks, defects


def group(hits: list[dict]) -> dict:
    out: dict[str, list[dict]] = {}
    for h in sorted(hits, key=lambda x: (SURFACE_ORDER.index(x["surface"])
                                         if x["surface"] in SURFACE_ORDER else 99,
                                         x["file"], x["line"])):
        out.setdefault(h["surface"], []).append(
            {"file": h["file"], "line": h["line"], "text": h["text"]})
    return out


def cmd_plan(course: Path, claim_arg: str, fix_id: str | None, to: str | None,
             note: str | None, export: str | None, also: list[str] | None = None) -> int:
    claim, claim_id = resolve_claim(course, claim_arg)
    aliases = list(also or [])
    claims = [claim] + aliases
    hits, assets = sweep(course, claims, export)
    review = review_rows(course, claims, hits)
    fid = fix_id or f"fix-{_slug(claim_id or claim)}"
    grouped = group(hits)
    doc = {
        "fix": {
            "id": fid,
            "course": course.name,
            "claim": claim,
            **({"aliases": aliases} if aliases else {}),
            **({"claim_id": claim_id} if claim_id else {}),
            **({"replacement": to} if to else {}),
            **({"note": note} if note else {}),
            "opened": _dt.date.today().isoformat(),
            "status": "open",
            "surfaces_found": len(hits),
        },
        "surfaces": grouped or {},
        "assets": assets or [],
        "review": review or [],
    }
    d = fixes_dir(course)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{fid}.yaml"
    out.write_text(to_yaml(doc), "utf-8")

    print(f"fix {fid}  claim: {claim[:100]!r}")
    print(f"{len(hits)} surface hit(s) in {len(grouped)} class(es); "
          f"{len(assets)} rendered-asset group(s)\n")
    for k in SURFACE_ORDER:
        if k not in grouped:
            continue
        print(f"  {k}  ({len(grouped[k])})")
        for h in grouped[k]:
            where = f"{h['file']}:{h['line']}" if h["line"] else h["file"]
            print(f"     {where}\n        {h['text'][:120]}")
    for a in assets:
        print(f"  rendered-asset  {a['html']} -> {', '.join(a['rendered'])}")
    for r in review:
        print(f"  BY HAND  {r['file']}:{r['line']}\n        {r['check']}")
    print(f"\nledger: {out}")
    print("Fix every surface above, re-render any listed image, then:")
    print(f"  fix_sweep.py close {course} --fix {fid}")
    return 0


def verify(course: Path, ledger: dict, export: str | None = None) -> tuple[list[str], list[str]]:
    """(failures, warnings) for one ledger."""
    fix = ledger.get("fix") or {}
    claim = fix.get("claim") or ""
    fails: list[str] = []
    warns: list[str] = []
    if not claim:
        return [f"{fix.get('id', '?')}: ledger has no claim text"], []
    claims = [claim] + list(fix.get("aliases") or [])

    listed = set()
    for cls, rows in (ledger.get("surfaces") or {}).items():
        for r in rows or []:
            listed.add(f"{r.get('file')}:{r.get('line')}")

    # Hand-added escape hatch. A literal can be RIGHT somewhere: the same number in a
    # different lesson's correct context, a changelog line that must quote the old text.
    # Without this the gate is unclosable there, and an unclosable gate gets deleted.
    # Add `exempt: ["<file>"]` or `["<file>:<line>"]` to the ledger; it is reported, never silent.
    exempt = {str(x) for x in (ledger.get("exempt") or [])}

    hits, _ = sweep(course, claims, export)
    for h in hits:
        key = f"{h['file']}:{h['line']}"
        if key in exempt or h["file"] in exempt:
            warns.append(f"exempt by hand: {h['surface']} {key} — the old text is correct here")
            continue
        tag = "listed" if key in listed else "NEW"
        if h["surface"] == "twin-code":
            warns.append(f"twin-code {key} — structural twin still present; "
                         f"confirm the fix applies there too ({h['text']})")
            continue
        fails.append(f"[{tag}] {h['surface']} {key} still matches the old text: "
                     f"{h['text'][:100]!r}")

    # A prose fix does not change code STRUCTURE, so a twin listed at plan time is
    # invisible to the re-sweep. Re-state it: the closer confirms it, nothing silently
    # drops. (This is the "twin passage two lessons later" the audit kept finding.)
    for r in ((ledger.get("surfaces") or {}).get("twin-code") or []):
        warns.append(f"twin-code {r.get('file')}:{r.get('line')} was listed by plan — "
                     f"confirm the same correction landed there")
    for r in (ledger.get("review") or []):
        warns.append(f"by hand: {r.get('file')}:{r.get('line')} — {r.get('check')}")

    assets = ledger.get("assets") or []
    for a in assets:
        html = a.get("html", "")
        src = _asset_path(course, html, export)
        if not src.is_file():
            warns.append(f"{html}: HTML source no longer exists")
            continue
        hm = src.stat().st_mtime
        for r in a.get("rendered") or []:
            p = _asset_path(course, r, export)
            if not p.is_file():
                fails.append(f"{r}: listed render is missing")
            elif p.stat().st_mtime < hm:
                fails.append(f"{r} is OLDER than {html} — the shipped image still teaches "
                             f"the retracted model; re-run render_visuals.py render")

    opened = str(fix.get("opened") or "")
    for cls in ("research", "facts"):
        for r in ((ledger.get("surfaces") or {}).get(cls) or []):
            f = (r.get("file") or "").split("#")[0]
            p = course / f
            if not p.is_file() or not opened:
                continue
            m = re.search(r"verified_on:\s*\"?(\d{4}-\d{2}-\d{2})", p.read_text("utf-8"))
            if m and m.group(1) < opened:
                warns.append(f"{f}: verified_on {m.group(1)} predates this fix ({opened}) "
                             f"— re-date the grounding record you just corrected")

    repl = fix.get("replacement")
    if repl:
        for f in sorted({(r.get("file") or "").split("#")[0]
                         for rows in (ledger.get("surfaces") or {}).values()
                         for r in rows or []}):
            if "::" in f or not (course / f).is_file():
                continue
            if not find_lines((course / f).read_text("utf-8"), str(repl)):
                warns.append(f"{f}: the replacement text is absent — confirm this "
                             f"surface was rewritten, not just deleted")
    return fails, list(dict.fromkeys(warns))


def cmd_check(course: Path, only: str | None, export: str | None, close: bool = False) -> int:
    ledgers = open_ledgers(course)
    if only:
        ledgers = [(p, d) for p, d in ledgers if (d.get("fix") or {}).get("id") == only
                   or p.stem == only]
        if not ledgers:
            print(f"fix_sweep: no ledger '{only}' under {fixes_dir(course)}", file=sys.stderr)
            return 2
    if not ledgers:
        print("ok: no fix sweeps recorded")
        return 0
    rc = 0
    for p, d in ledgers:
        fix = d.get("fix") or {}
        fid = fix.get("id", p.stem)
        status = fix.get("status", "open")
        fails, warns = verify(course, d, export)
        state = "FAIL" if fails else ("ok" if status == "closed" or close else "open")
        print(f"[{state}] {fid}  ({status})  claim: {str(fix.get('claim'))[:80]!r}")
        for w in warns:
            print(f"   - warn: {w}")
        for f in fails:
            print(f"   - {f}")
        if fails:
            rc = 1
            continue
        if close and status != "closed":
            fix["status"] = "closed"
            fix["closed"] = _dt.date.today().isoformat()
            d["fix"] = fix
            p.write_text(to_yaml(d), "utf-8")
            print(f"   - closed {p.name} (every surface clean, every render current)")
        elif not close and status == "open":
            print(f"   - every surface clean; run `fix_sweep.py close {course} "
                  f"--fix {fid}` to close it")
    print("\n" + ("SWEEP INCOMPLETE" if rc else "SWEEP CLEAN"))
    return rc


def cmd_list(course: Path) -> int:
    ledgers = open_ledgers(course)
    if not ledgers:
        print("no fix sweeps recorded")
        return 0
    for p, d in ledgers:
        fix = d.get("fix") or {}
        n = sum(len(v or []) for v in (d.get("surfaces") or {}).values())
        print(f"{fix.get('status', '?'):7} {fix.get('id', p.stem):34} "
              f"{n:3} surfaces  {str(fix.get('claim'))[:60]!r}")
    return 0


# ── selftest ────────────────────────────────────────────────────────────────────

def selftest() -> int:
    import os
    import tempfile
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    # normalised matching
    chk(find_lines("the cap is 200 pulls\nper 6 hours today", "200 pulls per 6 hours") == [1],
        "claim wrapped across a newline is still found (whitespace-collapsed index)")
    chk(find_lines("<td>200 <strong>pulls</strong> per 6 hours</td>", "200 pulls per 6 hours"),
        "claim split by an inline HTML tag is found (markup-stripped index)")
    chk(find_lines("200 pulls per 6 hours", "200 PULLS per 6 hours"),
        "matching is case-insensitive")
    chk(find_lines("a — 200 pulls per 6 hours", "200 pulls per 6 hours"),
        "em-dash canonicalisation does not break the match")
    chk(not find_lines("100 pulls per 6 hours", "200 pulls per 6 hours"),
        "a different number is not a hit")

    # code normalisation / twin hashing
    a = "fn main() {\n    // set it up\n    let x = 1;\n}"
    b = "fn main() {\n// a totally different comment\n        let x = 1;\n}"
    chk(_fence_hash(a, "rust") == _fence_hash(b, "rust"),
        "twin hash ignores comments and whitespace (structure, not text)")
    chk(_fence_hash("#[account]\nlet x = 1;", "rust") != _fence_hash("let x = 1;", "rust"),
        "rust attributes are NOT stripped as comments (#[account] survives)")
    chk(_fence_hash("let x = 1;", "rust") != _fence_hash("let y = 1;", "rust"),
        "different code hashes differently")

    with tempfile.TemporaryDirectory() as td:
        # the real layout: content/courses/<slug>, so the export root resolves to the
        # sibling content/academy/courses/<slug> INSIDE the temp dir
        c = Path(td) / "content" / "courses" / "demo"
        (c / "lessons" / "drafts").mkdir(parents=True)
        (c / "lessons" / "briefs").mkdir(parents=True)
        (c / "lessons" / "facts").mkdir(parents=True)
        (c / "lessons" / "assets" / "m00-l1-pull-caps").mkdir(parents=True)
        (c / "lessons" / "challenges" / "l1" / "ch").mkdir(parents=True)

        CLAIM = "200 pulls per 6 hours"
        DUP = ("```rust\nfn pull_budget(signed_in: bool) -> u32 {\n"
               "    // the shared pool is counted per public IPv4\n"
               "    let per_ip: u32 = 100;\n    let per_account: u32 = 200;\n"
               "    if signed_in { per_account } else { per_ip }\n}\n```\n")
        (c / "lessons" / "drafts" / "m00-l1-pull-caps.md").write_text(
            f"# T\n\nan account gets {CLAIM} of its own.\n\n" + DUP +
            "```visual\ntype: diagram\ntitle: pulls\npurpose: show the cap\n"
            f"data: logged in -> {CLAIM}\nprompt: meter labeled {CLAIM}\n"
            f"alt: a meter showing {CLAIM} for one signed-in account and a shared pool\n```\n"
            # second block: the spec carries the number, the alt SPELLS IT OUT — no literal
            # sweep can reach it, so it must come back as a by-hand row
            "\n```visual\ntype: chart\ntitle: the two pools\npurpose: compare pools\n"
            f"data: shared 100 vs account {CLAIM}\nprompt: two bars, the taller one {CLAIM}\n"
            "alt: a logged-in account gets its own two hundred every six hours\n```\n",
            "utf-8")
        # a twin lesson: same code, different prose, claim NOT mentioned
        (c / "lessons" / "drafts" / "m01-l1-budget-reuse.md").write_text(
            "# Later\n\nwe reuse the budget helper here.\n\n"
            "```rust\nfn pull_budget(signed_in: bool) -> u32 {\n// a rewritten comment\n"
            "        let per_ip: u32 = 100;\n        let per_account: u32 = 200;\n"
            "        if signed_in { per_account } else { per_ip }\n}\n```\n", "utf-8")
        (c / "lessons" / "facts" / "m00-l1-pull-caps.facts.md").write_text(CLAIM + "\n", "utf-8")
        (c / "lessons" / "briefs" / "m00-l1-pull-caps.brief.yaml").write_text(
            f'lesson:\n  hook: "you hit the {CLAIM} wall"\n', "utf-8")
        html = c / "lessons" / "assets" / "m00-l1-pull-caps" / "v01-diagram.html"
        html.write_text(
            "<!doctype html>\n<body>\n<!-- diagram: pulls\n     purpose: show the cap\n"
            f"     data: logged in -> {CLAIM}\n     prompt: meter labeled {CLAIM} -->\n"
            f'<div class="m">{CLAIM}, yours alone</div>\n</body>\n', "utf-8")
        (c / "lessons" / "challenges" / "l1" / "ch" / "solution.rs").write_text(
            "fn pull_budget(signed_in: bool) -> u32 {\n    let per_ip: u32 = 100;\n"
            "    let per_account: u32 = 200;\n"
            "    if signed_in { per_account } else { per_ip }\n}\n", "utf-8")
        (c / "manifest.json").write_text(json.dumps({"lessons": [
            {"id": "pull-caps", "brief": {
                "hook": f"you hit the {CLAIM} wall",
                "quiz_blocks": [{"questions": [{"id": "q1", "prompt": "how many?", "options": [
                    {"id": "o1", "label": "unlimited", "correct": False,
                     "feedback": f"no: it is {CLAIM}"}]}]}]}},
            # the twin lesson: matched (by its duplicated code) but its quiz says nothing
            # about the claim — exactly the surface a fix wave forgets
            {"id": "budget-reuse", "brief": {
                "hook": "we reuse the helper",
                "quiz_blocks": [{"questions": [{"id": "q1", "prompt": "which helper?",
                                                "options": [{"id": "o1", "label": "the budget one",
                                                             "correct": True, "feedback": "yes"}]}]}]}},
        ]}), "utf-8")
        png = html.with_suffix(".png")
        png.write_bytes(b"\x89PNG old render")
        os.utime(png, (1, 1))                       # render OLDER than its HTML source

        hits, assets = sweep(c, CLAIM)
        g = group(hits)
        for cls in ("draft-prose", "visual-spec", "visual-meta", "visual-src",
                    "facts", "brief", "quiz", "twin-code"):
            chk(cls in g, f"sweep finds the {cls} surface")
        chk(any(h["file"].startswith("manifest.json#") and h["surface"] == "quiz"
                for h in hits), "quiz feedback inside manifest.json is found by JSON path")
        chk(any("m01-l1-budget-reuse.md" in h["file"] for h in g.get("twin-code", [])),
            "the duplicated snippet in the twin LESSON is found by structure")
        chk(any("solution.rs" in h["file"] for h in g.get("twin-code", [])),
            "the same snippet shipped as a challenge solution is found too")
        chk(assets and assets[0]["rendered"] == ["lessons/assets/m00-l1-pull-caps/v01-diagram.png"],
            "the rendered image hanging off the hit HTML is tracked")

        rev = review_rows(c, CLAIM, hits)
        chk(any("the two pools" in r["check"] for r in rev),
            "a visual whose spec matched but whose alt SPELLS THE NUMBER OUT comes back by hand")
        chk(any("budget-reuse" in r["check"] for r in rev),
            "a matched lesson whose quiz did NOT match comes back by hand")
        chk(find_lines((c / "lessons" / "drafts" / "m00-l1-pull-caps.md").read_text("utf-8"),
                       [CLAIM, "own two hundred"]),
            "--also carries a second phrasing of the same claim into the sweep")

        rc = cmd_plan(c, CLAIM, None, "unlimited for signed-in accounts", None, None)
        led = c / "fixes" / "fix-200-pulls-per-6-hours.yaml"
        chk(rc == 0 and led.is_file(), "plan writes the ledger")
        d = load_ledger(led)
        chk(d["fix"]["status"] == "open" and d["fix"]["claim"] == CLAIM,
            "ledger round-trips through the minimal YAML reader")
        chk(sum(len(v) for v in d["surfaces"].values()) == len(hits),
            "every hit is recorded in the ledger")
        chk(not find_lines(json.dumps(sorted(f for f in
                                             (x["file"] for x in hits))), "fixes/"),
            "the ledger's own directory is excluded from the scan")

        fails, _w = verify(c, d)
        chk(any("still matches" in f for f in fails), "check FAILS while the old text stands")
        chk(cmd_check(c, None, None) == 1, "check exits 1 on an incomplete sweep")

        # fix every textual surface, leave the stale render
        for p in list((c / "lessons").rglob("*")) + [c / "manifest.json"]:
            if p.is_file() and p.suffix in (".md", ".yaml", ".html", ".json"):
                t = p.read_text("utf-8")
                if CLAIM in t:
                    p.write_text(t.replace(CLAIM, "unlimited for signed-in accounts"), "utf-8")
        fails, _w = verify(c, load_ledger(led))
        chk(fails and all("OLDER than" in f for f in fails),
            "text clean but the image untouched -> the mtime rule is the only failure")
        chk(any("v01-diagram.png is OLDER" in f for f in fails),
            "the failure names the shipped image, not a memory of it")

        # a claim that is CORRECT somewhere: exempt it by hand, or the gate is unclosable
        (c / "lessons" / "drafts" / "m02-l1-history.md").write_text(
            f"# History\n\nback then the cap really was {CLAIM}.\n", "utf-8")
        fails, _w = verify(c, load_ledger(led))
        chk(any("m02-l1-history.md" in f and "NEW" in f for f in fails),
            "a hit that appeared after plan is a NEW failure, not a silent pass")
        d2 = load_ledger(led)
        d2["exempt"] = ["lessons/drafts/m02-l1-history.md"]
        fails, warns = verify(c, d2)
        chk(not any("m02-l1-history.md" in f for f in fails)
            and any("exempt by hand" in w for w in warns),
            "an exempt path drops out of the failures and is reported instead")
        led.write_text(to_yaml(d2), "utf-8")

        os.utime(png, None)                          # re-render
        fails, warns = verify(c, load_ledger(led))
        chk(not fails, "after a re-render the sweep verifies clean")
        chk(any("twin-code" in w for w in warns),
            "the structural twin stays a warning, never a silent pass")
        chk(cmd_check(c, "fix-200-pulls-per-6-hours", None, close=True) == 0,
            "close exits 0 on a clean sweep")
        chk(load_ledger(led)["fix"]["status"] == "closed", "close flips status to closed")

        # the export tree is swept too
        er = c.parent.parent / "academy" / "courses" / "demo"
        (er / "lessons" / "l1").mkdir(parents=True)
        (er / "lessons" / "l1" / "intro.md").write_text(f"still says {CLAIM}\n", "utf-8")
        hits2, _a2 = sweep(c, CLAIM)
        chk(any(h["surface"] == "export" for h in hits2),
            "an exported copy of the claim is found (content/academy/courses/<slug>)")

    print("\n" + ("FIX_SWEEP SELFTESTS PASSED" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="plan and verify a corpus-wide fix sweep")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan")
    p.add_argument("course")
    p.add_argument("--claim", required=True, help="literal text, or a research claim id")
    p.add_argument("--also", action="append", default=[],
                   help="another phrasing of the SAME claim (repeatable) — alt text that "
                        "spells the number out, a shorthand the figure uses")
    p.add_argument("--id", help="fix id (default: derived from the claim)")
    p.add_argument("--to", help="the replacement text, recorded for the check")
    p.add_argument("--note")
    p.add_argument("--export", help="export tree (default: ../../academy/courses/<slug>)")
    for name in ("check", "close"):
        q = sub.add_parser(name)
        q.add_argument("course")
        q.add_argument("--fix", help="ledger id (default: every ledger)")
        q.add_argument("--export")
    l = sub.add_parser("list")
    l.add_argument("course")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.print_help()
        return 2
    # resolved, so `.` still yields a course NAME for the ledger and for export-root lookup
    course = Path(a.course).resolve()
    if not course.is_dir():
        print(f"fix_sweep: not a course directory: {course}", file=sys.stderr)
        return 2
    if a.cmd == "plan":
        return cmd_plan(course, a.claim, a.id, a.to, a.note, a.export, a.also)
    if a.cmd == "check":
        return cmd_check(course, a.fix, a.export)
    if a.cmd == "close":
        if not a.fix:
            print("fix_sweep: close needs --fix <id>", file=sys.stderr)
            return 2
        return cmd_check(course, a.fix, a.export, close=True)
    return cmd_list(course)


if __name__ == "__main__":
    raise SystemExit(main())
