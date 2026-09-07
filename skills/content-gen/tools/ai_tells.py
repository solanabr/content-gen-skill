#!/usr/bin/env python3
"""Find the prose tics that make generated course text read as generated.

WHY THIS IS A TOOL AND NOT A PROMPT RULE
----------------------------------------
The em-dash rule was a prompt rule, and the generator satisfied it by dedashing
`lessons/drafts/*.md` and nothing else -- 794 em-dashes shipped in quiz YAML while
every draft came back clean. Asking a model to "vary your prose" produces the same
shape of failure: a scheme that satisfies the request in the surface the model was
thinking about. So these are measured, on every prose surface, after writing.

WHY ADVISORY AND NOT HARD
-------------------------
Every tell here has legitimate instances. "Chargeback fraud is not reduced, it is
structurally impossible" is the sentence doing the teaching -- ruling out the wrong
model IS the lesson. A HARD gate would push a writer to eliminate the construction
entirely, which trades a tic for a flattened voice, and that is strictly worse. The
gate reports a RATE and the specific sites; a human decides which are load-bearing.

The rates below were calibrated against five hand-audited courses (~800k words).

THE TELLS
---------
1. NEGATION-THEN-REVERSAL. "X is not Y. It is Z." The negated half usually carries
   no information, and at one per lesson the rhythm is the single strongest signal
   that prose was generated. Found ~330 times across the five audited courses.

2. REPEATED RHETORICAL FRAME. One figure of speech reused until it is a signature.
   One course reached for the same metaphor 19 times: a plan "wearing an engineering
   costume", "a judgment lesson wearing a build lesson's clothes", "a preference in
   a suit", "a preference wearing a lab coat", "a rumour with good posture", "the
   same mistake wearing different hats". Any one is good writing. Nineteen is a
   machine with one idea.

3. REPEATED SENTENCE OPENER. The same run-up, sentence after sentence: "Here is the
   ..." (34x in one course, including the second paragraph of four different
   lessons), "Sit with that for a second" (12x), "says the quiet part out loud" (4x).
   Distinct from #2 -- it is the POSITION that makes it a tic, not the words. That is
   also why this is measured over sentence openers rather than free n-grams: a
   generic n-gram scan of the same corpus returned mangled lesson ids and ordinary
   English ("is the difference between"), and missed all three of the above, which
   are almost entirely stopwords.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# Same convention as course_lib.count_prose_emdashes: prose is what a reader sees,
# so bash/python fences are excluded but a ```visual fence counts.
FENCE = re.compile(r"^```(.*)$")

# "... is not <something>. It is ..." and its comma-spliced twin. Bounded so the
# match cannot run across a paragraph.
NEG_TWO_SENTENCE = re.compile(
    r"\b(is|are|was|were|do|does|did|will|can)\s+not\b[^.!?\n]{0,90}[.!?]\s+"
    r"(It|They|That|This|These|Those)\s+(is|are|was|were|do|does|did|will|can)\b",
    re.I,
)
NEG_COMMA_SPLICE = re.compile(
    r"\b(is|are|was|were)\s+not\b[^,.!?\n]{0,70},\s*"
    r"(it|they|that|this)\s+(is|are|was|were)\b",
    re.I,
)

# Frames worth watching: a small closed set of "X wearing a Y" style constructions
# that generated prose reaches for. Kept explicit rather than inferred -- a generic
# metaphor detector would fire on every good sentence in the corpus.
FRAME = re.compile(
    r"\b(wearing (a|an|its|their)\b|in (a|an) \w+(?:'s)? (suit|costume|coat|clothing)\b"
    r"|dressed (up )?as\b|with good posture\b|\bmasquerading as\b)",
    re.I,
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "it", "its", "that", "this", "you", "your", "not",
    "as", "at", "by", "from", "be", "has", "have", "had", "will", "can", "if",
    "so", "than", "then", "there", "what", "which", "who", "when", "how", "why",
}


def prose_text(md: str) -> str:
    """Everything a reader sees: code fences dropped, ```visual kept, markup stripped."""
    out, in_fence, in_visual = [], False, False
    for ln in md.split("\n"):
        m = FENCE.match(ln.strip())
        if m:
            if not in_fence:
                in_fence, in_visual = True, m.group(1).strip().lower() == "visual"
            else:
                in_fence = in_visual = False
            continue
        if in_fence and not in_visual:
            continue
        out.append(ln)
    t = "\n".join(out)
    t = re.sub(r"`[^`\n]*`", " ", t)            # inline code is not prose
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)  # images
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"[*_#>|]", " ", t)               # emphasis / headings / tables
    return t


