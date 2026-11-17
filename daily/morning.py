"""Phase 1.5: the daily morning wallpaper, launched and published from here.

    python daily/morning.py                 # make today's morning on Kaggle, publish it, commit the record
    python daily/morning.py --no_push       # don't start a new Kaggle run: collect the latest one
    python daily/morning.py --local DIR     # publish a morning already made locally (DIR/<date>/)
    python daily/morning.py --no_commit     # publish, but leave git alone

This is the light half of the pipeline; the heavy half (dream, remember, paint,
wallpaper) is daily/morning_job.py, run on Kaggle's GPU by
notebooks/kaggle_morning.ipynb. Steps here:

  1. push the notebook as a new Kaggle run, with the private dataset
     danieltgregory/arcadia-run4-model attached (the model + train.txt)
  2. wait for it, download out/morning/<date>/ and the run's log
  3. upload the paintings and wallpapers to Supabase Storage as JPEGs
     (mornings/<date>/...) and upsert the day's row in the "mornings" table:
     that is what the gallery's Today tab shows
  4. keep the day's record in the repo: daily/mornings/<date>.json and .md
     (the dream, the edit, the scores, the prompt; no images), commit and push

Needs: ~/.kaggle/kaggle.json, and SUPABASE_SECRET_KEY in the environment or .env.
Kaggle bills the GPU for the whole run (about 10 minutes, most of it
downloading SDXL); the minutes are recorded in the day's record.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "daily"))
from kaggle_run import USER, gpu_minutes, kaggle, push, wait  # noqa: E402
from upload_review import DEFAULT_URL, Supabase, load_env  # noqa: E402

JOB = {"notebook": "notebooks/kaggle_morning.ipynb", "slug": "arcadia-morning", "title": "Arcadia Morning",
       "datasets": [f"{USER}/arcadia-run4-model"]}
LOCAL = ROOT / "out/morning"          # full output, images included (gitignored)
RECORDS = ROOT / "daily/mornings"     # the permanent record, committed


def run_on_kaggle(no_push: bool) -> tuple[Path, float]:
    """Steps 1-2. Returns (the downloaded day folder, GPU minutes)."""
    kernel = f"{USER}/{JOB['slug']}"
    if not no_push:
        push(JOB)
        time.sleep(30)  # let Kaggle register the new version before asking its status
    status = wait(kernel)
    with tempfile.TemporaryDirectory() as tmp:
        kaggle("kernels", "output", kernel, "-p", tmp, "--force")
        log = next(Path(tmp).glob("*.log"), None)
        minutes = gpu_minutes(log) if log else 0.0
        days = sorted((Path(tmp) / "morning").glob("*/morning.json"))
        if "COMPLETE" not in status or not days:
            if log:
                LOCAL.mkdir(parents=True, exist_ok=True)
                shutil.copy2(log, LOCAL / "failed.kaggle.log")
            sys.exit(f"{kernel}: {status}, no morning made ({minutes:.1f} GPU minutes). Log: out/morning/failed.kaggle.log")
        src = days[-1].parent
        dest = LOCAL / src.name
        shutil.copytree(src, dest, dirs_exist_ok=True)
        if log:
            shutil.copy2(log, dest / "kaggle.log")
    print(f"{kernel}: {status} | {minutes:.1f} GPU minutes -> {dest.relative_to(ROOT)}")
    return dest, minutes


def jpeg(path: Path, quality: int = 90) -> bytes:
    """PNG -> JPEG bytes. Wallpapers are big; JPEG keeps a day at ~2 MB instead of ~15 MB."""
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def publish(day_dir: Path, record: dict, dry_run: bool) -> None:
    """Step 3: Storage + the mornings table."""
    load_env()
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not key and not dry_run:
        sys.exit("SUPABASE_SECRET_KEY is not set (put it in .env)")
    sb = Supabase(os.environ.get("SUPABASE_URL", DEFAULT_URL), key or "", dry_run)
    day = record["day"]
    paths = {}
    for name in ("painting_desktop", "painting_phone", "wallpaper_desktop", "wallpaper_phone"):
        remote = f"mornings/{day}/{name}.jpg"
        sb.upload_bytes(jpeg(day_dir / f"{name}.png"), remote, "image/jpeg")
        paths[name] = remote
        if not dry_run:
            print(f"  uploaded {remote}")
    meta = {k: record[k] for k in ("number", "label", "tag", "caption", "style", "seed", "opening", "chosen",
                                   "prompt_sent", "prompt_2_sent", "paint_model", "steps", "ip_scale", "painted",
                                   "settings", "edit", "timings_s", "gpu_minutes") if k in record}
    meta["candidates"] = [{k: v for k, v in c.items() if k != "copied_run"} for c in record["candidates"]]
    sb.upsert("mornings", [{
        "day": day, "run": record["run"], "raw": record["raw"], "remembered": record["as_remembered"],
        "painting_prompt": record["painting_prompt"], "painting": paths["painting_desktop"],
        "wallpaper_desktop": paths["wallpaper_desktop"], "wallpaper_phone": paths["wallpaper_phone"], "meta": meta,
    }])
    print(f"  upserted mornings row for {day}")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def commit(record: dict) -> None:
    """Step 4: commit the day's record and push it to main (retrying, the network is not always kind)."""
    day = record["day"]
    files = [f"daily/mornings/{day}.json", f"daily/mornings/{day}.md"]
    git("add", *files)
    if not git("status", "--porcelain", "--", *files).strip():
        print("  record unchanged; nothing to commit")
        return
    git("commit", "-m", f"Morning {record['number']}: {day}", "--", *files)
    for attempt in range(4):
        try:
            git("pull", "--rebase", "origin", "main")
            git("push", "origin", "HEAD:main")
            print(f"  committed and pushed Morning {record['number']}")
            return
        except subprocess.CalledProcessError as err:
            print(f"  push failed ({err.stderr.strip()}); retrying", flush=True)
            time.sleep(2 ** (attempt + 1))
    sys.exit("could not push the morning record")


