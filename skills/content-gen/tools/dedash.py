#!/usr/bin/env python3
"""dedash.py — remove em-dashes from EVERY reader-visible surface, repairing by syntactic role.

Two defects, both from the R2 handoff, both fixed here.

1. COVERAGE. The old tool globbed `lessons/drafts/*.md` and nothing else, so 794 em-dashes
   ship in quiz text across six courses, plus more in course.yaml descriptions, module.yaml,
   briefs, covers and READMEs. Quizzes render to the learner exactly like prose does. This
   version walks every surface a reader can see.

2. GRAMMAR. The old mapping was unconditional: every em-dash became a comma. That mints comma
   splices ("the vault is a PDA, it has no private key") and destroys parenthetical boundaries,
   and it replaces one uniform machine fingerprint with another one -- a corpus of
   comma-appositive chains reads just as generated as a corpus of em-dashes. So the dash is
   classified first, and the repair follows its ROLE:

     sentence boundary   -> period (+ capitalise) or semicolon
     appositive pair     -> a comma pair or parentheses
     list-introducing    -> colon
     trailing fragment   -> comma
     numeric range       -> "to" or a hyphen

   Where a role admits more than one correct repair, the choice is seeded from the surrounding
   text: deterministic and idempotent, but distributed across the corpus, so the fix does not
   itself become a tell.

Bilingual by necessity: most live courses are PT-BR originals, so clause detection carries both
English and Portuguese function words.

    python3 dedash.py <course_dir>              # every surface, in place
    python3 dedash.py <course_dir> --dry-run    # unified diff, writes nothing
    python3 dedash.py <course_dir> --surfaces drafts,quiz
    python3 dedash.py --file <path>
    python3 dedash.py --selftest
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from course_lib import count_prose_emdashes  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────────
# role classification
# ─────────────────────────────────────────────────────────────────────────────────

# em-dash, en-dash, or the spaced double-hyphen evasion. `--flag` and `|---|` are NOT dashes
# here: the double-hyphen form must be spaced on BOTH sides to count.
_DASH = re.compile(r"\s*—\s*|\s*–\s*|(?<= )--(?= )")

# A finite verb anywhere in the first few words is the cheapest reliable signal that what
# follows a dash is a clause and not a noun phrase. Both languages, because the corpus is both.
_FINITE = {
    # english
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "do", "does", "did",
    "will", "would", "can", "could", "should", "must", "may", "might", "means", "gives",
    "makes", "returns", "needs", "fails", "works", "lets", "gets", "keeps", "takes", "costs",
    "happens", "matters", "wins", "breaks", "ships", "runs", "sits", "holds", "becomes",
    "comes", "goes", "knows", "shows", "wants", "looks", "stays", "turns", "starts", "stops",
    "isn't", "aren't", "doesn't", "don't", "won't", "can't", "cannot", "didn't", "wasn't",
    # portuguese
    "é", "são", "era", "eram", "foi", "foram", "está", "estão", "estava", "tem", "têm",
    "tinha", "vai", "vão", "pode", "podem", "deve", "devem", "faz", "fazem", "significa",
    "retorna", "precisa", "precisam", "funciona", "falha", "custa", "existe", "existem",
    "acontece", "importa", "serve", "vira", "fica", "ficam", "roda", "rodam", "quebra",
    "não", "nao", "há", "havia", "seria", "será", "serão",
}
_SUBJECTY = {
    "it", "that", "this", "they", "you", "we", "he", "she", "there", "here", "these",
    "those", "the", "a", "an", "one", "each", "every", "no", "nothing", "everything",
    "isso", "isto", "ele", "ela", "eles", "elas", "você", "voce", "vocês", "nós", "nos",
    "o", "a", "os", "as", "um", "uma", "cada", "todo", "toda", "nada", "tudo", "aquilo",
    "esse", "essa", "esses", "essas", "este", "esta",
}
# cues that the dash is introducing an enumeration or a definition, which wants a colon
_LIST_CUE = re.compile(
    r"^(for example|e\.g\.|such as|namely|like this|as in|i\.e\.|that is|"
    r"por exemplo|ou seja|isto é|como assim|a saber|tipo assim)\b", re.I)
_WORD = re.compile(r"[\w'’ç-]+", re.U)


def _words(s: str, n: int = 8):
    return [w.lower() for w in _WORD.findall(s)][:n]


def is_clause(s: str) -> bool:
    """Does `s` stand alone as a sentence? Heuristic, tuned to be conservative: a false NO
    yields a comma (always grammatical), a false YES yields a period splitting a phrase off,
    which reads worse. So the bar is a finite verb AND a subject-ish opener."""
    ws = _words(s)
    if len(ws) < 3:
        return False
    if not any(w in _FINITE for w in ws):
        return False
    return ws[0] in _SUBJECTY or (len(ws) > 1 and ws[1] in _FINITE) or \
        (len(ws) > 2 and ws[2] in _FINITE)


_SHORT_TOKEN = re.compile(r"[A-Za-z]{0,3}\d+[A-Za-z]?$")


def _is_range(left: str, right: str, spaced: bool = True) -> bool:
    """`1 — 2`, and the unspaced `V0–V4` / `2020–2024` / `pp.10–12` shapes.

    An UNSPACED dash between two short alphanumeric tokens is nearly always a range, and
    turning `V0–V4` into `V0, V4` silently changes what the sentence claims -- caught on the
    real corpus, where an sBPF "ISA enum V0–V4" became "ISA enum V0, V4"."""
    lt = left.split()[-1] if left.split() else ""
    rt = right.split()[0] if right.split() else ""
    if re.search(r"\d\s*$", left) and re.match(r"^\s*\d", right):
        return True
    return (not spaced and bool(_SHORT_TOKEN.search(lt)) and bool(_SHORT_TOKEN.match(rt)))


def is_label(s: str) -> bool:
    """A short naming phrase with no finite verb: `pinocchio v0.11.2`, `@solana/kit`,
    `networking: NOT required`. A dash after one of these introduces a gloss, not a clause."""
    ws = _words(s, 12)
    return len(ws) <= 8 and not any(w in _FINITE for w in ws)


def classify(left: str, right: str, paired: bool, spaced: bool = True) -> str:
    """sentence | appositive-pair | list | range | gloss | trailing"""
    if _is_range(left, right, spaced):
        return "range"
    if paired:
        return "appositive-pair"
    if _LIST_CUE.match(right.strip()) or (right.count(",") >= 2 and not is_clause(right)):
        return "list"
    # A SENTENCE boundary needs an independent clause on BOTH sides. Testing only the right
    # side turned every "<label> — <noun phrase with a verb in it>" gloss into a full stop:
    # "pinocchio v0.11.2 — the no_std bridge the turnstile sits on" became two sentences, the
    # first of which is not one. Caught on the real corpus.
    if is_clause(right) and is_clause(left):
        return "sentence"
    # A gloss expands its label. A two-word afterthought ("ship it — nothing else") is not a
    # gloss, it is an appended fragment, and a colon in front of it reads as a false promise.
    if is_label(left) and len(_words(right, 6)) >= 4:
        return "gloss"
    return "trailing"


def _pick(options: list, seed: str):
    """Deterministic but distributed. The same sentence always repairs the same way (so the
    pass is idempotent and reviewable), yet across a corpus the choices spread, so the fix
    does not stamp its own uniform fingerprint on everything it touches."""
    h = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return options[h % len(options)]


def _cap(s: str) -> str:
    m = re.search(r"[^\s\"'(\[]", s)
    return s if not m else s[:m.start()] + s[m.start()].upper() + s[m.start() + 1:]


# ─────────────────────────────────────────────────────────────────────────────────
# line repair
# ─────────────────────────────────────────────────────────────────────────────────

def repair_line(s: str) -> str:
    """Replace every dash in one line of prose with punctuation chosen for its role."""
    if not _DASH.search(s):
        return s
    lead = s[:len(s) - len(s.lstrip(" \t"))]
    body = s[len(lead):]

    # a markdown list bullet / blockquote marker is layout, not prose; keep it out of the
    # left-hand context so "- item — detail" is not read as a range or a bullet dash
    mk = re.match(r"^([-*+>]\s+|\d+\.\s+|#{1,6}\s+)", body)
    marker, body = (mk.group(1), body[mk.end():]) if mk else ("", body)

    spaced = [bool(m.group(0).strip() != m.group(0)) for m in _DASH.finditer(body)]
    parts = _DASH.split(body)
    if len(parts) < 2:
        return s

    # A pair of dashes bracketing a phrase inside one sentence is an appositive pair -- but
    # only if BOTH are spaced. An unspaced dash is a range or a compound, and pairing a real
    # em-dash with the "–" inside "V0–V4" swallowed the range into the appositive on the real
    # corpus ("ISA enum V0–V4" came out as ", ISA enum V0, V4").
    paired = (len(parts) == 3 and parts[1].strip() and all(spaced)
              and not re.search(r"[.!?]\s*$", parts[1].strip()))

    if paired:
        inner = parts[1].strip()
        # Parentheses are only safe when neither the insert nor its host already uses them:
        # wrapping a phrase that itself contains "(" produces text no reader can parse, and the
        # real corpus is full of glosses like "(source hierarchy: a > b > c)".
        nestable = "(" in body or ")" in body
        style = "commas" if nestable else _pick(["parens", "commas"], body)
        if style == "parens":
            out = f"{parts[0].rstrip()} ({inner}){_glue(parts[2])}"
        else:
            out = f"{parts[0].rstrip()}, {inner},{_glue(parts[2])}"
        return lead + marker + _tidy(out)

    out = parts[0]
    for i, right in enumerate(parts[1:]):
        sp = spaced[i] if i < len(spaced) else True
        role = classify(out, right, paired=False, spaced=sp)
        r = right.lstrip()
        if role == "range":
            out = out.rstrip() + (_pick([" to ", "-"], out + right) if sp else "-") + r
        elif role in ("list", "gloss"):
            # one colon per clause: a line that already has one takes a comma instead
            out = out.rstrip() + (", " if ":" in out else ": ") + r
        elif role == "sentence":
            sep = _pick([". ", "; "], out + right)
            out = out.rstrip() + sep + (_cap(r) if sep == ". " else r)
        else:
            out = out.rstrip() + ", " + r
    return lead + marker + _tidy(out)


def _glue(tail: str) -> str:
    t = tail.lstrip()
    return "" if not t else ("" if t[0] in ".,;:!?)" else " ") + t


def _tidy(s: str) -> str:
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r",\s*([.;:!?])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.rstrip()


# ─────────────────────────────────────────────────────────────────────────────────
# surfaces
# ─────────────────────────────────────────────────────────────────────────────────

_CODE_FENCE = re.compile(r"^\s*```")


def repair_markdown(md: str) -> str:
    """Prose and `visual` specs are repaired; real code fences keep their dashes (a dash can
    be syntax), except in comments, where an em-dash becomes a plain hyphen."""
    out, in_fence, in_visual = [], False, False
    for ln in md.split("\n"):
        if _CODE_FENCE.match(ln):
            st = ln.strip()
            if not in_fence:
                in_fence, in_visual = True, st[3:].strip().lower() == "visual"
            else:
                in_fence = in_visual = False
            out.append(ln)
            continue
        if not in_fence or in_visual:
            out.append(repair_line(ln))
        else:
            out.append(re.sub(r"\s*[—–]\s*", " - ", ln) if ("—" in ln or "–" in ln) else ln)
    return "\n".join(out)


# YAML keys whose values are commands, paths or identifiers: a dash there is syntax.
CODE_KEYS = {"command", "verify", "starter", "solution", "tests", "id", "slug", "key", "src",
             "path", "file", "idl", "cmd", "install", "run", "artifact", "consumes", "produces",
             "requires_skills", "skills", "language", "buildType", "expectedOutput", "input"}
_YAML_KV = re.compile(r"^(\s*(?:-\s+)?)([A-Za-z_][\w.-]*)(\s*:\s*)(.*)$")


def repair_yaml(text: str) -> str:
    """Repair YAML VALUES only. Keys, structure, and any value under a CODE_KEYS key are left
    exactly as they are; block scalars inherit their key's decision."""
    out, block_key, block_indent = [], None, -1
    for ln in text.split("\n"):
        indent = len(ln) - len(ln.lstrip(" "))
        if block_key is not None:
            if ln.strip() and indent <= block_indent:
                block_key = None
            else:
                out.append(ln if block_key in CODE_KEYS else repair_line(ln))
                continue
        m = _YAML_KV.match(ln)
        if not m:
            out.append(ln if _looks_codey(ln) else repair_line(ln))
            continue
        pre, key, sep, val = m.groups()
        if val.strip() in ("|", ">", "|-", ">-", "|+", ">+"):
            block_key, block_indent = key, indent
            out.append(ln)
            continue
        out.append(pre + key + sep + (val if key in CODE_KEYS else repair_line(val)))
    return "\n".join(out)


