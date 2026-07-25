"""Generate the Rigo Brace custom step icons.

Writes five 64x64 RGBA PNG "badge" icons (a soft coloured disc with a white
step number) into rigo_brace/icons/. Pure standard library — no Pillow, no
Blender — so it can run with plain ``py -3 tools\\make_icons.py``.

These ship inside the add-on and are loaded at runtime with bpy.utils.previews
so each workflow stage gets a distinctive clinical badge instead of one of
Blender's generic monochrome icons.
"""

import os
import struct
import zlib

SIZE = 64

# Clinical palette — one accent per workflow stage (R, G, B).
STEPS = (
    ("01_file", (45, 125, 210)),       # blue
    ("02_scan", (23, 163, 152)),       # teal
    ("03_landmarks", (224, 164, 88)),  # amber
    ("04_mesh", (131, 103, 199)),      # violet
    ("05_design", (63, 163, 77)),      # green
)

# 5x7 bitmap font for the digits 1-5.
DIGITS = {
    1: ("01100", "00100", "00100", "00100", "00100", "00100", "01110"),
    2: ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    3: ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    4: ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    5: ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
}


def _blend(bg, fg, a):
    return tuple(int(round(bg[i] * (1 - a) + fg[i] * a)) for i in range(3))


def _make_badge(color, digit):
    """Return a list of (r, g, b, a) rows for one badge icon."""
    cx = cy = (SIZE - 1) / 2.0
    radius = SIZE / 2.0 - 3.0

    # Pre-compute which pixels the digit covers (scaled, centred).
    glyph = set()
    rows = DIGITS[digit]
    gw, gh = 5, 7
    scale = 5
    ox = int(cx - (gw * scale) / 2.0)
    oy = int(cy - (gh * scale) / 2.0)
    for ry, line in enumerate(rows):
        for rx, ch in enumerate(line):
            if ch == "1":
                for sy in range(scale):
                    for sx in range(scale):
                        glyph.add((ox + rx * scale + sx, oy + ry * scale + sy))

    pixels = bytearray()
    for y in range(SIZE):
        pixels.append(0)  # PNG filter type 0 (none) per scanline
        for x in range(SIZE):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            # Anti-aliased disc alpha.
            if dist <= radius - 1.0:
                disc_a = 1.0
            elif dist >= radius:
                disc_a = 0.0
            else:
                disc_a = radius - dist

            if disc_a <= 0.0:
                pixels.extend((0, 0, 0, 0))
                continue

            if (x, y) in glyph:
                r, g, b = _blend(color, (255, 255, 255), 1.0)
            else:
                r, g, b = color
            pixels.extend((r, g, b, int(round(disc_a * 255))))
    return bytes(pixels)


def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _write_png(path, raw):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(raw, 9)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", idat))
        f.write(_chunk(b"IEND", b""))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "..", "rigo_brace", "icons")
    out_dir = os.path.normpath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    for idx, (name, color) in enumerate(STEPS, start=1):
        raw = _make_badge(color, idx)
        path = os.path.join(out_dir, name + ".png")
        _write_png(path, raw)
        print(f"[make_icons] wrote {path}")


if __name__ == "__main__":
    main()
