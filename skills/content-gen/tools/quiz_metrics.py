#!/usr/bin/env python3
"""quiz_metrics.py — the statistics behind the quiz gate. Pure functions, stdlib only.

Why this exists
---------------
A quiz layer can satisfy every naive fairness check and still be free to a learner
who never reads the lesson. The wave-2 courses are the worked example. Their
correct-answer positions are near-perfectly balanced globally, because the
generator prompt said so:

    "make your first question's correct answer sit at option index ${mi % 3}
     and rotate forward from there; never put >half on one slot"

That instruction existed to satisfy a gate that HARD-failed ">50% of keys in one
slot". It worked. It also made the key a deterministic per-lesson a->b->c cycle,
so the position of one answer predicts the next: the best order-1 Markov predictor
scores 85.4%, 86.2%, 92.0% and 94.0% on the shipped courses against 39.6% for an
honest shuffle. The gate measured the marginal; the rotation made the marginal
perfect.

    THE GOVERNING LAW: when a statistical property must hold, COMPUTE IT IN A
    TOOL. Never ask for it in a prompt. A stronger instruction produces a
    different artifact, not randomness.

So this module does not test one statistic. Its primary metric is *exploitability*
— the accuracy of the best order-1/order-2 Markov predictor over the key sequence,
measured against a permutation null that holds the marginal fixed. Position
uniformity owns the marginal; the Markov test owns everything else. Every
deterministic scheme a prompt can induce (constant, forward or reverse rotation,
alternation, per-lesson reset, any period <= 3) is order <= 2 and is caught.

Every test is TWO-SIDED. Being too even is a failure: a balancing scheme lands too
close to perfect and real randomness is lumpy.

Agreement contract
------------------
This is a port of `academy-courses/scripts/quiz_stats.py`, which gates the target
repo. The two MUST agree on every number: same thresholds, same estimators, same
permutation seed. Verified 2026-09-07 by running both over the same three courses
(`content/courses/<id>/manifest.json` vs `content/academy/courses/<id>/`): every
statistic matched exactly, with the differences below.

  1. the loader — this one reads a content-gen `manifest.json`
     (`lessons[].brief.quiz_blocks`), that one reads an emitted `course.yaml` tree;
  2. em-dashes are ERROR here and INFO there — that script audits already-shipped
     content, this one gates a generator that must not emit them at all;
  3. every below-floor metric here emits an explicit INCONCLUSIVE finding. A quiet
     pass is the failure mode this whole workstream exists to remove;
  4. LESSON ORDER, which is a real divergence and not a preference. The two
     order-dependent metrics (order-1/order-2 Markov accuracy) disagreed on
     solana-speedrun: 66.7%/75.0% there against 77.8%/100.0% here. The cause is
     that quiz_stats.py breaks ties WITHIN a module by lesson-directory name, and
     emitted lesson directories are bare slugs, so `como-funciona` sorts before
     `por-que-solana` even though it is lesson 2. This module uses the manifest's
     authoritative `(module index, lesson.order)`, which is the order a learner
     actually meets the questions in and therefore the only order the sequential
     test means anything in. The fix belongs in quiz_stats.py (its `course.yaml`
     modules list carries the lesson ids in order; it should index into that rather
     than sort by directory name). Until then, treat its Markov numbers on any
     multi-lesson module as a lower bound.

    python3 quiz_metrics.py --course content/courses/<id>
    python3 quiz_metrics.py --manifest manifest.json --json
    python3 quiz_metrics.py --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# ── Tuning ────────────────────────────────────────────────────────────────────
# Every constant below is mirrored in academy-courses/scripts/quiz_stats.py.
# Change both together or the generator gate and the target-repo gate disagree.

PERM_B = 999            # permutation-null resamples; p floors at 1/(B+1) = 0.001
PERM_SEED = 20260907    # fixed so a run is reproducible and a diff is meaningful
MARKOV_P_ERROR = 0.01   # sequential exploitability fails at or below this
CHI2_P_ERROR = 0.001    # marginal uniformity fails below this (and above 1-this)
CHI2_MIN_N = 20         # below this the marginal test is inconclusive, not passed
SHORT_LABEL_CHARS = 70  # mean option label at or under this must carry 5 options
MIN_OPTIONS = 4         # authoring floor; multiSelect's floor is 5 (see MULTI_MIN_OPTIONS)
MULTI_MIN_OPTIONS = 5   # a set-valued answer needs room for 2 <= correct <= k-2
LEN_RATIO_ERROR = (0.80, 1.25)   # mean(len key) / mean(len distractor)
LEN_RATIO_WARN = (0.90, 1.12)
SPREAD_FLAG = 1.7       # per-question longest/shortest label ratio worth counting
SPREAD_ERROR = 2.2      # a single question this lopsided is a defect on its own
ABSOLUTES_WARN, ABSOLUTES_ERROR = 1.5, 2.0   # distractor rate / key rate
HEDGE_WARN, HEDGE_ERROR = 1.5, 2.0           # key rate / distractor rate
DEDUP_JACCARD = 0.55    # cross-lesson key similarity that flags a repeat-keyed fact
MIN_EXPECTED_CELL = 5   # chi-square cell floor before a metric is downgraded

# Sample floors. Below each of these the metric CANNOT pass — it reports
# INCONCLUSIVE and names what it could not rule out.
SEQ_MIN_N = 3           # single-select questions needed for a Markov test
REPEAT_MIN_N = 6        # adjacent same-k pairs needed for the repeat test
SEED_MIN_N = 8          # lessons needed for the module-seed test
HEURISTIC_MIN_N = 12    # scorable questions needed per content-blind strategy

HEDGE_RE = re.compile(
    r"\b(usually|often|typically|generally|in practice|tends to|sometimes|"
    r"not always|roughly|approximately|mostly|primarily|largely|depends on|"
    r"in most cases|can be|may be|might|verify|re-?check|as of)\b",
    re.I,
)
ABSOLUTE_RE = re.compile(
    r"\b(always|never|only|cannot|can't|impossible|guarantees?|every|all of|"
    r"none of|must be|automatically|entirely|completely)\b",
    re.I,
)
WORD_RE = re.compile(r"[A-Za-z0-9_]{4,}")
EMDASH_RE = re.compile(r"[–—]")

STOPWORDS = {
    "that", "this", "with", "from", "have", "which", "what", "when", "your",
    "they", "them", "then", "than", "into", "over", "only", "will", "does",
    "each", "same", "both", "some", "more", "most", "other", "there", "these",
    "those", "because", "before", "after", "while", "would", "could", "about",
}

ERROR, WARN, INFO = "error", "warning", "info"


# ── Statistics (stdlib only — no scipy in CI) ─────────────────────────────────

def _gser(a: float, x: float) -> float:
    """Series form of the regularized lower incomplete gamma P(a, x)."""
    ap, s, d = a, 1.0 / a, 1.0 / a
    for _ in range(1000):
        ap += 1.0
        d *= x / ap
        s += d
        if abs(d) < abs(s) * 1e-15:
            break
    return s * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Continued-fraction form of the regularized upper incomplete gamma Q(a, x)."""
    tiny = 1e-300
    b, c = x + 1.0 - a, 1.0 / tiny
    d = 1.0 / b if b != 0 else 1.0 / tiny
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(chi2: float, df: int) -> float:
    """P(X >= chi2) for X ~ chi-square with df degrees of freedom."""
    if df <= 0 or chi2 <= 0:
        return 1.0
    a, x = df / 2.0, chi2 / 2.0
    return 1.0 - _gser(a, x) if x < a + 1.0 else _gcf(a, x)


