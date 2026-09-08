#!/usr/bin/env python3
"""render_visuals.py — turn a piece's ```visual specs into on-brand images.

The skill writes text + ` ```visual ` placeholder specs (type/title/purpose/data/prompt/
alt). This renders each spec the Claude-Design way: an AGENT writes on-brand HTML/CSS
(guided by references/visual-rendering.md + brand/brand-guide.md), and this tool wraps it
against the shipped brand stylesheet and renders it deterministically through **WeasyPrint**
(HTML/CSS → vector PDF) then rasterizes to PNG — no browser.

Split (mirrors verify_code): Python does the deterministic scaffolding + render; the model
does the creative HTML authoring in between.

    render_visuals.py extract  <course|--file X>   # the work-list: what to build
    render_visuals.py scaffold <course>            # write brand-linked <asset>.html starters
    #   ... agent fills each <asset>.html's .viz with on-brand markup ...
    render_visuals.py render   <course> [--dpi N]  # weasyprint -> PDF -> PNG (SKIP if absent)
    render_visuals.py check    <course>            # rendered vs unrendered report
    render_visuals.py banner   <course>            # STANDARD banner -> branding/banner.webp
    render_visuals.py scaffold-banner <course>     # LEGACY composed-banner starter
    render_visuals.py render-banner   <course>     # LEGACY composed banner -> banner.{png,webp}
    render_visuals.py --selftest

Assets land beside the lessons in `lessons/assets/<lesson-stem>/v<NN>-<type>.{html,pdf,png}`
(gitignored with the course). A FAIL is a real render error; SKIP = WeasyPrint/rasterizer
absent (install: `pip install weasyprint` + a rasterizer, or `pip install pymupdf`).

The COURSE BANNER is the one course-level visual: the Academy card thumbnail
(references/banner.md). It lives in `content/courses/<id>/branding/`.

  STANDARD (`banner`, since 2026-09): the course art, cover-cropped to 1600x900, with
  the Superteam mark composited into the top-right corner and NOTHING else. Pillow only
  — no WeasyPrint, no HTML to author, no title burned into the thumbnail (the Academy
  card already prints the title beside the image, so a second copy inside it was
  duplicated, and it was the part that went stale when a course was retitled).

  LEGACY (`scaffold-banner` + `render-banner`): the composed title card — authored HTML
  through WeasyPrint, cream card over a pre-blurred photo, title and level/lesson/XP
  pills. Kept working for courses whose banner is already authored that way.

Both write `branding/banner.webp` (1600x900, <=1 MiB), which academy_export.py ships as
the course `thumbnail:`.
"""
from __future__ import annotations
import argparse
import hashlib
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate_course import _parse_visuals   # noqa: E402  (reuse the canonical parser)

SKILL = HERE.parent                          # skills/content-gen
BRAND_CSS = SKILL / "brand" / "styles.css"
RENDER_CSS = SKILL / "brand" / "render.css"
CANVAS = (1600, 900)


def _slug(s: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in str(s).lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "x"


# ---- brand background decoration ---------------------------------------------
# Each visual gets two brand-colour blobs bled off two different borders, drawn as CSS
# border-radius shapes. A border-radius div FILLS its box, so a crop is always a solid,
# smooth mound — unlike the SVG morphs, whose transparent padding cropped to invisible
# slivers. Deterministic per asset_id so renders stay reproducible; content = the spec.
# Matches the whole decor layer up to the `.viz` content that follows it. Spans the
# wrapper AND its nested blob <div>s (and any orphans from older runs), so re-decorate
# fully replaces it — a `</div>`-only match would stop at the first blob and leak the rest.
_DECOR_RE = re.compile(r'<div class="stbr-decor".*?(?=<div class="viz")', re.DOTALL)
# The scaffold embeds the block spec in an HTML comment after <body>. If the spec's data
# holds "-->" (ASCII arrows), that comment closes early and the tail leaks as visible text.
# Strip the whole spec comment before rendering (source of truth is the draft's ```visual).
_SPEC_COMMENT_RE = re.compile(r'(<body>)\s*<!--.*?(?=<div class="(?:stbr-decor|viz)")', re.DOTALL)


def _strip_spec(html: str) -> str:
    return _SPEC_COMMENT_RE.sub(r"\1\n", html, count=1)


def _safe_area_html(html: str) -> str:
    """Top-align the card instead of vertically centering it. Content taller than the ~756px safe
    area (900px canvas − 2×72px padding) is clipped by the centered page yet stays ONE page — so
    the page-count overflow check can't see it; top-aligned, that same overflow spills to a 2nd
    page and becomes detectable. This is how a clipped last row/line slips past `render`."""
    return _strip_spec(html).replace("align-items: center", "align-items: flex-start", 1)


# CSS the authored `.viz` must never contain (WeasyPrint drops or mis-renders these).
# display:contents is silently ignored — a grid/flex child relying on it lands wrong
# (collapsed cells, a title shoved off the top); make every cell a real direct child.
_FORBIDDEN_CSS = ("box-shadow", "background-image:url(", "background-image: url(",
                  "font-stretch", "position:fixed", "position: fixed",
                  "display:contents", "display: contents")

# Any HTML comment. Used to test what the page actually RENDERS: authoring notes name
# the very constructs they warn against, so a raw substring scan flags its own prose.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _viz_inner(html: str) -> str:
    """The authored `.viz` content (so lint checks the author's CSS, not the head/decor)."""
    m = re.search(r'<div class="viz">(.*?)</div>\s*</body>', html, re.DOTALL)
    return m.group(1) if m else ""


def _pdf_pages(pdf: Path) -> int:
    """Page count of a rendered PDF. WeasyPrint emits >1 page when the visual overflows the
    1600x900 canvas — the single most reliable automated glitch signal."""
    if shutil.which("pdfinfo"):
        r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True)
        m = re.search(r"^Pages:\s*(\d+)", r.stdout, re.MULTILINE)
        if m:
            return int(m.group(1))
    try:                                            # fallback: count Page objects in the raw PDF
        return len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes())) or 1
    except OSError:
        return 1


