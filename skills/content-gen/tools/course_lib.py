#!/usr/bin/env python3
"""
course_lib.py — shared, dependency-free helpers for the content-gen tools.

Single source of truth for:
  - the course manifest model (JSON in, validated here),
  - a minimal YAML *emitter* (dict/list/str/int/bool/None -> readable YAML),
  - DAG helpers (topological sort + forward-dependency walk),
  - the closed vocabularies the validator enforces (dominant_job enum,
    artifact-ladder rung order, lesson-brief required keys).

Design choice (mirrors writer-style's "no third-party deps" stance): the
machine source of truth is JSON (stdlib `json`, bulletproof). The emitted
human/handoff files are YAML, produced by the one-way emitter below. We never
PARSE YAML — only emit it — so there is no fragile regex YAML reader to rot.

    python course_lib.py --selftest
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

# ── closed vocabularies (the validator enforces these) ──────────────────────────

# The voice router input. Must match writer-style's lesson-brief-schema §D enum.
DOMINANT_JOBS = {
    "show-how", "derive-why", "demystify", "economics", "frame", "sustain", "motivate",
}
# Jobs writer-style uses ONLY as single-position guests, never a whole-lesson backbone.
# Allowed as a value, but flagged advisory when set as a lesson's dominant_job.
GUEST_ONLY_JOBS = {"frame", "demystify"}

# Canonical Solana artifact ladder (rung index -> the build). From
# references/solana-syllabus-dag.md §2. Module `artifact_rung` must be monotonic
# non-decreasing along course order; the capstone sits at the top.
ARTIFACT_LADDER = [
    "hello-world",            # 0  toolchain win
    "counter",                # 1  account state, read/write, init
    "spl-token",              # 2  mint -> transfer
    "pda-app",                # 3  vault / escrow / per-user state
    "payment-splitter",       # 4  SOL movement, signers, CPI to system program
    "defi",                   # 5  AMM / auction / fundraiser
    "cpi-composition",        # 6  factory -> child program
    "capstone",               # 7  freeform learner design
]

# Required keys on every lesson brief (lesson-brief-schema §C).
# `kind: build` (the default) also requires the build triad; `kind: concept`
# (non-technical / pure-model lessons) drops it — assessment still gates on doing
# (retrieval / explain-back counts as doing for a concept lesson).
BRIEF_CORE_KEYS = [
    "id", "title", "objectives", "prerequisites", "hook", "concept_spec",
    "the_tradeoff", "just_in_time", "assessment", "difficulty", "dominant_job",
]
BRIEF_BUILD_KEYS = ["artifact_spec", "exercise_spec", "fading"]
LESSON_KINDS = {"build", "concept"}
BRIEF_REQUIRED_KEYS = BRIEF_CORE_KEYS + BRIEF_BUILD_KEYS  # the build profile (back-compat)
# Bloom verbs that signal a measurable objective; "know/understand/learn" do not.
WEAK_BLOOM_VERBS = {"know", "understand", "learn", "be aware", "appreciate", "grasp"}

# Academy publish-schema vocab (references/academy-schema.md). The two interactive
# plugins content-gen can emit as first-class Academy blocks are OPTIONAL on a lesson
# brief (`quiz_blocks`, `coding_challenges`); when present they must satisfy these
# closed sets. Mirrors academy-courses schema/lesson.schema.json.
CHALLENGE_LANGS = {"rust", "typescript"}            # the Academy code runner compiles ONLY these
CHALLENGE_BUILD_TYPES = {"standard", "buildable"}   # code.buildType enum (deployable is a separate bool)

# ── the continuity ledger (lesson-brief-schema §C `ledger`) ─────────────────────
# Every symbol is `<kind>:<name>`. The kind is closed so the call-site scanner in
# continuity.py knows which entries are code identifiers it may look for in a fence
# (fn/type/const/ix) and which are not (cmd/file/env/account/artifact).
#
# `artifact` is the BRIDGE kind: the legacy `brief.artifact.{id,consumes}` edge is
# read as `artifact:<id>` in the same graph, so the accretion ladder and the symbol
# ledger are one DAG and not two systems that can disagree.
SYMBOL_KINDS = {
    "fn":       "a function/method the reader writes here and calls later",
    "type":     "a struct / interface / account layout / type alias",
    "const":    "a named constant, seed literal, or program id",
    "ix":       "a program instruction (the on-chain entry point name)",
    "cmd":      "a runnable command the reader is told to re-use ('npm run mint')",
    "file":     "a source file treated as a named handle ('file:scripts/mint.ts')",
    "env":      "an environment variable / config key the later lessons read",
    "account":  "a named on-chain account or PDA",
    "artifact": "a rung of the artifact ladder (bridge from brief.artifact.id)",
}
# Kinds whose `name` is a code identifier the fence scanner may search for.
CODE_SYMBOL_KINDS = {"fn", "type", "const", "ix"}
SYMBOL_RE = re.compile(r"^([a-z][a-z0-9_]*):(\S.*)$")
LEDGER_KEYS = ("state_in", "state_out", "opens", "emits", "provides", "consumes", "renames")
# Documented in references/output-contract.md for the tool's whole life and implemented
# by nothing. Accepted here only so a brief written against that doc is TOLD where the
# field went, instead of being silently ignored a second time.
LEDGER_LEGACY_KEYS = {
    "artifact_state_in": "ledger.state_in",
    "artifact_state_out": "ledger.state_out",
    "carry_forward": "ledger.provides / ledger.emits (enumerate symbols, don't narrate)",
}

# Strings in an `assessment` field that mean "watch/read", i.e. NOT gated on doing.
PASSIVE_ASSESSMENT_RE = re.compile(
    r"\b(watch|read|review the video|listen|observe)\b", re.I
)
LIFECYCLE = ["briefed", "researched", "drafted", "verified", "published"]

LOG = lambda *a: print(*a, file=sys.stderr, flush=True)


# ── YAML emitter (one-way: Python object -> YAML text) ──────────────────────────

_SIMPLE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./]*$")
_RESERVED = {"true", "false", "null", "yes", "no", "on", "off", "~", ""}
# Strings a YAML reader would silently re-type if emitted bare (numbers, dates, times).
_YAML_AMBIGUOUS = re.compile(
    r"^(?:[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    r"|0[xob][0-9a-fA-F_]+"
    r"|\d{4}-\d{2}-\d{2}([Tt ].+)?"
    r"|\d+:\d+(:\d+)?)$"
)
# The documented id contract (output-contract.md): kebab-case; ids become filesystem paths.
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Kit surfaces a verified claim may cite (research-grounding.md §Dispatch is literal).
KIT_SURFACES = {"solana-dev", "context7", "helius", "surfpool", "deep-research",
                "solana-researcher", "solana-guide", "local-execution", "web", "websearch"}
# Visual placeholder contract (references/visual-placeholders.md).
VISUAL_TYPES = {"flowchart", "diagram", "chart", "table", "comparison", "annotated-code", "timeline"}
VISUAL_FIELDS = ("type", "title", "purpose", "data", "prompt", "alt")


# ── fact freshness: per-claim expiry ────────────────────────────────────────────
#
# WHY. An audit of five generated courses found six shipped defects that were all the
# same defect: a fact that was TRUE WHEN WRITTEN and expired quietly. A rent mechanism
# the runtime now rejects up front; rent constants (890,880 / 2,282,880) matching no
# live cluster (mainnet returns 810,624 / 2,077,224, devnet 650,240 / 1,666,240); a
# protocol feature taught backwards; a dead API (`quote-api.jup.ag`) taught as live; an
# archived repo called "the living reference"; and one hardcoded ATA rent figure in ~10
# sites including a graded quiz key. Nothing re-verified a claim at publish time and no
# claim carried an expiry, so each one shipped, read fine, and was wrong.
#
# The three fields that fix it live on `lesson.research.claims[]`:
#   verified_on  ISO date — REQUIRED when status is verified. Without it "verified" is
#                a mood, not a measurement.
#   ttl_days     defaulted PER KIND from TTL_DAYS below, never per claim. A per-claim
#                value may only SHORTEN the kind default; lengthening it is exactly how
#                a stale fact gets smuggled past the gate, so it is a HARD failure.
#   recheck      the exact re-runnable probe (an RPC call, a curl, a `--version`), not
#                prose. This is the field that makes re-verification cheap enough to
#                actually happen; an un-runnable probe is not a probe.
#
# Changing a number here reaches every course, which is the point of declaring it once.

CLAIM_KINDS = {
    "concept",          # durable model / history: "DigiCash filed Chapter 11 in 1998"
    "number",           # a bare figure with no cluster behind it (legacy, generic)
    "api",              # a call, endpoint, or signature a lesson depends on
    "code",             # a snippet the lesson ships (also gated by verify_code/verify_blocks)
    "onchain-number",   # rent, account sizes, fees — read off a live cluster
    "cli-default",      # what a command does with no flags (`solana config get`, scaffolds)
    "version-pin",      # a pinned crate/npm/toolchain version an example builds against
    "protocol-param",   # slot time, epoch length, a feature-gate's activation state
}

# TTL per kind, in days. See method/fact-recheck.md for the evidence behind each number.
TTL_DAYS = {
    "onchain-number": 14,   # rent/fee figures move with the rent rate; the audit's worst class
    "number": 30,
    "cli-default": 30,      # tracks the Agave/Anchor release train, ~monthly
    "version-pin": 30,      # same train; aligns with references/pins.yaml's own TTL discipline
    "protocol-param": 30,   # ~10 epochs: long enough to not re-probe weekly, short enough to
                            # catch a cluster-wide feature-gate activation
    "api": 60,              # NOT 90 — a 90-day window still called `quote-api.jup.ag` fresh
    "code": 90,             # re-compiled every run by verify_blocks; TTL is the backstop
    "concept": 365,         # a liveness check on the lesson, not on the fact
}
# A claim with no `kind` is treated as volatile, never as a concept: guessing "durable"
# on an undeclared claim is how a rent number inherits a one-year TTL.
TTL_DEFAULT_DAYS = 30

# Kinds where a claim with no runnable `recheck` is a HARD failure. Every one of these is
# read off a machine, so "how do I re-check this" always has a one-line answer.
RECHECK_REQUIRED_KINDS = {"onchain-number", "cli-default", "protocol-param", "version-pin"}
# Kinds where a probe is usually possible but not always (an API *shape* claim can be a
# doc read). Advisory only, and only when the claim cites a URL — a cited URL is a free
# probe, and a dead cited URL is defect #4 verbatim.
RECHECK_ADVISORY_KINDS = {"api", "number"}

# Claim statuses whose facts actually ship, and therefore actually expire.
LIVE_CLAIM_STATUSES = {"verified", "user-attested"}

# Warn at three-quarters of the TTL so a re-probe can be scheduled instead of ambushing a
# publish. Same shape as pin_refresh.py's pin TTL.
AGING_FRACTION = 0.75

# THE GRANDFATHER CLAUSE. `verified_on` shipped on this date. Claims authored before it
# have no date and never will — 74 of the 127 claims in the ten-course corpus are in that
# state. Two dishonest options were available: treat them as fresh (the exact failure this
# layer exists to prevent) or treat them as infinitely old (which HARD-fails the entire
# corpus on day one and gets the gate switched off). Neither is a gate.
#
# So an undated claim is dated FROM THE EPOCH — "we do not know when you checked this, so
# the clock starts the day we started asking". The consequences fall out on their own:
# an undated onchain-number goes HARD 14 days after the epoch, an undated concept has a
# year, and the missing-field rule itself hardens from advisory to HARD once the backfill
# window closes. No per-course opt-in, no flag, and it expires by itself.
FRESHNESS_EPOCH = "2026-09-07"
UNDATED_GRACE_DAYS = 30

# A date is inferred from `evidence` only behind an explicit marker. The corpus already
# writes `https://… (dispatched 2026-07-06)`, which is a real verification date; a bare
# year inside a cited URL is not, and inferring from one would manufacture staleness.
_INFER_DATE_RE = re.compile(
    r"(?:dispatched|verified|checked|probed|retrieved|as of|accessed)\s*:?\s*(\d{4}-\d{2}-\d{2})"
    r"|\((\d{4}-\d{2}-\d{2})\)\s*$", re.I)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URL_RE = re.compile(r"https?://[^\s)\"']+")


def parse_iso_date(s) -> _dt.date | None:
    """An ISO `YYYY-MM-DD` string as a date, or None. Never raises — a malformed date is
    reported by the caller as a flag, not as a traceback in the middle of a gate."""
    if isinstance(s, _dt.date):
        return s
    t = str(s or "").strip()
    if not _ISO_DATE_RE.match(t):
        return None
    try:
        return _dt.date.fromisoformat(t)
    except ValueError:
        return None


def today() -> _dt.date:
    return _dt.date.today()


def resolve_verified_on(claim: dict) -> tuple[_dt.date | None, str]:
    """(date, provenance) for when this claim was last actually checked.

    provenance is one of:
      declared  `verified_on` is present and is a real ISO date
      inferred  mined out of `evidence` behind an explicit marker ("(dispatched 2026-07-06)")
      malformed `verified_on` is present but is not an ISO date
      none      no date is obtainable — the grandfather clause applies
    """
    raw = claim.get("verified_on")
    if raw not in (None, ""):
        d = parse_iso_date(raw)
        return (d, "declared") if d else (None, "malformed")
    m = _INFER_DATE_RE.search(str(claim.get("evidence") or ""))
    if m:
        d = parse_iso_date(m.group(1) or m.group(2))
        if d:
            return d, "inferred"
    return None, "none"


def course_ttl_policy(manifest: dict) -> dict:
    """`cadence.release.freshness_policy` as a {kind: days} narrowing, plus its scope.

    That block already exists in the schema (output-contract.md §Cadence) and eight of the
    ten courses in the corpus declare it — and until now NOTHING READ IT. Wiring it here
    turns a decorative field into the gate. It may only NARROW a kind default: a course
    that declares 90 days for on-chain numbers is asking for a longer rope than the rent
    figures deserve, so the default wins and check_freshness says so out loud.

    Returns {"days": int|None, "applies_to": [lesson_id, ...], "declared": int|None}.
    """
    rel = ((manifest.get("cadence") or {}).get("release") or {})
    pol = rel.get("freshness_policy") or {}
    declared = pol.get("onchain_numbers_restale_after_days")
    days = declared if isinstance(declared, int) and declared > 0 else None
    return {"days": days, "applies_to": list(pol.get("applies_to") or []),
            "declared": declared}


def claim_ttl(claim: dict, policy: dict | None = None, lesson_id: str | None = None
              ) -> tuple[int, int]:
    """(effective_ttl_days, kind_default_days).

    Both narrowing knobs are one-directional. A per-claim `ttl_days` and a course-level
    `freshness_policy` may SHORTEN a kind default; neither may lengthen it. Lengthening is
    how a fact that expired gets a second life without anyone re-reading it.
    """
    kind = claim.get("kind")
    default = TTL_DAYS.get(kind, TTL_DEFAULT_DAYS)
    eff = default
    if policy and policy.get("days") and kind == "onchain-number":
        scope = policy.get("applies_to") or []
        if not scope or lesson_id in scope:
            eff = min(eff, policy["days"])
    own = claim.get("ttl_days")
    if isinstance(own, int) and own > 0:
        eff = min(eff, own)
    return eff, default


def claim_freshness(claim: dict, as_of: _dt.date | None = None,
                    epoch: str | None = None, policy: dict | None = None,
                    lesson_id: str | None = None) -> dict:
    """Everything the gate and the reporter need about one claim's expiry.

    Returned keys: id, kind, status, ttl, kind_ttl, verified_on (ISO or None),
    provenance, undated, age_days, days_left, state, recheck, urls, live.
    `state` is fresh | aging | stale, and is only meaningful when `live` is true.
    """
    as_of = as_of or today()
    ep = parse_iso_date(epoch or FRESHNESS_EPOCH) or as_of
    d, prov = resolve_verified_on(claim)
    undated = prov in ("none", "malformed")
    effective = d or ep
    ttl, kind_ttl = claim_ttl(claim, policy, lesson_id)
    age = (as_of - effective).days
    status = str(claim.get("status") or "")
    text = f"{claim.get('claim') or ''} {claim.get('evidence') or ''}"
    state = "fresh"
    if age >= ttl:
        state = "stale"
    elif age >= ttl * AGING_FRACTION:
        state = "aging"
    return {
        "id": claim.get("id") or "?",
        "kind": claim.get("kind"),
        "status": status,
        "ttl": ttl,
        "kind_ttl": kind_ttl,
        "verified_on": d.isoformat() if d else None,
        "provenance": prov,
        "undated": undated,
        "age_days": age,
        "days_left": ttl - age,
        "state": state,
        "recheck": str(claim.get("recheck") or "").strip() or None,
        "urls": _URL_RE.findall(text),
        "live": status in LIVE_CLAIM_STATUSES,
        "mcp": claim.get("mcp"),
        "claim": claim.get("claim"),
    }


def iter_claims(manifest: dict):
    """(lesson_id, claim_dict) for every claim in every lesson's research scaffold."""
    for l in manifest.get("lessons", []) or []:
        r = l.get("research") or {}
        for c in (r.get("claims") or []):
            if isinstance(c, dict):
                yield l.get("id", "?"), c