def chi2_uniform(counts: list[int]) -> tuple[float, int, float]:
    """Goodness-of-fit against a uniform distribution. Returns (chi2, df, p)."""
    n, k = sum(counts), len(counts)
    if n == 0 or k < 2:
        return 0.0, 0, 1.0
    exp = n / k
    chi2 = sum((c - exp) ** 2 / exp for c in counts)
    return chi2, k - 1, chi2_sf(chi2, k - 1)


def markov_accuracy(seq: list[int], order: int) -> float | None:
    """Training accuracy of the best order-`order` predictor of `seq`.

    order 0 is the best constant predictor — exactly what the old gate measured,
    and exactly what a rotation makes look perfect.
    """
    if order == 0:
        return (Counter(seq).most_common(1)[0][1] / len(seq)) if seq else None
    if len(seq) <= order:
        return None
    ctx: dict[tuple, Counter] = defaultdict(Counter)
    for i in range(order, len(seq)):
        ctx[tuple(seq[i - order:i])][seq[i]] += 1
    hits = sum(c.most_common(1)[0][1] for c in ctx.values())
    total = sum(sum(c.values()) for c in ctx.values())
    return hits / total if total else None


def permutation_p(seq: list[int], order: int) -> tuple[float | None, float | None]:
    """Observed order-`order` accuracy and its p-value under a permutation null.

    Shuffling preserves the multiset, so the null is conditional on the marginal:
    this asks "is the ORDER structured?", never "is the mix uneven?". It also
    degrades honestly — a short honest sequence simply returns a large p.
    """
    obs = markov_accuracy(seq, order)
    if obs is None:
        return None, None
    rng = random.Random(PERM_SEED + order)
    scratch, at_least = list(seq), 0
    for _ in range(PERM_B):
        rng.shuffle(scratch)
        acc = markov_accuracy(scratch, order)
        if acc is not None and acc >= obs - 1e-12:
            at_least += 1
    return obs, (at_least + 1) / (PERM_B + 1)


def binomial_band(p: float, n: int, sigmas: float = 3.0) -> tuple[float, float]:
    """Two-sided normal-approximation band around a rate, so a threshold that is
    fair to 135 questions does not fire spuriously on 33."""
    if n <= 0:
        return 0.0, 1.0
    half = sigmas * math.sqrt(max(p * (1.0 - p), 1e-12) / n)
    return max(0.0, p - half), min(1.0, p + half)


def binom_pmf(k: int, n: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k))


def binom_two_sided_p(obs: int, n: int, p: float) -> float:
    """Exact two-sided binomial p: the total probability of every outcome no more
    likely than the observed one. Exact matters here because the courses that most
    need judging are the small ones."""
    if n <= 0:
        return 1.0
    target = binom_pmf(obs, n, p) * (1.0 + 1e-9)
    return min(1.0, sum(pm for i in range(n + 1) if (pm := binom_pmf(i, n, p)) <= target))


def binom_accept_region(n: int, p: float, alpha: float) -> tuple[int, int]:
    """Counts the two-sided exact test would NOT reject at `alpha`."""
    keep = [i for i in range(n + 1) if binom_two_sided_p(i, n, p) >= alpha]
    return (keep[0], keep[-1]) if keep else (0, n)


def power_against(n: int, p_null: float, p_alt: float, alpha: float) -> float:
    """P(reject | the alternative is true). Used to say UNDERPOWERED, not PASS.

    The point-mass case matters most: a scheme that never repeats a slot puts all
    its mass at 0, so if 0 sits inside the acceptance region the test is blind to
    exactly the artifact it exists to find.
    """
    lo, hi = binom_accept_region(n, p_null, alpha)
    return sum(binom_pmf(i, n, p_alt) for i in range(n + 1) if i < lo or i > hi)


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def content_tokens(text: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(text)} - STOPWORDS


# ── Model ─────────────────────────────────────────────────────────────────────

@dataclass
class Question:
    course: str
    lesson_slug: str
    lesson_title: str
    module_index: int
    block_key: str
    qid: str
    prompt: str
    explanation: str
    multi: bool
    labels: list[str]
    option_ids: list[str]
    correct_idx: list[int]
    feedback_present: list[bool]

    @property
    def k(self) -> int:
        return len(self.labels)

    @property
    def single(self) -> bool:
        return not self.multi and len(self.correct_idx) == 1

    @property
    def key_label(self) -> str:
        return self.labels[self.correct_idx[0]] if self.correct_idx else ""

    @property
    def distractors(self) -> list[str]:
        return [l for i, l in enumerate(self.labels) if i not in set(self.correct_idx)]

    @property
    def keys(self) -> list[str]:
        return [self.labels[i] for i in self.correct_idx]

    @property
    def mean_label_len(self) -> float:
        return sum(len(l) for l in self.labels) / max(1, self.k)

    @property
    def address(self) -> tuple[str, str, str, str]:
        """The 4-tuple a layout ledger is keyed on. Question ids are NOT unique
        within a course — one shipped course uses q1/q2/q3 for all 33 questions —
        so anything coarser silently merges distinct questions."""
        return (self.course, self.lesson_slug, self.block_key, self.qid)

    def texts(self) -> list[str]:
        return [self.prompt, self.explanation, *self.labels]


@dataclass
class Finding:
    severity: str
    metric: str
    message: str


@dataclass
class Report:
    slug: str
    questions: list[Question]
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, severity: str, metric: str, message: str) -> None:
        self.findings.append(Finding(severity, metric, message))

    def inconclusive(self, metric: str, why: str, cannot_rule_out: str) -> None:
        """The small-sample rule. A metric under its floor never passes quietly —
        it says so, and names the artifact it was unable to exclude."""
        self.add(WARN, metric, f"INCONCLUSIVE, not passed — {why}. "
                               f"Cannot rule out: {cannot_rule_out}")

    @property
    def failed(self) -> bool:
        return any(f.severity == ERROR for f in self.findings)


