#!/usr/bin/env python3
"""
academy_export.py — project an authored course into the Superteam Academy publish tree.

ContentGen's `manifest.json` + written drafts are the AUTHORING representation. The
Academy platform (github.com/solanabr/academy-courses) consumes a different, YAML
block-based shape (references/academy-schema.md). This tool is the one-way projection:

    content/courses/<id>/                academy/courses/<slug>/
      manifest.json          ──────▶       course.yaml
      lessons/drafts/*.md                   lessons/<slug>/lesson.yaml   (blocks: prose + quiz + code)
      (brief.quiz_blocks)                   lessons/<slug>/intro.md      (visuals → ![alt](assets/vNN-*.webp))
      (brief.coding_challenges)             lessons/<slug>/<challenge>/{starter,solution}.{rs,ts},tests.json
      lessons/assets/<stem>/vNN-*.{webp,png} lessons/<slug>/assets/vNN-*  (webp wins over its PNG sibling)
      lessons/assets/<stem>/vNN-*.html      visual-src/<slug>/vNN-*.html  (+ shared _brand/_render.css)
      branding/banner.webp                  assets/banner.webp + `thumbnail:` in course.yaml
      branding/banner.html (+logo, bg)      visual-src/  (re-renderable banner source)

It is ADDITIVE: it reads the course dir read-only and writes only into --out. The
source course is never mutated. Publish-only metadata (creator wallet, difficulty,
xp, id prefix, dag-node→skills map) is read from an optional additive `academy` block
in the manifest, overridable by CLI flags; nothing else in the manifest changes.

    python academy_export.py emit  --course content/courses/<id> --out content/academy/courses/<slug>
    python academy_export.py check --course content/courses/<id>
    python academy_export.py --selftest

The runtime contract (starter fails / solution passes) is NOT checked here — that is
verify_challenges.py. This tool only materializes the tree.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

from course_lib import to_yaml, load_manifest, flatten_lessons, CHALLENGE_LANGS

EXT = {"rust": ".rs", "typescript": ".ts"}


def _safe(fragment) -> str:
    return re.sub(r"[^a-z0-9-]", "-", str(fragment).lower()).strip("-") or "x"


def _prefix_default(course_id: str) -> str:
    """Deterministic short id prefix from the course id (initials of each token)."""
    toks = [t for t in str(course_id).split("-") if t]
    return ("".join(t[0] for t in toks) or "c")[:6]


def _draft_stem(mod_idx: int, order, lid: str) -> str:
    """Mirror scaffold_course.py's draft filename: m{NN}-l{order}-{safe(id)}."""
    return f"m{mod_idx:02d}-l{order}-{_safe(lid)}"


def _asset_visuals(asset_dir: Path) -> dict[int, str]:
    """Map visual ordinal → the filename that SHIPS for it from a lesson's asset dir
    (render_visuals.py names them v<NN>-<type>.png, NN = Nth ```visual spec). A same-stem
    `.webp` sibling is the compressed publish form and supersedes the PNG: upstream ships
    webp, and the PNG stays on disk here only as the render intermediate."""
    out: dict[int, str] = {}
    if asset_dir.is_dir():
        for p in sorted(asset_dir.glob("v*.png")) + sorted(asset_dir.glob("v*.webp")):
            mt = re.match(r"v(\d+)-", p.name)
            if mt and (p.suffix == ".webp" or int(mt.group(1)) not in out):
                out[int(mt.group(1))] = p.name
    return out


def _strip_html_comments(md: str) -> str:
    """Drop `<!-- ... -->` spans from prose so source-side harness annotations (the
    `verify: expect-fail` markers the code oracle reads) never reach a learner. Fenced
    code is passed through untouched: a fence may legitimately contain `<!--` as the
    very thing it is teaching. Comment-only lines are removed rather than left blank."""
    out, in_fence, in_comment = [], False, False
    for raw in md.split("\n"):
        ln = raw
        if in_comment:
            idx = ln.find("-->")
            if idx == -1:
                continue
            ln, in_comment = ln[idx + 3:], False
            if not ln.strip():
                continue
        if in_fence:
            if ln.lstrip().startswith("```"):
                in_fence = False
            out.append(ln)
            continue
        if ln.lstrip().startswith("```"):
            in_fence = True
            out.append(ln)
            continue
        stripped = re.sub(r"<!--.*?-->", "", ln, flags=re.S)
        idx = stripped.find("<!--")
        if idx != -1:
            in_comment = True
            stripped = stripped[:idx]
        if stripped != ln and not stripped.strip():
            continue
        out.append(stripped)
    return "\n".join(out)