def stale_claims(manifest: dict, as_of: _dt.date | None = None) -> list[dict]:
    """Every live claim past its TTL, as `claim_freshness` rows with a `lesson` key.
    This is the one function the publish gate consults, so validate_course.py and
    academy_export.py can never disagree about what 'stale' means."""
    pol = course_ttl_policy(manifest)
    out = []
    for lid, c in iter_claims(manifest):
        f = claim_freshness(c, as_of, policy=pol, lesson_id=lid)
        if f["live"] and f["state"] == "stale":
            f["lesson"] = lid
            out.append(f)
    return out


def undated_deadline(epoch: str = FRESHNESS_EPOCH) -> _dt.date:
    """The day the missing-`verified_on` rule hardens from advisory to HARD."""
    ep = parse_iso_date(epoch) or today()
    return ep + _dt.timedelta(days=UNDATED_GRACE_DAYS)


def _scalar(v) -> str:
    """Render a single-line scalar. Bias: simple tokens bare, everything else
    double-quoted (safe; prose stays readable). Multiline strings are handled by
    the caller as block scalars."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if _SIMPLE_TOKEN.match(s) and s.lower() not in _RESERVED and not _YAML_AMBIGUOUS.match(s):
        return s
    esc = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{esc}"'


def _emit(obj, indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        if not obj:
            return [pad + "{}"]
        for k, v in obj.items():
            kk = _scalar(k)
            if isinstance(v, str) and "\n" in v:
                out.append(f"{pad}{kk}: |-")
                out.extend(f"{pad}  {ln}" for ln in v.split("\n"))
            elif isinstance(v, dict) and v:
                out.append(f"{pad}{kk}:")
                out.extend(_emit(v, indent + 1))
            elif isinstance(v, list) and v:
                out.append(f"{pad}{kk}:")
                out.extend(_emit(v, indent + 1))
            elif isinstance(v, dict):
                out.append(f"{pad}{kk}: {{}}")
            elif isinstance(v, list):
                out.append(f"{pad}{kk}: []")
            else:
                out.append(f"{pad}{kk}: {_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item:
                inner = _emit(item, indent + 1)
                first = inner[0][len(pad) + 2:]  # strip one level of indent
                out.append(f"{pad}- {first}")
                out.extend(inner[1:])
            elif isinstance(item, list) and item:
                out.append(f"{pad}-")
                out.extend(_emit(item, indent + 1))
            elif isinstance(item, str) and "\n" in item:
                out.append(f"{pad}- |-")
                out.extend(f"{pad}    {ln}" for ln in item.split("\n"))
            else:
                out.append(f"{pad}- {_scalar(item)}")
    else:
        out.append(f"{pad}{_scalar(obj)}")
    return out



_CODE_LANGS = {"bash", "sh", "shell", "console", "python", "py", "rust", "rs",
               "solidity", "sol", "ts", "tsx", "typescript", "js", "javascript",
               "json", "toml", "yaml", "yml", "text", "diff", "sql"}


def _dedash_line(s: str) -> str:
    """Replace em/en-dashes and the spaced double-hyphen with grammatical punctuation.
    Preserves leading indentation and never collapses interior alignment spaces."""
    lead = s[:len(s) - len(s.lstrip(" "))]
    b = s[len(lead):]
    b = re.sub(r" ?[—–] ?", ", ", b)               # em/en dash (with at most one flanking space) -> comma
    b = re.sub(r" -- ", ", ", b)                    # spaced double-hyphen evasion -> comma
    b = re.sub(r"^,\s*", "", b)                     # no leading comma if dash was line-initial
    b = re.sub(r" +,", ",", b)                      # no space before comma
    b = re.sub(r",\s*,", ", ", b)                   # collapse doubled commas
    b = re.sub(r",\s*([.;:\!?])", r"\1", b)          # ", ." -> "."
    return lead + b


def dedash_text(md: str) -> str:
    """Strip em-dashes everywhere EXCEPT inside code fences (bash/python/etc.), where a
    dash may be syntax. Prose and `visual` blocks (which carry prose specs) are cleaned.
    Idempotent."""
    out, in_fence, in_visual = [], False, False
    for ln in md.split("\n"):
        st = ln.strip()
        if st.startswith("```"):
            if not in_fence:
                in_fence = True
                in_visual = st[3:].strip().lower() == "visual"
            else:
                in_fence = False
                in_visual = False
            out.append(ln)
            continue
        if not in_fence or in_visual:
            out.append(_dedash_line(ln))          # prose + visual specs -> comma de-dash
        else:
            # inside code/output fences: em-dashes only ever appear in comments here
            # (our code + strings are ASCII); convert to a plain hyphen, no syntax risk.
            out.append(re.sub(r" ?[—–] ?", " - ", ln) if ("—" in ln or "–" in ln) else ln)
    return "\n".join(out)


def count_prose_emdashes(md: str) -> int:
    """Count em/en-dashes (and spaced double-hyphen) OUTSIDE code fences — the ones a
    reader would ever see. `visual` blocks count; bash/python code fences do not."""
    n, in_fence, in_visual = 0, False, False
    for ln in md.split("\n"):
        st = ln.strip()
        if st.startswith("```"):
            if not in_fence:
                in_fence = True; in_visual = st[3:].strip().lower() == "visual"
            else:
                in_fence = False; in_visual = False
            continue
        if in_fence and not in_visual:
            continue
        n += ln.count("—") + ln.count("–") + ln.count(" -- ")
    return n


def to_yaml(obj) -> str:
    """Emit a Python object as readable YAML text (trailing newline)."""
    return "\n".join(_emit(obj, 0)) + "\n"


# ── manifest io ─────────────────────────────────────────────────────────────────

def load_manifest(path: str | Path) -> dict:
    p = Path(path)
    if p.is_dir():
        p = p / "manifest.json"
    if not p.is_file():
        raise SystemExit(f"course: no manifest at {p}")
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"course: manifest is not valid JSON ({p}): {e}")


def flatten_lessons(manifest: dict) -> list[dict]:
    """Lessons in canonical course order: by module order in course.modules, then
    by each lesson's `order` within its module. Returns the lesson objects."""
    mods = manifest.get("modules", [])
    mod_order = {m["id"]: i for i, m in enumerate(mods)}
    lessons = list(manifest.get("lessons", []))

    def key(l):
        return (mod_order.get(l.get("module"), 1_000_000), l.get("order", 0))

    return sorted(lessons, key=key)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── continuity ledger: parsing + derivation ─────────────────────────────────────