def _ordered_lessons(manifest: dict) -> list[tuple[int, dict]]:
    """Lessons in the order a learner meets them, tagged with their module index.

    Display order is what a learner experiences and therefore what the sequential
    test must see. Mirrors course_lib.flatten_lessons; kept local so this module
    stays stdlib-only and portable between the two repos it has to agree across.
    """
    mods = manifest.get("modules") or []
    mod_order = {m.get("id"): i for i, m in enumerate(mods)}
    lessons = list(manifest.get("lessons") or [])
    lessons.sort(key=lambda l: (mod_order.get(l.get("module"), 1_000_000), l.get("order", 0)))
    return [(mod_order.get(l.get("module"), len(mods)), l) for l in lessons]


def load_questions(manifest: dict) -> list[Question]:
    """Read a manifest's quiz questions in display order."""
    course_id = str((manifest.get("course") or {}).get("id", ""))
    out: list[Question] = []
    for module_index, lesson in _ordered_lessons(manifest):
        brief = lesson.get("brief") or {}
        for bi, block in enumerate(brief.get("quiz_blocks") or []):
            block = block or {}
            # A block with no `key` still needs a stable address: fall back to its
            # index, which is what the exporter uses to name it (check / check-N).
            key = str(block.get("key") or f"#{bi}")
            for q in block.get("questions") or []:
                q = q or {}
                options = [o or {} for o in (q.get("options") or [])]
                out.append(Question(
                    course=course_id,
                    lesson_slug=str(lesson.get("id", "")),
                    lesson_title=str(brief.get("title", "")),
                    module_index=module_index,
                    block_key=key,
                    qid=str(q.get("id", "")),
                    prompt=str(q.get("prompt", "")),
                    explanation=str(q.get("explanation", "")),
                    multi=bool(q.get("multiSelect", False)),
                    labels=[str(o.get("label", "")) for o in options],
                    option_ids=[str(o.get("id", "")) for o in options],
                    correct_idx=[i for i, o in enumerate(options) if o.get("correct") is True],
                    feedback_present=[bool(str(o.get("feedback", "")).strip()) for o in options],
                ))
    return out


# ── Metrics ───────────────────────────────────────────────────────────────────

def _sample(items: list[str], n: int = 4) -> str:
    head = ", ".join(items[:n])
    return head + (f", +{len(items) - n} more" if len(items) > n else "")


def m_structure(rep: Report) -> None:
    """Option-count policy, multiSelect shape, feedback completeness, explanation.

    Per-question and exact — no sampling, so nothing here is ever inconclusive.
    """
    too_few, needs_five, no_feedback, no_expl = [], [], [], []
    bad_multi = []
    for q in rep.questions:
        where = f"{q.lesson_slug}/{q.block_key}/{q.qid}"
        if q.multi:
            if q.k < MULTI_MIN_OPTIONS:
                bad_multi.append(f"{where} (k={q.k} < {MULTI_MIN_OPTIONS})")
            elif not (2 <= len(q.correct_idx) <= q.k - 2):
                bad_multi.append(f"{where} ({len(q.correct_idx)} correct of {q.k}; "
                                 f"need 2..{q.k - 2})")
        elif q.k < MIN_OPTIONS:
            too_few.append(f"{where} (k={q.k})")
        elif q.mean_label_len <= SHORT_LABEL_CHARS and q.k < 5:
            needs_five.append(f"{where} (mean label {q.mean_label_len:.0f} chars, k={q.k})")
        if not all(q.feedback_present):
            missing = sum(1 for f in q.feedback_present if not f)
            no_feedback.append(f"{where} ({missing}/{q.k})")
        if not q.explanation.strip():
            no_expl.append(where)

    rep.stats["questions"] = len(rep.questions)
    rep.stats["option_counts"] = dict(sorted(Counter(q.k for q in rep.questions).items()))
    rep.stats["multiselect"] = sum(1 for q in rep.questions if q.multi)

    if too_few:
        rep.add(ERROR, "option-count",
                f"{len(too_few)} question(s) below {MIN_OPTIONS} options: " + _sample(too_few))
    if needs_five:
        rep.add(ERROR, "option-count",
                f"{len(needs_five)} short-label question(s) must carry 5 options "
                f"(mean label <= {SHORT_LABEL_CHARS} chars): " + _sample(needs_five))
    if bad_multi:
        rep.add(ERROR, "multiselect-shape",
                f"{len(bad_multi)} multiSelect question(s) outside the shape rule "
                f"(>= {MULTI_MIN_OPTIONS} options, 2 <= correct <= k-2): " + _sample(bad_multi))
    if no_feedback:
        rep.add(ERROR, "feedback",
                f"{len(no_feedback)} question(s) with options lacking feedback — EVERY option "
                f"carries feedback, the correct one included: " + _sample(no_feedback))
    if no_expl:
        rep.add(ERROR, "explanation",
                f"{len(no_expl)} question(s) with no explanation: " + _sample(no_expl))
    if rep.stats["multiselect"] == 0 and len(rep.questions) >= 20:
        rep.add(WARN, "multiselect",
                "no question in this course has a set-valued answer; confirm that is true of the "
                "subject matter (never convert a single-answer question just to add difficulty)")


def m_sequence(rep: Report) -> None:
    """Sequential exploitability — the metric a rotation cannot survive."""
    seq = [q.correct_idx[0] for q in rep.questions if q.single]
    rep.stats["single_select"] = len(seq)
    if len(seq) < SEQ_MIN_N:
        rep.inconclusive("sequence", f"only {len(seq)} single-select question(s), floor {SEQ_MIN_N}",
                         "a rotation, an alternation, or any other order-1/order-2 pattern in the "
                         "answer key")
        return

    rep.stats["acc0"] = markov_accuracy(seq, 0)
    for order in (1, 2):
        obs, p = permutation_p(seq, order)
        if obs is None:
            rep.inconclusive("sequence", f"{len(seq)} keys is too short for an order-{order} test",
                             f"an order-{order} pattern in the answer key")
            continue
        rep.stats[f"acc{order}"] = obs
        rep.stats[f"p_acc{order}"] = p
        if p <= MARKOV_P_ERROR:
            rep.add(ERROR, "sequence",
                    f"order-{order} predictor scores {obs:.1%} on the key sequence "
                    f"(p={p:.3f} vs a permutation null holding the marginal fixed) — "
                    f"the answer position is predictable from the answers before it")
        elif p <= 0.05:
            rep.add(WARN, "sequence",
                    f"order-{order} predictor scores {obs:.1%} (p={p:.3f}) — borderline structure")


