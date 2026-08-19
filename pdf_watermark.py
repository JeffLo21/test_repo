# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pypdf>=5.0",
#     "reportlab>=4.0",
#     "pillow>=10.0",
#     "flask>=3.0",
# ]
# ///

"""Add a text or image watermark to a PDF. Run with: uv run pdf_watermark.py"""

import argparse
import io
import re
import sys
import uuid
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import toColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas as rl_canvas
from PIL import Image

POSITIONS = ["center", "tile", "top-left", "top-right", "bottom-left", "bottom-right"]
CJK_FONT = "MSung-Light"  # built-in reportlab CID font covering Traditional Chinese


def parse_page_ranges(spec: str, page_count: int) -> set[int]:
    if spec.lower() == "all":
        return set(range(page_count))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start) - 1, int(end)))
        else:
            pages.add(int(part) - 1)
    return {p for p in pages if 0 <= p < page_count}


def resolve_font(text: str, requested: str | None) -> str:
    if requested:
        return requested
    if any(ord(ch) > 0x2E80 for ch in text):
        pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))
        return CJK_FONT
    return "Helvetica-Bold"


def anchor_point(width, height, position, box_w, box_h, margin=40):
    return {
        "center": (width / 2, height / 2),
        "top-left": (box_w / 2 + margin, height - box_h / 2 - margin),
        "top-right": (width - box_w / 2 - margin, height - box_h / 2 - margin),
        "bottom-left": (box_w / 2 + margin, box_h / 2 + margin),
        "bottom-right": (width - box_w / 2 - margin, box_h / 2 + margin),
    }[position]


def build_text_overlay(width, height, text, opacity, rotation, font_size, color, position, font_name):
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(width, height))
    font_name = resolve_font(text, font_name)
    c.setFont(font_name, font_size)
    c.setFillColor(toColor(color), alpha=opacity)

    if position == "tile":
        text_w = c.stringWidth(text, font_name, font_size)
        step_x, step_y = text_w + font_size * 3, font_size * 6
        y = -height
        while y < height * 2:
            x = -width
            while x < width * 2:
                c.saveState()
                c.translate(x, y)
                c.rotate(rotation)
                c.drawString(0, 0, text)
                c.restoreState()
                x += step_x
            y += step_y
    else:
        text_w = c.stringWidth(text, font_name, font_size)
        x, y = anchor_point(width, height, position, text_w, font_size)
        c.saveState()
        c.translate(x, y)
        c.rotate(rotation)
        c.drawCentredString(0, 0, text)
        c.restoreState()

    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def build_image_overlay(width, height, image_path, opacity, scale, position, rotation):
    img = Image.open(image_path).convert("RGBA")
    r, g, b, a = img.split()
    img.putalpha(a.point(lambda p: int(p * opacity)))

    img_w, img_h = img.size
    ratio = min(width * scale / img_w, height * scale / img_h, 1.0)
    draw_w, draw_h = img_w * ratio, img_h * ratio

    png_buf = io.BytesIO()
    img.save(png_buf, format="PNG")
    png_buf.seek(0)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(width, height))
    x, y = anchor_point(width, height, position, draw_w, draw_h)
    c.saveState()
    c.translate(x, y)
    c.rotate(rotation)
    c.drawImage(ImageReader(png_buf), -draw_w / 2, -draw_h / 2, width=draw_w, height=draw_h, mask="auto")
    c.restoreState()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def add_watermark(input_path: Path, output_path: Path, pages_spec: str, build_overlay):
    reader = PdfReader(input_path)
    writer = PdfWriter()
    target_pages = parse_page_ranges(pages_spec, len(reader.pages))

    for i, page in enumerate(reader.pages):
        if i in target_pages:
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            page.merge_page(build_overlay(width, height))
        writer.add_page(page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        writer.write(f)


CACHE_DIR = Path(__file__).resolve().parent / "cache"
FRONT_END_DIR = Path(__file__).resolve().parent / "front_end"
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

UPLOADS: dict[str, Path] = {}
RESULTS: dict[str, tuple[Path, str]] = {}


def safe_display_stem(name: str) -> str:
    stem = Path(name).stem
    stem = _ILLEGAL_CHARS.sub("_", stem)
    stem = stem.strip().strip(".") or "watermark"
    return stem[:100]


def create_app():
    from flask import Flask, jsonify, request, send_file

    app = Flask(__name__, static_folder=str(FRONT_END_DIR), static_url_path="")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.post("/api/upload")
    def upload():
        file = request.files.get("pdf")
        if not file or not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "請上傳一個 .pdf 檔案"}), 400

        file_id = uuid.uuid4().hex
        saved_path = CACHE_DIR / f"{file_id}.pdf"
        file.save(saved_path)

        try:
            PdfReader(saved_path)
        except Exception:
            saved_path.unlink(missing_ok=True)
            return jsonify({"error": "不是有效的 PDF 檔案"}), 400

        UPLOADS[file_id] = saved_path
        return jsonify({"file_id": file_id, "stem": safe_display_stem(file.filename)})

    @app.post("/api/watermark")
    def watermark():
        data = request.get_json(silent=True) or {}
        file_id = data.get("file_id")
        input_path = UPLOADS.get(file_id)
        if not input_path:
            return jsonify({"error": "找不到上傳的檔案，請重新上傳"}), 404

        text = (data.get("text") or "").strip() or "Confidential"
        output_name = safe_display_stem(data.get("output_name") or "watermark")
        download_name = f"{output_name}.pdf"

        result_id = uuid.uuid4().hex
        result_path = CACHE_DIR / f"{result_id}.pdf"

        def build_overlay(width, height):
            return build_text_overlay(width, height, text, 0.3, 45, 40, "gray", "center", None)

        try:
            add_watermark(input_path, result_path, "all", build_overlay)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        RESULTS[result_id] = (result_path, download_name)
        return jsonify({
            "result_id": result_id,
            "download_name": download_name,
            "download_url": f"/api/download/{result_id}",
        })

    @app.get("/api/download/<result_id>")
    def download(result_id):
        entry = RESULTS.get(result_id)
        if not entry or not entry[0].exists():
            return jsonify({"error": "找不到處理結果，請重新處理"}), 404
        result_path, download_name = entry
        return send_file(result_path, mimetype="application/pdf",
                          as_attachment=True, download_name=download_name)

    return app


