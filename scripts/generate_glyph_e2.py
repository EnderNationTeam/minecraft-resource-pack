#!/usr/bin/env python3
"""
Generate bedrock/font/glyph_E2.png from the Java font definitions in
java/assets/minecraft/font/default.json.

The Bedrock glyph page is a 1200x1200 RGBA atlas divided into a 16x16 grid.
Each 75x75 cell corresponds to Unicode character U+E2XX where
  col = XX & 0x0F  (lower nibble)
  row = XX >> 4    (upper nibble)

Uses ImageMagick (magick) for all image operations
"""

import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_JSON = os.path.join(REPO_ROOT, "java/assets/minecraft/font/default.json")
OUTPUT = os.path.join(REPO_ROOT, "bedrock/font/glyph_E2.png")
JAVA_ASSETS = os.path.join(REPO_ROOT, "java/assets")

CELL = 75       # pixels per glyph cell  (75 * 16 = 1200)
GRID = 16       # cells per row/column
IMG_SIZE = CELL * GRID


def resolve_path(file_ref: str) -> str | None:
    """
    Resolve a Java bitmap font file reference (namespace:path) to an
    absolute filesystem path, with fallback for mismatched paths in this pack.
    """
    ns, rel = file_ref.split(":", 1)
    candidates = [
        os.path.join(JAVA_ASSETS, ns, "textures", rel),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def magick(*args: str) -> None:
    cmd = ["magick", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] magick {' '.join(args[:4])!r}...\n  {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError("ImageMagick command failed")


def main() -> None:
    with open(FONT_JSON, encoding="utf-8") as f:
        font_data = json.load(f)

    # Collect all E2xx glyph entries from the font JSON
    glyphs: dict[int, dict] = {}   # xx (0x00-0xFF) -> info dict

    for provider in font_data["providers"]:
        if provider["type"] != "bitmap":
            continue

        chars = provider["chars"]  # list of strings (rows)
        file_ref = provider["file"]
        total_rows = len(chars)
        total_cols = max(len(row) for row in chars) if chars else 1

        for img_row_idx, row_str in enumerate(chars):
            for img_col_idx, ch in enumerate(row_str):
                code = ord(ch)
                if 0xE200 <= code <= 0xE2FF:
                    xx = code - 0xE200
                    glyphs[xx] = {
                        "file_ref": file_ref,
                        "img_row": img_row_idx,
                        "img_col": img_col_idx,
                        "total_rows": total_rows,
                        "total_cols": total_cols,
                    }

    print(f"Found {len(glyphs)} E2xx glyphs defined in default.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        canvas_path = os.path.join(tmpdir, "canvas.png")
        magick("-size", f"{IMG_SIZE}x{IMG_SIZE}", "xc:none",
               "-type", "TrueColorAlpha", "-define", "png:color-type=6", canvas_path)

        current = canvas_path

        for xx in sorted(glyphs.keys()):
            info = glyphs[xx]
            dest_col = xx & 0x0F
            dest_row = xx >> 4
            dest_x = dest_col * CELL
            dest_y = dest_row * CELL

            src_path = resolve_path(info["file_ref"])
            if src_path is None:
                print(f"  [WARN] U+E2{xx:02X}: source not found: {info['file_ref']}")
                continue

            # Determine crop geometry for this glyph within the source image
            img_row = info["img_row"]
            img_col = info["img_col"]
            total_rows = info["total_rows"]
            total_cols = info["total_cols"]

            # Get source image dimensions via ImageMagick
            result = subprocess.run(
                ["magick", "identify", "-format", "%wx%h", src_path],
                capture_output=True, text=True, check=True
            )
            src_w, src_h = map(int, result.stdout.strip().split("x"))

            cell_w = src_w // total_cols
            cell_h = src_h // total_rows
            crop_x = img_col * cell_w
            crop_y = img_row * cell_h

            # Composite this glyph cell onto the canvas:
            # 1. Crop the cell from the source image
            # 2. Resize to fit within CELL×CELL (maintain aspect ratio)
            # 3. Center it within the CELL×CELL area
            next_canvas = os.path.join(tmpdir, f"step_{xx:02X}.png")

            magick(
                current,
                "(",
                    src_path,
                    "-crop", f"{cell_w}x{cell_h}+{crop_x}+{crop_y}",
                    "+repage",
                    "-filter", "Point",
                    "-resize", f"{CELL}x{CELL}>",        # shrink-only, keep AR, nearest-neighbor
                    "-background", "none",
                    "-gravity", "Center",
                    "-extent", f"{CELL}x{CELL}",         # pad to full cell size, centered
                ")",
                "-gravity", "NorthWest",
                "-geometry", f"+{dest_x}+{dest_y}",      # place at cell top-left
                "-composite",
                "-type", "TrueColorAlpha", "-define", "png:color-type=6",
                next_canvas,
            )
            current = next_canvas
            print(f"  U+E2{xx:02X} → cell ({dest_col},{dest_row}) from {os.path.basename(src_path)} row={img_row} col={img_col}")

        import shutil
        shutil.copy2(current, OUTPUT)

    print(f"\nDone! Written to {OUTPUT}")


if __name__ == "__main__":
    main()