def m_repeat(rep: Report) -> None:
    """Does the key ever land on the same slot twice running?

    The keystone, and the only position metric with real power at small n. Any
    scheme that "spreads the keys evenly" — a rotation, a Latin square, a
    per-lesson stratified permutation — produces far FEWER repeats than chance,
    which is why the test is two-sided. Being too even is a failure.
    """
    trans, repeats, chances = 0, 0, []
    by_lesson: dict[str, list[Question]] = defaultdict(list)
    for q in rep.questions:
        if q.single:
            by_lesson[q.lesson_slug].append(q)
    for questions in by_lesson.values():
        for a, b in zip(questions, questions[1:]):
            if a.k != b.k:
                continue  # an offset across different option counts is not comparable
            trans += 1
            chances.append(1.0 / b.k)
            if a.correct_idx[0] == b.correct_idx[0]:
                repeats += 1

    if trans < REPEAT_MIN_N:
        rep.inconclusive("repeat-rate",
                         f"only {trans} adjacent same-k pair(s), floor {REPEAT_MIN_N}",
                         "a never-repeats scheme (the signature of any 'spread the keys evenly' rule)")
        return

    p_null = sum(chances) / len(chances)
    p_val = binom_two_sided_p(repeats, trans, p_null)
    rep.stats["repeat_rate"] = f"{repeats}/{trans}"
    rep.stats["p_repeat"] = p_val

    # Can this test even see a never-repeats scheme at this n?
    power = power_against(trans, p_null, 0.0, CHI2_P_ERROR)
    rep.stats["repeat_power"] = power
    if p_val < CHI2_P_ERROR:
        direction = "far fewer" if repeats / trans < p_null else "far more"
        rep.add(ERROR, "repeat-rate",
                f"the key repeats its slot {repeats}/{trans} times ({repeats/trans:.1%}) — "
                f"{direction} than the {p_null:.1%} chance rate (exact two-sided p={p_val:.2g}). "
                f"Keys that never repeat are as predictable as keys that always do")
    elif power < 0.80:
        rep.add(WARN, "repeat-rate",
                f"repeat rate {repeats}/{trans} is within tolerance, but at n={trans} this test has "
                f"only {power:.0%} power against a never-repeats scheme — UNDERPOWERED, not passed")


def m_marginal(rep: Report) -> None:
    """Position uniformity, per option-count stratum. Two-sided."""
    strata: dict[int, list[int]] = defaultdict(list)
    for q in rep.questions:
        if q.single:
            strata[q.k].append(q.correct_idx[0])

    dist = {}
    for k, positions in sorted(strata.items()):
        counts = [positions.count(i) for i in range(k)]
        dist[k] = counts
        n = len(positions)
        chi2, df, p = chi2_uniform(counts)
        if n < CHI2_MIN_N or n / k < MIN_EXPECTED_CELL:
            rep.inconclusive("marginal",
                             f"k={k}: n={n} (expected cell {n/k:.1f} < {MIN_EXPECTED_CELL}, "
                             f"floor n={CHI2_MIN_N}) {counts}",
                             "a one-slot pile-up, and equally a too-perfect balance")
            continue
        if p < CHI2_P_ERROR:
            rep.add(ERROR, "marginal",
                    f"k={k}: key positions are not uniform, {counts} "
                    f"(chi2={chi2:.1f}, df={df}, p={p:.2g})")
        elif p > 1.0 - CHI2_P_ERROR:
            # A balancing scheme lands too close to perfect. Real randomness is lumpy.
            rep.add(ERROR, "marginal",
                    f"k={k}: key positions are TOO uniform, {counts} (chi2={chi2:.2f}, p={p:.4f}) — "
                    f"honest randomness is lumpier than this; a balancing scheme is the usual cause")
    rep.stats["position_distribution"] = dist


def m_module_seed(rep: Report) -> None:
    """Is a lesson's first key position a function of its module index?

    The exact shape of the generator's `${mi % 3}` seed, so it is worth testing
    directly rather than hoping the sequential test notices.
    """
    firsts: dict[str, Question] = {}
    for q in rep.questions:
        if q.single and q.lesson_slug not in firsts:
            firsts[q.lesson_slug] = q
    trials = [(q.module_index, q.correct_idx[0], q.k) for q in firsts.values()]
    if len(trials) < SEED_MIN_N:
        rep.inconclusive("module-seed",
                         f"only {len(trials)} lesson(s) with a single-select question, "
                         f"floor {SEED_MIN_N}",
                         "a first-key position seeded from the module index (the `mi % 3` shape)")
        return
    hits = sum(1 for mi, pos, k in trials if pos == mi % k)
    n = len(trials)
    p_chance = sum(1.0 / k for _, _, k in trials) / n
    lo, hi = binomial_band(p_chance, n)
    rep.stats["module_seed_hits"] = f"{hits}/{n}"
    if hits / n > hi:
        rep.add(ERROR, "module-seed",
                f"each lesson's first key sits at (module index mod k) in {hits}/{n} lessons "
                f"({hits/n:.0%} vs {p_chance:.0%} chance) — the key position is a function of "
                f"the module index")