def split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split `s` on `sep` at bracket depth 0, honoring () [] {} and quotes.

    Shared on purpose: the ledger's signature parser and continuity.py's call-site
    scanner both count arguments with THIS function, so the two can never disagree
    about how many arguments a call has. Angle brackets are deliberately NOT tracked
    -- `a < b` in a call site is far more common than a comma inside `HashMap<K, V>`,
    and mistaking a comparison for a generic would over-count real calls. Declare
    `arity:` explicitly for a signature with a comma inside a generic."""
    out, buf, depth, quote, esc = [], [], 0, "", False
    for ch in s:
        if esc:
            buf.append(ch); esc = False; continue
        if quote:
            buf.append(ch)
            if ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch; buf.append(ch); continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(buf)); buf = []
            continue
        buf.append(ch)
    out.append("".join(buf))
    return [p.strip() for p in out]


def _arity_from_sig(sig: str) -> tuple[int, int | None]:
    """(min_args, max_args) from a signature string. `max` is None for varargs.

    A default (`=`), an optional marker (`?`), or a Rust `Option<..>` widens the span
    downward: a helper declared `(a, b, c = None)` is legitimately called with 2 or 3
    arguments, and a scanner that insisted on 3 would manufacture a false positive on
    every correct call site."""
    s = sig.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    parts = [p for p in split_top_level(s) if p]
    if not parts:
        return 0, 0
    hi_open = any(p.startswith(("*", "...")) or p.endswith("...") for p in parts)
    req = 0
    for p in parts:
        if p.startswith(("*", "...")) or p.endswith("..."):
            continue
        name = p.split(":")[0].strip()
        optional = ("=" in p) or name.endswith("?") or p.strip().startswith("Option<")
        if not optional:
            req += 1
    hard = len([p for p in parts if not (p.startswith(("*", "...")) or p.endswith("..."))])
    return req, (None if hi_open else hard)


def parse_symbol(entry) -> dict:
    """Normalize ONE provides/consumes entry.

    Accepts a bare string (`"fn:derive_vault_pda"`) or a dict
    (`{symbol|id, sig, arity, terminal, note}`). Returns
    `{symbol, kind, name, lo, hi, sig, terminal, error}`; `error` non-empty means the
    entry is malformed and the caller should flag it rather than silently drop it --
    a typo'd kind that quietly disables checking is the exact hole this gate exists
    to close."""
    sig, terminal, note = "", None, ""
    if isinstance(entry, dict):
        raw = str(entry.get("symbol") or entry.get("id") or "").strip()
        sig = str(entry.get("sig") or "").strip()
        terminal = entry.get("terminal")
        note = str(entry.get("note") or "")
        arity = entry.get("arity")
    else:
        raw, arity = str(entry or "").strip(), None
    out = {"symbol": raw, "kind": "", "name": "", "lo": None, "hi": None,
           "sig": sig, "terminal": terminal, "note": note, "error": ""}
    if not raw:
        out["error"] = "empty symbol entry"
        return out
    m = SYMBOL_RE.match(raw)
    if not m:
        out["error"] = (f"symbol '{raw}' is not '<kind>:<name>' "
                        f"(kinds: {', '.join(sorted(SYMBOL_KINDS))})")
        return out
    kind, name = m.group(1), m.group(2).strip()
    if kind not in SYMBOL_KINDS:
        out["error"] = f"unknown symbol kind '{kind}:' in '{raw}' (kinds: {', '.join(sorted(SYMBOL_KINDS))})"
        return out
    out["kind"], out["name"] = kind, name
    if isinstance(arity, int):
        out["lo"] = out["hi"] = arity
    elif isinstance(arity, (list, tuple)) and len(arity) == 2:
        out["lo"], out["hi"] = arity[0], arity[1]
    elif sig:
        out["lo"], out["hi"] = _arity_from_sig(sig)
    return out


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def derive_ledger(lesson: dict) -> dict:
    """The continuity ledger for one lesson -- ONE graph, not two.

    Merges the explicit `brief.ledger` with the legacy `brief.artifact` accretion
    edge, which is read as a VIEW over the same graph (`artifact.id` -> the symbol
    `artifact:<id>`, each `consumes` entry -> `artifact:<that id>`). A course that
    declares only `artifact` still gets a real continuity graph; a course that
    declares only `ledger` still gets its accretion ladder checked."""
    b = lesson.get("brief") or {}
    led = b.get("ledger") or {}
    if not isinstance(led, dict):
        led = {}
    out = {
        "lesson": lesson.get("id", "?"),
        "kind": b.get("kind", "build"),
        "declared": bool(led),
        "state_in": str(led.get("state_in") or "").strip(),
        "state_out": str(led.get("state_out") or "").strip(),
        "opens": [str(p).strip() for p in _as_list(led.get("opens")) if str(p).strip()],
        "emits": [str(p).strip() for p in _as_list(led.get("emits")) if str(p).strip()],
        "provides": [parse_symbol(e) for e in _as_list(led.get("provides"))],
        "consumes": [parse_symbol(e) for e in _as_list(led.get("consumes"))],
        "renames": [r for r in _as_list(led.get("renames")) if isinstance(r, dict)],
        "legacy": [k for k in LEDGER_LEGACY_KEYS if b.get(k) or led.get(k)],
    }
    art = b.get("artifact")
    if isinstance(art, dict) and art.get("id"):
        out["provides"].append(parse_symbol(
            {"symbol": f"artifact:{art['id']}", "terminal": art.get("terminal")}))
        for c in _as_list(art.get("consumes")):
            if str(c).strip():
                out["consumes"].append(parse_symbol(f"artifact:{str(c).strip()}"))
    return out


def course_ledgers(manifest: dict) -> list[dict]:
    """Derived ledgers for every lesson, in canonical course order."""
    return [derive_ledger(l) for l in flatten_lessons(manifest)]


# ── DAG helpers ─────────────────────────────────────────────────────────────────

def topo_sort(nodes: list[str], edges: list[list[str]]) -> tuple[list[str], list[str]]:
    """Kahn's algorithm. edges are [from, to] = "from taught before to".
    Returns (order, cycle): on success cycle is []; on failure order is partial
    and cycle lists the nodes still entangled."""
    nodeset = list(dict.fromkeys(nodes))
    indeg = {n: 0 for n in nodeset}
    adj: dict[str, list[str]] = {n: [] for n in nodeset}
    for a, b in edges:
        if a in indeg and b in indeg:
            adj[a].append(b)
            indeg[b] += 1
    queue = [n for n in nodeset if indeg[n] == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if len(order) != len(nodeset):
        cycle = [n for n in nodeset if indeg[n] > 0]
        return order, cycle
    return order, []


# ── selftest ────────────────────────────────────────────────────────────────────

def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    # to_yaml: scalars, quoting, nesting, list-of-dicts, multiline
    y = to_yaml({"id": "abc-123", "title": "Store: do it (now)", "n": 3, "b": True,
                 "empty": None, "list": ["x", "y"],
                 "objs": [{"bloom": "implement", "statement": "derive a PDA"}],
                 "blk": "line1\nline2"})
    check("id: abc-123" in y, "simple token stays bare")
    check('title: "Store: do it (now)"' in y, "prose with colon is quoted")
    check("n: 3" in y and "b: true" in y and "empty: null" in y, "int/bool/None render")
    check("  - x" in y and "  - y" in y, "scalar list items")
    check("  - bloom: implement" in y and "    statement:" in y, "list-of-dicts aligns")
    check("blk: |-" in y and "  line1" in y and "  line2" in y, "multiline -> block scalar")

    # round-trip-ish: emitting a brief produces a `lesson:` block
    brief_y = to_yaml({"lesson": {"id": "the-counter", "dominant_job": "show-how"}})
    check(brief_y.startswith("lesson:\n") and "  id: the-counter" in brief_y,
          "brief wraps under lesson:")

    # topo_sort: acyclic order respects edges
    order, cycle = topo_sort(["a", "b", "c"], [["a", "b"], ["b", "c"], ["a", "c"]])
    check(not cycle and order.index("a") < order.index("b") < order.index("c"),
          "acyclic graph sorts in dependency order")
    # cycle detected
    _, cyc = topo_sort(["a", "b"], [["a", "b"], ["b", "a"]])
    check(set(cyc) == {"a", "b"}, "cycle is reported")
    # edge to unknown node is ignored, not a crash
    o2, c2 = topo_sort(["a"], [["a", "ghost"]])
    check(o2 == ["a"] and not c2, "edge to unknown node is ignored")

    # flatten_lessons orders by module then lesson order
    man = {"modules": [{"id": "m1"}, {"id": "m2"}],
           "lessons": [{"id": "l2", "module": "m2", "order": 1},
                       {"id": "l1b", "module": "m1", "order": 2},
                       {"id": "l1a", "module": "m1", "order": 1}]}
    flat = [l["id"] for l in flatten_lessons(man)]
    check(flat == ["l1a", "l1b", "l2"], "flatten_lessons sorts by module then order")

    # vocab sanity
    check("derive-why" in DOMINANT_JOBS and "frame" in GUEST_ONLY_JOBS, "vocab loaded")
    check(ARTIFACT_LADDER.index("counter") < ARTIFACT_LADDER.index("capstone"),
          "artifact ladder ordered")
    check(CHALLENGE_LANGS == {"rust", "typescript"} and "buildable" in CHALLENGE_BUILD_TYPES,
          "academy challenge vocab loaded")

    # ── continuity ledger ──────────────────────────────────────────────────────
    check(split_top_level("a, b, c") == ["a", "b", "c"], "split_top_level: flat args")
    check(split_top_level("a, f(x, y), [1, 2]") == ["a", "f(x, y)", "[1, 2]"],
          "split_top_level: nesting is not split")
    check(split_top_level('a, "x, y", b') == ["a", '"x, y"', "b"],
          "split_top_level: a comma inside a string is not a separator")
    check(split_top_level("a < b, c") == ["a < b", "c"],
          "split_top_level: a comparison is not a generic")

    check(_arity_from_sig("(a, b, c)") == (3, 3), "arity: three required")
    check(_arity_from_sig("(a, b, c = None)") == (2, 3), "arity: a default widens the span down")
    check(_arity_from_sig("(a, b?)") == (1, 2), "arity: an optional marker widens the span")
    check(_arity_from_sig("(a, *rest)") == (1, None), "arity: varargs is unbounded above")
    check(_arity_from_sig("()") == (0, 0), "arity: no args")

    s = parse_symbol("fn:derive_vault_pda")
    check(s["kind"] == "fn" and s["name"] == "derive_vault_pda" and not s["error"],
          "parse_symbol: bare string")
    s = parse_symbol({"symbol": "fn:mint", "sig": "(conn, payer, amount)"})
    check((s["lo"], s["hi"]) == (3, 3), "parse_symbol: dict form derives arity from sig")
    check(parse_symbol("derive_vault_pda")["error"], "parse_symbol: bare name is an error")
    check(parse_symbol("func:x")["error"], "parse_symbol: unknown kind is an error")
    check(parse_symbol("cmd:npm run mint")["name"] == "npm run mint",
          "parse_symbol: a cmd name may contain spaces")

    led = derive_ledger({"id": "l1", "brief": {
        "artifact": {"id": "vault", "consumes": ["counter"], "terminal": "why"},
        "ledger": {"provides": ["fn:derive_vault_pda"], "emits": ["src/vault.rs"],
                   "state_out": "a vault program that builds"}}})
    prov = {p["symbol"] for p in led["provides"]}
    cons = {c["symbol"] for c in led["consumes"]}
    check(prov == {"fn:derive_vault_pda", "artifact:vault"},
          "derive_ledger: the artifact edge joins the SAME provides graph")
    check(cons == {"artifact:counter"}, "derive_ledger: artifact.consumes becomes artifact:<id>")
    check(led["emits"] == ["src/vault.rs"] and led["declared"], "derive_ledger: paths + declared flag")
    legacy = derive_ledger({"id": "l2", "brief": {"artifact_state_in": "x", "carry_forward": "y"}})
    check(set(legacy["legacy"]) == {"artifact_state_in", "carry_forward"},
          "derive_ledger: the never-implemented output-contract fields are reported, not ignored")

    # ── fact freshness ──────────────────────────────────────────────────────────
    D = _dt.date
    check(set(TTL_DAYS) == CLAIM_KINDS, "every claim kind has a TTL and vice-versa")
    check(TTL_DAYS["onchain-number"] < TTL_DAYS["api"] < TTL_DAYS["concept"],
          "TTLs ordered by volatility")
    check(RECHECK_REQUIRED_KINDS <= CLAIM_KINDS and not (RECHECK_REQUIRED_KINDS & RECHECK_ADVISORY_KINDS),
          "recheck kind sets are disjoint subsets of the vocab")

    # date resolution: declared / inferred / malformed / none
    check(resolve_verified_on({"verified_on": "2026-08-01"}) == (D(2026, 8, 1), "declared"),
          "verified_on is declared")
    check(resolve_verified_on({"evidence": "https://x/y (dispatched 2026-07-06)"})
          == (D(2026, 7, 6), "inferred"), "dispatch date is inferred from evidence")
    check(resolve_verified_on({"evidence": "https://x/y verified 2026-07-06"})
          == (D(2026, 7, 6), "inferred"), "bare marker date is inferred")
    check(resolve_verified_on({"evidence": "https://en.wikipedia.org/wiki/Foo_2015-07-30_launch"})
          == (None, "none"), "an unmarked date inside evidence is NOT inferred")
    check(resolve_verified_on({"verified_on": "last tuesday"}) == (None, "malformed"),
          "a non-ISO verified_on is malformed, not silently accepted")
    check(resolve_verified_on({}) == (None, "none"), "no date at all")

    # ttl: per-claim may shorten, never lengthen
    check(claim_ttl({"kind": "onchain-number"}) == (14, 14), "kind default applies")
    check(claim_ttl({"kind": "concept", "ttl_days": 30}) == (30, 365), "per-claim TTL may shorten")
    check(claim_ttl({"kind": "onchain-number", "ttl_days": 999}) == (14, 14),
          "per-claim TTL may NOT lengthen the kind default")
    check(claim_ttl({}) == (TTL_DEFAULT_DAYS, TTL_DEFAULT_DAYS),
          "a kindless claim is volatile by default, not a concept")

    # course-level freshness_policy: an existing, previously-inert manifest field
    polman = {"cadence": {"release": {"freshness_policy": {
        "onchain_numbers_restale_after_days": 7, "applies_to": ["l9"]}}}}
    pol = course_ttl_policy(polman)
    check(pol["days"] == 7 and pol["applies_to"] == ["l9"], "freshness_policy is read")
    check(claim_ttl({"kind": "onchain-number"}, pol, "l9") == (7, 14),
          "a course policy may shorten an on-chain TTL for the lessons it scopes")
    check(claim_ttl({"kind": "onchain-number"}, pol, "l1") == (14, 14),
          "…and does not reach lessons outside applies_to")
    laxpol = course_ttl_policy({"cadence": {"release": {"freshness_policy": {
        "onchain_numbers_restale_after_days": 90}}}})
    check(claim_ttl({"kind": "onchain-number"}, laxpol, "l1") == (14, 14),
          "a course policy may NOT lengthen a kind default (btc-to-sol declares 90)")
    check(course_ttl_policy({})["days"] is None, "no policy is not an error")

    # state transitions around the TTL boundary
    base = {"kind": "onchain-number", "status": "verified", "verified_on": "2026-09-01"}
    check(claim_freshness(base, D(2026, 9, 5))["state"] == "fresh", "day 4 of 14 is fresh")
    check(claim_freshness(base, D(2026, 9, 12))["state"] == "aging", "day 11 of 14 is aging")
    check(claim_freshness(base, D(2026, 9, 15))["state"] == "stale", "day 14 of 14 is stale")
    check(claim_freshness(base, D(2026, 9, 15))["days_left"] == 0, "days_left reaches 0 at expiry")

    # grandfather: an undated claim is dated from the epoch, not from forever ago
    und = {"kind": "onchain-number", "status": "verified"}
    f = claim_freshness(und, D(2026, 9, 7))
    check(f["undated"] and f["age_days"] == 0 and f["state"] == "fresh",
          "an undated claim starts its clock at the epoch, not at day one of a HARD fail")
    check(claim_freshness(und, D(2026, 9, 25))["state"] == "stale",
          "…and still expires on its own kind's TTL")
    check(claim_freshness({"kind": "concept", "status": "verified"}, D(2026, 12, 1))["state"] == "fresh",
          "an undated concept keeps a year of grace")
    check(undated_deadline() == D(2026, 10, 7), "the backfill window is one publish cycle")

    # only shipping statuses expire
    check(not claim_freshness({"kind": "api", "status": "refuted"}, D(2027, 1, 1))["live"],
          "a refuted claim is not a shipping fact")
    check(claim_freshness({"kind": "api", "status": "user-attested"}, D(2027, 1, 1))["live"],
          "a user-attested claim is a shipping fact and does expire")

    # urls are harvested for the advisory probe rule
    check(claim_freshness({"kind": "api", "evidence": "see https://station.jup.ag/docs"})["urls"]
          == ["https://station.jup.ag/docs"], "cited URL harvested")

    # stale_claims / iter_claims walk the manifest shape
    man2 = {"lessons": [{"id": "l1", "research": {"claims": [
        {"id": "C1", "kind": "onchain-number", "status": "verified", "verified_on": "2026-01-01"},
        {"id": "C2", "kind": "concept", "status": "verified", "verified_on": "2026-09-01"}]}}]}
    sc = stale_claims(man2, D(2026, 9, 7))
    check([s["id"] for s in sc] == ["C1"] and sc[0]["lesson"] == "l1",
          "stale_claims finds the expired claim and names its lesson")
    check(len(list(iter_claims(man2))) == 2, "iter_claims walks every lesson")

    print("\n" + ("COURSE_LIB SELFTESTS PASSED" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    print(__doc__)