def find_sites(text: str) -> dict[str, list[str]]:
    """Every tell instance, as the sentence fragment a human needs to judge it."""
    hits: dict[str, list[str]] = {"negation-reversal": [], "repeated-frame": []}
    for rx in (NEG_TWO_SENTENCE, NEG_COMMA_SPLICE):
        for m in rx.finditer(text):
            s = max(0, m.start() - 60)
            hits["negation-reversal"].append(" ".join(text[s:m.end() + 20].split()))
    for m in FRAME.finditer(text):
        s = max(0, m.start() - 50)
        hits["repeated-frame"].append(" ".join(text[s:m.end() + 30].split()))
    return hits


def repeated_openers(text: str) -> list[tuple[str, int]]:
    """Sentence openers reused often enough to become a signature.

    Openers, not free n-grams. A generic n-gram scan over 130k words returns pure
    noise -- mangled lesson ids, legitimate repeated CTAs, and ordinary English like
    "is the difference between" -- and it MISSES the real tells, because those are
    mostly stopwords ("sit with that for a second", "here is the ..."). What makes
    those tics is their POSITION: the same run-up, sentence after sentence.

    The floor scales with length so a long course is not penalised for repetition a
    reader would never notice.
    """
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n\s*\n", text) if s.strip()]
    counts = Counter()
    for s in sents:
        w = re.findall(r"[A-Za-z']+", s.lower())[:3]
        if len(w) == 3 and not all(x in STOPWORDS for x in w):
            counts[" ".join(w)] += 1
    floor = max(6, len(sents) // 400)
    return [(p, c) for p, c in counts.most_common(12) if c >= floor]


# Calibrated on five audited courses. Post-remediation the worst course sits at
# 0.53 per 1k words, the best at 0.16; pre-remediation the worst was 0.87. A course
# above 0.60 has the rhythm a reader notices.
RATE_WARN = 0.60


def scan(paths: list[Path]) -> dict:
    text, per_file = [], {}
    for p in paths:
        try:
            t = prose_text(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        per_file[p] = t
        text.append(t)
    joined = "\n".join(text)
    words = max(1, len(joined.split()))
    hits = find_sites(joined)
    return {
        "words": words,
        "files": len(per_file),
        "per_file": per_file,
        "hits": hits,
        "neg_rate": len(hits["negation-reversal"]) * 1000 / words,
        "phrases": repeated_openers(joined),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", type=Path, help="course dir, or any dir with prose")
    ap.add_argument("--glob", action="append", default=None,
                    help="prose globs (repeatable). Default covers drafts and lessons.")
    ap.add_argument("--show", type=int, default=6, help="sites to print per tell")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a rate exceeds its threshold (default: report only)")
    a = ap.parse_args(argv)

    globs = a.glob or ["lessons/drafts/*.md", "lessons/*/intro.md", "README.md"]
    paths: list[Path] = []
    for g in globs:
        paths += sorted(a.target.glob(g))
    if not paths:
        print(f"ai_tells: no prose found under {a.target} for {globs}", file=sys.stderr)
        return 2

    r = scan(paths)
    n_neg = len(r["hits"]["negation-reversal"])
    n_frame = len(r["hits"]["repeated-frame"])
    print(f"{a.target.name}: {r['files']} file(s), {r['words']:,} words of prose")
    print(f"  negation-then-reversal : {n_neg} ({r['neg_rate']:.2f} per 1k words, "
          f"warn above {RATE_WARN})")
    for s in r["hits"]["negation-reversal"][:a.show]:
        print(f"      {s[:150]}")
    print(f"  repeated frame         : {n_frame}")
    for s in r["hits"]["repeated-frame"][:a.show]:
        print(f"      {s[:150]}")
    print(f"  repeated sentence openers: {len(r['phrases'])}")
    for p, c in r["phrases"][:a.show]:
        print(f"      {c:>3}x  {p}")

    over = r["neg_rate"] > RATE_WARN or n_frame >= 6 or bool(r["phrases"])
    if over:
        print("  -> ADVISORY: read the sites above. Keep the ones where ruling out the "
              "wrong answer IS the teaching; vary the rest, and vary the REPAIR too "
              "so the fix does not become its own tic.")
    return 1 if (over and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