def m_length_rank(rep: Report) -> None:
    """Uniformity of the key's length RANK among its own options.

    Rate-of-longest is blind to two real tells: one shipped course keys the
    SHORTEST option 41.8% of the time, and another sits at a blameless 33.0%
    longest while its key is the middle length in 61% and the shortest in 5.7%
    (chi2=40.9, p=1.3e-9) — so "never pick the shortest" eliminates an option in
    94% of its questions. Rank uniformity sees all three; longest-correct sees one.
    """
    singles = [q for q in rep.questions if q.single]
    if not singles:
        return

    by_k: dict[int, list[int]] = defaultdict(list)
    longest = shortest = 0.0
    # A question whose extreme is TIED is not evidence in either direction, so it is
    # not a trial. Counting ties as misses is what makes a set of exactly-parallel
    # options look like a deliberate "never key the longest" scheme.
    ext: dict[str, dict] = {"longest": {"hits": 0, "chances": []},
                            "shortest": {"hits": 0, "chances": []}}
    spread_hits, worst_spread = 0, 0.0
    for q in singles:
        lens = [len(l) for l in q.labels]
        # rank by (length, option index) so ties resolve deterministically
        order = sorted(range(q.k), key=lambda i: (lens[i], i))
        by_k[q.k].append(order.index(q.correct_idx[0]))
        top, bot = max(lens), min(lens)
        longest += (1.0 / lens.count(top)) if len(q.key_label) == top else 0.0
        shortest += (1.0 / lens.count(bot)) if len(q.key_label) == bot else 0.0
        if lens.count(top) == 1:
            ext["longest"]["chances"].append(1.0 / q.k)
            ext["longest"]["hits"] += 1 if len(q.key_label) == top else 0
        if lens.count(bot) == 1:
            ext["shortest"]["chances"].append(1.0 / q.k)
            ext["shortest"]["hits"] += 1 if len(q.key_label) == bot else 0
        spread = top / max(1, bot)
        worst_spread = max(worst_spread, spread)
        if spread > SPREAD_FLAG:
            spread_hits += 1

    n = len(singles)
    p_chance = sum(1.0 / q.k for q in singles) / n
    rep.stats["chance"] = p_chance
    rep.stats["longest_correct"] = longest / n
    rep.stats["shortest_correct"] = shortest / n

    ranks = {}
    for k, positions in sorted(by_k.items()):
        counts = [positions.count(i) for i in range(k)]
        ranks[k] = counts
        if len(positions) < CHI2_MIN_N or len(positions) / k < MIN_EXPECTED_CELL:
            rep.inconclusive("length-rank",
                             f"k={k}: n={len(positions)} is under the floor {CHI2_MIN_N} {counts}",
                             "option length predicting the answer (longest, shortest, or middle)")
            continue
        chi2, df, p = chi2_uniform(counts)
        if p < CHI2_P_ERROR:
            rep.add(ERROR, "length-rank",
                    f"k={k}: the key's length rank is not uniform, {counts} shortest->longest "
                    f"(chi2={chi2:.1f}, df={df}, p={p:.2g}) — option length predicts the answer")
        elif p < 0.01:
            rep.add(WARN, "length-rank", f"k={k}: key length rank drifting, {counts} (p={p:.3f})")
    rep.stats["length_rank"] = ranks

    # correct-is-longest / correct-is-shortest. HARD here (advisory in the old gate,
    # which is why four generated courses shipped at 91-97% with GATE: PASS). Exact
    # two-sided binomial, so a key that is NEVER the longest fails too — that is a
    # scheme, not an absence of one.
    for name, acc in ext.items():
        hits, trials = acc["hits"], len(acc["chances"])
        if trials < HEURISTIC_MIN_N:
            rep.inconclusive(f"{name}-correct",
                             f"only {trials} question(s) have a unique {name} option, "
                             f"floor {HEURISTIC_MIN_N}",
                             f"a course that systematically keys the {name} option")
            continue
        p_null = sum(acc["chances"]) / trials
        p_val = binom_two_sided_p(hits, trials, p_null)
        rep.stats[f"p_{name}"] = p_val
        if p_val < CHI2_P_ERROR:
            direction = "more" if hits / trials > p_null else "less"
            rep.add(ERROR, f"{name}-correct",
                    f"the key is the {name} option in {hits}/{trials} questions that have a unique "
                    f"{name} ({hits/trials:.1%}) — {direction} often than the {p_null:.1%} chance "
                    f"rate (exact two-sided p={p_val:.2g}); write distractors matching the answer's "
                    f"length and register")
        elif p_val < 0.05:
            rep.add(WARN, f"{name}-correct",
                    f"the key is the {name} option in {hits}/{trials} ({hits/trials:.1%}) vs "
                    f"{p_null:.1%} chance (p={p_val:.3f}) — drifting")

    rep.stats["spread_over_flag"] = f"{spread_hits}/{n}"
    rep.stats["worst_spread"] = worst_spread
    if worst_spread > SPREAD_ERROR or spread_hits / n > 0.10:
        rep.add(ERROR, "option-spread",
                f"{spread_hits}/{n} questions have a longest/shortest label ratio above "
                f"{SPREAD_FLAG} (worst {worst_spread:.1f}x) — options are not parallel, so length "
                f"alone carries signal")

    key_lens = [len(q.key_label) for q in singles]
    dis_lens = [len(l) for q in singles for l in q.distractors]
    if key_lens and dis_lens:
        ratio = (sum(key_lens) / len(key_lens)) / max(1e-9, sum(dis_lens) / len(dis_lens))
        rep.stats["key_distractor_len_ratio"] = ratio
        if not (LEN_RATIO_ERROR[0] <= ratio <= LEN_RATIO_ERROR[1]):
            rep.add(ERROR, "length-ratio",
                    f"mean key length / mean distractor length = {ratio:.2f}, outside "
                    f"{LEN_RATIO_ERROR}")
        elif not (LEN_RATIO_WARN[0] <= ratio <= LEN_RATIO_WARN[1]):
            rep.add(WARN, "length-ratio", f"mean key/distractor length ratio {ratio:.2f} is drifting")


def m_heuristics(rep: Report) -> None:
    """Score the strategies a learner who never read the lesson would actually use.

    This is the anti-Goodhart centrepiece: it cannot be gamed by word choice
    because the metric IS the adversary's objective function. Adding a heuristic
    rescores the whole corpus for free; tuning phrasing to dodge one lexicon does
    nothing here.
    """
    singles = [q for q in rep.questions if q.single]

    def pick_longest(q): return max(range(q.k), key=lambda i: (len(q.labels[i]), -i))
    def pick_shortest(q): return min(range(q.k), key=lambda i: (len(q.labels[i]), i))

    def pick_no_absolute(q):
        free = [i for i in range(q.k) if not ABSOLUTE_RE.search(q.labels[i])]
        return free[0] if len(free) == 1 else None

    def pick_hedged(q):
        hedged = [i for i in range(q.k) if HEDGE_RE.search(q.labels[i])]
        return hedged[0] if len(hedged) == 1 else None

    def pick_prompt_overlap(q):
        pt = content_tokens(q.prompt)
        scores = [len(content_tokens(q.labels[i]) & pt) for i in range(q.k)]
        best = max(scores) if scores else 0
        return scores.index(best) if best and scores.count(best) == 1 else None

    def pick_least_similar(q):
        toks = [content_tokens(l) for l in q.labels]
        scores = [sum(jaccard(toks[i], toks[j]) for j in range(q.k) if j != i) for i in range(q.k)]
        low = min(scores) if scores else 0
        return scores.index(low) if scores and scores.count(low) == 1 else None

    suite = {
        "longest": pick_longest, "shortest": pick_shortest,
        "only-option-without-an-absolute": pick_no_absolute,
        "only-hedged-option": pick_hedged,
        "most-prompt-overlap": pick_prompt_overlap,
        "least-like-the-others": pick_least_similar,
    }

    results, thin = {}, []
    for name, fn in suite.items():
        hits = attempts = 0
        chances = []
        for q in singles:
            guess = fn(q)
            if guess is None:
                continue
            attempts += 1
            chances.append(1.0 / q.k)
            if guess == q.correct_idx[0]:
                hits += 1
        if attempts < HEURISTIC_MIN_N:
            thin.append(f"{name} (n={attempts})")
            continue
        p_null = sum(chances) / len(chances)
        p_val = binom_two_sided_p(hits, attempts, p_null)
        results[name] = {"hits": hits, "n": attempts, "rate": hits / attempts, "p": p_val}
        if hits / attempts > p_null and p_val < CHI2_P_ERROR:
            rep.add(ERROR, "content-blind",
                    f"the '{name}' strategy scores {hits}/{attempts} ({hits/attempts:.1%}) against "
                    f"{p_null:.1%} chance (exact p={p_val:.2g}) — this question set is partly "
                    f"solvable without reading the lesson")

    if thin:
        rep.inconclusive("content-blind",
                         f"{len(thin)} strategy/strategies under the floor {HEURISTIC_MIN_N}: "
                         + _sample(thin),
                         "a content-blind strategy that beats chance on this question set")
    rep.stats["heuristics"] = results
    if results:
        rep.stats["best_heuristic"] = max(r["rate"] for r in results.values())


