"""Paint a wallpaper PREVIEW from one of the world engine's dreams (the GPU half; never production).

    python -m world.preview_job --dream dream.json --out out/preview

Run on Kaggle's GPU by notebooks/kaggle_preview.ipynb, launched by world/wallpaper_preview.py.
It answers one question: what would tomorrow's wallpaper look like if it came from the engine's
most-discussed dream, rather than from the production model's own candidates?

It uses the morning job's own steps unchanged (imported, not copied, so the preview is the same
pipeline), skipping the ones that don't apply: the dream is already chosen (by the engine), so
there is no candidate dreaming or selection.
  1. CAPTION   the editor picks the most vivid sentence, from the dream as its dreamer TOLD it
               (the retelling, already in Corva's own terms) when there is one, else the raw dream;
  2. PROMPT    the editor condenses it into one painting (morning_job.PAINT_SYSTEM);
  3. PAINT     SDXL in the style the morning would pick for this dream's voice and tomorrow's seed;
  4. WALLPAPER the caption set over it, labelled with the dreamer, their house and Arcadia's
               year and season (not "Dream N", which belongs to production mornings).

Input (dream.json): {"id", "text", "retelling", "tag", "dreamer", "house", "year", "season", "date"}.
Output in --out: painting_{desktop,phone}.png, wallpaper_{desktop,phone}.png, preview.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import json
import re
import time
from pathlib import Path

import torch


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dream", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/preview"))
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--no_paint", action="store_true", help="CPU test: the canonical Corva as the painting")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    from PIL import Image

    from daily.morning_job import PAINT_MODEL, PAINT_SYSTEM, ROOT, STYLE_REFERENCE, best_sentence, choose_style, paint
    from engine.remember import Rememberer
    from render.wallpaper import render

    d = json.loads(args.dream.read_text(encoding="utf-8"))
    day = dt.date.fromisoformat(d["date"])
    seed = int(day.strftime("%Y%m%d"))            # tomorrow's seed: the same style draw the morning would make
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    told = d.get("retelling") or d["text"]
    label = f"A dream of {d['dreamer']}, House {d['house']} · {d['season'].title()}, year {d['year']}"
    print(f"preview of {d['id']} ({label}), seed {seed}, on {args.device}", flush=True)

    editor = Rememberer(device=args.device)
    caption = best_sentence(editor, told)
    print(f"  caption: {caption}", flush=True)
    del editor
    gc.collect()
    painter = Rememberer(model_id=PAINT_MODEL, device=args.device)
    scene = painter.chat(PAINT_SYSTEM, told, max_new_tokens=80).strip()
    scene = re.split(r"(?<=[.!?])\s", scene, maxsplit=1)[0].strip().rstrip(".")   # as the morning job does
    scene = " ".join(scene.split()[:45])
    print(f"  painting prompt: {scene}", flush=True)
    del painter
    gc.collect()
    if args.device == "cuda":
        torch.cuda.empty_cache()

    style = choose_style(d.get("tag") or "dream", seed)
    print(f"  style: {style['name']} ({style['pool']} pool)", flush=True)
    if args.no_paint:
        corva = Image.open(ROOT / STYLE_REFERENCE).convert("RGB")
        paintings = {"desktop": corva, "phone": corva}
    else:
        paintings = paint(scene, style, seed, args.device, args.steps, 0.0)
    for name, img in paintings.items():
        img.save(args.out / f"painting_{name}.png")
    for name, size in {"desktop": (2560, 1440), "phone": (1290, 2796)}.items():
        render(caption, d["text"], args.out / f"wallpaper_{name}.png", size=size, background=paintings[name], label=label)
    record = {**d, "seed": seed, "caption": caption, "label": label, "painting_prompt": scene, "style": style,
              "painted": not args.no_paint, "seconds": round(time.time() - t0, 1)}
    (args.out / "preview.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"done in {record['seconds']:.0f}s -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