def _prose_from_draft(md: str, imgs: dict[int, str] | None = None,
                      warnings: list[str] | None = None, where: str = "") -> str:
    """Project a written draft into an Academy prose `.md`. Lossless of prose; the Nth
    ```visual spec becomes a markdown image embed of its rendered visual
    (`![alt](assets/vNN-<type>.webp)`, the Academy convention — courses/README.md there).
    A spec with no rendered image degrades to a blockquote carrying its title + alt, so no
    learner-facing meaning is lost and no orphan image reference is created."""
    imgs = imgs or {}
    out, i, n, lines = [], 0, 0, _strip_html_comments(md).split("\n")
    while i < len(lines):
        s = lines[i].strip()
        if s == "```visual":
            n += 1
            j, body = i + 1, []
            while j < len(lines) and lines[j].strip() != "```":
                body.append(lines[j]); j += 1
            spec = {}
            for ln in body:
                mt = re.match(r"\s*([a-z_]+):\s*(.*)$", ln)
                if mt and mt.group(1) in ("type", "title", "purpose", "alt"):
                    spec[mt.group(1)] = mt.group(2).strip()
            title = spec.get("title", spec.get("type", "diagram"))
            alt = spec.get("alt", "").strip()
            img = imgs.get(n)
            if img:
                out.append(f"![{alt or title}](assets/{img})")
            else:
                if warnings is not None:
                    warnings.append(f"{where}: visual {n} ('{title}') has no rendered image — "
                                    f"blockquote placeholder emitted (run render_visuals.py first)")
                out.append(f"> **Visual — {title}.**" + (f" {alt}" if alt else ""))
            i = j + 1
        else:
            out.append(lines[i]); i += 1
    return "\n".join(out).rstrip() + "\n"


def _academy_cfg(m: dict, opts: dict) -> dict:
    """Resolve publish-only metadata: CLI flags > manifest['academy'] > derived defaults."""
    course = m.get("course", {})
    internal_id = course.get("id", "course")
    ac = dict(m.get("academy", {}))
    ac.update({k: v for k, v in opts.items() if v is not None})
    slug = ac.get("slug") or _safe(internal_id)
    cid = ac.get("course_id") or f"course-{slug}"
    cid = cid[:32].rstrip("-")
    lessons = flatten_lessons(m)
    # Academy `duration` is HOURS, display only (the course card renders "{duration} hours").
    # Derive from the authoring estimate; a lesson count here is the legacy bug this fixes.
    hours = (course.get("length_target", {}) or {}).get("hours")
    if isinstance(hours, (int, float)) and not isinstance(hours, bool) and hours > 0:
        default_duration = math.ceil(hours) if hours >= 1 else round(hours, 2)
    else:
        default_duration = len(lessons)              # last resort when no estimate exists
    return {
        "slug": slug,
        "course_id": cid,
        "prefix": ac.get("prefix") or _prefix_default(internal_id),
        "title": ac.get("title") or course.get("title", internal_id),
        "description": ac.get("description") or course.get("one_line_promise", ""),
        "difficulty": ac.get("difficulty", "beginner"),
        "duration": ac.get("duration", default_duration),
        "xpPerLesson": ac.get("xpPerLesson", 20),
        "xpReward": ac.get("xpReward", min(5000, 20 * max(1, len(lessons)))),
        "creator": ac.get("creator", "REPLACE_WITH_YOUR_SOLANA_WALLET"),
        "skills_map": ac.get("skills_map", {}),
        "default_skills": ac.get("default_skills", []),
        "extra_course_keys": ac.get("extra_course_keys", {}),
    }


