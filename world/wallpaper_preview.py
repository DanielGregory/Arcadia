"""Wallpaper PREVIEW: what tomorrow's wallpaper would be if it came from the world engine's dreams.

    python -m world.wallpaper_preview              # pick the dream, paint it on Kaggle, publish the preview
    python -m world.wallpaper_preview --pick_only  # just say which dream it would be
    python -m world.wallpaper_preview --no_push    # collect the latest Kaggle preview run instead of starting one

Not production. The daily morning (daily/morning.py) is untouched and still makes the real wallpaper.
This reads the engine's world from the sandbox_* tables (Supabase, the same tables the site reads),
never from the engine's private files, and writes only:
  * Storage, under sandbox/preview/ in the 'arcadia' bucket (the mornings live elsewhere);
  * one row in sandbox_previews, which the review page's Chronicle tab shows.

The dream: the one most discussed in the latest season (told to the most people, interpreted by the
most), ties broken by the more vivid recall. Labelled with its dreamer, their house, and Arcadia's
year and season.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daily"))

from kaggle_run import USER, gpu_minutes, kaggle, push, wait  # noqa: E402
from memory_sync import client, select  # noqa: E402

JOB = {"notebook": "notebooks/kaggle_preview.ipynb", "slug": "arcadia-preview", "title": "Arcadia Preview"}
LOCAL = ROOT / "out/preview"


def pick(sb) -> dict:
    world = select(sb, "sandbox_world?select=*")[0]
    dreams = select(sb, f"sandbox_dreams?select=*&year=eq.{world['year']}&season=eq.{world['season']}")
    people = {p["id"]: p for p in select(sb, "sandbox_people?select=id,name,house_id")}
    houses = {h["id"]: h for h in select(sb, "sandbox_houses?select=id,name")}
    best = max(dreams, key=lambda d: (d["discussed"], bool(d["recalled"]), bool(d["retelling"]), len(d["shared_with"])))
    who = people.get(best["dreamer_id"], {})
    tomorrow = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
    return {"id": best["id"], "text": best["text"], "retelling": best["retelling"], "tag": best["tag"],
            "discussed": best["discussed"], "dreamer": who.get("name", "someone"),
            "house": houses.get(who.get("house_id"), {}).get("name", "no house"),
            "year": world["year"], "season": world["season"], "date": tomorrow.isoformat()}


def record(sb, row: dict) -> None:
    r = sb.session.post(f"{sb.url}/rest/v1/sandbox_previews", json=row, headers={"Prefer": "return=minimal"}, timeout=60)
    r.raise_for_status()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pick_only", action="store_true")
    ap.add_argument("--no_push", action="store_true")
    args = ap.parse_args()
    sb = client()
    dream = pick(sb)
    print(f"most-discussed dream: {dream['id']} by {dream['dreamer']} (House {dream['house']}), "
          f"talked about {dream['discussed']}x, {dream['season']} of year {dream['year']}")
    if args.pick_only:
        print(dream["retelling"] or dream["text"])
        return
    base = {"year": dream["year"], "season": dream["season"], "dream_id": dream["id"], "dreamer": dream["dreamer"], "house": dream["house"]}
    kernel = f"{USER}/{JOB['slug']}"
    if not args.no_push:
        # the notebook file is JSON, so the line of code that carries the dream is JSON-escaped into it
        line = f"PREVIEW = json.loads({json.dumps(dream, ensure_ascii=False)!r})"
        push(JOB, {"PREVIEW = None": json.dumps(line, ensure_ascii=False)[1:-1]})
        time.sleep(30)
    status = wait(kernel)
    with tempfile.TemporaryDirectory() as tmp:
        kaggle("kernels", "output", kernel, "-p", tmp, "--force")
        log = next(Path(tmp).glob("*.log"), None)
        minutes = gpu_minutes(log) if log else 0.0
        made = Path(tmp) / "preview"
        if "COMPLETE" not in status or not (made / "preview.json").exists():
            record(sb, {**base, "status": "failed", "error": f"{status}, {minutes:.1f} GPU minutes"})
            sys.exit(f"{kernel}: {status}, no preview made ({minutes:.1f} GPU minutes)")
        dest = LOCAL / f"y{dream['year']}_{dream['season']}"
        shutil.copytree(made, dest, dirs_exist_ok=True)
    meta = json.loads((dest / "preview.json").read_text(encoding="utf-8"))
    from morning import jpeg  # the same JPEG settings as the mornings
    remote = f"sandbox/preview/y{dream['year']}_{dream['season']}"
    for name in ("desktop", "phone"):
        sb.upload_bytes(jpeg(dest / f"wallpaper_{name}.png"), f"{remote}/wallpaper_{name}.jpg", "image/jpeg")
    record(sb, {**base, "scene": meta["painting_prompt"], "image": f"{remote}/wallpaper_desktop.jpg", "status": "done"})
    print(f"{kernel}: {status} | {minutes:.1f} GPU minutes -> {remote}/ (sandbox_previews)")


if __name__ == "__main__":
    main()