def run_web_server():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    app = create_app()
    print("Watermark web UI running at http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=5050, threaded=True)


def main():
    if len(sys.argv) == 1:
        run_web_server()
        return

    parser = argparse.ArgumentParser(description="Add a text or image watermark to a PDF.")
    parser.add_argument("input", type=Path, help="Input PDF file")
    parser.add_argument("-o", "--output", type=Path, help="Output PDF file (default: <input>_wm.pdf)")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--text", help="Watermark text (CJK text is handled automatically; default: Confidential)")
    group.add_argument("--image", type=Path, help="Watermark image file (PNG/JPG)")

    parser.add_argument("--opacity", type=float, default=0.3, help="Opacity 0.0-1.0 (default: 0.3)")
    parser.add_argument("--rotation", type=float, default=45, help="Rotation angle in degrees (default: 45)")
    parser.add_argument("--font-size", type=float, default=40, help="Text font size (default: 40)")
    parser.add_argument("--font", default=None, help="Text font (default: Helvetica-Bold, auto-switches to a CJK font for Chinese text)")
    parser.add_argument("--color", default="gray", help="Text color, name or hex, e.g. gray or #FF0000 (default: gray)")
    parser.add_argument("--scale", type=float, default=0.5, help="Image max size as fraction of page (default: 0.5)")
    parser.add_argument("--position", choices=POSITIONS, default="center",
                         help="Watermark position; 'tile' repeats across the page and only applies to --text (default: center)")
    parser.add_argument("--pages", default="all", help='Pages to watermark, e.g. "1,3,5-7" (default: all)')

    args = parser.parse_args()

    if not 0.0 <= args.opacity <= 1.0:
        parser.error("--opacity must be between 0.0 and 1.0")
    if not args.input.exists():
        parser.error(f"Input file not found: {args.input}")
    if args.image and not args.image.exists():
        parser.error(f"Image file not found: {args.image}")
    if not args.text and not args.image:
        args.text = "Confidential"

    output = args.output or args.input.with_stem(args.input.stem + "_wm")

    if args.text:
        def build_overlay(width, height):
            return build_text_overlay(width, height, args.text, args.opacity, args.rotation,
                                       args.font_size, args.color, args.position, args.font)
    else:
        position = "center" if args.position == "tile" else args.position

        def build_overlay(width, height):
            return build_image_overlay(width, height, args.image, args.opacity, args.scale, position, args.rotation)

    add_watermark(args.input, output, args.pages, build_overlay)
    print(f"Watermarked PDF saved to: {output}")


if __name__ == "__main__":
    main()