def _lesson_id(prefix: str, lid: str) -> str:
    return f"lesson-{prefix}-{_safe(lid)}"


def _skills_for(brief: dict, mod: dict, cfg: dict) -> list[str]:
    """Map internal DAG skill nodes (module teaches/requires) to academy skills.yaml slugs
    via cfg['skills_map']; fall back to default_skills. Deduped, order-stable."""
    smap = cfg["skills_map"]
    nodes = list(mod.get("teaches_skills", [])) + list(brief.get("prerequisites", []))
    out: list[str] = []
    for n in nodes:
        slug = smap.get(n)
        if slug and slug not in out:
            out.append(slug)
    if not out:
        out = list(cfg["default_skills"])
    return out


def plan_academy(course_dir: Path, cfg: dict, m: dict,
                 out_dir: Path | None = None) -> tuple[dict[str, str], list[str], list[tuple[str, str]]]:
    """Return ({relpath: text}, warnings, copies) for the whole academy tree.
    `copies` are (src_abs, rel_dest) for binary-safe file copies (challenge sources)."""
    files: dict[str, str] = {}
    warnings: list[str] = []
    copies: list[tuple[str, str]] = []

    modules = m.get("modules", [])
    mod_idx = {mod["id"]: i for i, mod in enumerate(modules)}
    lessons = flatten_lessons(m)
    by_mod: dict[str, list[dict]] = {}
    for l in lessons:
        by_mod.setdefault(l.get("module"), []).append(l)

    # course.yaml
    course_doc = {
        "id": cfg["course_id"], "slug": cfg["slug"], "title": cfg["title"],
    }
    if cfg["description"]:
        course_doc["description"] = cfg["description"]
    course_doc.update({
        "difficulty": cfg["difficulty"], "duration": cfg["duration"],
        "xpPerLesson": cfg["xpPerLesson"], "xpReward": cfg["xpReward"],
        "creator": cfg["creator"],
    })
    course_doc.update(cfg["extra_course_keys"])
    # course banner → platform `thumbnail:` (course-level assets/ is a recognized upstream
    # asset source, 1 MiB per-file cap). Only the compressed render ships — never
    # branding/banner.png, the full-res review intermediate.
    bdir = course_dir / "branding"
    banner = next((bdir / f"banner{e}" for e in (".webp", ".jpg", ".jpeg")
                   if (bdir / f"banner{e}").is_file()), None)
    if banner:
        if banner.stat().st_size > (1 << 20):
            warnings.append(f"branding/{banner.name}: {banner.stat().st_size} bytes exceeds "
                            f"the 1 MiB upstream asset cap — re-run render_visuals.py render-banner")
        copies.append((str(banner.resolve()), f"assets/{banner.name}"))
        course_doc.setdefault("thumbnail", f"assets/{banner.name}")  # academy block wins
        for extra in ("banner.html", "logo.svg"):
            f = bdir / extra
            if f.is_file():
                copies.append((str(f.resolve()), f"visual-src/{extra}"))
        bg = next(iter(sorted(bdir.glob("banner-bg.*"))), None)      # original, not the -blur bake
        if bg:
            copies.append((str(bg.resolve()), f"visual-src/{bg.name}"))
    course_doc["modules"] = [
        {"key": _safe(mod["id"].replace("module-", "")),
         "title": mod.get("title", mod["id"]),
         **({"description": mod["description"]} if mod.get("description") else {}),
         "lessons": [_lesson_id(cfg["prefix"], l["id"]) for l in by_mod.get(mod["id"], [])]}
        for mod in modules
    ]
    files["course.yaml"] = to_yaml(course_doc)

    # slots.lock.json — the on-chain lesson-slot assignment. CONTRIBUTING forbids editing it
    # by hand (CI regenerates and compares), so a new course ships the initial lock: every
    # lesson numbered 0..n-1 in course.yaml order, nothing retired yet. Re-exporting an
    # already-published course must NOT renumber, so preserve any lock already on disk and
    # only append lessons it has never seen.
    ordered = [lid for mod in course_doc["modules"] for lid in mod["lessons"]]
    prev = (out_dir / "slots.lock.json") if out_dir else None
    slots, retired = {}, []
    if prev is not None and prev.is_file():
        try:
            old = json.loads(prev.read_text("utf-8"))
            slots = dict(old.get("slots", {}))
            retired = list(old.get("retired", []))
        except (json.JSONDecodeError, OSError):
            slots, retired = {}, []
    nxt = max([*slots.values(), *retired, -1]) + 1
    for lid in ordered:
        if lid not in slots:
            slots[lid] = nxt
            nxt += 1
    files["slots.lock.json"] = json.dumps(
        {"version": 1, "slots": {k: slots[k] for k in ordered}, "retired": retired, "next": nxt},
        indent=2) + "\n"

    # per-lesson tree
    for l in lessons:
        brief = l.get("brief", {}) or {}
        lid = l["id"]
        slug = _safe(lid)
        mod = next((mm for mm in modules if mm["id"] == l.get("module")), {})
        ldir = f"lessons/{slug}"

        # prose from the written draft, with rendered visuals embedded as images
        stem = _draft_stem(mod_idx.get(l.get("module"), 99), l.get("order", 0), lid)
        draft = course_dir / "lessons" / "drafts" / f"{stem}.md"
        asset_dir = course_dir / "lessons" / "assets" / stem
        imgs = _asset_visuals(asset_dir)
        if draft.is_file():
            text = draft.read_text("utf-8")
            n_specs = sum(1 for ln in text.split("\n") if ln.strip() == "```visual")
            if imgs and len(imgs) != n_specs:
                warnings.append(f"{lid}: {n_specs} visual spec(s) but {len(imgs)} rendered "
                                f"visual(s) in assets/{stem}/ — spec↔render join is positional, re-render")
            files[f"{ldir}/intro.md"] = _prose_from_draft(text, imgs, warnings, lid)
        else:
            warnings.append(f"no draft for {lid} ({stem}.md) — emitting placeholder prose")
            files[f"{ldir}/intro.md"] = f"# {brief.get('title', lid)}\n\n_(draft pending)_\n"
        # every raster in the lesson's asset dir ships beside the lesson: rendered vNN
        # visuals plus any hand-placed image a draft references as ![alt](assets/<name>).
        # HTML sources stay re-renderable under course-level visual-src/ (linter-ignored
        # upstream, never published). PDFs are render intermediates and never ship.
        # A rendered vNN PNG superseded by its .webp sibling stays behind: `imgs` already
        # points the markdown ref at the webp, so shipping the PNG too would be an orphan.
        superseded = {Path(n).with_suffix(".png").name
                      for n in imgs.values() if n.endswith(".webp")}
        if asset_dir.is_dir():
            for img in sorted(asset_dir.iterdir()):
                if img.name in superseded:
                    continue
                if img.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    copies.append((str(img.resolve()), f"{ldir}/assets/{img.name}"))
            for html in sorted(asset_dir.glob("v*.html")):
                # `<name>.__render.html` / `.__safe.html` are render intermediates, written and
                # usually deleted per render. Shipping them would put orphan duplicates in the
                # PR and make the export non-deterministic (the set depends on whether a
                # render was mid-flight), so only the authored source ships. Match the whole
                # `.__*.html` family — an interrupted run leaves whichever stage it died in.
                if re.search(r"\.__[\w-]+\.html$", html.name):
                    continue
                copies.append((str(html.resolve()), f"visual-src/{slug}/{html.name}"))

        blocks: list[dict] = [{"key": "intro", "type": "prose", "src": "intro.md"}]

        # code blocks (coding challenges) — copy source files into <challenge>/
        for cc in brief.get("coding_challenges", []) or []:
            cc = cc or {}
            cid = _safe(cc.get("id", "exercise"))
            lang = cc.get("language")
            if lang not in CHALLENGE_LANGS:
                warnings.append(f"{lid}/{cid}: skipped, language {lang!r} not runnable")
                continue
            ext = EXT[lang]
            blk = {"key": cid, "type": "code", "language": lang}
            if cc.get("buildType") and cc["buildType"] != "standard":
                blk["buildType"] = cc["buildType"]
            if cc.get("deployable"):
                blk["deployable"] = True
            for role, fname in (("starter", f"starter{ext}"), ("solution", f"solution{ext}"),
                                ("tests", "tests.json")):
                rel = str(cc.get(role, "")).strip()
                src = (course_dir / rel)
                dest = f"{ldir}/{cid}/{fname}"
                if rel and src.is_file():
                    copies.append((str(src.resolve()), dest))
                else:
                    warnings.append(f"{lid}/{cid}: {role} file missing ({rel}) — placeholder written")
                    files[dest] = "" if role != "tests" else "[]\n"
                blk[role] = f"{cid}/{fname}"
            if cc.get("hints"):
                blk["hints"] = list(cc["hints"])
            blocks.append(blk)

        # quiz blocks
        for qi, qb in enumerate(brief.get("quiz_blocks", []) or []):
            qb = qb or {}
            key = _safe(qb.get("key") or ("check" if qi == 0 else f"check-{qi + 1}"))
            questions = qb.get("questions") or []
            blocks.append({"key": key, "type": "quiz", "questions": questions})

        lesson_doc = {"id": _lesson_id(cfg["prefix"], lid), "slug": slug,
                      "title": brief.get("title", lid)}
        # content-lint gate-1 (the app's Zod, stricter than the repo's lesson.schema.json)
        # requires `skills` to be an ARRAY on every lesson — an omitted key fails the lesson
        # and cascades into gate-4 "missing lesson" errors. Always emit, empty when unmapped.
        lesson_doc["skills"] = _skills_for(brief, mod, cfg)
        lesson_doc["blocks"] = blocks
        files[f"{ldir}/lesson.yaml"] = to_yaml(lesson_doc)

    # shared stylesheets the visual-src HTML links as ../_brand.css / ../_render.css
    # (the banner links them same-dir; branding/ is the fallback for banner-only courses)
    if any(rel.startswith("visual-src/") for _, rel in copies):
        for css in ("_brand.css", "_render.css"):
            f = course_dir / "lessons" / "assets" / css
            if not f.is_file():
                f = course_dir / "branding" / css
            if f.is_file():
                copies.append((str(f.resolve()), f"visual-src/{css}"))
            else:
                warnings.append(f"visual-src: shared {css} missing from lessons/assets/")

    return files, warnings, copies


