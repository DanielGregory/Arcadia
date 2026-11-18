"""Portraits of Corva's principal characters: one painted portrait each, in one consistent style.

    python -m world.portraits --dry_run     # print the prompts
    python -m world.portraits               # paint them on Kaggle's GPU, upload, store each on its person's record
    python -m world.portraits --no_push     # collect the latest Kaggle run instead of starting one

Sandbox only. The prompt for each person is built from their record (house, role, age, the public note
about them) plus a fixed style, so the portraits read as one painter's gallery; the house sets the colours
and dress, the person's id fixes the seed (the same person always looks the same). Painted by SDXL on
Kaggle (world/portrait_job.py, notebooks/kaggle_portraits.ipynb).

What it writes:
  * the images to the public 'arcadia' bucket, sandbox/portraits/p<id>.jpg (a face is not a secret);
  * the path to people.portrait in the engine's own record (this IS the engine writing its world), then
    the snapshot is republished and the state pushed (world/publish.py, world/state.py).

Sex is not recorded by genesis; it is read from the person's first name (genesis drew every name from a
male or a female list, and the story names are fixed) and stored as people.sex (PROPOSED).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daily"))

from world.db import connect, rows  # noqa: E402
from world.genesis import FEMALE, MALE  # noqa: E402

STORY_SEX = {"Marius": "m", "Livia": "f", "Lucan": "m", "Galen": "m", "Tiberon": "m", "Soren": "m", "Neria": "f",
             "Gaius": "m", "Ismene": "f", "Theodric": "m", "Octavia": "f", "Rufus": "m", "Aldric": "m", "Hesione": "f",
             "Kael": "m", "Seraphine": "f", "Decimus": "m", "Corin": "m", "Drusilla": "f", "Iola": "f", "Nikias": "m",
             "Brenna": "f", "Quintus": "m", "Ysolde": "f", "Silvan": "m", "Philo": "m", "Dion": "m", "Hesper": "m"}

STYLE = ("oil painting portrait, head and shoulders, three-quarter view, an inhabitant of an ancient island city of "
         "oars and sails, soft warm window light from the left, dark plain background, visible brushstrokes and canvas "
         "texture, the clothing in vivid saturated colour against the dark ground, the quiet dignity of an old master portrait")
NEGATIVE = ("photo, photograph, 3d render, cartoon, anime, modern clothes, glasses, text, letters, watermark, frame, "
            "two people, deformed face, extra eyes, blurry")
DRESS = {   # by house: the strong colour and the clothing (PROPOSED)
    "Corvane": "black and deep gold robes of an old ruling house, a gold signet ring",
    "Valerius": "a sea-blue cloak pinned with a bronze clasp, a naval commander's bearing",
    "Theren": "an olive-green wool tunic and a landowner's sun-browned look",
    "Aurelian": "white priestly robes with a sea-blue stole, a shell pendant",
    "Marcellan": "rich saffron-orange merchant's robes, rings on the fingers",
    "Cassian": "a grey tunic dusted with stone, a builder's strong hands",
    "Severin": "a violet judge's mantle over pale linen",
    "Damaris": "teal healer's robes, a bundle of dried herbs at the belt",
    "Veyra": "rust-red hunter's leathers and a fur collar, weathered by mountain wind",
    "Solenne": "faded rose silk, once very fine, now worn at the seams",
}
HAIR = ["dark brown", "black", "chestnut", "auburn", "dark curly", "light brown"]


def sex_of(name: str) -> str:
    first = name.split()[0]
    if first in STORY_SEX:
        return STORY_SEX[first]
    return "f" if first in FEMALE else "m" if first in MALE else "m"


def age_words(age: int, sex: str) -> str:
    noun = "woman" if sex == "f" else "man"
    if age < 18:
        return f"a young {'girl' if sex == 'f' else 'boy'} of about {age}"
    if age < 30:
        return f"a young {noun} of about {age}, youthful smooth skin"
    if age < 40:
        return f"a {noun} of about {age}, in the prime of life, no grey hair"
    if age < 50:
        return f"a {noun} of about {age}"
    if age < 65:
        return f"a {noun} in late middle age, about {age}, greying"
    return f"an old {noun} of about {age}, white-haired and lined"


def prompts(con) -> list[dict]:
    year = rows(con, "select max(year) y from storyteller_proposals")[0]["y"] or 0
    out = []
    for p in rows(con, "select p.id, p.name, p.born_year, p.note, p.dream_temperament, m.role, h.name house from people p "
                       "join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                       "where p.tier = 'principal' order by p.id"):
        sex = sex_of(p["name"])
        age = year - p["born_year"]
        h = int(hashlib.sha1(p["name"].encode()).hexdigest(), 16)
        hair = HAIR[h % len(HAIR)] if age < 50 else ""
        what = (p["note"] or "").split(";")[0]
        # the parts of a note that are not visible (what they said, believe or did) are left out
        what = "" if any(k in what for k in ("said", "swore", "believes", "fled", "took ")) else what
        what = what.removeprefix("his ").removeprefix("her ")
        of_house = "" if p["house"] in what else f", of House {p['house']}"
        prompt = (f"{age_words(age, sex)}" + (f" with {hair} hair" if hair else "") + f", wearing {DRESS[p['house']]}"
                  + (f", {what}" if what else "") + f"{of_house}, a {p['dream_temperament']} temperament in the eyes")
        out.append({"id": p["id"], "name": p["name"], "sex": sex, "prompt": prompt, "style": STYLE, "negative": NEGATIVE,
                    "seed": 1000 + p["id"]})
    return out


JOB = {"notebook": "notebooks/kaggle_portraits.ipynb", "slug": "arcadia-portraits", "title": "Arcadia Portraits"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--no_push", action="store_true")
    args = ap.parse_args()
    con = connect()
    batch = prompts(con)
    if args.dry_run:
        for b in batch:
            print(f"p{b['id']} {b['name']} ({b['sex']}): {b['prompt']}")
        return
    from kaggle_run import USER, gpu_minutes, kaggle, push, wait
    from memory_sync import client
    from morning import jpeg
    kernel = f"{USER}/{JOB['slug']}"
    if not args.no_push:
        line = f"PORTRAITS = json.loads({json.dumps(batch, ensure_ascii=False)!r})"
        push(JOB, {"PORTRAITS = None": json.dumps(line, ensure_ascii=False)[1:-1]})
        time.sleep(30)
    status = wait(kernel)
    sb = client()
    with tempfile.TemporaryDirectory() as tmp:
        kaggle("kernels", "output", kernel, "-p", tmp, "--force")
        log = next(Path(tmp).glob("*.log"), None)
        minutes = gpu_minutes(log) if log else 0.0
        made = Path(tmp) / "portraits"
        if "COMPLETE" not in status or not (made / "portraits.json").exists():
            sys.exit(f"{kernel}: {status}, no portraits ({minutes:.1f} GPU minutes)")
        dest = ROOT / "out/portraits"
        shutil.copytree(made, dest, dirs_exist_ok=True)
    done = json.loads((dest / "portraits.json").read_text())
    for d in done:
        remote = f"sandbox/portraits/p{d['id']}.jpg"
        sb.upload_bytes(jpeg(dest / f"p{d['id']}.png", quality=88), remote, "image/jpeg")
        con.execute("update people set portrait = ?, sex = ? where id = ?", (remote, d["sex"], d["id"]))
    con.commit()
    print(f"{kernel}: {status} | {minutes:.1f} GPU minutes | {len(done)} portraits stored on their people's records")


if __name__ == "__main__":
    main()