def _rate(texts: list[str], pattern: re.Pattern) -> tuple[float, int]:
    if not texts:
        return 0.0, 0
    hits = sum(1 for t in texts if pattern.search(t))
    return hits / len(texts), hits


def m_lexical(rep: Report) -> None:
    """Hedging concentrated in keys, absolutes concentrated in distractors."""
    keys = [l for q in rep.questions for l in q.keys]
    distractors = [l for q in rep.questions for l in q.distractors]
    if not keys or not distractors:
        return

    hedge_k, hk = _rate(keys, HEDGE_RE)
    hedge_d, hd = _rate(distractors, HEDGE_RE)
    abs_k, ak = _rate(keys, ABSOLUTE_RE)
    abs_d, ad = _rate(distractors, ABSOLUTE_RE)
    rep.stats["hedge_key_rate"], rep.stats["hedge_distractor_rate"] = hedge_k, hedge_d
    rep.stats["absolutes_key_rate"], rep.stats["absolutes_distractor_rate"] = abs_k, abs_d

    if hk + hd >= 8 and hedge_d > 0:
        ratio = hedge_k / hedge_d
        rep.stats["hedge_ratio"] = ratio
        if ratio >= HEDGE_ERROR:
            rep.add(ERROR, "hedge-tell",
                    f"keys hedge {ratio:.2f}x as often as distractors ({hedge_k:.1%} vs "
                    f"{hedge_d:.1%}) — 'pick the cautious option' is a working strategy")
        elif ratio >= HEDGE_WARN:
            rep.add(WARN, "hedge-tell", f"keys hedge {ratio:.2f}x as often as distractors")
    elif hk + hd < 8:
        rep.inconclusive("hedge-tell", f"only {hk + hd} hedged label(s) course-wide, floor 8",
                         "hedging concentrated in the keys")

    if ak + ad >= 8 and abs_k > 0:
        ratio = abs_d / abs_k
        rep.stats["absolutes_ratio"] = ratio
        if ratio >= ABSOLUTES_ERROR:
            rep.add(ERROR, "absolutes-tell",
                    f"distractors carry absolutes {ratio:.2f}x as often as keys ({abs_d:.1%} vs "
                    f"{abs_k:.1%}) — 'eliminate the absolute' is a working strategy")
        elif ratio >= ABSOLUTES_WARN:
            rep.add(WARN, "absolutes-tell",
                    f"distractors carry absolutes {ratio:.2f}x as often as keys")
    elif ak + ad < 8:
        rep.inconclusive("absolutes-tell", f"only {ak + ad} absolute-carrying label(s), floor 8",
                         "absolutes concentrated in the distractors")


def m_answer_leak(rep: Report) -> None:
    """Does the key's distinguishing vocabulary appear in the lesson title or prompt?"""
    leaks = []
    for q in rep.questions:
        if not q.single:
            continue
        key_tokens = content_tokens(q.key_label)
        other = set().union(*(content_tokens(l) for l in q.distractors)) if q.distractors else set()
        unique = key_tokens - other
        if not unique:
            continue
        for where, text in (("title", q.lesson_title), ("prompt", q.prompt)):
            if len(unique & content_tokens(text)) >= 2:
                leaks.append(f"{q.lesson_slug}/{q.qid} (in {where})")
                break
    rep.stats["answer_leaks"] = len(leaks)
    if leaks:
        rep.add(WARN, "answer-leak",
                f"{len(leaks)} question(s) whose key vocabulary appears in the lesson title or "
                f"prompt: " + _sample(leaks))


def m_dedup(rep: Report) -> None:
    """Repeat-keyed facts: the same claim keyed again in a different lesson."""
    singles = [q for q in rep.questions if q.single and len(content_tokens(q.key_label)) >= 4]
    pairs = []
    for i, a in enumerate(singles):
        ta = content_tokens(a.key_label)
        for b in singles[i + 1:]:
            if a.lesson_slug == b.lesson_slug:
                continue
            if jaccard(ta, content_tokens(b.key_label)) >= DEDUP_JACCARD:
                pairs.append(f"{a.lesson_slug}/{a.qid} ~ {b.lesson_slug}/{b.qid}")
    rep.stats["repeat_keyed_pairs"] = len(pairs)
    if pairs:
        rep.add(WARN, "repeat-keyed",
                f"{len(pairs)} cross-lesson pair(s) key near-identical claims: " + _sample(pairs))


def m_emdash(rep: Report) -> None:
    """Em-dashes in quiz text.

    ERROR here, INFO in academy-courses/scripts/quiz_stats.py. That script audits
    content that already shipped; this one gates a generator, and the generator
    must not emit them at all (794 ship across six courses today). The COUNT is
    identical — only the severity differs.
    """
    hits = sum(len(EMDASH_RE.findall(t)) for q in rep.questions for t in q.texts())
    rep.stats["emdashes"] = hits
    if hits:
        rep.add(ERROR, "em-dash",
                f"{hits} em/en-dash(es) in quiz prompts, options, or explanations — the em-dash is "
                f"the top AI tell and house policy is essentially none (tools/dedash.py covers "
                f"drafts, not quiz text; fix these in the brief)")


METRICS = (m_structure, m_sequence, m_repeat, m_marginal, m_module_seed,
           m_length_rank, m_heuristics, m_lexical, m_answer_leak, m_dedup, m_emdash)


def analyse(manifest: dict) -> Report:
    slug = str((manifest.get("course") or {}).get("id", "?"))
    rep = Report(slug=slug, questions=load_questions(manifest))
    if not rep.questions:
        rep.add(WARN, "empty", "no quiz questions found")
        return rep
    for metric in METRICS:
        metric(rep)
    return rep


# ── Output ────────────────────────────────────────────────────────────────────

ICON = {ERROR: "FAIL", WARN: "warn", INFO: "info"}


