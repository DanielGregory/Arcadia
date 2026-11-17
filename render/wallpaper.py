"""Phase 1.5, the morning wallpaper: one dream, set as an image.

Layout (top to bottom):
    ARCADIA · DREAM 7 · 17 NOVEMBER 2026        small spaced capitals
    the dream "as remembered"                    large serif, the focus
    ── as dreamed ──
    the raw dream, exactly as the model wrote it small italic, faint

Two layouts:

  PAINTING (the daily morning pipeline, daily/morning_job.py): the art is the
  point. The painting fills the screen untouched and the dream is a small
  caption in a corner (bottom-left on a desktop, low on a phone, clear of the
  lock-screen clock and the dock), on a soft shadow rather than a box. Only the
  "as remembered" text goes on; the raw dream lives in the gallery.

  SKY (no painting): the text is the point, as in the layout below. The sky's palette (dawn, morning, dusk or night) is picked from a
hash of the dream text, so the same dream always gets the same sky, with a
little film grain and a vignette. The text sizes shrink until everything fits.

    python -m render.wallpaper --in out/read_test/run2_remembered.json --ids 3 7 14 --out out/wallpapers
    python -m render.wallpaper --in ... --ids 3 --size 1290x2796        # phone (portrait)
    python -m render.wallpaper --in ... --ids 3 --background painting.png   # painting behind the text
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Serif fonts to try, in order of preference; the first one found is used.
SERIF = [
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/Library/Fonts/Georgia.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf", "C:/Windows/Fonts/georgia.ttf",
]
SERIF_ITALIC = [
    "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/Library/Fonts/Georgia Italic.ttf", "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
    "C:/Windows/Fonts/georgiai.ttf",
]

# (top colour, bottom colour, main text, secondary text) for each sky.
PALETTES = {
    "dawn":    ((58, 52, 92), (232, 170, 140), (250, 242, 232), (250, 236, 222)),
    "morning": ((168, 196, 220), (246, 232, 204), (42, 40, 48), (70, 66, 72)),
    "dusk":    ((44, 36, 70), (196, 112, 92), (248, 236, 226), (240, 220, 208)),
    "night":   ((10, 14, 30), (40, 46, 78), (232, 228, 240), (190, 190, 210)),
}


def find_font(candidates: list[str]) -> str:
    for path in candidates:
        if Path(path).exists():
            return path
    raise SystemExit("no serif font found; pass --font and --font_italic")


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Greedy word wrap to a pixel width; paragraph breaks are kept."""
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def sky(size: tuple[int, int], top: tuple, bottom: tuple, seed: int) -> Image.Image:
    """Vertical gradient + faint grain + vignette."""
    w, h = size
    grad = Image.new("RGB", (1, 256))
    for y in range(256):
        t = (y / 255) ** 1.4  # more of the top colour, a glow near the horizon
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    img = grad.resize((w, h), Image.BICUBIC)

    # Film grain: low-amplitude noise, blurred a little so it reads as texture, not pixels.
    rng = random.Random(seed)
    noise = Image.frombytes("L", (w // 2, h // 2), bytes(rng.randrange(118, 138) for _ in range((w // 2) * (h // 2))))
    noise = noise.resize((w, h)).filter(ImageFilter.GaussianBlur(0.6))
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.06)

    # Vignette: darken the edges slightly.
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.25, -h * 0.35, w * 1.25, h * 1.35), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    dark = Image.new("RGB", (w, h), tuple(int(c * 0.55) for c in top))
    return Image.composite(img, dark, mask)


def cover(picture: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale and centre-crop a picture so it fills `size` exactly (like CSS background-size: cover)."""
    w, h = size
    s = max(w / picture.width, h / picture.height)
    scaled = picture.convert("RGB").resize((round(picture.width * s), round(picture.height * s)), Image.LANCZOS)
    left, top = (scaled.width - w) // 2, (scaled.height - h) // 2
    return scaled.crop((left, top, left + w, top + h))


def soft_shadow(img: Image.Image, box: tuple[int, int, int, int], blur: float, strength: int = 165) -> Image.Image:
    """Darken the painting softly around a box: a shadow with no edges, so it reads as light, not as a panel."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=strength)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    return Image.composite(Image.new("RGB", img.size, (8, 8, 14)), img, mask)


def render_caption(text: str, out_path: Path, painting: Image.Image, size: tuple[int, int], number: int | None,
                   date: dt.date | None, font_path: str | None, italic_path: str | None) -> None:
    """The painting full screen, the dream as a small caption in a corner."""
    w, h = size
    img = cover(painting, size)
    draw = ImageDraw.Draw(img)
    font_path = font_path or find_font(SERIF)
    phone = h > w
    # Where the caption goes, as fractions of the screen. Phones keep the top third
    # for the clock and the bottom for the lock-screen buttons; desktops keep the
    # bottom strip for a dock or taskbar.
    if phone:
        left, box_w, bottom, max_h, base_px = 0.08 * w, 0.84 * w, 0.12 * h, 0.32 * h, 40 * w / 1290
    else:
        left, box_w, bottom, max_h, base_px = 0.045 * w, 0.31 * w, 0.09 * h, 0.40 * h, 29 * w / 2560

    date = date or dt.date.today()
    header = "  ·  ".join(filter(None, ["ARCADIA", f"DREAM {number}" if number else None,
                                        date.strftime("%-d %B %Y").upper()]))
    spaced = " ".join(header)
    # The largest text size (down to 70% of the base) that fits in max_h.
    for px in range(int(base_px), int(base_px * 0.7) - 1, -1):
        font = ImageFont.truetype(font_path, px)
        lines = wrap(draw, text, font, int(box_w))
        line_h = int(px * 1.45)
        header_px = max(12, int(px * 0.55))
        block_h = int(header_px * 2.4) + len(lines) * line_h
        if block_h <= max_h:
            break
    header_font = ImageFont.truetype(font_path, header_px)
    top = int(h - bottom - block_h)
    pad = px * 1.6
    img = soft_shadow(img, (int(left - pad), int(top - pad), int(left + box_w + pad), int(h - bottom + pad)), blur=pad * 1.4)
    draw = ImageDraw.Draw(img)
    draw.text((left, top), spaced, font=header_font, fill=(226, 218, 206))
    y = top + int(header_px * 2.4)
    for line in lines:
        draw.text((left, y), line, font=font, fill=(250, 244, 234))
        y += line_h
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)


