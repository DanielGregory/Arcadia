"""Phase 1.5, the morning wallpaper: one dream, set as an image.

Layout (top to bottom):
    ARCADIA · DREAM 7 · 17 NOVEMBER 2026        small spaced capitals
    the dream "as remembered"                    large serif, the focus
    ── as dreamed ──
    the raw dream, exactly as the model wrote it small italic, faint

The background is either a painting of the dream (the daily morning
pipeline, daily/morning_job.py) or, without one, a soft sky gradient. The
painting is scaled to cover the whole screen and the text sits on a frosted
panel (the painting blurred and darkened beneath it) so it stays readable on
any picture. The sky's palette (dawn, morning, dusk or night) is picked from a
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


def frosted_panel(img: Image.Image, box: tuple[int, int, int, int], radius: int) -> Image.Image:
    """Blur and darken the picture inside a rounded box, so text on it is readable."""
    w, h = img.size
    blurred = img.filter(ImageFilter.GaussianBlur(max(w, h) / 90))
    dark = Image.blend(blurred, Image.new("RGB", img.size, (12, 12, 20)), 0.55)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius / 3))  # soft edge
    return Image.composite(dark, img, mask)


def render(remembered: str, raw: str, out_path: Path, size=(2560, 1440), number: int | None = None,
           date: dt.date | None = None, font_path: str | None = None, italic_path: str | None = None,
           background: Image.Image | None = None) -> str:
    """Draw one wallpaper; returns the palette name used ("painting" with a background picture)."""
    w, h = size
    seed = int(hashlib.sha256(remembered.encode()).hexdigest(), 16)
    if background is not None:
        palette = "painting"
        ink, ink2 = (250, 244, 234), (226, 218, 206)  # warm off-white on the dark panel
        img = cover(background, size)
    else:
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
    if background is not None:
        # The panel covers the text block with some padding; the header gets its own small one.
        pad = int(48 * unit)
        img = frosted_panel(img, (margin_x - pad, y - pad, w - margin_x + pad, y + block_h + pad), int(28 * unit))
        hw = draw.textlength(spaced, font=header_font)
        img = frosted_panel(img, (int(w / 2 - hw / 2 - 30 * unit), int(h * 0.07 - 26 * unit),
                                  int(w / 2 + hw / 2 + 30 * unit), int(h * 0.07 + 26 * unit)), int(20 * unit))
        draw = ImageDraw.Draw(img)
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