def render(rep: Report) -> str:
    s = rep.stats
    lines = [f"-- {rep.slug} " + "-" * max(0, 66 - len(rep.slug))]
    counts = ", ".join(f"{k}-option x{v}" for k, v in sorted(s.get("option_counts", {}).items()))
    lines.append(f"   {s.get('questions', 0)} questions ({counts}); "
                 f"{s.get('single_select', 0)} single-select, {s.get('multiselect', 0)} multiSelect")
    if "acc1" in s:
        lines.append(f"   predictability   constant {s.get('acc0', 0):.1%} | "
                     f"order-1 {s['acc1']:.1%} (p={s.get('p_acc1', 1):.3f}) | "
                     f"order-2 {s.get('acc2', 0):.1%} (p={s.get('p_acc2', 1):.3f})")
    if "repeat_rate" in s:
        lines.append(f"   slot repeats     {s['repeat_rate']} (p={s.get('p_repeat', 1):.2g}, "
                     f"power vs never-repeats {s.get('repeat_power', 0):.0%})")
    if "longest_correct" in s:
        lines.append(f"   length tells     longest {s['longest_correct']:.1%} | "
                     f"shortest {s.get('shortest_correct', 0):.1%} | "
                     f"chance {s.get('chance', 0):.1%} | "
                     f"key/distractor {s.get('key_distractor_len_ratio', 0):.2f} | "
                     f"worst spread {s.get('worst_spread', 0):.1f}x")
    if s.get("length_rank"):
        rank = "; ".join(f"k={k}: {v}" for k, v in s["length_rank"].items())
        lines.append(f"   key length rank  {rank}   (shortest->longest)")
    if s.get("heuristics"):
        best = max(s["heuristics"].items(), key=lambda kv: kv[1]["rate"])
        lines.append(f"   content-blind    best strategy '{best[0]}' scores {best[1]['rate']:.1%} "
                     f"({best[1]['hits']}/{best[1]['n']}, p={best[1]['p']:.2g})")
    if "hedge_ratio" in s or "absolutes_ratio" in s:
        lines.append(f"   lexical tells    hedge {s.get('hedge_ratio', float('nan')):.2f}x | "
                     f"absolutes {s.get('absolutes_ratio', float('nan')):.2f}x")
    if s.get("position_distribution"):
        pos = "; ".join(f"k={k}: {v}" for k, v in s["position_distribution"].items())
        lines.append(f"   key positions    {pos}")
    if "module_seed_hits" in s:
        lines.append(f"   module seed      {s['module_seed_hits']} lessons open on (module index mod k)")
    if s.get("emdashes"):
        lines.append(f"   em-dashes        {s['emdashes']} in quiz text")

    order = {ERROR: 0, WARN: 1, INFO: 2}
    for f in sorted(rep.findings, key=lambda f: order[f.severity]):
        lines.append(f"   [{ICON[f.severity]}] {f.metric}: {f.message}")
    lines.append(f"   => {'FAIL' if rep.failed else 'pass'}")
    return "\n".join(lines)


# ── Selftest ──────────────────────────────────────────────────────────────────

def _h(*parts) -> int:
    import hashlib
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16)


def _fair_label(i: int, o: int) -> str:
    """A parallel option label whose LENGTH is a function of (question, slot) only —
    never of correctness. Fixtures must not accidentally encode a length tell."""
    base = ("the account's rent-exempt minimum is recomputed from its data length "
            "and charged to the payer at creation")
    return base[: 76 + _h("len", i, o) % 34]