def render(remembered: str, raw: str, out_path: Path, size=(2560, 1440), number: int | None = None,
           date: dt.date | None = None, font_path: str | None = None, italic_path: str | None = None,
           background: Image.Image | None = None) -> str:
    """Draw one wallpaper; returns the palette name used ("painting" with a background picture)."""
    if background is not None:
        render_caption(remembered, out_path, background, size, number, date, font_path, italic_path)
        return "painting"
    w, h = size
    seed = int(hashlib.sha256(remembered.encode()).hexdigest(), 16)
    palette = list(PALETTES)[seed % len(PALETTES)]
    top, bottom, ink, ink2 = PALETTES[palette]
    img = sky(size, top, bottom, seed)
    draw = ImageDraw.Draw(img)
    font_path = font_path or find_font(SERIF)
    italic_path = italic_path or find_font(SERIF_ITALIC)

    unit = min(w, h) / 1440                          # scale everything to the image size
    margin_x = int(w * (0.16 if w > h else 0.09))
    text_w = w - 2 * margin_x

    # Header: small spaced capitals.
    date = date or dt.date.today()
    header = "  ·  ".join(filter(None, ["ARCADIA", f"DREAM {number}" if number else None,
                                        date.strftime("%-d %B %Y").upper()]))
    header_font = ImageFont.truetype(font_path, int(22 * unit))
    spaced = " ".join(header)

    # Find the largest main and raw sizes that fit in the space between header and footer.
    avail_h = h - int(h * 0.24)
    for main_px in range(int(56 * unit), int(20 * unit), -2):
        raw_px = max(int(main_px * 0.42), int(13 * unit))
        main_font = ImageFont.truetype(font_path, main_px)
        raw_font = ImageFont.truetype(italic_path, raw_px)
        main_lines = wrap(draw, remembered, main_font, text_w)
        raw_lines = wrap(draw, raw, raw_font, int(text_w * 0.9))
        main_lh, raw_lh = int(main_px * 1.42), int(raw_px * 1.5)
        block_h = len(main_lines) * main_lh + int(70 * unit) + len(raw_lines) * raw_lh
        if block_h <= avail_h:
            break

    y = int((h - block_h) / 2 + h * 0.03)
    draw.text((w / 2, int(h * 0.07)), spaced, font=header_font, fill=ink2, anchor="mm")

    for line in main_lines:
        draw.text((margin_x, y), line, font=main_font, fill=ink)
        y += main_lh

    # Divider with the label "as dreamed", then the raw dream, faint.
    y += int(24 * unit)
    label_font = ImageFont.truetype(italic_path, max(raw_px, int(15 * unit)))
    label = "as dreamed"
    lw = draw.textlength(label, font=label_font)
    mid = margin_x + lw / 2
    draw.text((margin_x, y), label, font=label_font, fill=ink2)
    line_y = y + label_font.size * 0.6
    draw.line((margin_x + lw + 16 * unit, line_y, margin_x + text_w * 0.9, line_y), fill=ink2, width=max(1, int(unit)))
    y += int(46 * unit)
    faint = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(faint)
    for line in raw_lines:
        fd.text((margin_x, y), line, font=raw_font, fill=(*ink2, 150))
        y += raw_lh
    img = Image.alpha_composite(img.convert("RGBA"), faint).convert("RGB")
    del mid

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)
    return palette


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="inp", type=Path, required=True, help="JSON from engine.remember")
    parser.add_argument("--ids", type=int, nargs="+", required=True, help="dream numbers to render")
    parser.add_argument("--out", type=Path, default=Path("out/wallpapers"))
    parser.add_argument("--size", default="2560x1440", help="WIDTHxHEIGHT (default desktop 2560x1440)")
    parser.add_argument("--font", help="serif .ttf for the main text")
    parser.add_argument("--font_italic", help="italic .ttf for the raw dream")
    parser.add_argument("--background", type=Path, help="a painting to put behind the text (instead of the sky)")
    args = parser.parse_args()
    background = Image.open(args.background) if args.background else None

    size = tuple(int(v) for v in args.size.lower().split("x"))
    dreams = {d["n"]: d for d in json.loads(args.inp.read_text(encoding="utf-8"))}
    for n in args.ids:
        d = dreams[n]
        out = args.out / f"dream_{n:02d}_{size[0]}x{size[1]}.png"
        palette = render(d["as_remembered"], d["text"], out, size=size, number=n,
                         font_path=args.font, italic_path=args.font_italic, background=background)
        print(f"wrote {out} ({palette})")


if __name__ == "__main__":
    main()
