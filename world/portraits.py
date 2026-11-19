"""Portraits of Corva's principal characters: one painted portrait each, in one consistent style.

    python -m world.portraits --dry_run     # print the prompts
    python -m world.portraits               # paint 4 candidates per principal on Kaggle's GPU (from their appearance record)
    python -m world.portraits --only 2,6    # just these people (e.g. once Danny has written their descriptions)
    python -m world.portraits adopt         # make Danny's picks (review page, Portraits tab) their portraits + reference images

Since the second round, every prompt is built from the person's appearance record (world/appearance.py: exact
age, build, face, hair, eyes, marks, clothing), plus their station. Four candidates each; Danny picks one on the
review page; the engine adopts the pick as the portrait and keeps the full-size image as a REFERENCE: later
portraits of that person are painted with it as an image prompt (IP-Adapter), so they keep their face.

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
import re
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


def role_words(p) -> str:
    """Their station, from the public note (the parts that are not visible, what they said or did, left out)."""
    what = (p["note"] or "").split(";")[0]
    what = "" if any(k in what for k in ("said", "swore", "believes", "fled", "took ", "spouse of")) else what
    return what.removeprefix("his ").removeprefix("her ")


def prompts(con, candidates: int = 4, only: list[int] | None = None) -> tuple[list[dict], list[str]]:
    """The batch to paint: everyone principal who has an appearance record, built from that record (exact age now,
    build, face, hair, eyes, marks, clothing) plus their station; candidates each, with their own seeds. People
    whose record is still empty (Danny's to write) are returned by name, waiting."""
    year = rows(con, "select max(year) y from storyteller_proposals")[0]["y"] or 0
    out, waiting = [], []
    for p in rows(con, "select p.id, p.name, p.born_year, p.note, p.dream_temperament, p.appearance, p.portrait_ref, m.role, "
                       "h.name house from people p join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                       "where p.tier = 'principal' order by p.id"):
        if only and p["id"] not in only:
            continue
        a = json.loads(p["appearance"] or "{}")
        if not any(a.get(f) for f in ("build", "face", "hair")):
            waiting.append(p["name"])
            continue
        sex = a.get("sex") or sex_of(p["name"])
        age = year - p["born_year"]
        noun = ("girl" if sex == "f" else "boy") if age < 16 else ("woman" if sex == "f" else "man")
        station = role_words(p)
        # SDXL reads only ~77 tokens: what must show comes first (age, the house's clothes and colours, hair, eyes,
        # face), then build and any mark a head-and-shoulders portrait can show (not hands or knuckles)
        clothing = re.sub(r"\s*\(House [^)]*\)", "", a["clothing"])
        marks = [m.strip() for m in (a.get("marks") or "").split(";")
                 if m.strip() and m.strip() != "no marks of note" and not re.search(r"hand|finger|knuckle|forearm|smell", m)]
        if "nose" in a["face"]:
            marks = [m for m in marks if "nose" not in m]
        prompt = (f"a {noun} of exactly {age} years wearing {clothing}, hair {a['hair']}, {a['eyes']} eyes, {a['face']}, "
                  f"{a['build']}" + (f", {marks[0]}" if marks else ""))
        for k in range(candidates):
            out.append({"id": p["id"], "k": k, "name": p["name"], "sex": sex, "prompt": prompt, "style": STYLE, "negative": NEGATIVE,
                        "seed": 5000 + p["id"] * 10 + k,
                        "reference": (STORAGE_PUBLIC + p["portrait_ref"]) if p["portrait_ref"] else None})
    return out, waiting


# --- character cards (portraits v2): the person in their element, doing what they do ------------------------------
# (test 1 used sepia ink on cream paper: it drained every house to one brown; since test 2, colour washes in the
#  house's own colours, and sepia is in the negative prompt)
CARD_STYLE = ("loose ink line drawing with transparent watercolour washes, a character plate from an old illustrated book, "
              "expressive pen linework, white paper showing through")
CARD_NEGATIVE = ("photo, photograph, 3d render, glossy digital painting, anime, cartoon mascot, modern clothes, glasses, "
                 "text, letters, watermark, frame border, deformed hands, extra fingers, blurry, sepia, monochrome, "
                 "brown tint, grayscale, close-up headshot")
CARD_NEGATIVE_3 = ("Japanese, ukiyo-e, Asian clothing, Victorian, engraving, church, building only, architecture only, "
                   "empty room, landscape without a figure, close-up, headshot, portrait crop, face only")
# the look every card shares: a test-1 plate (Aldric, the strongest ink line), given to the IP-Adapter in style-only mode
STYLE_REF = "https://dbrtvwhslxkdpmuawrgd.supabase.co/storage/v1/object/public/arcadia/sandbox/portraits/style/plate_ref.png"
YOUNG_NEGATIVE = "wrinkles, grey hair, gray hair, white hair, aged skin, old, elderly, sagging skin, crow's feet"
# what they do and the one prop of their role, matched on their note and role (first match wins), then by house
SCENES = [
    ("harbour pilot", "standing at a ship's steering oar, eyes on the harbour mouth", "a coil of rope over one shoulder"),
    ("ship's captain", "on a ship's deck with one hand on the rigging", "a weathered sea chart"),
    ("priestess", "kneeling at a sea altar lit by oil lamps", "a large conch shell"),
    ("high priest", "raising a bronze bowl of sea water before an altar", "a bronze libation bowl"),
    ("judges", "seated in judgment on a stone bench, leaning forward to listen", "a carved staff of office"),
    ("judge", "seated in judgment on a stone bench, weighing a case", "a wax tablet and stylus"),
    ("healers", "grinding herbs in a stone mortar at a cluttered table", "a stone mortar and pestle"),
    ("servant", "carrying a water jar through a courtyard", "a clay water jar"),
    ("herders", "leaning on a crook on a windy mountain slope with sheep behind", "a shepherd's crook"),
    ("huntress", "drawing a bow on a misty mountain path", "a short hunting bow"),
    ("quarries", "inspecting a block of cut stone in a quarry", "an iron chisel"),
    ("builder", "measuring a wall with a plumb line on a scaffold", "a plumb line"),
    ("merchant", "counting coins at a table in a counting house", "a ledger of wax tablets"),
    ("matriarch", "seated in a faded hall among old heirlooms", "an old silver brooch held in the hand"),
    ("heir", "standing on a terrace above the city, hand on a sword hilt", "a sheathed short sword"),
    ("lord", "standing in a council hall, one hand raised to speak", "a gold signet ring"),
    ("head", "standing in the house's hall, receiving a petitioner", "a seal ring"),
]
HOUSE_SCENES = {
    "Corvane": ("standing on the citadel terrace above the city", "a gold signet ring"),
    "Valerius": ("on the deck of a war galley in the harbour", "a bronze helmet held under the arm"),
    "Theren": ("among olive trees in the hills at harvest", "a basket of olives"),
    "Aurelian": ("on the steps of the sea temple", "a shell pendant held in the hand"),
    "Marcellan": ("on the busy quay among bales of cargo", "a purse of coins"),
    "Cassian": ("in the quarry under the ridge", "a mason's hammer"),
    "Severin": ("in the stone hall of judgment", "a scroll of laws"),
    "Damaris": ("in the herb garden by the western gate", "a bundle of dried herbs"),
    "Veyra": ("on the mountain pastures in the wind", "a horn on a leather cord"),
    "Solenne": ("in an old house with shuttered windows", "a faded silk fan"),
}
TEMPERAMENT = {
    "mystic": "a distant dreaming gaze, head tilted as if listening to something far off",
    "romantic": "a wistful half-smile, open and leaning forward",
    "traditionalist": "stern and upright, chin raised, utterly composed",
    "sage": "calm and thoughtful, a slight frown of concentration",
    "pragmatist": "alert and purposeful, caught mid-gesture",
    "skeptic": "one eyebrow raised, arms folded, a wry look",
}
HOUSE_LIGHT = {
    "Corvane": "dim gold candlelight and heavy shadows", "Valerius": "cool bright sea light and wind",
    "Theren": "warm afternoon sun through olive leaves", "Aurelian": "pale dawn light through incense haze",
    "Marcellan": "warm lamplight glinting on coins", "Cassian": "hard dusty noon light",
    "Severin": "cool even light of a stone hall", "Damaris": "soft green morning light",
    "Veyra": "cold mountain light and drifting mist", "Solenne": "faded rose dusk light through shutters",
}


def scene_for(note: str, role: str, house: str) -> tuple[str, str]:
    text = f"{note or ''} {role or ''}".lower()
    for key, action, prop in SCENES:
        if key in text:
            return action, prop
    return HOUSE_SCENES[house]


def age_phrase(age: int, noun: str) -> str:
    if age < 30:
        return f"a young {noun} of {age}, smooth youthful face, no wrinkles"
    if age < 40:
        return f"a {noun} of {age} in the prime of life, firm unlined skin, dark hair"
    if age < 55:
        return f"a {noun} of {age}, middle-aged, first lines on the face"
    if age < 68:
        return f"an older {noun} of {age}, greying, lined face"
    return f"an old {noun} of {age}, white-haired, deeply wrinkled, aged"


def card_prompts(con, candidates: int = 4, only: list[int] | None = None) -> tuple[list[dict], list[str]]:
    """Portraits v2, character cards. Encoder 1 (prompt) gets who and what: age, action, prop, expression, clothes;
    encoder 2 (prompt_2) gets the look and the style: face, skin, hair, eyes, build, the house's light, ink and wash.
    Each is read up to 77 tokens, so splitting them lets more of the record reach the painting."""
    year = rows(con, "select max(year) y from storyteller_proposals")[0]["y"] or 0
    out, waiting = [], []
    for p in rows(con, "select p.id, p.name, p.born_year, p.note, p.dream_temperament, p.appearance, p.portrait_ref, m.role, "
                       "h.name house from people p join house_members m on m.person_id = p.id join houses h on h.id = m.house_id "
                       "where p.tier = 'principal' order by p.id"):
        if only and p["id"] not in only:
            continue
        a = json.loads(p["appearance"] or "{}")
        if not any(a.get(f) for f in ("build", "face", "hair")):
            waiting.append(p["name"])
            continue
        sex = a.get("sex") or sex_of(p["name"])
        age = year - p["born_year"]
        noun = ("girl" if sex == "f" else "boy") if age < 16 else ("woman" if sex == "f" else "man")
        from world.appearance import HOUSE_DRESS
        if a.get("scene"):
            scene = a["scene"]
        else:
            action, prop = scene_for(p["note"], p["role"], p["house"])
            scene = f"{action}, holding {prop}"
        clothing = re.sub(r"\s*\(House [^)]*\)", "", a["clothing"])
        colours = HOUSE_DRESS[p["house"]][0]
        # encoder 1: the SCENE first (what they are doing, with their prop), the figure at half length, then who
        # they are; younger women also get their own face and skin here, so they don't drift to one generic face
        # (each encoder reads only 77 tokens: short age words, the first clause of the mood and of the clothes)
        own_face = f", {', '.join(a['face'].split(', ')[:2])}" if sex == "f" and age < 40 else ""
        short_age = (f"a young {noun} of {age}" if age < 30 else f"a {noun} of {age}" if age < 55 else
                     f"an old {noun} of {age}, white-haired and lined" if age >= 68 else f"an older {noun} of {age}, greying")
        mood = TEMPERAMENT.get(p["dream_temperament"], "").split(",")[0]
        # test 3: the scene leads BOTH encoders (encoder 2, the stronger, took the face and drew headshots in test 2),
        # the framing is concrete, the style is pinned to a period and a technique
        prompt = (f"{scene}; waist-up figure in the middle ground, the whole scene visible, {short_age}{own_face}, {mood}, "
                  f"wearing {clothing.split(',')[0]}")
        prompt_2 = (f"{scene}; pen and ink drawing with flat watercolour washes of {colours}, Mediterranean antiquity, "
                    f"illustrated book plate; {a.get('skin', 'olive')} skin, {a['face']}, hair {a['hair'].split(',')[0]}")
        negative = CARD_NEGATIVE + ", " + CARD_NEGATIVE_3 + (", " + YOUNG_NEGATIVE if age < 40 else "")
        pose = (STORAGE_PUBLIC + f"sandbox/portraits/poses/{a['pose']}.png") if a.get("pose") else None
        for k in range(candidates):
            out.append({"id": p["id"], "k": k, "name": p["name"], "sex": sex, "prompt": prompt, "prompt_2": prompt_2,
                        "style": CARD_STYLE, "negative": negative, "seed": 7000 + p["id"] * 10 + k,
                        "pose": pose, "style_ref": STYLE_REF, "guidance": 7.5,
                        "reference": (STORAGE_PUBLIC + p["portrait_ref"]) if p["portrait_ref"] else None})
    return out, waiting


STORAGE_PUBLIC = "https://dbrtvwhslxkdpmuawrgd.supabase.co/storage/v1/object/public/arcadia/"
JOB = {"notebook": "notebooks/kaggle_portraits.ipynb", "slug": "arcadia-portraits", "title": "Arcadia Portraits"}


def paint(con, args) -> None:
    """Candidates on Kaggle -> the public bucket (sandbox/portraits/candidates/) -> portrait_candidates (engine record)."""
    batch, waiting = (card_prompts if args.style == "card" else prompts)(con, args.candidates, args.only)
    if waiting:
        print("waiting for their appearance to be written: " + ", ".join(waiting))
    if args.dry_run:
        for b in batch:
            if b["k"] == 0:
                print(f"p{b['id']} {b['name']}: {b['prompt']}" + (f"\n    [2] {b['prompt_2']}" if b.get("prompt_2") else ""))
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
    dest = ROOT / ("out/portrait_tests" if args.test else "out/portrait_candidates")
    with tempfile.TemporaryDirectory() as tmp:
        kaggle("kernels", "output", kernel, "-p", tmp, "--force")
        log = next(Path(tmp).glob("*.log"), None)
        minutes = gpu_minutes(log) if log else 0.0
        made = Path(tmp) / "portraits"
        if "COMPLETE" not in status or not (made / "portraits.json").exists():
            sys.exit(f"{kernel}: {status}, no portraits ({minutes:.1f} GPU minutes)")
        shutil.copytree(made, dest, dirs_exist_ok=True)
    done = json.loads((dest / "portraits.json").read_text())
    if args.test:   # a trial: kept here to look at, not uploaded, not on the review page
        print(f"{kernel}: {status} | {minutes:.1f} GPU minutes | {len(done)} test images in {dest.relative_to(ROOT)}")
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for d in done:
        remote = f"sandbox/portraits/candidates/p{d['id']}_{d['k']}.jpg"
        sb.upload_bytes(jpeg(dest / f"p{d['id']}_{d['k']}.png", quality=88), remote, "image/jpeg")
        con.execute("delete from portrait_candidates where person_id = ? and k = ?", (d["id"], d["k"]))
        con.execute("insert into portrait_candidates (person_id, k, seed, prompt, image, made_at) values (?, ?, ?, ?, ?, ?)",
                    (d["id"], d["k"], d["seed"], d["prompt"], remote, now))
    con.commit()
    print(f"{kernel}: {status} | {minutes:.1f} GPU minutes | {len(done)} candidates for "
          f"{len({d['id'] for d in done})} people; pick them on the review page (Portraits)")


def adopt(con=None) -> int:
    """Danny's picks (portrait_picks, chosen on the review page) become portraits: people.portrait is the chosen
    candidate, and the full-size image is kept as the person's reference (sandbox/portraits/ref/p<id>.png,
    people.portrait_ref) for every later portrait of them. Returns how many changed."""
    from memory_sync import client, select
    con = con or connect()
    sb = client()
    picks = select(sb, "portrait_picks?select=*")
    n = 0
    for pk in picks:
        c = rows(con, "select * from portrait_candidates where id = ? and person_id = ?", pk["candidate_id"], pk["person_id"])
        if not c:
            continue
        c = c[0]
        cur = rows(con, "select portrait from people where id = ?", c["person_id"])[0]["portrait"]
        if cur == c["image"]:
            continue
        ref = f"sandbox/portraits/ref/p{c['person_id']}.png"
        local = ROOT / f"out/portrait_candidates/p{c['person_id']}_{c['k']}.png"
        data = local.read_bytes() if local.exists() else sb.session.get(STORAGE_PUBLIC + c["image"], timeout=60).content
        sb.upload_bytes(data, ref, "image/png" if local.exists() else "image/jpeg")
        con.execute("update people set portrait = ?, portrait_ref = ? where id = ?", (c["image"], ref, c["person_id"]))
        n += 1
    con.commit()
    print(f"{n} portrait(s) adopted from the review page's picks")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="paint", choices=["paint", "adopt"])
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--no_push", action="store_true")
    ap.add_argument("--candidates", type=int, default=4)
    ap.add_argument("--only", type=lambda s: [int(x) for x in s.split(",")], help="person ids, e.g. 2,6")
    ap.add_argument("--style", choices=["card", "head"], default="card", help="card: half-body character plates (v2); head: v1")
    ap.add_argument("--test", action="store_true", help="a trial: download to out/portrait_tests, upload and record nothing")
    args = ap.parse_args()
    con = connect()
    paint(con, args) if args.command == "paint" else adopt(con)


if __name__ == "__main__":
    main()
