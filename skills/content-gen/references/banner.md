# Course banner — the Academy thumbnail

The one **course-level** visual: the image the Academy course card shows at 400×225
(and the `/cover.png` fallback replaces when absent). Everything lives in
`content/courses/<id>/branding/` (gitignored with the course).

## The standard: the art, plus the mark

Since 2026-09 a banner is **the course art with the Superteam mark in the top-right
corner, and nothing else**.

```
cp <course-art>.png content/courses/<id>/branding/banner-bg.png
python3 tools/render_visuals.py banner content/courses/<id>
#   -> branding/banner.png   (1600x900 lossless, for the eyeball review — never ships)
#   -> branding/banner.webp  (1600x900, <=1MiB — what the export picks up)
python3 tools/academy_export.py emit --course ... --out ...   # thumbnail: assets/banner.webp
```

One command, Pillow only. No HTML to author, no WeasyPrint, no rasterizer.

**Why no title on the image.** The card already prints the title, level, lesson count
and XP beside the thumbnail, straight from `course.yaml`. A second copy inside the image
was the copy nothing recomputed: rename a course or reprice its XP and the card updates
while the thumbnail keeps asserting the old value. The image now carries the one thing
`course.yaml` cannot: what the course *looks* like, and who made it.

### What the tool does

1. **Cover-crop** the art to 1600×900 — scale to cover, centre-crop. Fills the canvas,
   never distorts, never letterboxes. Art smaller than the canvas is upscaled and the
   output line says so.
2. **Composite the mark** at 17% of the canvas width, inset 4.5% from the top and right
   edges. The mark is `brand/assets/logos/horizontal-<variant>.png`, alpha-composited —
   no scrim, no plate, no shadow.
3. **Pick the variant by contrast.** `--logo auto` (the default) measures the mean
   luminance of the rectangle the mark will cover and takes whichever of cream / dark /
   emerald has the higher WCAG contrast ratio against it. The choice and the ratio are
   printed. A mean is a proxy — a mark over busy art has no single background — so when
   the eye disagrees, override with `--logo cream|dark|emerald`.
4. **Compress** on a quality ladder until the file is under the upstream 1 MiB cap, and
   FAIL rather than ship over it.

### Flags

| Flag | Default | For |
|---|---|---|
| `--in <image>` | `branding/banner-bg.*` | run on art that is not in the course yet |
| `--out <file.webp>` | `branding/banner.webp` | write somewhere else (`.png` review copy lands beside it) |
| `--logo cream\|dark\|emerald` | `auto` | override the contrast pick |
| `--logo-file <png\|svg>` | shipped mark | a different mark entirely (SVG needs `cairosvg`) |
| `--logo-width 0.17` | 0.17 | mark width as a fraction of 1600px |
| `--margin 0.045` | 0.045 | top/right inset, same fraction |
| `--no-logo` | off | art only, unbranded |

With `--in` and `--out` the course directory is optional, so the command also works as a
one-off on a loose file.

### Review

Look at `branding/banner.png` before exporting, and look at it **small** — the card is
400px wide. The mark should read at that size without hunting for it, and it should not
land on the busiest part of the art. When it does, the fix is the art (re-crop, or
regenerate with the top-right corner kept calm), not a scrim behind the mark.

## Legacy: the composed title card

The pre-2026-09 banner — an authored HTML card rendered through WeasyPrint: cream card
over a pre-blurred photo, title, and level / lessons+hours / XP pills. **Still works, and
courses already authored this way keep rendering.** New courses should use the standard
above.

```
python3 tools/render_visuals.py scaffold-banner content/courses/<id>
#   ... author branding/banner.html: eyebrow, title, pill texts; delete the TODO marker ...
python3 tools/render_visuals.py render-banner   content/courses/<id>
```

`scaffold-banner` keeps an authored `banner.html` (no `TODO(render)` marker) — delete
the file or re-add the marker to reset. It also drops `_brand.css`, `_render.css`, and
`logo.svg` beside the banner so the HTML is self-contained and re-renderable.

**Two modes.**

- **Photo mode** (a `branding/banner-bg.{png,jpg,jpeg,webp}` exists): the photo is placed
  as an `<img class="bg">` **element**, not `background-image: url()` (which stays
  forbidden CSS). Because **WeasyPrint has no `filter`/`backdrop-filter`**, any blur or
  darkening is pre-baked by `render-banner` (Pillow: cover-crop to 1600×900, then blur +
  brightness). The banner HTML declares its own backdrop treatment with a directive:

      <!-- banner-bg: blur=0 brightness=1.0 file=banner-bg-sharp.png -->

  `blur`/`brightness` feed the bake; `file` is the baked filename the HTML's
  `<img class="bg">` must reference. No directive = the heavy title-card treatment
  (blur 14, brightness 0.72, `banner-bg-blur.png`). "Liquid glass" panels are faked:
  translucent fill + hairline light border + a gradient sheen (`background-color` rgba +
  `background-image: linear-gradient(...)`), which reads as glass over the photo.
- **Pure-brand mode** (no photo): cream page + the per-course `.stbr-decor` blob layer +
  a white card — the standard visual house style, so any course gets a banner even
  without art.

Composition variants: explore beside the main file (`branding/banner-<variant>.html`) and
render each with `render-banner <course> --html branding/banner-<variant>.html` (outputs
`<stem>.png/.webp` beside it, never picked up by the export); promote the winner by
copying it over `banner.html`.

**Card anatomy (what you author).**

- `.stbr-eyebrow` — short kicker, e.g. `// SOLANA CORE`. Uppercase, emerald.
- `logo.svg` — the Superteam mark, `horizontal-emerald.svg` by default (the cream logo
  vanishes on the cream card). Swap the file in `branding/` to rebrand.
- `.card-title` — Archivo Black ~82px. The banner is judged at 400px wide: keep it
  punchy, break lines deliberately with `<br>`, shrink a couple of px only if a long
  title needs it.
- `.meta` pills — level pill (emerald), `NN LESSONS · NN HOURS` stat pill (outline;
  match the course language), XP pill (yellow) with the **inline-SVG bolt — never the ⚡
  emoji** (Pango emoji fallback is unreliable under WeasyPrint).
- Match the pill texts to the manifest: `academy.difficulty`, lesson count,
  `academy.duration` (hours — see academy-schema.md), `academy.xpReward`. This coupling is
  exactly what the standard banner drops.

Review `branding/banner.png` before exporting: title legible at 25% zoom, pills on one
line, logo not cramped, blur strong enough that backdrop detail doesn't fight the title,
fonts actually Archivo/Inter (Google Fonts `@import` needs network at render time — a
fallback-font render looks subtly wrong).

## Contract (upstream)

Identical for both paths: a 1600×900 render (16:9), shipped as `banner.webp` ≤ **1 MiB**
(platform hard cap; both commands compress on a quality ladder and FAIL past the cap).
The export emits `thumbnail: assets/banner.webp` in `course.yaml` and ships the original
`banner-bg.*` — plus `banner.html` + `logo.svg` when the legacy path authored them — to
linter-ignored `visual-src/` so the banner stays re-renderable. `branding/banner.png`
(the full-res review copy) and `banner-bg-blur.png` (a legacy bake) never ship.
