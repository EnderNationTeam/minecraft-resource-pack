#!/usr/bin/env python3
"""
Generate bedrock/font/glyph_E2.png from the Java font definitions in
java/assets/minecraft/font/default.json.

The Bedrock glyph page is a 1200x1200 RGBA atlas divided into a 16x16 grid.
Each 75x75 cell corresponds to Unicode character U+E2XX where
  col = XX & 0x0F  (lower nibble)
  row = XX >> 4    (upper nibble)

Uses ImageMagick (magick) for all image operations.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_JSON = os.path.join(REPO_ROOT, "java/assets/minecraft/font/default.json")
OUTPUT    = os.path.join(REPO_ROOT, "bedrock/font/glyph_E2.png")
JAVA_ASSETS = os.path.join(REPO_ROOT, "java/assets")

CELL     = 160
GRID     = 16
IMG_SIZE = CELL * GRID
MAX_UPSCALE = 2.0
MIN_SCALABLE_DIMENSION = 2

def resolve_java_texture(file_ref: str) -> Optional[str]:
    """Resolve a 'namespace:path' font file reference to an absolute path."""
    ns, rel = file_ref.split(":", 1)
    path = os.path.join(JAVA_ASSETS, ns, "textures", rel)
    return path if os.path.exists(path) else None


def magick(*args: str) -> None:
    result = subprocess.run(["magick", *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] magick {' '.join(args[:4])!r}...\n  {result.stderr.strip()}", file=sys.stderr)
        raise RuntimeError("ImageMagick command failed")


def get_image_dimensions(path: str) -> tuple[int, int]:
    result = subprocess.run(
        ["magick", "identify", "-format", "%wx%h", path],
        capture_output=True, text=True, check=True,
    )
    w, h = result.stdout.strip().split("x")
    return int(w), int(h)


def get_trimmed_dimensions(src_path: str, crop: tuple[int, int, int, int]) -> tuple[int, int]:
    cell_w, cell_h, crop_x, crop_y = crop
    result = subprocess.run(
        [
            "magick",
            src_path,
            "-crop", f"{cell_w}x{cell_h}+{crop_x}+{crop_y}",
            "+repage",
            "-trim",
            "+repage",
            "-format", "%wx%h",
            "info:",
        ],
        capture_output=True, text=True, check=True,
    )
    width, height = result.stdout.strip().split("x")
    return int(width), int(height)


def get_target_dimensions(trimmed_w: int, trimmed_h: int) -> tuple[int, int]:
    if trimmed_w <= MIN_SCALABLE_DIMENSION and trimmed_h <= MIN_SCALABLE_DIMENSION:
        return trimmed_w, trimmed_h

    scale = min(CELL / trimmed_w, CELL / trimmed_h)
    if scale > 1:
        scale = min(scale, MAX_UPSCALE)

    target_w = max(1, round(trimmed_w * scale))
    target_h = max(1, round(trimmed_h * scale))
    return target_w, target_h


def collect_e2_glyphs(font_data: dict) -> dict[int, dict]:
    glyphs: dict[int, dict] = {}
    for provider in font_data["providers"]:
        if provider["type"] != "bitmap":
            continue
        chars = provider["chars"]
        file_ref = provider["file"]
        total_rows = len(chars)
        total_cols = max(len(row) for row in chars) if chars else 1
        for row_idx, row_str in enumerate(chars):
            for col_idx, ch in enumerate(row_str):
                code = ord(ch)
                if 0xE200 <= code <= 0xE2FF:
                    glyphs[code - 0xE200] = {
                        "file_ref":   file_ref,
                        "img_row":    row_idx,
                        "img_col":    col_idx,
                        "total_rows": total_rows,
                        "total_cols": total_cols,
                    }
    return glyphs


def create_blank_canvas(path: str) -> None:
    magick("-size", f"{IMG_SIZE}x{IMG_SIZE}", "xc:none",
           "-type", "TrueColorAlpha", "-define", "png:color-type=6", path)


def composite_glyph(canvas: str, src_path: str, crop: tuple[int, int, int, int],
                    dest: tuple[int, int], output: str) -> None:
    cell_w, cell_h, crop_x, crop_y = crop
    dest_x, dest_y = dest
    trimmed_w, trimmed_h = get_trimmed_dimensions(src_path, crop)
    target_w, target_h = get_target_dimensions(trimmed_w, trimmed_h)
    offset_x = dest_x + max(0, (CELL - target_w) // 2)
    offset_y = dest_y + max(0, (CELL - target_h) // 2)
    magick(
        canvas,
        "(",
            src_path,
            "-crop", f"{cell_w}x{cell_h}+{crop_x}+{crop_y}",
            "+repage",
            "-trim", "+repage",
            "-filter", "Point",
            "-resize", f"{target_w}x{target_h}!",
            "-background", "none",
        ")",
        "-gravity", "NorthWest",
        "-geometry", f"+{offset_x}+{offset_y}",
        "-composite",
        "-type", "TrueColorAlpha", "-define", "png:color-type=6",
        output,
    )


def main() -> None:
    with open(FONT_JSON, encoding="utf-8") as f:
        font_data = json.load(f)

    glyphs = collect_e2_glyphs(font_data)
    print(f"Found {len(glyphs)} E2xx glyphs defined in default.json")

    with tempfile.TemporaryDirectory() as tmpdir:
        canvas = os.path.join(tmpdir, "canvas.png")
        create_blank_canvas(canvas)

        for xx in sorted(glyphs):
            info = glyphs[xx]
            src_path = resolve_java_texture(info["file_ref"])
            if src_path is None:
                print(f"  [WARN] U+E2{xx:02X}: source not found: {info['file_ref']}")
                continue

            src_w, src_h = get_image_dimensions(src_path)
            cell_w = src_w // info["total_cols"]
            cell_h = src_h // info["total_rows"]
            crop_x = info["img_col"] * cell_w
            crop_y = info["img_row"] * cell_h

            dest_col, dest_row = xx & 0x0F, xx >> 4
            dest_x, dest_y = dest_col * CELL, dest_row * CELL

            next_canvas = os.path.join(tmpdir, f"step_{xx:02X}.png")
            composite_glyph(
                canvas, src_path,
                (cell_w, cell_h, crop_x, crop_y),
                (dest_x, dest_y),
                next_canvas,
            )
            canvas = next_canvas
            print(f"  U+E2{xx:02X} → cell ({dest_col},{dest_row}) from {os.path.basename(src_path)} row={info['img_row']} col={info['img_col']}")

        shutil.copy2(canvas, OUTPUT)

    print(f"\nDone! Written to {OUTPUT}")


if __name__ == "__main__":
    main()