def _mk(seq, k=5, *, labels=None, per_lesson=3, multi=False, feedback=True,
        explanation="a paragraph that teaches the point after answering", module_of=None):
    """Build a manifest whose single-select key positions are exactly `seq`."""
    labels = labels or _fair_label
    lessons, modules = [], []
    n_lessons = max(1, (len(seq) + per_lesson - 1) // per_lesson)
    for li in range(n_lessons):
        mi = module_of(li) if module_of else li
        mid = f"m{mi}"
        if not any(x["id"] == mid for x in modules):
            modules.append({"id": mid})
        qs = []
        for j in range(per_lesson):
            idx = li * per_lesson + j
            if idx >= len(seq):
                break
            correct = seq[idx]
            opts = []
            for oi in range(k):
                o = {"id": f"o{oi + 1}", "label": labels(idx, oi), "correct": oi == correct}
                if feedback:
                    o["feedback"] = "why this option lands where it does"
                opts.append(o)
            q = {"id": f"q{j + 1}", "prompt": f"prompt {idx} asking something specific",
                 "multiSelect": multi, "options": opts}
            if explanation:
                q["explanation"] = explanation
            qs.append(q)
        lessons.append({"id": f"l{li}", "module": mid, "order": 1,
                        "brief": {"title": f"Lesson {li}", "quiz_blocks": [{"key": "check",
                                                                            "questions": qs}]}})
    return {"course": {"id": "fixture"}, "modules": modules, "lessons": lessons}


def selftest() -> int:
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("PASS - " if cond else "FAIL - ") + msg)
        ok = ok and bool(cond)

    # ── statistics primitives ──
    chk(abs(chi2_sf(0.0, 3) - 1.0) < 1e-12, "chi2_sf(0) == 1")
    chk(abs(chi2_sf(3.84146, 1) - 0.05) < 1e-4, "chi2_sf matches the 1-df 5% point")
    chk(abs(chi2_sf(11.3449, 3) - 0.01) < 1e-4, "chi2_sf matches the 3-df 1% point")
    c, df, p = chi2_uniform([10, 10, 10])
    chk(c == 0.0 and df == 2 and abs(p - 1.0) < 1e-12, "perfectly flat counts -> chi2 0, p 1")
    chk(chi2_uniform([30, 0, 0])[2] < 1e-6, "all-one-slot counts -> p ~ 0")

    chk(abs(sum(binom_pmf(i, 10, 0.3) for i in range(11)) - 1.0) < 1e-12, "binomial pmf sums to 1")
    chk(abs(binom_two_sided_p(5, 10, 0.5) - 1.0) < 1e-9, "exact binomial at the mode -> p 1")
    chk(binom_two_sided_p(0, 20, 1 / 3) < 0.001, "0/20 repeats at 1/3 chance is significant")
    chk(binom_two_sided_p(20, 20, 1 / 3) < 1e-6, "20/20 at 1/3 chance is significant")
    lo, hi = binom_accept_region(20, 1 / 3, 0.001)
    chk(lo > 0, "the acceptance region at n=20 excludes 0 (the never-repeats point mass)")
    chk(power_against(20, 1 / 3, 0.0, 0.001) > 0.99, "n=20 has power against never-repeats")
    chk(power_against(4, 1 / 3, 0.0, 0.001) < 0.5, "n=4 does not — hence the sample floor")

    chk(markov_accuracy([0, 0, 0, 1], 0) == 0.75, "order-0 accuracy is the modal rate")
    chk(markov_accuracy([0, 1, 2, 0, 1, 2, 0, 1, 2], 1) == 1.0, "a rotation is order-1 perfect")
    chk(markov_accuracy([], 0) is None and markov_accuracy([0], 1) is None, "short sequences -> None")
    _, p_rot = permutation_p([0, 1, 2] * 8, 1)
    chk(p_rot is not None and p_rot <= MARKOV_P_ERROR, "permutation null rejects a rotation")

    # ── the three regression fixtures ──
    # This is the regression test for the whole workstream. FIXTURE 1 is the exact
    # artifact `_briefs_emit.wf.js` asked for and the old gate waved through.
    rot = analyse(_mk([i % 3 for i in range(60)]))
    chk(rot.failed, "FIXTURE 1: a perfect a->b->c rotation FAILS")
    chk(any(f.metric == "sequence" for f in rot.findings if f.severity == ERROR),
        "FIXTURE 1: on sequential exploitability")
    chk(any(f.metric == "repeat-rate" for f in rot.findings if f.severity == ERROR),
        "FIXTURE 1: and on the never-repeats slot rate")
    # ... and a rotation whose MARGINAL is flawless still fails, proving the
    # marginal is not what is doing the work.
    rot5 = analyse(_mk([i % 5 for i in range(60)]))
    chk(rot5.failed and any(f.metric in ("sequence", "repeat-rate")
                            for f in rot5.findings if f.severity == ERROR),
        "FIXTURE 1b: a full-cycle rotation with a PERFECT marginal still FAILS")

    one = analyse(_mk([0] * 60))
    chk(one.failed, "FIXTURE 2: an all-one-slot sequence FAILS")
    chk(any(f.metric == "marginal" for f in one.findings if f.severity == ERROR),
        "FIXTURE 2: it fails on the marginal")

    hashed = [_h("fixture", i) % 5 for i in range(60)]
    good = analyse(_mk(hashed))
    chk(not good.failed, "FIXTURE 3: a hash-balanced sequence PASSES\n"
        + "\n".join(f"      {f.severity}/{f.metric}: {f.message}" for f in good.findings
                    if f.severity == ERROR))

    # ── structure policy ──
    chk(any(f.metric == "option-count" for f in analyse(_mk(hashed, k=3)).findings),
        "3 options -> option-count ERROR")
    short = analyse(_mk([h % 4 for h in hashed], k=4,
                        labels=lambda i, o: f"a short parallel label {o}"))
    chk(any("must carry 5 options" in f.message for f in short.findings),
        "short labels with k=4 -> must carry 5 options")
    nofb = analyse(_mk(hashed, feedback=False))
    chk(any(f.metric == "feedback" and f.severity == ERROR for f in nofb.findings),
        "missing feedback -> ERROR (every option, correct one included)")
    noex = analyse(_mk(hashed, explanation=""))
    chk(any(f.metric == "explanation" and f.severity == ERROR for f in noex.findings),
        "missing explanation -> ERROR")

    # ── em-dash ──
    em = _mk(hashed)
    em["lessons"][0]["brief"]["quiz_blocks"][0]["questions"][0]["prompt"] = "a — dash"
    chk(any(f.metric == "em-dash" and f.severity == ERROR for f in analyse(em).findings),
        "an em-dash in quiz text -> ERROR")

    # ── length tells ──
    longkey = analyse(_mk(hashed, labels=lambda i, o: (
        _fair_label(i, o) + " and it keeps going with a further clarifying clause"
        if o == hashed[i] else _fair_label(i, o)[:70])))
    chk(any(f.metric == "longest-correct" and f.severity == ERROR for f in longkey.findings),
        "correct-is-longest -> ERROR (advisory in the old gate)")
    shortkey = analyse(_mk(hashed, labels=lambda i, o: (
        "the payer" if o == hashed[i] else _fair_label(i, o))))
    chk(any(f.metric == "shortest-correct" and f.severity == ERROR for f in shortkey.findings),
        "correct-is-shortest -> ERROR (invisible to a longest-only check)")

    # ── module seed: first key = module index mod k ──
    seeded = []
    for li in range(12):
        seeded += [li % 5, _h("s", li, 0) % 5, _h("s", li, 1) % 5]
    seed_rep = analyse(_mk(seeded, per_lesson=3, module_of=lambda li: li))
    chk(any(f.metric == "module-seed" and f.severity == ERROR for f in seed_rep.findings),
        "first key seeded from the module index -> ERROR")

    # ── the small-sample rule: below the floor is INCONCLUSIVE, never a silent pass ──
    tiny = analyse(_mk([0, 0], per_lesson=2))
    inc = [f for f in tiny.findings if "INCONCLUSIVE, not passed" in f.message]
    chk({f.metric for f in inc} >= {"sequence", "repeat-rate", "marginal", "module-seed",
                                    "length-rank", "content-blind", "longest-correct"},
        "every below-floor distributional metric says INCONCLUSIVE, not passed "
        f"(got {sorted({f.metric for f in inc})})")
    chk(all("Cannot rule out:" in f.message for f in inc),
        "each INCONCLUSIVE names what it could not rule out")

    # ── multiSelect shape ──
    chk(any(f.metric == "multiselect-shape" for f in analyse(_mk(hashed, k=4, multi=True)).findings),
        "multiSelect with k=4 and 1 correct -> shape ERROR")

    # ── address 4-tuple: question ids are not unique within a course ──
    dup = _mk(hashed)
    addrs = [q.address for q in load_questions(dup)]
    qids = [q.qid for q in load_questions(dup)]
    chk(len(set(qids)) < len(qids), "the fixture reproduces non-unique question ids")
    chk(len(set(addrs)) == len(addrs), "the 4-tuple address is still unique")

    print("\n" + ("QUIZ_METRICS SELFTESTS PASSED" if ok else "QUIZ_METRICS SELFTESTS FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Statistical metrics for a course's quiz layer.")
    ap.add_argument("--course", help="course directory (reads manifest.json)")
    ap.add_argument("--manifest", help="manifest.json path")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    src = a.course or a.manifest
    if not src:
        ap.print_help()
        return 2
    from pathlib import Path
    p = Path(src)
    if p.is_dir():
        p = p / "manifest.json"
    if not p.is_file():
        print(f"quiz_metrics: no manifest at {p}", file=sys.stderr)
        return 2
    rep = analyse(json.loads(p.read_text("utf-8")))
    if a.json:
        print(json.dumps({"course": rep.slug, "failed": rep.failed, "stats": rep.stats,
                          "findings": [{"severity": f.severity, "metric": f.metric,
                                        "message": f.message} for f in rep.findings]}, indent=2))
    else:
        print(render(rep))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