def supabase() -> Supabase:
    load_env()
    return Supabase(os.environ.get("SUPABASE_URL", DEFAULT_URL), os.environ.get("SUPABASE_SECRET_KEY", ""))


def log_run(day: str, status: str, error: str | None = None, minutes: float | None = None) -> None:
    """One row in morning_runs: the gallery shows a banner when today's run failed or never came.
    Never let the logging itself break the run."""
    try:
        supabase().upsert("morning_runs", [{"day": day, "status": status, "error": error and error[:800],
                                            "gpu_minutes": minutes}])
    except BaseException as err:  # noqa: BLE001
        print(f"  (could not log the run status: {err})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no_push", action="store_true", help="collect the latest Kaggle run instead of starting one")
    parser.add_argument("--local", type=Path, help="publish a morning made locally: the folder holding <date>/")
    parser.add_argument("--date", help="with --local: which day (default: the newest)")
    parser.add_argument("--no_commit", action="store_true")
    parser.add_argument("--dry_run", action="store_true", help="show what would be uploaded; no commit")
    parser.add_argument("--no_publish", action="store_true", help="just run and download (a test): no upload, no commit")
    args = parser.parse_args()

    # Only the real daily run (Kaggle, published) reports its status to the gallery.
    report = not (args.local or args.no_publish or args.dry_run)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()  # the job dates mornings the same way
    if report:
        log_run(today, "started")
    try:
        record, minutes = make_and_publish(args)
    except BaseException as err:  # SystemExit from sys.exit(...) included
        if report:
            log_run(today, "failed", str(err) or type(err).__name__)
        raise
    if record is None:
        return
    if report:
        log_run(record["day"], "ok", minutes=record.get("gpu_minutes"))
    if not args.dry_run and not args.no_commit:
        try:
            commit(record)
        except BaseException as err:
            if report:
                log_run(record["day"], "failed", f"published, but the record could not be committed: {err}")
            raise


def make_and_publish(args) -> tuple[dict | None, float | None]:
    if args.local:
        days = sorted(args.local.glob(f"{args.date or '*'}/morning.json"))
        if not days:
            sys.exit(f"no morning.json under {args.local}")
        day_dir, minutes = days[-1].parent, None
    else:
        day_dir, minutes = run_on_kaggle(args.no_push)

    record = json.loads((day_dir / "morning.json").read_text(encoding="utf-8"))
    if minutes is not None:
        record["gpu_minutes"] = round(minutes, 1)
    print(f"{record.get('label', 'Morning ' + str(record['number']))} ({record['day']}): {record['painting_prompt']}")

    if args.no_publish:
        print(f"not published; the output is in {day_dir.relative_to(ROOT)}")
        return None, minutes
    publish(day_dir, record, args.dry_run)

    if not args.dry_run:
        RECORDS.mkdir(parents=True, exist_ok=True)
        (RECORDS / f"{record['day']}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")
        md = (day_dir / "morning.md").read_text(encoding="utf-8")
        if minutes is not None:
            md += f"Kaggle GPU minutes: {minutes:.1f}\n"
        (RECORDS / f"{record['day']}.md").write_text(md, encoding="utf-8")
    return record, minutes


if __name__ == "__main__":
    main()