def _looks_codey(ln: str) -> bool:
    return bool(re.search(r"(^|\s)--?[A-Za-z]", ln)) and not re.search(r"\s--\s", ln)


def repair_json_text(raw: str):
    """Repair string values in a JSON document WITHOUT reserialising it.

    manifest.json is the authoring source of truth and two of the ten shipped manifests do not
    round-trip through json.dumps byte-for-byte, so reserialising would rewrite files this pass
    has no business rewriting. Instead each changed value is swapped as its exact JSON literal.
    Returns (new_raw, n_changed, n_unlocatable)."""
    obj = json.loads(raw)
    pairs: list[tuple[str, str]] = []

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and key not in CODE_KEYS and _DASH.search(node):
            fixed = "\n".join(repair_line(l) for l in node.split("\n"))
            if fixed != node:
                pairs.append((node, fixed))

    walk(obj)
    # str.replace swaps EVERY occurrence, so a value that appears twice in the document must be
    # deduped or its second visit reports a false "unlocatable" against text already fixed.
    uniq = dict(pairs)
    new, missed = raw, 0
    for old, fixed in uniq.items():
        lit_old, lit_new = json.dumps(old, ensure_ascii=False), json.dumps(fixed, ensure_ascii=False)
        if lit_old in new:
            new = new.replace(lit_old, lit_new)
        else:
            missed += 1
    return new, len(uniq) - missed, missed


