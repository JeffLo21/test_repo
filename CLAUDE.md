# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Single-file Python CLI (`pdf_watermark.py`) that adds a text or image watermark to a PDF. There is no package manifest, build system, or test suite — the whole project is this one script plus sample PDFs used for manual verification.

## Running the script

Dependencies (`pypdf`, `reportlab`, `pillow`) are declared inline in the script's PEP 723 header (lines 1-8), not in a `requirements.txt` or `pyproject.toml`. Always run it with `uv run`, never plain `python` — a bare `python pdf_watermark.py` will fail with `ModuleNotFoundError` because nothing installs the dependencies into the system interpreter.

```
uv run pdf_watermark.py input.pdf [options]
```

This machine's network intercepts TLS for PyPI, so `uv` needs system certs. This is already set globally via the user env var `UV_SYSTEM_CERTS=true`; if a fresh shell doesn't have it, pass `--system-certs` explicitly:

```
uv run --system-certs pdf_watermark.py input.pdf
```

Key CLI options: `--text` (default `"Confidential"` if neither `--text` nor `--image` given), `--image`, `--opacity`, `--rotation`, `--font-size`, `--font`, `--color`, `--scale` (image only), `--position` (`center`/`tile`/four corners — `tile` is text-only), `--pages` (e.g. `"1,3,5-7"`, default `all`), `-o/--output` (default `<input>_wm.pdf`).

## Architecture

The script has one core pipeline, `add_watermark()`, that pypdf drives page-by-page:

1. For each target page (from `parse_page_ranges`), read that page's own `mediabox` width/height — pages in the same PDF can have different sizes, so the watermark overlay is built per-page rather than once for the whole document.
2. Build a one-page watermark overlay sized to match, using a reportlab `Canvas` in memory (`build_text_overlay` or `build_image_overlay`), then `page.merge_page()` it onto the original page.
3. Write all pages (watermarked and untouched) via `PdfWriter`.

`main()` builds a `build_overlay(width, height)` closure over the parsed args and passes it into `add_watermark`, so the overlay builders never see argparse directly.

Text and image overlays share `anchor_point()` for the five fixed positions (center + 4 corners); `tile` mode is handled separately inside `build_text_overlay` by looping a translate/rotate/draw grid across a padded area (`-width..2*width`, `-height..2*height`) so rotated repeats still cover the full page after rotation.

## Gotchas specific to this script

- **CJK text**: `resolve_font()` auto-switches to a CID font when the watermark text contains characters above `0x2E80`, since the default `Helvetica-Bold` base-14 font has no CJK glyphs. The font name is `MSung-Light` — check `reportlab.pdfbase.cidfonts.defaultUnicodeEncodings` before changing it; the installed reportlab version only recognizes a fixed short list of CID font names (`HeiseiMin-W3`, `HeiseiKakuGo-W5`, `STSong-Light`, `MSung-Light`, `HYSMyeongJo-Medium`, `HYGothic-Medium`), not arbitrary CJK font names.
- **Opacity on images**: applied by multiplying the alpha channel in PIL before embedding (`build_image_overlay`), not via reportlab fill-alpha, since that only affects vector fills/strokes.
- **No automated tests**: verify changes by generating a throwaway sample PDF with reportlab (including one with mixed page sizes, e.g. A4/A3/Letter/landscape, to exercise the per-page sizing path), running the script against it, and checking with `pypdf` that each output page's `mediabox` still matches the original and that the watermark text/image is present — then delete the scratch files.