def _render_pdf(it) -> tuple[bool, str]:
    """Render one asset's HTML (spec comment stripped) to its `.pdf`. Returns (ok, stderr)."""
    tmp = it["html"].parent / (it["html"].stem + ".__render.html")
    tmp.write_text(_strip_spec(it["html"].read_text("utf-8")))
    r = subprocess.run(["weasyprint", str(tmp), str(it["pdf"])], capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    return (r.returncode == 0 and it["pdf"].exists()), (r.stderr or "").strip()


def _safe_area_overflow(it) -> bool:
    """True if the card's content is taller than the ~756px safe area — a within-page vertical clip
    (the last row/line cut off) that the normal 1-page check misses because the card is centered.
    Render top-aligned and count pages: >1 means the content overran the safe area."""
    tmp = it["html"].parent / (it["html"].stem + ".__safe.html")
    pdf = it["html"].parent / (it["html"].stem + ".__safe.pdf")
    tmp.write_text(_safe_area_html(it["html"].read_text("utf-8")))
    r = subprocess.run(["weasyprint", str(tmp), str(pdf)], capture_output=True, text=True)
    tmp.unlink(missing_ok=True)
    n = _pdf_pages(pdf) if (r.returncode == 0 and pdf.exists()) else 1
    pdf.unlink(missing_ok=True)
    return n > 1


def _radius(rng) -> str:
    """An organic, asymmetric border-radius: 8 values (4 horizontal / 4 vertical)."""
    v = [rng.randint(35, 65) for _ in range(8)]
    return f"{v[0]}% {v[1]}% {v[2]}% {v[3]}% / {v[4]}% {v[5]}% {v[6]}% {v[7]}%"


# Fill opacity, eased off full saturation. Yellow reads much fainter than green on
# cream (luminance-close), so it gets more to stay legible as the sparing accent.
_GREEN_OPACITY = 0.50
_YELLOW_OPACITY = 0.80


def _fill_opacity(fill: str) -> float:
    return _YELLOW_OPACITY if fill == "#ffd23f" else _GREEN_OPACITY


# Border anchors on a coarse (col L/C/R, row T/M/B) grid. Corners bleed off BOTH edges;
# edge-mids bleed off ONE and centre along it. Excluded: top-centre / top-left (eyebrow +
# title) and dead-centre (content) — so every anchor stays clear of where content lives.
_ANCHORS = {"tr": ("R", "T"), "br": ("R", "B"), "bl": ("L", "B"),
            "bc": ("C", "B"), "lm": ("L", "M"), "rm": ("R", "M")}
# A lone blob reads best in a corner; pairs go diagonally opposite (opposite on BOTH
# axes, for balance); triples spread across rows and side columns.
_SINGLES = ["tr", "br", "bl", "tr", "br", "bl", "rm", "bc"]
_PAIRS = [("tr", "bl"), ("tr", "lm"), ("tr", "bc"), ("rm", "bl"), ("rm", "bc"), ("br", "lm")]
# Triangles across three regions. Avoid pairing top-right (tr) with right-mid (rm) —
# adjacent on the right edge, they merge into one blob rather than reading as two.
_TRIPLES = [("tr", "lm", "bc"), ("tr", "bl", "br"), ("tr", "bl", "bc"), ("tr", "lm", "br")]


def _density_n(html: str) -> int:
    """Choose 1-3 blobs from the authored `.viz` text density: dense → 1 (keep a busy
    slide calm), sparse → 3, most land at 2. Style/comments are stripped so only the
    visible text counts."""
    m = re.search(r'<div class="viz">(.*?)</div>\s*</body>', html, re.DOTALL)
    viz = m.group(1) if m else ""
    viz = re.sub(r"<style.*?</style>", "", viz, flags=re.DOTALL)
    viz = re.sub(r"<!--.*?-->", "", viz, flags=re.DOTALL)
    text_len = len(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", viz)).strip())
    return 1 if text_len > 600 else 3 if text_len < 345 else 2


def _blob(rng, anchor, fill, opacity) -> str:
    """One brand-colour CSS blob bled off a border at `anchor`. A border-radius div FILLS
    its box, so the visible part is always a solid, smooth mound — no empty-padding
    slivers. Corner anchors bleed off both edges; edge-mids bleed off one and centre
    along it. Kept compact, clear of the centre content, behind everything (z-index 0)."""
    col, row = _ANCHORS[anchor]
    over = rng.randint(220, 340)                         # how much bleeds off the border
    if col in ("L", "R") and row in ("T", "B"):          # corner — bleed off both edges
        w = rng.randint(205, 290) + over
        h = rng.randint(180, 265) + over
        xside = "right" if col == "R" else "left"
        yside = "top" if row == "T" else "bottom"
        pos = f"{yside}:-{over}px;{xside}:-{over}px;"
    elif col == "C":                                     # bottom-centre — bleed off the horizontal edge
        w = rng.randint(360, 540)                        # span along the edge
        h = rng.randint(175, 250) + over
        yside = "top" if row == "T" else "bottom"
        left = round(CANVAS[0] * rng.uniform(0.36, 0.64) - w / 2)
        pos = f"{yside}:-{over}px;left:{left}px;"
    else:                                                # left/right-middle — bleed off the vertical edge
        w = rng.randint(175, 250) + over
        h = rng.randint(340, 520)                        # span along the edge
        xside = "right" if col == "R" else "left"
        top = round(CANVAS[1] * rng.uniform(0.34, 0.66) - h / 2)
        pos = f"{xside}:-{over}px;top:{top}px;"
    return (f'<div style="position:absolute;width:{w}px;height:{h}px;'
            f'{pos}border-radius:{_radius(rng)};background:{fill};opacity:{opacity};"></div>')


def _decor(asset_id: str, n: int = 2) -> str:
    """A unique <div class="stbr-decor"> layer for this asset: `n` (1-3) brand-colour
    blobs bled off the borders (corners AND edge-midpoints) as smooth mounds behind
    content. n=2 places them diagonally opposite for balance; n=3 spreads them. Varied
    per asset by anchor / position / size / shape / fill. Deterministic from asset_id."""
    n = max(1, min(3, n))
    rng = random.Random(int(hashlib.sha256(asset_id.encode("utf-8")).hexdigest()[:16], 16))
    if n == 1:
        anchors = [rng.choice(_SINGLES)]
    elif n == 2:
        anchors = list(rng.choice(_PAIRS))               # opposite on both x and y (balance)
    else:
        anchors = list(rng.choice(_TRIPLES))             # spread across the borders
    colors = ["#008b4c", "#306c40"]                      # emerald + green by default
    rng.shuffle(colors)
    while len(colors) < n:                               # extend for a 3rd blob
        colors.append(rng.choice(("#008b4c", "#306c40")))
    colors = colors[:n]
    if rng.random() < 0.30:                              # yellow is the sparing accent
        colors[rng.randrange(n)] = "#ffd23f"
    blobs = [_blob(rng, a, c, _fill_opacity(c)) for a, c in zip(anchors, colors)]
    return '<div class="stbr-decor" aria-hidden="true">\n  ' + "\n  ".join(blobs) + "\n</div>\n"


def work_list(course_dir: Path):
    """Every visual block across the course's drafts, as render work items."""
    drafts = course_dir / "lessons" / "drafts"
    items = []
    for draft in sorted(drafts.glob("*.md")):
        blocks, _ = _parse_visuals(draft.read_text("utf-8"))
        for i, b in enumerate(blocks, 1):
            f = b["fields"]
            vtype = _slug(f.get("type", "diagram"))
            asset_id = f"{draft.stem}/v{i:02d}-{vtype}"
            base = course_dir / "lessons" / "assets" / f"{draft.stem}" / f"v{i:02d}-{vtype}"
            items.append({
                "lesson": draft.stem, "idx": i, "type": f.get("type", ""),
                "title": f.get("title", ""), "purpose": f.get("purpose", ""),
                "data": f.get("data", ""), "prompt": f.get("prompt", ""),
                "alt": f.get("alt", ""), "asset_id": asset_id,
                "html": base.with_suffix(".html"), "pdf": base.with_suffix(".pdf"),
                "png": base.with_suffix(".png"),
            })
    return items


_STARTER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="{css}">
<link rel="stylesheet" href="{render_css}">
<style>
  @page {{ size: {w}px {h}px; margin: 0; }}
  html, body {{ margin: 0; }}
  body {{ width: {w}px; height: {h}px; display: flex; align-items: center;
         justify-content: center; background: var(--surface-page); padding: 72px; }}
  .viz {{ position: relative; width: 100%; }}
</style></head>
<body>
<!-- {type}: {title}
     purpose: {purpose}
     data: {data}
     prompt: {prompt}
     BUILD .viz as on-brand HTML per skills/content-gen/references/visual-rendering.md.
     Header: <div class="stbr-eyebrow">..</div> + <h2 class="viz-title">..</h2>.
     Leave the .stbr-decor block untouched (per-asset brand decoration).
     WeasyPrint-safe CSS only: flexbox/grid/borders/gradients; NO box-shadow, NO
     background-image url(), NO JS. Use brand tokens (--surface-*, --text-*, --stbr-*). -->
{decor}<div class="viz">
  <!-- TODO(render): build this visual -->
</div>
</body></html>
"""


def cmd_scaffold(course_dir: Path) -> int:
    items = work_list(course_dir)
    assets = course_dir / "lessons" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    # shared copies of the brand + render stylesheets, linked relatively (portable)
    local_css = assets / "_brand.css"
    if BRAND_CSS.is_file():
        local_css.write_text(BRAND_CSS.read_text("utf-8"))
    local_render = assets / "_render.css"
    if RENDER_CSS.is_file():
        local_render.write_text(RENDER_CSS.read_text("utf-8"))
    written = kept = 0
    for it in items:
        it["html"].parent.mkdir(parents=True, exist_ok=True)
        if it["html"].exists() and it["html"].read_text("utf-8").count("TODO(render)") == 0:
            kept += 1                                    # already filled by the agent, don't clobber
            continue
        def sc(v):                                       # keep "-->" out of the spec comment
            return str(v).replace("-->", "->")
        it["html"].write_text(_STARTER.format(
            css=_rel(it["html"], local_css), render_css=_rel(it["html"], local_render),
            decor=_decor(it["asset_id"]), w=CANVAS[0], h=CANVAS[1],
            type=sc(it["type"]), title=sc(it["title"]),
            purpose=sc(it["purpose"]), data=sc(it["data"]), prompt=sc(it["prompt"])))
        written += 1
    print(f"scaffold: {written} starter(s) written, {kept} filled asset(s) kept "
          f"({len(items)} visual blocks total) -> {assets}")
    return 0


def cmd_decorate(course_dir: Path) -> int:
    """(Re)apply the per-asset morph decoration to every asset HTML — refreshes the
    _render.css link + swaps in each asset's unique .stbr-decor block. Idempotent:
    the block is a stable function of asset_id. Use to retrofit already-authored
    visuals or re-roll the look after tuning render.css / _decor()."""
    assets = course_dir / "lessons" / "assets"
    if RENDER_CSS.is_file():
        (assets / "_render.css").write_text(RENDER_CSS.read_text("utf-8"))
    changed = 0
    for it in work_list(course_dir):
        h = it["html"]
        if not h.exists():
            continue
        s = h.read_text("utf-8")
        if "_render.css" not in s:
            s = s.replace('<link rel="stylesheet" href="../_brand.css">',
                          '<link rel="stylesheet" href="../_brand.css">\n'
                          '<link rel="stylesheet" href="../_render.css">', 1)
        block = _decor(it["asset_id"], _density_n(s))    # 1-3 blobs by content density
        s = (_DECOR_RE.sub(block, s, count=1) if 'class="stbr-decor"' in s
             else s.replace('<div class="viz">', block + '<div class="viz">', 1))
        h.write_text(s)
        changed += 1
    print(f"decorate: {changed} asset(s) given unique border decoration -> {assets}")
    return 0


def _rel(html: Path, css: Path) -> str:
    import os
    return os.path.relpath(css, html.parent)


def _rasterize(pdf: Path, png: Path, dpi: int) -> tuple[bool, str]:
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(pdf))
        doc[0].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False).save(str(png))
        doc.close()
        return True, "pymupdf"
    except ModuleNotFoundError:
        pass
    if shutil.which("pdftoppm"):
        r = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile",
                            str(pdf), str(png.with_suffix(""))],
                           capture_output=True, text=True)
        return (r.returncode == 0 and png.exists()), "pdftoppm"
    if shutil.which("mutool"):
        r = subprocess.run(["mutool", "draw", "-r", str(dpi), "-o", str(png), str(pdf), "1"],
                           capture_output=True, text=True)
        return (r.returncode == 0 and png.exists()), "mutool"
    return False, "no-rasterizer"


def cmd_render(course_dir: Path, dpi: int, only: str | None) -> int:
    if not shutil.which("weasyprint"):
        print("render: SKIP - weasyprint not installed "
              "(`pip install weasyprint`; needs pango/cairo). No images produced.", file=sys.stderr)
        return 0
    items = [it for it in work_list(course_dir) if not only or only in it["asset_id"]]
    todo = [it for it in items if it["html"].exists()
            and "TODO(render)" not in it["html"].read_text("utf-8")]
    skipped = len(items) - len(todo)
    ok = fail = 0
    for it in todo:
        ok_pdf, err = _render_pdf(it)
        if not ok_pdf:
            fail += 1
            print(f"  FAIL {it['asset_id']}: {(err.splitlines()[-1][:80] if err else 'weasyprint error')}")
            continue
        pages = _pdf_pages(it["pdf"])
        if pages > 1:                                  # content overflowed the 1600x900 canvas
            fail += 1
            it["pdf"].unlink(missing_ok=True)
            print(f"  FAIL {it['asset_id']}: overflow — spans {pages} pages (must fit one 1600x900 page)")
            continue
        rok, how = _rasterize(it["pdf"], it["png"], dpi)
        it["pdf"].unlink(missing_ok=True)              # PDF is a throwaway intermediate; keep only .png (+ .html)
        if rok:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {it['asset_id']}: rasterize failed ({how})")
    print(f"render: {ok} PNG · {fail} FAIL · {skipped} not-yet-authored (still a TODO starter) "
          f"[dpi={dpi}]")
    return 1 if fail else 0


def cmd_review(course_dir: Path, only: str | None = None) -> int:
    """Deterministic QA pass over authored cards: page-overflow, within-page clip (content taller
    than the ~756px safe area — vertical centering hides it from the page count), and forbidden-CSS
    lint. This is the automated backstop; it catches the overflow + clipped-edge classes. Internal
    overlaps, misaligned or out-of-bounds components, malformed borders, unanchored connectors, and
    low contrast are NOT statically detectable — a reviewer must VIEW each PNG per visual-review.md."""
    # `--only` matters here as much as it does for render: this pass re-renders a PDF per card,
    # so a whole course is ~50 min and a per-lesson reviewer cannot wait for it. Without the
    # filter the flag was silently ignored and the sweep re-scanned all 244 cards.
    items = [it for it in work_list(course_dir)
             if (not only or only in it["asset_id"])
             and it["html"].exists() and "TODO(render)" not in it["html"].read_text("utf-8")]
    have_wp = bool(shutil.which("weasyprint"))
    if not have_wp:
        print("review: weasyprint absent — running CSS lint only (no overflow check).", file=sys.stderr)
    flagged = 0
    for it in items:
        issues = []
        viz = _viz_inner(it["html"].read_text("utf-8"))
        issues += [f"forbidden-css:{b}" for b in _FORBIDDEN_CSS if b in viz]
        if have_wp:
            ok_pdf, err = _render_pdf(it)
            if not ok_pdf:
                issues.append("render-error")
            else:
                p = _pdf_pages(it["pdf"])
                it["pdf"].unlink(missing_ok=True)
                if p > 1:
                    issues.append(f"overflow:{p}pages")
                elif _safe_area_overflow(it):
                    issues.append("clipped:content taller than the 756px safe area (last row/line cut)")
        if issues:
            flagged += 1
            print(f"  FLAG {it['asset_id']}: {', '.join(issues)}")
    print(f"\nreview (static): {flagged}/{len(items)} card(s) flagged. Overlap / misalignment / "
          f"out-of-bounds / contrast need the VISUAL pass — see references/visual-review.md.")
    return 1 if flagged else 0


def cmd_extract(course_dir: Path, file: str | None) -> int:
    items = work_list(course_dir) if not file else _file_items(Path(file))
    print(f"{'asset_id':46} {'type':14} title")
    for it in items:
        print(f"{it['asset_id']:46} {it['type']:14} {it['title'][:60]}")
    print(f"\n{len(items)} visual block(s). Next: `scaffold`, author each .viz, then `render`.")
    return 0


def _file_items(md: Path):
    blocks, _ = _parse_visuals(md.read_text("utf-8"))
    out = []
    for i, b in enumerate(blocks, 1):
        f = b["fields"]
        out.append({"asset_id": f"{md.stem}/v{i:02d}-{_slug(f.get('type', 'x'))}",
                    "type": f.get("type", ""), "title": f.get("title", "")})
    return out


def cmd_check(course_dir: Path) -> int:
    items = work_list(course_dir)
    by_lesson: dict[str, list] = {}
    for it in items:
        by_lesson.setdefault(it["lesson"], []).append(it)
    total = done = 0
    for lesson, its in sorted(by_lesson.items()):
        rendered = sum(1 for it in its if it["png"].exists())
        total += len(its); done += rendered
        mark = "ok " if rendered == len(its) else "-- "
        print(f"  {mark}{lesson}: {rendered}/{len(its)} rendered")
    print(f"\ncheck: {done}/{total} visuals rendered across {len(by_lesson)} lessons")
    return 0


# ---- course banner (the one course-level visual: the Academy thumbnail) -------
# Upstream contract (solanabr/academy-courses → superteam-academy compile):
# `thumbnail:` is a course-relative path under a course-level assets/ dir, formats
# png/jpg/jpeg/webp/svg, HARD 1 MiB per-file cap, card displays it at 400x225 (16:9).

_BANNER_BG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_BANNER_CAP = 1 << 20                                # 1 MiB upstream per-asset cap


def _banner_paths(course_dir: Path) -> dict:
    b = course_dir / "branding"
    bg = next((b / f"banner-bg{e}" for e in _BANNER_BG_EXTS
               if (b / f"banner-bg{e}").is_file()), None)
    return {"dir": b, "html": b / "banner.html", "pdf": b / "banner.pdf",
            "png": b / "banner.png", "webp": b / "banner.webp",
            "blur": b / "banner-bg-blur.png", "bg": bg,
            "asset_id": f"{course_dir.name}/banner"}


def _cover_crop(im, size: tuple[int, int]):
    """Scale to cover `size`, then centre-crop: the canvas fills, the aspect never
    distorts, and the subject stays centred."""
    from PIL import Image
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    im = im.resize((max(tw, round(im.width * scale)), max(th, round(im.height * scale))),
                   Image.LANCZOS)
    left, top = (im.width - tw) // 2, (im.height - th) // 2
    return im.crop((left, top, left + tw, top + th))


# ---- the STANDARD banner: the art, plus the mark, top-right -------------------
# House standard since 2026-09. The banner adds exactly ONE thing to the course art:
# the Superteam horizontal mark in the top-right corner. No title, no pills, no scrim.
# The Academy card already prints the title, level, lesson count and XP beside the
# image from course.yaml, so burning a second copy into the thumbnail duplicated them
# — and the burnt-in copy is the one that went stale when a course was retitled or
# re-priced, because nothing recomputed it.
#
# Pillow only: no WeasyPrint, no rasterizer, no HTML to author. The legacy composed
# banner further down needs all three, which is why this one is the default.

_LOGO_DIR = SKILL / "brand" / "assets" / "logos"
_LOGO_W = 0.17            # mark width, as a fraction of the canvas width
_LOGO_MARGIN = 0.045      # inset from the top and right edges, same fraction
_LOGO_LUMA = {"cream": (245, 232, 202), "dark": (27, 35, 29), "emerald": (0, 139, 76)}


def _srgb_luma(rgb) -> float:
    """WCAG relative luminance of an 8-bit sRGB triple."""
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: float, b: float) -> float:
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _pick_logo_variant(im, box) -> tuple[str, float, float]:
    """Which mark to composite: whichever has more contrast against the corner.

    The corner's MEAN colour is a proxy — a mark over busy art has no single
    background — but it is deterministic, it is reported in the output line, and
    `--logo` overrides it whenever the eye disagrees.
    """
    from PIL import ImageStat
    bg = _srgb_luma(ImageStat.Stat(im.crop(box).convert("RGB")).mean)
    ranked = sorted(_LOGO_LUMA, key=lambda k: -_contrast(_srgb_luma(_LOGO_LUMA[k]), bg))
    best = ranked[0]
    return best, bg, _contrast(_srgb_luma(_LOGO_LUMA[best]), bg)


def _logo_image(variant: str, width: int, logo_file: str | None = None):
    """The Superteam horizontal mark as an RGBA image `width` px wide.

    Shipped PNG first, which is what keeps this path Pillow-only; cairosvg second, for
    a swapped-in SVG. There is no third rung — a banner that cannot load the mark FAILs
    rather than shipping unbranded.
    """
    from PIL import Image
    src = Path(logo_file) if logo_file else _LOGO_DIR / f"horizontal-{variant}.png"
    if src.suffix.lower() == ".svg" or not src.is_file():
        svg = src if src.suffix.lower() == ".svg" else src.with_suffix(".svg")
        if not svg.is_file():
            return None, f"no mark at {src}"
        try:
            import cairosvg
        except ModuleNotFoundError:
            return None, (f"{svg.name} is an SVG and cairosvg is absent — "
                          "`pip install cairosvg`, or point --logo-file at a PNG")
        import io
        im = Image.open(io.BytesIO(cairosvg.svg2png(url=str(svg),
                                                    output_width=width))).convert("RGBA")
    else:
        im = Image.open(src).convert("RGBA")
    if im.width != width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    return im, src.name


def cmd_banner(course_dir: Path | None, src: str | None = None, out: str | None = None,
               variant: str = "auto", logo_file: str | None = None, logo_w: float = _LOGO_W,
               margin: float = _LOGO_MARGIN, no_logo: bool = False) -> int:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        print("banner: SKIP - Pillow not installed (`pip install Pillow`)", file=sys.stderr)
        return 0
    art = Path(src) if src else (_banner_paths(course_dir)["bg"] if course_dir else None)
    if art is None:
        print("banner: FAIL no course art — drop branding/banner-bg.{png,jpg,jpeg,webp} "
              "into the course, or pass --in <image>", file=sys.stderr)
        return 2
    if not art.is_file():
        print(f"banner: FAIL no such image: {art}", file=sys.stderr)
        return 2
    if out:
        webp = Path(out)
        png = webp.with_suffix(".png")
    elif course_dir is not None:
        p = _banner_paths(course_dir)
        p["dir"].mkdir(parents=True, exist_ok=True)
        png, webp = p["png"], p["webp"]
    else:
        print("banner: FAIL pass a course dir or --out", file=sys.stderr)
        return 2

    im = Image.open(art).convert("RGB")
    src_size = im.size
    small = im.width < CANVAS[0] or im.height < CANVAS[1]
    im = _cover_crop(im, CANVAS)
    note = "no logo"
    if not no_logo:
        lw, m = max(1, round(CANVAS[0] * logo_w)), round(CANVAS[0] * margin)
        logo, why = _logo_image("cream" if variant == "auto" else variant, lw, logo_file)
        if logo is None:
            print(f"banner: FAIL {why}", file=sys.stderr)
            return 1
        x, y = CANVAS[0] - m - logo.width, m
        if variant == "auto" and not logo_file:      # a --logo-file has no variants to pick from
            variant, bg_luma, ratio = _pick_logo_variant(im, (x, y, x + logo.width,
                                                              y + logo.height))
            note = f"logo {variant} (auto: corner luma {bg_luma:.2f}, contrast {ratio:.1f}:1)"
            if variant != "cream":
                logo, why = _logo_image(variant, lw, logo_file)
                if logo is None:
                    print(f"banner: FAIL {why}", file=sys.stderr)
                    return 1
        else:
            note = f"logo {why}"
        im = im.convert("RGBA")
        im.alpha_composite(logo, (x, y))
        im = im.convert("RGB")
    im.save(png, "PNG")
    shipped, meth = _compress_banner(png, webp)
    if shipped is None:
        print(f"banner: {png.name} rendered, but compression FAILED: {meth}")
        return 1
    size = shipped.stat().st_size
    print(f"banner: {art.name} -> {shipped} {size // 1024}KB via {meth} · {note}"
          f" [1MiB cap: {'PASS' if size <= _BANNER_CAP else 'FAIL'}]"
          + (f"\n  note: {art.name} is {src_size[0]}x{src_size[1]}, smaller than "
             f"{CANVAS[0]}x{CANVAS[1]} — it was upscaled" if small else ""))
    return 0 if size <= _BANNER_CAP else 1


# ---- LEGACY composed banner (title card through WeasyPrint) -------------------
# Superseded by `banner` above, kept working for courses whose branding/banner.html is
# already authored. Everything below this line — the starter, the pre-baked backdrop,
# the forbidden-CSS lint — belongs to that path only.

# The XP bolt as inline SVG — the ⚡ emoji is unreliable under WeasyPrint/Pango.
_BOLT_SVG = ('<svg width="18" height="26" viewBox="0 0 16 24">'
             '<polygon points="9,0 0,14 6,14 5,24 16,9 9,9" fill="#1b231d"/></svg>')

_BANNER_STARTER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<link rel="stylesheet" href="_brand.css">
<link rel="stylesheet" href="_render.css">
<style>
  @page {{ size: {w}px {h}px; margin: 0; }}
  html, body {{ margin: 0; }}
  body {{ width: {w}px; height: {h}px; position: relative; overflow: hidden;
         background: {page_bg}; padding: 0; }}
  .bg {{ position: absolute; top: 0; left: 0; width: {w}px; height: {h}px;
        object-fit: cover; }}
  .vignette {{ position: absolute; top: 0; left: 0; width: {w}px; height: {h}px;
              background: linear-gradient(180deg, rgba(27,35,29,0.32) 0%,
                          rgba(27,35,29,0.10) 42%, rgba(27,35,29,0.40) 100%); }}
  .stbr-decor {{ top: 0; right: 0; bottom: 0; left: 0; }}  /* banner body has no padding */
  .stage {{ position: absolute; top: 0; left: 0; width: {w}px; height: {h}px; z-index: 1;
           display: flex; align-items: center; justify-content: center; }}
  .card {{ background: {card_bg}; border-radius: var(--radius-2xl);
          padding: 56px 72px 60px; width: 1240px; }}
  .card-top {{ display: flex; justify-content: space-between; align-items: center;
              margin-bottom: 30px; }}
  .card-top .stbr-eyebrow {{ font-size: 24px; }}
  .card-title {{ font-family: var(--font-display); font-weight: var(--weight-black);
                color: var(--text-primary); font-size: 82px; line-height: 1.05;
                letter-spacing: var(--tracking-tight); margin: 0 0 44px;
                text-wrap: balance; }}
  .meta {{ display: flex; gap: 16px; align-items: center; }}
  /* inline-BLOCK, not inline-flex: WeasyPrint double-draws borders on inline-flex */
  .pill {{ display: inline-block; padding: 13px 28px;
          border-radius: var(--radius-pill); font-family: var(--font-display);
          font-weight: var(--weight-bold); font-size: 23px; letter-spacing: 0.08em;
          text-transform: uppercase; white-space: nowrap; }}
  .pill svg {{ vertical-align: -4px; margin-right: 8px; }}
  .pill--level {{ background: var(--stbr-emerald); color: var(--text-on-brand); }}
  .pill--stat  {{ border: var(--border-bold) solid var(--stbr-dark);
                 color: var(--text-primary); }}
  .pill--xp    {{ background: var(--stbr-yellow); color: var(--text-on-accent);
                 margin-left: auto; }}
</style></head>
<body>
<!-- COURSE BANNER: the Academy course thumbnail (card shows it at 400x225 — keep
     text short and large; judge legibility at 25% zoom). AUTHOR the .card content:
     eyebrow, title (break lines with <br> if needed), pill texts. Rules and both
     modes: skills/content-gen/references/banner.md.
     WeasyPrint-safe CSS only: NO filter/backdrop-filter (photo blur is pre-baked
     into banner-bg-blur.png by `render-banner`), no box shadows, no CSS
     background images via url, NO emoji (the XP bolt is inline SVG). -->
{bg_layer}<div class="stage">
  <div class="card">
    <div class="card-top">
      <div class="stbr-eyebrow">// COURSE TAG</div>
      <img src="logo.svg" style="height: 46px;" alt="">
    </div>
    <h1 class="card-title">COURSE TITLE</h1>
    <div class="meta">
      <span class="pill pill--level">BEGINNER</span>
      <span class="pill pill--stat">NN LESSONS &middot; NN HOURS</span>
      <span class="pill pill--xp">{bolt}NNN XP</span>
    </div>
  </div>
</div>
<!-- TODO(render): author this banner, then delete this marker -->
</body></html>
"""


def cmd_scaffold_banner(course_dir: Path) -> int:
    p = _banner_paths(course_dir)
    p["dir"].mkdir(parents=True, exist_ok=True)
    if BRAND_CSS.is_file():
        (p["dir"] / "_brand.css").write_text(BRAND_CSS.read_text("utf-8"))
    if RENDER_CSS.is_file():
        (p["dir"] / "_render.css").write_text(RENDER_CSS.read_text("utf-8"))
    # emerald mark: legible on the cream/white card (the cream logo would vanish)
    logo = SKILL / "brand" / "assets" / "logos" / "horizontal-emerald.svg"
    if logo.is_file() and not (p["dir"] / "logo.svg").exists():
        (p["dir"] / "logo.svg").write_text(logo.read_text("utf-8"))
    if p["html"].exists() and "TODO(render)" not in p["html"].read_text("utf-8"):
        print(f"scaffold-banner: kept authored {p['html']} (re-author or delete to reset)")
        return 0
    photo = p["bg"] is not None
    if photo:
        bg_layer = ('<img class="bg" src="banner-bg-blur.png" alt="">\n'
                    '<div class="vignette"></div>\n')
        page_bg, card_bg = "var(--stbr-dark)", "var(--stbr-cream)"
    else:
        bg_layer = _decor(p["asset_id"], 3)
        page_bg, card_bg = "var(--surface-page)", "var(--surface-card)"
    p["html"].write_text(_BANNER_STARTER.format(
        w=CANVAS[0], h=CANVAS[1], bg_layer=bg_layer,
        page_bg=page_bg, card_bg=card_bg, bolt=_BOLT_SVG))
    print(f"scaffold-banner: {'photo' if photo else 'pure-brand'} starter -> {p['html']}"
          + ("" if photo else "  (drop branding/banner-bg.png + re-run for photo mode)"))
    return 0


# Per-banner backdrop treatment, declared IN the banner HTML so each variant carries its
# own bake: <!-- banner-bg: blur=5 brightness=0.92 file=banner-bg-soft.png -->
# Defaults (no directive): the heavy title-card treatment.
_BANNER_BG_DIRECTIVE_RE = re.compile(r"<!--\s*banner-bg:([^>]*?)-->")
_BANNER_BG_DEFAULTS = {"blur": 14.0, "brightness": 0.72, "file": "banner-bg-blur.png"}


def _banner_bg_params(html: str) -> dict:
    out = dict(_BANNER_BG_DEFAULTS)
    m = _BANNER_BG_DIRECTIVE_RE.search(html)
    if m:
        for kv in m.group(1).split():
            k, _, v = kv.partition("=")
            if k in ("blur", "brightness"):
                try:
                    out[k] = float(v)
                except ValueError:
                    pass
            elif k == "file":
                out[k] = v
    return out


def _prepare_banner_bg(p: dict, params: dict) -> tuple[bool, str]:
    """Bake branding/banner-bg.* into the treated 1600x900 backdrop the banner references.
    WeasyPrint has no CSS blur, so blur/darken is pre-baked (Pillow)."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ModuleNotFoundError:
        return False, "Pillow not installed (`pip install Pillow`) — cannot bake the backdrop"
    im = _cover_crop(Image.open(p["bg"]).convert("RGB"), CANVAS)
    if params["blur"] > 0:
        im = im.filter(ImageFilter.GaussianBlur(radius=params["blur"]))
    if params["brightness"] != 1.0:
        im = ImageEnhance.Brightness(im).enhance(params["brightness"])
    im.save(p["dir"] / params["file"], "PNG")
    return True, "ok"


def _compress_banner(png: Path, out: Path, cap: int = _BANNER_CAP) -> tuple[Path | None, str]:
    """Shrink the full-res render to a shippable <=1MiB 1600x900 image (webp, jpg last
    resort). Pillow first, then cwebp, then sips (macOS)."""
    try:
        from PIL import Image
        im = Image.open(png).convert("RGB")
        if im.size != CANVAS:
            im = im.resize(CANVAS, Image.LANCZOS)
        for q in (82, 72, 62, 50):
            im.save(out, "WEBP", quality=q, method=6)
            if out.stat().st_size <= cap:
                return out, f"pillow webp q{q}"
        return None, f"still {out.stat().st_size} bytes over the {cap} cap at q50"
    except ModuleNotFoundError:
        pass
    if shutil.which("cwebp"):
        for q in (82, 72, 62, 50):
            r = subprocess.run(["cwebp", "-q", str(q), "-resize", str(CANVAS[0]), str(CANVAS[1]),
                                str(png), "-o", str(out)], capture_output=True, text=True)
            if r.returncode == 0 and out.exists() and out.stat().st_size <= cap:
                return out, f"cwebp q{q}"
    if shutil.which("sips"):
        jpg = out.with_suffix(".jpg")
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "70",
                            "-z", str(CANVAS[1]), str(CANVAS[0]), str(png), "--out", str(jpg)],
                           capture_output=True, text=True)
        if r.returncode == 0 and jpg.exists() and jpg.stat().st_size <= cap:
            return jpg, "sips jpeg"
    return None, "no compressor available (install Pillow or cwebp)"


def cmd_render_banner(course_dir: Path, dpi: int, html_file: str | None = None) -> int:
    p = _banner_paths(course_dir)
    if html_file:                                        # a variant beside banner.html
        p["html"] = Path(html_file)
        p["pdf"] = p["html"].with_suffix(".pdf")
        p["png"] = p["html"].with_suffix(".png")
        p["webp"] = p["html"].with_suffix(".webp")
    if not p["html"].is_file():
        print(f"render-banner: no {p['html']} — run scaffold-banner first", file=sys.stderr)
        return 2
    html = p["html"].read_text("utf-8")
    if "TODO(render)" in html:
        print(f"render-banner: {p['html'].name} is still the unauthored starter (TODO marker present)",
              file=sys.stderr)
        return 2
    # Markup only: the scaffold's own authoring comment names both the forbidden CSS and
    # the backdrop file, so testing raw text puts every freshly scaffolded banner in
    # photo mode (and flags CSS it merely warns about).
    live = _COMMENT_RE.sub("", html)
    bad = [b for b in _FORBIDDEN_CSS if b in live]
    if bad:
        print(f"render-banner: FAIL forbidden CSS in {p['html'].name}: {', '.join(bad)}")
        return 1
    if not shutil.which("weasyprint"):
        print("render-banner: SKIP - weasyprint not installed "
              "(`pip install weasyprint`; needs pango/cairo).", file=sys.stderr)
        return 0
    params = _banner_bg_params(html)
    if params["file"] in live:
        if p["bg"] is None:
            print(f"render-banner: FAIL {p['html'].name} references {params['file']} but no "
                  "branding/banner-bg.{png,jpg,jpeg,webp} exists")
            return 1
        ok_bg, msg = _prepare_banner_bg(p, params)
        if not ok_bg:
            print(f"render-banner: SKIP - {msg}", file=sys.stderr)
            return 0
    ok_pdf, err = _render_pdf(p)
    if not ok_pdf:
        print(f"render-banner: FAIL weasyprint: {(err.splitlines()[-1][:100] if err else 'error')}")
        return 1
    pages = _pdf_pages(p["pdf"])
    if pages > 1:
        p["pdf"].unlink(missing_ok=True)
        print(f"render-banner: FAIL overflow — spans {pages} pages "
              f"(must fit one {CANVAS[0]}x{CANVAS[1]} page)")
        return 1
    rok, how = _rasterize(p["pdf"], p["png"], dpi)
    p["pdf"].unlink(missing_ok=True)
    if not rok:
        print(f"render-banner: FAIL rasterize ({how})")
        return 1
    out, meth = _compress_banner(p["png"], p["webp"])
    if out is None:
        print(f"render-banner: {p['png'].name} rendered, but compression FAILED: {meth}")
        return 1
    size = out.stat().st_size
    print(f"render-banner: {p['png']} (full-res review) + {out.name} "
          f"{size // 1024}KB via {meth} [1MiB cap: {'PASS' if size <= _BANNER_CAP else 'FAIL'}]")
    return 0


def selftest() -> int:
    ok = True
    def chk(c, m):
        nonlocal ok; print(("PASS" if c else "FAIL") + " - " + m); ok = ok and c
    chk(_slug("Annotated Code!") == "annotated-code", "slug kebabs + strips punctuation")
    chk(_slug("flowchart") == "flowchart", "slug passes clean type")
    md = ("# t\n\n```visual\ntype: flowchart\ntitle: A to B\npurpose: p\n"
          "data: |\n a -> b\nprompt: |\n draw it\nalt: a goes to b in one hop here ok\n```\n")
    import tempfile
    d = Path(tempfile.mkdtemp()); (d / "lessons" / "drafts").mkdir(parents=True)
    (d / "lessons" / "drafts" / "m01-l1-x.md").write_text(md)
    items = work_list(d)
    chk(len(items) == 1 and items[0]["asset_id"] == "m01-l1-x/v01-flowchart",
        "work_list builds a stable asset_id from the block")
    chk(items[0]["type"] == "flowchart" and "a -> b" in items[0]["data"], "carries type + data")
    cmd_scaffold(d)
    starter = items[0]["html"].read_text("utf-8")
    chk("TODO(render)" in starter and "_brand.css" in starter and "1600px 900px" in starter,
        "scaffold writes a brand-linked, canvas-sized starter")
    chk("_render.css" in starter and 'class="stbr-decor"' in starter and "border-radius" in starter,
        "scaffold bakes in the render layer + per-asset decoration")
    for nn in (1, 2, 3):
        dec = _decor("m01-l1-x/v01-flowchart", nn)
        b = re.findall(r'<div style="([^"]+)"></div>', dec)
        chk('class="stbr-decor"' in dec and len(b) == nn, f"_decor(n={nn}) emits {nn} blob(s)")
        chk(all("border-radius" in x and "position:absolute" in x for x in b),
            f"_decor(n={nn}) blobs are CSS border-radius shapes (fill their box → visible)")
        chk(all(re.search(r'(?:top|bottom|left|right):-\d+px', x) for x in b),
            f"_decor(n={nn}) blobs are each bled off a border")
        chk(all(any(c in x for c in ("#008b4c", "#306c40", "#ffd23f")) for x in b),
            f"_decor(n={nn}) blobs use only brand fills")
    d1 = _decor("m01-l1-x/v01-flowchart", 2)
    chk(_decor("m01-l1-x/v01-flowchart", 2) == d1, "_decor is deterministic per (asset_id, n)")
    chk(d1 != _decor("m01-l1-x/v07-table", 2), "_decor varies across assets")
    chk(all(_ANCHORS[a][0] != _ANCHORS[b_][0] and _ANCHORS[a][1] != _ANCHORS[b_][1]
            for a, b_ in _PAIRS), "2-blob pairs are opposite on both x and y (balanced)")
    chk(_density_n('<div class="viz"><p>' + "x " * 400 + "</p></div>\n</body>") == 1
        and _density_n('<div class="viz"><p>hi</p></div>\n</body>') == 3,
        "_density_n: dense→1, sparse→3")
    cmd_decorate(d)
    redecor = items[0]["html"].read_text("utf-8")
    chk(redecor.count('class="stbr-decor"') == 1 and "_render.css" in redecor,
        "decorate keeps exactly one decor block + the render link")
    bad_viz = '<a><div class="viz"><style>.x{box-shadow:0 0 5px}</style>hi</div>\n</body>'
    good_viz = '<a><div class="viz"><style>.x{border:1px solid}</style>hi</div>\n</body>'
    chk(_viz_inner(bad_viz).startswith("<style>") and _viz_inner(good_viz).startswith("<style>"),
        "_viz_inner extracts the authored .viz content")
    chk(any(b in _viz_inner(bad_viz) for b in _FORBIDDEN_CSS)
        and not any(b in _viz_inner(good_viz) for b in _FORBIDDEN_CSS),
        "review lint flags forbidden CSS (box-shadow), passes clean CSS")
    dc_viz = '<a><div class="viz"><style>.g{display:contents}</style>hi</div>\n</body>'
    chk(any(b in _viz_inner(dc_viz) for b in _FORBIDDEN_CSS),
        "review lint flags display:contents (WeasyPrint ignores it → broken grid)")
    chk("align-items: flex-start" in _safe_area_html('body { align-items: center; }')
        and "align-items: center" not in _safe_area_html('body { align-items: center; }'),
        "safe-area check top-aligns the card (center → flex-start; exposes within-page clipping)")
    # ---- course banner: the standard path (art + mark, top-right) ----
    try:
        from PIL import Image
        bd = d / "branding"; bd.mkdir(parents=True, exist_ok=True)
        # 2000x1000 (2:1) so the cover-crop has to do real work in both axes
        Image.new("RGB", (2000, 1000), (12, 14, 20)).save(bd / "banner-bg.png")
        chk(cmd_banner(d) == 0, "banner: dark art -> banner.webp")
        chk(_banner_paths(d)["webp"].is_file()
            and _banner_paths(d)["webp"].stat().st_size <= _BANNER_CAP,
            "banner ships a webp under the 1MiB cap")
        shot = Image.open(_banner_paths(d)["png"]).convert("RGB")
        chk(shot.size == CANVAS, f"banner canvas is {CANVAS[0]}x{CANVAS[1]} (16:9, cover-cropped)")
        lw, m = round(CANVAS[0] * _LOGO_W), round(CANVAS[0] * _LOGO_MARGIN)
        logo, _ = _logo_image("cream", lw)
        chk(logo is not None and logo.width == lw,
            "the shipped horizontal mark loads as a PNG (no SVG rasterizer needed)")
        if logo is not None:
            corner = shot.crop((CANVAS[0] - m - lw, m, CANVAS[0] - m, m + logo.height))
            flat = Image.new("RGB", corner.size, (12, 14, 20))
            chk(list(corner.getdata()) != list(flat.getdata()),
                "the mark is composited into the top-right corner")
            left = shot.crop((0, 0, CANVAS[0] - m - lw, CANVAS[1]))
            chk(len(set(left.getdata())) == 1,
                "nothing but the mark is added — the rest of the art is untouched")
        chk(_pick_logo_variant(Image.new("RGB", CANVAS, (12, 14, 20)),
                               (0, 0, 100, 40))[0] == "cream",
            "auto picks the cream mark on dark art")
        chk(_pick_logo_variant(Image.new("RGB", CANVAS, (245, 245, 240)),
                               (0, 0, 100, 40))[0] == "dark",
            "auto picks the dark mark on light art")
        chk(cmd_banner(d, no_logo=True) == 0
            and len(set(Image.open(_banner_paths(d)["png"]).convert("RGB").getdata())) == 1,
            "--no-logo leaves the art unbranded")
        chk(cmd_banner(d, src=str(bd / "banner-bg.png"), out=str(d / "loose.webp")) == 0
            and (d / "loose.webp").is_file() and (d / "loose.png").is_file(),
            "banner runs standalone on --in/--out with no course dir")
        chk(cmd_banner(None) == 2 and cmd_banner(d, src=str(d / "nope.png")) == 2,
            "banner FAILs loudly with no art and with a missing --in")
        wide = _cover_crop(Image.new("RGB", (4000, 1000)), CANVAS)
        tall = _cover_crop(Image.new("RGB", (1000, 4000)), CANVAS)
        chk(wide.size == CANVAS and tall.size == CANVAS,
            "_cover_crop fills the canvas from either extreme aspect")
        for f in (bd / "banner-bg.png", d / "loose.webp", d / "loose.png",
                  _banner_paths(d)["png"], _banner_paths(d)["webp"]):
            f.unlink(missing_ok=True)
    except ModuleNotFoundError:
        print("SKIP - standard banner (Pillow not installed)")
    # ---- course banner: the legacy composed path ----
    cmd_scaffold_banner(d)
    bp = _banner_paths(d)
    brand_starter = bp["html"].read_text("utf-8")
    chk("stbr-decor" in brand_starter and 'class="bg"' not in brand_starter
        and "TODO(render)" in brand_starter,
        "scaffold-banner without a photo writes the pure-brand starter")
    chk((bp["dir"] / "_brand.css").is_file() and (bp["dir"] / "logo.svg").is_file(),
        "scaffold-banner ships brand css + logo beside the banner")
    (bp["dir"] / "banner-bg.png").write_bytes(b"\x89PNG fake photo")
    cmd_scaffold_banner(d)                           # TODO still present -> re-scaffolded
    photo_starter = bp["html"].read_text("utf-8")
    chk('class="bg"' in photo_starter and "banner-bg-blur.png" in photo_starter
        and "vignette" in photo_starter, "with a photo, re-scaffold switches to photo mode")
    chk("_brand.css" in photo_starter and f"{CANVAS[0]}px {CANVAS[1]}px" in photo_starter
        and "polygon" in photo_starter,
        "banner starter is brand-linked, canvas-sized, XP bolt is inline SVG (no emoji)")
    authored = photo_starter.replace(
        "<!-- TODO(render): author this banner, then delete this marker -->", "")
    bp["html"].write_text(authored)
    cmd_scaffold_banner(d)
    chk(bp["html"].read_text("utf-8") == authored, "scaffold-banner keeps an authored banner.html")
    try:
        from PIL import Image
        big = d / "big.png"
        Image.new("RGB", (2400, 1350), (0, 139, 76)).save(big)
        out, meth = _compress_banner(big, d / "banner.webp")
        chk(out is not None and out.stat().st_size <= _BANNER_CAP
            and Image.open(out).size == CANVAS,
            f"_compress_banner -> {CANVAS[0]}x{CANVAS[1]} webp under the 1MiB cap ({meth})")
    except ModuleNotFoundError:
        print("SKIP - _compress_banner (Pillow not installed)")
    print("RENDER_VISUALS SELFTESTS " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="render ```visual specs into on-brand images")
    ap.add_argument("cmd", nargs="?",
                    choices=["extract", "scaffold", "decorate", "render", "review", "check",
                             "banner", "scaffold-banner", "render-banner"])
    ap.add_argument("course", nargs="?")
    ap.add_argument("--file", help="extract from a single markdown file")
    ap.add_argument("--html", help="render-banner: render this variant HTML instead of "
                                   "branding/banner.html (outputs <stem>.png/.webp beside it)")
    ap.add_argument("--dpi", type=int, default=144, help="raster DPI (default 144 = 1.5x)")
    ap.add_argument("--only", help="render only asset_ids containing this substring")
    ap.add_argument("--in", dest="src", help="banner: course art (default branding/banner-bg.*)")
    ap.add_argument("--out", help="banner: output .webp (default branding/banner.webp)")
    ap.add_argument("--logo", default="auto", choices=["auto", "cream", "dark", "emerald"],
                    help="banner: mark variant (default auto — best contrast on the corner)")
    ap.add_argument("--logo-file", help="banner: composite this PNG/SVG instead of the "
                                        "shipped Superteam mark")
    ap.add_argument("--logo-width", type=float, default=_LOGO_W,
                    help=f"banner: mark width as a fraction of {CANVAS[0]}px "
                         f"(default {_LOGO_W})")
    ap.add_argument("--margin", type=float, default=_LOGO_MARGIN,
                    help=f"banner: top/right inset, same fraction (default {_LOGO_MARGIN})")
    ap.add_argument("--no-logo", action="store_true", help="banner: art only, unbranded")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "extract":
        return cmd_extract(Path(a.course) if a.course else Path("."), a.file)
    if a.cmd == "banner":                       # --in/--out make the course dir optional
        return cmd_banner(Path(a.course) if a.course else None, a.src, a.out, a.logo,
                          a.logo_file, a.logo_width, a.margin, a.no_logo)
    if not a.course:
        print("render_visuals: pass a course dir", file=sys.stderr); return 2
    course = Path(a.course)
    if a.cmd == "scaffold":
        return cmd_scaffold(course)
    if a.cmd == "decorate":
        return cmd_decorate(course)
    if a.cmd == "render":
        return cmd_render(course, a.dpi, a.only)
    if a.cmd == "review":
        return cmd_review(course, a.only)
    if a.cmd == "check":
        return cmd_check(course)
    if a.cmd == "scaffold-banner":
        return cmd_scaffold_banner(course)
    if a.cmd == "render-banner":
        return cmd_render_banner(course, a.dpi, a.html)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
