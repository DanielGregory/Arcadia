"""Upload everything there is to review to Supabase, for the review gallery in site/.

    python daily/upload_review.py              # upload images, wallpapers and dreams
    python daily/upload_review.py --dry_run    # list what would be uploaded

What goes where:
  Storage bucket "arcadia" (public read):
    assets/generated/corva_*.png  -> generated/corva/
    assets/generated/dream_*.png  -> generated/dreams/
    out/wallpapers/*.png          -> wallpapers/
  Table "images": one row per uploaded image (kind, prompt, seed, the full
    metadata JSON, and the dream it shows, if any).
  Table "dreams": the read-test dreams (out/read_test/run2.json, and run3.json
    once it exists), plus the priming-test dreams that have a painting or a
    wallpaper, linked to it.

Re-running is safe: files are overwritten and rows are upserted, and the
columns you set in the gallery (mark, note, picked) are never touched.

Needs the project's secret key (sb_secret_...) in SUPABASE_SECRET_KEY, read
from the environment or from .env (gitignored). Never put it in the frontend.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "arcadia"
DEFAULT_URL = "https://dbrtvwhslxkdpmuawrgd.supabase.co"


def load_env() -> None:
    """Read KEY=VALUE lines from .env into os.environ (without overriding real env vars)."""
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Supabase:
    def __init__(self, url: str, key: str, dry_run: bool = False):
        self.url = url.rstrip("/")
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({"apikey": key})

    def upload(self, local: Path, remote: str) -> None:
        if self.dry_run:
            print(f"  would upload {local.relative_to(ROOT)} -> {BUCKET}/{remote}")
            return
        r = self.session.post(f"{self.url}/storage/v1/object/{BUCKET}/{remote}", data=local.read_bytes(),
                              headers={"content-type": "image/png", "x-upsert": "true",
                                       "cache-control": "max-age=300"}, timeout=120)
        r.raise_for_status()

    def upsert(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        if self.dry_run:
            print(f"  would upsert {len(rows)} rows into {table}")
            return
        # merge-duplicates: insert new rows, update the given columns of existing ones.
        # mark/note/picked are never in `rows`, so the gallery's choices survive re-runs.
        r = self.session.post(f"{self.url}/rest/v1/{table}", json=rows, timeout=60,
                              headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        if r.status_code >= 400:
            sys.exit(f"upsert into {table} failed: {r.status_code} {r.text}")


def priming_prompts() -> dict[str, str]:
    """Prompt number -> opening, from the headings of out/priming/run2.md."""
    md = (ROOT / "out/priming/run2.md").read_text(encoding="utf-8")
    return {n: ("" if p == "(no priming)" else p) for n, p in re.findall(r"^## Prompt (\d+): (.*)$", md, re.M)}


def priming_dream_text(key: str) -> str:
    md = (ROOT / "out/priming/run2.md").read_text(encoding="utf-8")
    m = re.search(rf"^### {re.escape(key)} .*?\n\n(.*?)(?=\n### |\n## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    load_env()
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not key and not args.dry_run:
        sys.exit("SUPABASE_SECRET_KEY is not set (put it in .env)")
    sb = Supabase(os.environ.get("SUPABASE_URL", DEFAULT_URL), key or "", args.dry_run)

    dreams: dict[str, dict] = {}
    images: list[dict] = []
    prompts = priming_prompts()

    def add_priming_dream(key: str, text: str | None = None, image: str | None = None) -> str:
        """A dream from the run 2 priming test (e.g. '2.2'); returns its row id."""
        dream_id = f"run2-priming-{key}"
        row = dreams.setdefault(dream_id, {"id": dream_id, "run": "run2", "prompt": prompts.get(key.split(".")[0], ""),
                                           "text": text or priming_dream_text(key), "image": None})
        if image and not row["image"]:
            row["image"] = image
        return dream_id

    # 1. Read-test dreams.
    for run in ("run2", "run3"):
        path = ROOT / f"out/read_test/{run}.json"
        if path.exists():
            for d in json.loads(path.read_text(encoding="utf-8")):
                dream_id = f"{run}-read-{d['n']:02d}"
                dreams[dream_id] = {"id": dream_id, "run": run, "prompt": d.get("prompt", ""), "text": d["text"], "image": None}

    # 2. Generated images (canonical Corva and dream paintings), with their metadata.
    gen = ROOT / "assets/generated"
    for png in sorted(gen.glob("*.png")) if gen.exists() else []:
        meta_path = png.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        kind = "corva" if png.stem.startswith("corva") else "dream"
        remote = f"generated/{'corva' if kind == 'corva' else 'dreams'}/{png.name}"
        dream_id = None
        src = meta.get("source_dream")
        if src and src.get("dream"):
            dream_id = add_priming_dream(src["dream"], image=remote)
        images.append({"id": remote, "kind": kind, "prompt": meta.get("prompt"), "seed": meta.get("seed"),
                       "meta": meta or None, "dream_id": dream_id, "_local": png})

    # 3. Wallpapers (linked to the priming dream they show, via priming_picks.json).
    wp = ROOT / "out/wallpapers"
    picks = {}
    if (wp / "priming_picks.json").exists():
        picks = {d["n"]: d for d in json.loads((wp / "priming_picks.json").read_text(encoding="utf-8"))}
    for png in sorted(wp.glob("*.png")) if wp.exists() else []:
        m = re.match(r"dream_(\d+)_", png.name)
        pick = picks.get(int(m.group(1))) if m else None
        dream_id = add_priming_dream(pick["source"].split()[-1]) if pick else None
        images.append({"id": f"wallpapers/{png.name}", "kind": "wallpaper", "prompt": None, "seed": None,
                       "meta": {"source": pick["source"]} if pick else None, "dream_id": dream_id, "_local": png})

    print(f"{len(images)} images ({sum(i['kind'] == 'corva' for i in images)} Corva, "
          f"{sum(i['kind'] == 'dream' for i in images)} dream paintings, {sum(i['kind'] == 'wallpaper' for i in images)} "
          f"wallpapers) and {len(dreams)} dreams")

    # Dreams first, because images reference them.
    sb.upsert("dreams", list(dreams.values()))
    for img in images:
        sb.upload(img["_local"], img["id"])
        print(f"  uploaded {img['id']}" if not args.dry_run else "", end="\n" if not args.dry_run else "")
    sb.upsert("images", [{k: v for k, v in img.items() if k != "_local"} for img in images])
    print("done" if not args.dry_run else "dry run: nothing uploaded")


if __name__ == "__main__":
    main()