def emit(course_dir: str, out_dir: str, opts: dict, force: bool) -> int:
    course_dir = Path(course_dir)
    m = load_manifest(course_dir)
    cfg = _academy_cfg(m, opts)
    out = Path(out_dir)
    files, warnings, copies = plan_academy(course_dir, cfg, m, out_dir=out)
    written = 0
    for rel, content in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, "utf-8")
        written += 1
    for src, rel in copies:
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        written += 1
    for w in warnings:
        print(f"  warn: {w}", file=sys.stderr)
    n_refs = sum(f.count("](assets/") for rel, f in files.items() if rel.endswith("intro.md"))
    n_pngs = sum(1 for _, rel in copies if "/assets/" in rel
                 and rel.endswith((".png", ".webp", ".jpg", ".jpeg", ".gif")))
    print(f"academy emit: {written} files → {out}/  (course {cfg['course_id']}, {len(files)} generated, "
          f"{len(copies)} copied, images {n_refs} referenced/{n_pngs} copied, {len(warnings)} warning(s))")
    if cfg["creator"] == "REPLACE_WITH_YOUR_SOLANA_WALLET":
        print("  NOTE: set course.creator to a real Solana wallet before publishing "
              "(manifest 'academy.creator' or --creator).", file=sys.stderr)
    return 0