SURFACES = {
    "drafts":   ("lessons/drafts/*.md", repair_markdown),
    "briefs":   ("lessons/briefs/*", repair_yaml),
    "course":   ("course.yaml", repair_yaml),
    "modules":  ("modules/*/module.yaml", repair_yaml),
    "meta":     ("*.yaml", repair_yaml),
    "readme":   ("README.md", repair_markdown),
    "quiz":     ("manifest.json", None),          # quiz_blocks + brief prose live here
}


def _targets(course: Path, want: set[str]):
    """Each file once, under the most specific surface that claims it (`meta: *.yaml` overlaps
    `course: course.yaml`; processing twice is a no-op but reports the file twice)."""
    seen = set()
    for name, (pattern, fn) in SURFACES.items():
        if want and name not in want:
            continue
        for p in sorted(course.glob(pattern)):
            if p.is_file() and p not in seen:
                seen.add(p)
                yield name, p, fn


def process(path: Path, fn, dry: bool):
    """(changed, note). `fn is None` selects the JSON path."""
    before = path.read_text("utf-8")
    if fn is None:
        after, n, missed = repair_json_text(before)
        note = f"{n} string(s)" + (f", {missed} unlocatable" if missed else "")
    else:
        after, note = fn(before), ""
    if after == before:
        return False, ""
    if dry:
        for line in difflib.unified_diff(before.split("\n"), after.split("\n"),
                                         f"a/{path.name}", f"b/{path.name}", lineterm="", n=1):
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                print("   " + line[:170])
    else:
        path.write_text(after, "utf-8")
    return True, note


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="remove em-dashes from every reader-visible surface")
    ap.add_argument("target", nargs="?", help="course dir")
    ap.add_argument("--file", help="a single file (markdown, yaml or json)")
    ap.add_argument("--surfaces", help=f"comma list of {','.join(SURFACES)} (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    want = {s.strip() for s in a.surfaces.split(",")} if a.surfaces else set()
    jobs = []
    if a.file:
        p = Path(a.file)
        fn = None if p.suffix == ".json" else (
            repair_yaml if p.suffix in (".yaml", ".yml") else repair_markdown)
        jobs = [("file", p, fn)]
    elif a.target:
        c = Path(a.target)
        if not c.is_dir():
            print("dedash: target must be a course dir (or use --file)", file=sys.stderr)
            return 2
        jobs = list(_targets(c, want))
    if not jobs:
        print("dedash: pass a course dir or --file", file=sys.stderr)
        return 2

    touched, left = 0, 0
    for surface, p, fn in jobs:
        changed, note = process(p, fn, a.dry_run)
        if changed:
            touched += 1
            print(f"  [{surface}] {p.name}" + (f"  ({note})" if note else "")
                  + ("  (dry-run)" if a.dry_run else ""))
        if p.suffix == ".md" and not a.dry_run:
            left += count_prose_emdashes(p.read_text("utf-8"))
    verb = "would change" if a.dry_run else "changed"
    print(f"dedash: {verb} {touched}/{len(jobs)} file(s); "
          f"{left} em-dash(es) remain outside code in markdown (should be 0)")
    return 0


def selftest() -> int:
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    # ── role classification ──
    chk(is_clause("it has no private key"), "clause: pronoun + finite verb")
    chk(is_clause("a validator is just a program"), "clause: determiner + copula")
    chk(not is_clause("a clean environment"), "not a clause: bare noun phrase")
    chk(not is_clause("nothing else"), "not a clause: two words")
    chk(is_clause("ele não tem chave privada"), "clause: portuguese")
    chk(not is_clause("uma conta comum"), "not a clause: portuguese noun phrase")
    chk(classify("the vault is a PDA", "it has no private key", False) == "sentence", "role: sentence")
    chk(classify("you need three", "a payer, a mint, and an ATA", False) == "list", "role: list")
    chk(classify("run it twice", "for example on devnet", False) == "list", "role: list cue")
    chk(classify("blocks 1", "2 are empty", False) == "range", "role: range")
    chk(classify("the fix", "a clean env", True) == "appositive-pair", "role: appositive pair")
    chk(classify("ship it", "nothing else", False) == "trailing", "role: trailing fragment")
    # ── the four classifier bugs the real corpus exposed ──
    chk(classify("ISA enum V0", "V4 plus a disassembler", False, spaced=False) == "range",
        "role: unspaced V0-V4 is a range, not a comma list")
    chk(classify("pinocchio v0.11.2", "the no_std bridge the turnstile is built on", False)
        == "gloss", "role: label + noun phrase is a gloss, not a sentence boundary")
    chk(is_label("pinocchio v0.11.2") and not is_label("the vault is a PDA"),
        "label detection: no finite verb, short")

    # ── the defect the handoff filed: no more manufactured comma splices ──
    spliced = repair_line("The vault is a PDA — it has no private key.")
    chk("," not in spliced.replace("PDA", ""), f"sentence boundary is NOT a comma: {spliced!r}")
    chk(spliced.endswith("private key.") and ("PDA. It" in spliced or "PDA; it" in spliced),
        f"sentence boundary -> period or semicolon: {spliced!r}")
    chk(repair_line("ship it — nothing else.") == "ship it, nothing else.",
        "trailing fragment still takes a comma")
    pair = repair_line("The fix — a clean env — is boring.")
    chk(pair in ("The fix (a clean env) is boring.", "The fix, a clean env, is boring."),
        f"appositive pair -> parens or comma pair: {pair!r}")
    nested = repair_line("agave v4.2.1 (stable) — the pinned tag — is what source is read at.")
    chk(nested.count("(") == nested.count(")"),
        f"appositive pair never nests parens into text that already has them: {nested!r}")
    chk(repair_line("ISA enum V0–V4 plus a disassembler") == "ISA enum V0-V4 plus a disassembler",
        "unspaced V0-V4 stays a range")
    mixed = repair_line("solana-sbpf v0.23.0 — ISA enum V0–V4 + the disassembler")
    chk("V0-V4" in mixed, f"a spaced dash + an unspaced range is not read as a pair: {mixed!r}")
    gloss = repair_line("pinocchio v0.11.2 — the no_std bridge the turnstile is built on.")
    chk(gloss.startswith("pinocchio v0.11.2:"), f"label + gloss -> colon: {gloss!r}")
    dbl = repair_line("networking: NOT required — the one lab is a completion problem.")
    chk(dbl.count(":") == 1, f"a line that already has a colon does not get a second: {dbl!r}")
    chk(repair_line("you need three — a payer, a mint, and an ATA.")
        == "you need three: a payer, a mint, and an ATA.", "list-introducing -> colon")
    chk(repair_line("word—word") == "word, word", "unspaced dash still repaired")
    chk(repair_line("a range 1 -- 2") in ("a range 1 to 2", "a range 1-2"),
        "spaced double-hyphen range")

    # ── variation: the repair must not stamp one uniform shape on the corpus ──
    variants = {repair_line(f"The {w} is a PDA — it has no private key.")
                for w in ("vault", "escrow", "mint", "pool", "ledger", "market", "oracle",
                          "queue", "bank", "cache", "index", "relay")}
    kinds = {("period" if ". It" in v else "semicolon") for v in variants}
    chk(kinds == {"period", "semicolon"}, f"sentence repairs vary across the corpus ({kinds})")
    chk(repair_line("The vault is a PDA — it has no private key.")
        == repair_line("The vault is a PDA — it has no private key."),
        "...but the same sentence always repairs the same way (idempotent, reviewable)")

    # ── idempotence ──
    for s in ["The vault is a PDA — it has no private key.", "The fix — a clean env — is boring.",
              "you need three — a payer, a mint, and an ATA."]:
        chk(repair_line(repair_line(s)) == repair_line(s), f"idempotent: {s[:28]!r}")

    # ── things that must NOT be touched ──
    chk(repair_line("cargo build --release") == "cargo build --release", "`--flag` untouched")
    chk(repair_line("|---|---|") == "|---|---|", "markdown table rule untouched")
    chk(repair_line("- item") == "- item", "list bullet untouched")
    md = "prose — here\n```bash\ncargo build --release  # a — b\n```\n"
    got = repair_markdown(md)
    chk("cargo build --release" in got and "—" not in got, "code fence keeps syntax, comment dash goes")
    chk("—" not in repair_markdown("```visual\ndata: |\n  left: X — right: Y\n```\n"),
        "visual blocks ARE prose specs and get repaired")

    # ── yaml surface ──
    y = ("title: Bitcoin — the first ledger\n"
         "command: cargo build --release -- --nocapture\n"
         "id: lesson-a—b\n"
         "description: >-\n  A vault is a PDA — it has no private key.\n")
    ry = repair_yaml(y)
    chk("—" not in ry.split("\n")[0], "yaml: a title value is repaired")
    chk("cargo build --release -- --nocapture" in ry, "yaml: a command value is NOT repaired")
    chk("lesson-a—b" in ry, "yaml: an id value is NOT repaired")
    chk("—" not in ry.split("\n")[-2], "yaml: a block scalar body is repaired")
    chk(repair_yaml(ry) == ry, "yaml: idempotent")

    # ── json surface: quiz text, without reserialising the manifest ──
    doc = json.dumps({"lessons": [{"brief": {"quiz_blocks": [
        {"question": "What is a PDA — an account with no key?",
         "options": ["yes — always", "no"]}],
        "verify": {"command": "cargo test -- --nocapture"}}}]},
        indent=2, ensure_ascii=False)
    new, n, missed = repair_json_text(doc)
    chk(missed == 0 and n == 2, f"json: both quiz strings located and swapped ({n}, {missed})")
    chk("—" not in new, "json: quiz text de-dashed")
    chk("cargo test -- --nocapture" in new, "json: a verify command is NOT repaired")
    chk(json.loads(new)["lessons"][0]["brief"]["quiz_blocks"][0]["options"][1] == "no",
        "json: untouched values survive byte-identical")
    chk(repair_json_text(new)[1] == 0, "json: idempotent")
    dup = json.dumps({"a": "x — y", "b": "x — y"}, indent=2, ensure_ascii=False)
    dn, dc, dm = repair_json_text(dup)
    chk(dm == 0 and "—" not in dn,
        f"json: a value repeated in the document is not a false 'unlocatable' ({dc}, {dm})")
    other = json.dumps({"a": "x — y"}, indent=4)          # a manifest that does NOT round-trip
    chk(repair_json_text(other)[0].startswith('{\n    "a"'),
        "json: original formatting is preserved (no reserialisation)")

    # ── the coverage gap this rewrite closes ──
    chk(set(SURFACES) >= {"drafts", "briefs", "course", "modules", "readme", "quiz"},
        "every reader-visible surface is registered")

    print("\nDEDASH SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