def check(course_dir: str, opts: dict) -> int:
    course_dir = Path(course_dir)
    m = load_manifest(course_dir)
    cfg = _academy_cfg(m, opts)
    files, warnings, copies = plan_academy(course_dir, cfg, m)
    n_refs = sum(f.count("](assets/") for rel, f in files.items() if rel.endswith("intro.md"))
    n_pngs = sum(1 for _, rel in copies if "/assets/" in rel
                 and rel.endswith((".png", ".webp", ".jpg", ".jpeg", ".gif")))
    print(f"academy check: course '{cfg['course_id']}' → would write {len(files)} files "
          f"+ copy {len(copies)} file(s); images: {n_refs} referenced / {n_pngs} copied"
          + ("" if n_refs == n_pngs else "  ← MISMATCH"))
    for rel in sorted(files):
        print("   " + rel)
    for _, rel in sorted(copies, key=lambda c: c[1]):
        print("   " + rel + "  (copied)")
    for w in warnings:
        print("  warn: " + w)
    return 0


def selftest() -> int:
    import tempfile
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("PASS" if c else "FAIL") + " - " + m)
        ok = ok and c

    # prose projection: rendered visual -> image embed; unrendered -> blockquote fallback
    src = ("# T\n\nhello\n\n```visual\ntype: diagram\ntitle: the flow\n"
           "alt: a full sentence describing the flow\n```\n\nbye\n")
    proj = _prose_from_draft(src, {1: "v01-diagram.png"})
    chk("hello" in proj and "bye" in proj, "prose preserved")
    chk("![a full sentence describing the flow](assets/v01-diagram.png)" in proj
        and "```visual" not in proj and "> **Visual" not in proj,
        "rendered visual -> markdown image with alt")
    proj = _prose_from_draft(src, {1: "v01-diagram.webp"})
    chk("(assets/v01-diagram.webp)" in proj, "webp sibling is what the markdown ref points at")
    warns: list[str] = []
    proj = _prose_from_draft(src, {}, warns, "l1")
    chk("> **Visual — the flow.**" in proj and "a full sentence" in proj and len(warns) == 1,
        "unrendered visual -> blockquote fallback + warning")

    # html comments: harness annotations stripped from prose, kept inside fenced code
    csrc = ("# T\n\nkeep me\n\n<!-- verify: expect-fail -->\n```ts\n"
            "const tpl = `<!-- not a real comment -->`;\n```\n\n"
            "trailing <!-- inline note --> text\n\n"
            "<!-- a multi-line\nannotation that spans\nthree lines -->\n\nlast line\n")
    cproj = _prose_from_draft(csrc)
    chk("verify: expect-fail" not in cproj, "prose html comment stripped")
    chk("<!-- not a real comment -->" in cproj, "in-fence '<!--' literal survives")
    chk("trailing  text" in cproj and "inline note" not in cproj,
        "inline comment removed, surrounding prose kept")
    chk("annotation that spans" not in cproj and "last line" in cproj,
        "multi-line comment consumed without eating following prose")
    chk("\n\n\n\n" not in cproj, "comment-only lines dropped, not left as blank runs")

    # duration default: derived from length_target.hours (HOURS upstream, never lesson count)
    one_lesson = [{"id": "l1", "module": "m", "order": 1, "brief": {}}]
    chk(_academy_cfg({"course": {"length_target": {"hours": 18}},
                      "lessons": one_lesson}, {})["duration"] == 18,
        "duration defaults to length_target.hours (18)")
    chk(_academy_cfg({"course": {"length_target": {"hours": 17.5}},
                      "lessons": one_lesson}, {})["duration"] == 18,
        "fractional hours >= 1 round up to whole hours")
    chk(_academy_cfg({"course": {"length_target": {"hours": 0.2}},
                      "lessons": one_lesson}, {})["duration"] == 0.2,
        "sub-hour courses keep the fractional value (card shows '0.2 hours')")
    chk(_academy_cfg({"course": {}, "lessons": one_lesson}, {})["duration"] == 1,
        "no estimate at all falls back to the lesson count")
    chk(_academy_cfg({"course": {"length_target": {"hours": 2}}, "lessons": one_lesson,
                      "academy": {"duration": 5}}, {})["duration"] == 5,
        "an explicit academy.duration wins over the derivation")

    man = {
        "schema_version": 1,
        "course": {"id": "demo-course", "title": "Demo", "one_line_promise": "Do X.",
                   "length_target": {"hours": 6}},
        "academy": {"prefix": "dm", "creator": "Wa11etDemo1111111111111111111111111111111",
                    "skills_map": {"account-model": "account-model"}, "default_skills": []},
        "modules": [{"id": "module-intro", "title": "Intro", "teaches_skills": ["account-model"]},
                    {"id": "module-extra", "title": "Extra", "teaches_skills": ["unmapped-node"]}],
        "lessons": [{"id": "the-basics", "module": "module-intro", "order": 1, "brief": {
            "title": "The Basics",
            "coding_challenges": [{"id": "add-two", "language": "rust", "buildType": "standard",
                                   "starter": "ch/starter.rs", "solution": "ch/solution.rs",
                                   "tests": "ch/tests.json", "acceptance_criteria": ["adds"]}],
            "quiz_blocks": [{"key": "check", "questions": [
                {"id": "q1", "prompt": "unit?", "options": [
                    {"id": "a", "label": "gwei", "correct": False, "feedback": "no"},
                    {"id": "b", "label": "lamport", "correct": True}],
                 "explanation": "1e9"}]}]}},
                    {"id": "loose-ends", "module": "module-extra", "order": 1,
                     "brief": {"title": "Loose Ends"}}],
    }
    with tempfile.TemporaryDirectory() as td:
        cdir = Path(td) / "course"
        (cdir / "lessons" / "drafts").mkdir(parents=True)
        (cdir / "lessons" / "drafts" / "m00-l1-the-basics.md").write_text(
            "# The Basics\n\nbody words here\n\n```visual\ntype: diagram\ntitle: the flow\n"
            "alt: the whole flow at a glance\n```\n\n```visual\ntype: table\ntitle: unrendered\n"
            "```\n\n```visual\ntype: table\ntitle: the sizes\nalt: sizes side by side\n```\n"
            "\nmore words\n", "utf-8")
        adir = cdir / "lessons" / "assets" / "m00-l1-the-basics"
        adir.mkdir(parents=True)
        (adir / "v01-diagram.png").write_bytes(b"\x89PNG fake")
        (adir / "v01-diagram.webp").write_bytes(b"RIFF fake webp")   # supersedes the PNG
        (adir / "v03-table.png").write_bytes(b"\x89PNG no webp sibling")
        (adir / "v01-diagram.html").write_text("<html>viz</html>", "utf-8")
        (adir / "fonte-externa.png").write_bytes(b"\x89PNG photo")
        (adir / "v01-diagram.pdf").write_bytes(b"%PDF intermediate")
        (cdir / "lessons" / "assets" / "_brand.css").write_text(":root{}", "utf-8")
        (cdir / "lessons" / "assets" / "_render.css").write_text(".viz{}", "utf-8")
        (cdir / "ch").mkdir()
        (cdir / "ch" / "starter.rs").write_text("fn add(a:i64,b:i64)->i64{0}\n", "utf-8")
        (cdir / "ch" / "solution.rs").write_text("fn add(a:i64,b:i64)->i64{a+b}\n", "utf-8")
        (cdir / "ch" / "tests.json").write_text('[{"id":"t1","input":"2, 3","expectedOutput":"5"}]', "utf-8")
        bdir = cdir / "branding"
        bdir.mkdir()
        (bdir / "banner.webp").write_bytes(b"RIFF fake webp")
        (bdir / "banner.png").write_bytes(b"\x89PNG full-res intermediate")
        (bdir / "banner.html").write_text("<html>banner</html>", "utf-8")
        (bdir / "logo.svg").write_text("<svg/>", "utf-8")
        (bdir / "banner-bg.png").write_bytes(b"\x89PNG photo")
        (bdir / "banner-bg-blur.png").write_bytes(b"\x89PNG blur bake")
        (cdir / "manifest.json").write_text(json.dumps(man), "utf-8")
        out = Path(td) / "academy"
        emit(str(cdir), str(out), opts={}, force=True)

        cy = (out / "course.yaml").read_text()
        chk("id: course-demo-course" in cy and "lesson-dm-the-basics" in cy, "course.yaml ids")
        ly = (out / "lessons" / "the-basics" / "lesson.yaml").read_text()
        chk("id: lesson-dm-the-basics" in ly, "lesson id")
        chk("type: prose" in ly and "type: code" in ly and "type: quiz" in ly, "three block types")
        chk("account-model" in ly, "skills mapped from dag node")
        ly2 = (out / "lessons" / "loose-ends" / "lesson.yaml").read_text()
        chk("skills: []" in ly2, "unmapped lesson still emits skills as an EMPTY ARRAY "
            "(content-lint gate-1 rejects an omitted key)")
        chk("starter: add-two/starter.rs" in ly, "code block references copied starter")
        chk((out / "lessons" / "the-basics" / "add-two" / "starter.rs").is_file()
            and (out / "lessons" / "the-basics" / "add-two" / "solution.rs").is_file()
            and (out / "lessons" / "the-basics" / "add-two" / "tests.json").is_file(),
            "challenge source files copied")
        intro = (out / "lessons" / "the-basics" / "intro.md").read_text()
        chk(intro.startswith("# The Basics"), "intro.md carries the draft prose")
        chk("![the whole flow at a glance](assets/v01-diagram.webp)" in intro,
            "rendered visual embedded as image in intro.md, webp preferred over its PNG")
        chk("> **Visual — unrendered.**" in intro, "unrendered visual falls back to blockquote")
        chk("![sizes side by side](assets/v03-table.png)" in intro,
            "a visual with no webp sibling still references its PNG")
        lassets = out / "lessons" / "the-basics" / "assets"
        chk((lassets / "v01-diagram.webp").is_file() and not (lassets / "v01-diagram.png").exists(),
            "webp shipped, the PNG it supersedes left behind (no orphan)")
        chk((lassets / "v03-table.png").is_file(), "png-only visual copied beside the lesson")
        chk((out / "lessons" / "the-basics" / "assets" / "fonte-externa.png").is_file()
            and not (out / "lessons" / "the-basics" / "assets" / "v01-diagram.pdf").exists(),
            "hand-placed image copied; PDF intermediate not shipped")
        chk((out / "visual-src" / "the-basics" / "v01-diagram.html").is_file()
            and (out / "visual-src" / "_brand.css").is_file()
            and (out / "visual-src" / "_render.css").is_file(),
            "HTML source + shared css exported under visual-src/")
        chk("duration: 6" in cy, "course duration derived from length_target.hours")
        chk("thumbnail: assets/banner.webp" in cy, "banner detected -> thumbnail in course.yaml")
        chk((out / "assets" / "banner.webp").is_file()
            and not (out / "assets" / "banner.png").exists(),
            "compressed banner copied; full-res banner.png never ships")
        chk((out / "visual-src" / "banner.html").is_file()
            and (out / "visual-src" / "logo.svg").is_file()
            and (out / "visual-src" / "banner-bg.png").is_file()
            and not (out / "visual-src" / "banner-bg-blur.png").exists(),
            "banner source + logo + original bg (not the blur bake) under visual-src/")

    print("\n" + ("ACADEMY_EXPORT SELFTESTS PASSED" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="project a course into the Academy publish tree")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("emit", "check"):
        p = sub.add_parser(name)
        p.add_argument("--course", required=True, help="internal course dir (reads manifest.json + drafts)")
        if name == "emit":
            p.add_argument("--out", required=True, help="academy output dir (e.g. content/academy/courses/<slug>)")
            p.add_argument("--force", action="store_true")
        for flag in ("course-id", "slug", "prefix", "creator", "difficulty"):
            p.add_argument(f"--{flag}")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd not in ("emit", "check"):
        ap.print_help(); return 2
    opts = {k: getattr(a, k) for k in ("course_id", "slug", "prefix", "creator", "difficulty")
            if getattr(a, k, None)}
    if a.cmd == "emit":
        return emit(a.course, a.out, opts, a.force)
    return check(a.course, opts)


if __name__ == "__main__":
    raise SystemExit(main())
