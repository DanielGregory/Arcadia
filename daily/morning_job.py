"""Phase 1.5: make one morning's dream wallpaper, end to end.

This is the heavy half of the daily pipeline. It runs on Kaggle's GPU
(notebooks/kaggle_morning.ipynb); the light half, daily/morning.py, launches it
and publishes what it makes.

    python -m daily.morning_job --ckpt run4_best.pt --train train.txt --out out/morning
    python -m daily.morning_job ... --no_paint     # CPU test: skip SDXL, use the canonical Corva as the painting

The five steps, all in this one file:

  1. DREAM     run 4 dreams 24 candidates: half in its <dream> voice, a
               quarter each as <myth> and <tale> (half with no opening, half
               with an opening from the pool below). The day's date is the random
               seed, so a morning can always be re-made exactly.
  2. SELECT    every candidate is checked and scored: it should end itself, be
               a sensible length, not repeat itself, and not copy its training
               text (12+ words in a row found in train.txt rules it out). Then
               the editor model JUDGES each survivor: does it hold together?
               That rating is only a floor (engine/memory/novelty.py). Among the
               dreams that clear it, the most NOVEL (far from recent mornings,
               with new or rare images) are favoured, and the winner is drawn
               at random weighted by novelty, so strange dreams win often.
  3. REMEMBER  the editor model (Qwen2.5-1.5B-Instruct) tidies the best
               candidates into the "as remembered" version. The first one whose
               edit passes the retention checks (engine/remember.py) wins; if
               none pass, the best dream is used raw and the edit is dropped.
  4. PAINT     the editor condenses the dream into one painting's worth of
               strangest images, combined literally into one impossible scene
               (dreams are crazy; the calm brushstroke beauty belongs to the
               world itself). SDXL paints it twice (landscape for the desktop,
               portrait for the phone).
               Dreams change art style; the waking-world Corva never does. The
               style comes from a pool chosen by the dream's source tag (see
               STYLES), picked by the day's seed, with a ~10% wildcard drawn
               from every pool. No Corva style reference for dream paintings.
  5. WALLPAPER render/wallpaper.py sets ONE sentence over each painting: the
               editor picks the most vivid sentence of the "as remembered"
               dream. Label: Arcadia's calendar ("Dream N · Corva"), not the
               real date; the full dream and the real date live in the gallery.

Output, in --out/<date>/:
    morning.json            everything: candidates, scores, the pick, the edit,
                            retention, the painting prompt, seeds, timings
    morning.md              the same, readable
    painting_desktop.png    1344x768     painting_phone.png     768x1344
    wallpaper_desktop.png   2560x1440    wallpaper_phone.png    1290x2796
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import json
import random
import re
import time
from pathlib import Path

import torch

from engine.copy_check import FLAG_WORDS, longest_copied_run
from engine.memory import novelty
from engine.remember import Rememberer, is_flagged, length_ratio, retention
from engine.sample import cut_to_last_sentence, generate_dream, load

ROOT = Path(__file__).resolve().parents[1]
GENESIS = dt.date(2026, 11, 17)  # morning 1: the first day of Phase 1.5
STYLE_REFERENCE = "assets/canonical/corva.png"

# Same sampling settings as the run 4 read test.
SETTINGS = dict(temperature=0.9, top_p=0.9, repetition_penalty=1.1)
MAX_TOKENS = 250

# Openings the model can be started from (from the read test: storyteller and
# "the gods" openings gave the most Arcadian dreams). Half the candidates get
# one; the other half start from nothing and go wherever the model goes.
OPENINGS = [
    "The old shepherd told me of a tomb in the olive grove where",
    "The fisherman's wife said that long ago, before Corva had walls,",
    "They say that in the hills above Corva there was a well that",
    "An old woman by the harbour told the children how the first ship",
    "The herdsman sat by the fire and spoke of the night the river",
    "In the days before the city, the people of the shore believed that",
    "The traveller told us of a country beyond the mountains where",
    "My grandmother said that when she was a girl the stars over Corva",
    "In Corva, the city by the sea, I dreamed that the gods",
    "The gods of the harbour were angry, and the sea",
    "Before there were men in Corva, the gods",
    "The gods met on the mountain above the city and",
    "When the gods came down to the market at Corva,",
    "In the dream the gods of Corva were sleeping, and",
    "I dreamed I was walking on the shore below Corva and",
    "Last night I dreamed of the stairway up to the temple, and",
]

# --- 3. the painting prompt -------------------------------------------------
PAINT_SYSTEM = """You turn a dream into the description of ONE surreal painting.
Dreams are strange, and the painting must be just as strange. Choose THREE of the strangest, most visual things in the dream and put them together in one impossible scene, taken literally: wrong scale, wrong place, things that cannot be together. Do not make it sensible and do not explain it.

Rules:
- Write a phrase that describes a scene, the way a painting's catalogue entry does, NOT a list of keywords: say where each thing is and what it is doing.
- Exactly three things, at most 30 words in all, one line, no full stop at the end.
- Only things you can SEE. No names, no thoughts, no dialogue, no story.
- Take the images from the dream; do not invent new ones. Turn a strange word into a strange object.
Reply with the description only."""

# --- 4. art styles ---------------------------------------------------------------
# Dream paintings vary in style; the waking-world Corva stays one consistent
# painting. The pool depends on the dream's source tag (which voice the model
# dreamed in). Styles are described in words, never by naming an artist.
# Each entry: name -> (description for the prompt, extra negative words).
STYLES = {
    "myth": {
        "fresco": ("ancient fresco on cracked plaster wall, chalky earth pigments, faded ochre and lapis blue, "
                   "flat solemn figures", ""),
        "byzantine mosaic": ("Byzantine mosaic of tiny glass tesserae, shimmering gold background, flat solemn figures, "
                             "dark outlines", ""),
        "red-figure pottery": ("ancient Greek red-figure vase painting, terracotta orange figures on glossy black, "
                               "fine black line detail, figures in profile", ""),
        "stormy romantic oil": ("stormy romantic oil painting, sublime landscape, towering clouds, dramatic light "
                                "breaking through darkness, thick brushwork", ""),
    },
    "tale": {
        "symbolist": ("symbolist painting, muted jewel colours, mysterious solemn figures, decorative gold patterns, "
                      "hazy mystical atmosphere", ""),
        "illuminated manuscript": ("medieval illuminated manuscript miniature, tempera and gold leaf on vellum, flat bright "
                                   "colours, ornate decorated border", "allow_border"),
        "woodcut": ("woodcut print, bold black carved lines on cream paper, high contrast, hand-printed texture, "
                    "black and white", ""),
    },
    "dream": {
        "metaphysical": ("metaphysical painting, empty arcades, long raking shadows, deserted piazza, still green sky, "
                         "eerie silence, smooth flat colour", ""),
        "watercolor": ("loose watercolour painting, soft bleeding washes, wet paper texture, pale luminous colours", ""),
        "charcoal": ("charcoal drawing on rough paper, smudged black and grey, deep shadows, expressive strokes, "
                     "monochrome", ""),
        "stained glass": ("stained glass window, glowing jewel-coloured glass, thick black lead lines, light shining "
                          "through", "allow_border"),
        "faded photograph": ("faded antique photograph, sepia tones, soft focus, scratched and stained print, "
                             "early twentieth century", "allow_photo"),
    },
}
# Tags whose pool is not defined yet borrow one (run 4's <saga>; run 5's new tags
# until they get their own pools).
STYLE_POOL_FOR_TAG = {"saga": "myth", "poem": "tale", "wisdom": "myth", "chronicle": "myth"}
WILDCARD = 0.10
NEGATIVE_BASE = "text, letters, words, watermark, signature, modern buildings, cars, blurry, deformed hands, extra limbs"


def choose_style(tag: str, seed: int) -> dict:
    """The day's art style: from the tag's pool, or (~10%) a wildcard from any pool. Same seed, same style."""
    rng = random.Random(f"style-{seed}")
    pool_name = tag if tag in STYLES else STYLE_POOL_FOR_TAG.get(tag, "dream")
    wildcard = rng.random() < WILDCARD
    if wildcard:
        pool_name = rng.choice(sorted(STYLES))
    name = rng.choice(sorted(STYLES[pool_name]))
    description, allow = STYLES[pool_name][name]
    negative = NEGATIVE_BASE
    if allow != "allow_border":
        negative += ", picture frame, border"
    if allow != "allow_photo":
        negative += ", photograph, 3d render"
    return {"name": name, "pool": pool_name, "tag": tag, "wildcard": wildcard,
            "description": description, "negative": negative}


# --- 5. the caption: one sentence -------------------------------------------------
CAPTION_SYSTEM = """You choose the caption for a painting of a dream.
You get the dream's sentences, numbered. Choose the ONE sentence that is the most vivid and strange and still makes sense read on its own.
Reply with its number only."""


def split_sentences(text: str) -> list[str]:
    found = re.findall(r".+?[.!?][\"'”’)]*(?=\s|$)|.+$", " ".join(text.split()))
    return [x.strip() for x in found if x.strip()]


def best_sentence(editor: Rememberer, text: str) -> str:
    """The editor's pick of the dream's best single sentence (read from its answer probabilities)."""
    sentences = split_sentences(text)
    usable = [i for i, x in enumerate(sentences[:9]) if 5 <= len(x.split()) <= 40]
    if len(usable) <= 1:
        return sentences[usable[0]] if usable else (sentences[0] if sentences else text)
    listing = "\n".join(f"{n}. {sentences[i]}" for n, i in enumerate(usable, 1))
    tok, model = editor.tok, editor.model
    messages = [{"role": "system", "content": CAPTION_SYSTEM}, {"role": "user", "content": listing}]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    with torch.no_grad():
        logits = model(**tok(prompt, return_tensors="pt").to(editor.device)).logits[0, -1].float()
    answers = [tok.encode(str(n))[0] for n in range(1, len(usable) + 1)]
    return sentences[usable[int(torch.argmax(logits[answers]))]]


# --- 2b. the coherence judge -------------------------------------------------
# Tested on Morning 1's candidates: Qwen's plain fluency (how likely it finds
# the text) preferred flat modern DreamBank prose, but asking it to RATE
# coherence picked the dreams a reader would pick. We read the rating from the
# model's probabilities over the answers "1".."10" (the expected value), which
# is smoother and more repeatable than taking the single number it would say.
JUDGE_SYSTEM = """You judge short passages: dreams, myths and tales. Score how well the dream HOLDS TOGETHER: does it follow one thread (a place, a situation, a person) from sentence to sentence, so a reader can picture what happens? Strange events are fine; dreams are strange. Jumbled grammar, sentences that don't connect, and nonsense words score low.
Reply with one number from 1 (incoherent word salad) to 10 (one clear, vivid thread)."""


def judge(editor: Rememberer, text: str) -> float:
    """Expected 1-10 coherence rating of a dream, from the editor model."""
    tok, model = editor.tok, editor.model
    messages = [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": text}]
    prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    with torch.no_grad():
        logits = model(**tok(prompt, return_tensors="pt").to(editor.device)).logits[0, -1].float()
    answers = [tok.encode(str(n))[0] for n in range(1, 11)]  # "10" starts with the "1" token; fine for an estimate
    probs = torch.softmax(logits[answers], dim=0)
    return sum(n * probs[n - 1].item() for n in range(1, 11))


# The 1.5B editor is good at faithful, careful work (remembering, judging) but
# too literal for this: it tidied every dream back into a plain scene. The 3B
# model, loaded only for this step, keeps the strangeness (tested on Morning 1).
PAINT_MODEL = "Qwen/Qwen2.5-3B-Instruct"

# SDXL has two text encoders, each reading at most 77 tokens. The scene goes
# into both (the v2 lesson: a scene only in the first encoder gets ignored);
# the second one also carries the style, FIRST, so it is never cut off.


# Words from the modern world. The dreamers live in Arcadia, so a morning dream
# about cars and phones (DreamBank is 20th-century American) fits less well.
# Not banned, just ranked lower: -0.3 per different modern word, up to -1.5.
MODERN = set("""
car cars truck bus buses train trains plane airplane airport phone phones telephone television tv radio computer
internet email cd movie movies film camera photo school schools teacher class classes college university office
hospital doctor nurse store stores mall supermarket restaurant elevator apartment highway street cop cops police
gun guns bomb money dollars job boss coffee pizza hotel bathroom shower kitchen refrigerator jeans shirt
""".split())


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text.lower())


def distinct_trigrams(text: str) -> float:
    """Share of word trigrams that are unique: 1.0 = no repetition; loops score low."""
    w = words(text)
    grams = [tuple(w[i:i + 3]) for i in range(len(w) - 2)]
    return len(set(grams)) / len(grams) if grams else 0.0


def junk(text: str) -> str | None:
    """Corpus leftovers that make a dream unusable (the run 5 cleanup list)."""
    if re.search(r"\[\s*BL\s*\]|\[|\]", text):
        return "bracket marker"
    if re.search(r"\w-{2,}|-{3,}", text):
        return "redaction mark (DreamBank hides names as 'P---')"
    if re.search(r"(^|\s)\d{2,4}(\s|$)", text):
        return "stray number (line numbers from a poem?)"
    return None


def score(c: dict, train: str) -> dict:
    """Score one candidate; higher is better. Rejected candidates get score None.

    The score is deliberately simple and easy to read:
      +1.0  if the model ended the dream itself (closed its </dream> tag)
      +2.0 * distinct trigram share (1.0 = no repeated phrases)
      +1.0  if the length is in the sweet spot (70-180 words), less outside it
      -0.3  per different modern word (car, school, phone...), at most -1.5
      +0.3  if it grew from an Arcadian opening (those dreams are set in Corva)
      -0.001 per word away from 120: only matters as a tie-break
    """
    text = c["text"]
    n = len(text.split())
    c["words"] = n
    c["distinct_trigrams"] = round(distinct_trigrams(text), 3)
    c["copied_words"], c["copied_run"] = longest_copied_run(text, train)
    reason = junk(text)
    if n < 40:
        reason = "too short"
    elif n > 240:
        reason = "too long"
    elif c["copied_words"] >= FLAG_WORDS:
        reason = f"copies {c['copied_words']} words of its training text"
    elif c["distinct_trigrams"] < 0.85:
        reason = "repeats itself"
    if reason:
        c["rejected"], c["score"] = reason, None
        return c
    fit = 1.0 if 70 <= n <= 180 else max(0.0, 1.0 - min(abs(n - 70), abs(n - 180)) / 60)
    c["modern"] = sorted(set(words(text)) & MODERN)
    modern = min(1.5, 0.3 * len(c["modern"]))
    arcadian = 0.3 if c.get("opening") else 0.0
    c["score"] = round(c["closed"] * 1.0 + 2.0 * c["distinct_trigrams"] + fit - modern + arcadian - abs(n - 120) / 1000, 3)
    return c


# Which voices the candidates are dreamed in: half <dream>, a quarter each <myth> and <tale>.
TAG_MIX = ("dream", "dream", "myth", "tale")


def dream(ckpt: str, train: str, n: int, seed: int, device: str) -> list[dict]:
    """Steps 1 and 2: n candidates, scored, best first."""
    model, tok, _ = load(ckpt, device)
    rng = random.Random(seed)
    openings = rng.sample(OPENINGS, n // 2) + [""] * (n - n // 2)
    rng.shuffle(openings)
    tags = [TAG_MIX[i % len(TAG_MIX)] for i in range(n)]
    rng.shuffle(tags)
    out = []
    for i, (opening, tag) in enumerate(zip(openings, tags)):
        torch.manual_seed(seed * 100 + i)  # one fixed seed per candidate: reproducible
        text, closed = generate_dream(model, tok, opening, MAX_TOKENS, device, tag=tag, **SETTINGS)
        # A dream the model closed itself can still end mid-thought ("...the prophets said:").
        text = cut_to_last_sentence(text)
        c = score({"i": i, "seed": seed * 100 + i, "tag": tag, "opening": opening, "closed": closed, "text": text},
                  train)
        out.append(c)
        print(f"  candidate {i:2d} <{tag}>: {c['words']:3d} words, {'closed' if closed else 'cut   '}, "
              f"score {c['score'] if c['score'] is not None else 'rejected: ' + c['rejected']}", flush=True)
    del model
    return sorted(out, key=lambda c: (c["score"] is not None, c["score"] or 0), reverse=True)


def remember_best(editor: Rememberer, ranked: list[dict], tries: int = 3) -> tuple[dict, str | None, dict]:
    """Step 3: the first of the top candidates whose edit passes the checks."""
    usable = [c for c in ranked if c["score"] is not None] or ranked[:1]  # never come back empty-handed
    attempts = []
    for c in usable[:tries]:
        edit = editor.remember(c["text"])
        kept, added = retention(c["text"], edit)
        check = {"candidate": c["i"], "retention": round(kept, 3), "added": round(added, 3),
                 "length_ratio": round(length_ratio(c["text"], edit), 3), "flagged": is_flagged(c["text"], edit)}
        attempts.append({**check, "as_remembered": edit})
        print(f"  remembered candidate {c['i']}: retention {kept:.0%}, added {added:.0%}, "
              f"{'FLAGGED' if check['flagged'] else 'ok'}", flush=True)
        if not check["flagged"]:
            return c, edit, {"attempts": attempts}
    # Nothing passed: show the best dream as dreamed, with no edit.
    return usable[0], None, {"attempts": attempts}


def paint(scene: str, style: dict, seed: int, device: str, steps: int, ip_scale: float) -> dict:
    """Step 4: SDXL, text to image, in the day's style. With ip_scale > 0 the canonical Corva
    painting is added as a style-only reference (off for dreams: they change style; Corva doesn't)."""
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline
    from PIL import Image

    from render.generate_images import IP_ADAPTER

    dtype = torch.float16 if device == "cuda" else torch.float32
    extra = {}
    if ip_scale > 0:
        from transformers import CLIPVisionModelWithProjection

        extra["image_encoder"] = CLIPVisionModelWithProjection.from_pretrained(
            IP_ADAPTER["repo"], subfolder=IP_ADAPTER["image_encoder"], torch_dtype=dtype)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=dtype, use_safetensors=True,
        variant="fp16" if device == "cuda" else None,
        vae=AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dtype), **extra,
    ).to(device)
    pipe.set_progress_bar_config(disable=True)
    call = {}
    if ip_scale > 0:
        pipe.load_ip_adapter(IP_ADAPTER["repo"], subfolder=IP_ADAPTER["subfolder"], weight_name=IP_ADAPTER["weight_name"])
        # InstantStyle: the reference feeds only the "style" attention block (up_blocks.0, attention 1).
        pipe.set_ip_adapter_scale({"up": {"block_0": [0.0, ip_scale, 0.0]}})
        call["ip_adapter_image"] = Image.open(ROOT / STYLE_REFERENCE).convert("RGB")

    images = {}
    for name, (w, h) in {"desktop": (1344, 768), "phone": (768, 1344)}.items():
        t = time.time()
        # Encoder 1 gets the scene with the style after it; encoder 2 gets the style FIRST, so a long
        # scene can't push it past the 77-token window. The scene is in both (the v2 lesson).
        images[name] = pipe(
            prompt=f"{scene}, {style['description']}", prompt_2=f"{style['description']}: {scene}",
            negative_prompt=style["negative"], negative_prompt_2=style["negative"],
            width=w, height=h, num_inference_steps=steps, guidance_scale=6.5,
            generator=torch.Generator(device=device).manual_seed(seed), **call,
        ).images[0]
        print(f"  painted {name} {w}x{h} in {time.time() - t:.0f}s", flush=True)
    del pipe
    return images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ckpt", required=True, help="run 4 checkpoint (best.pt)")
    parser.add_argument("--train", type=Path, required=True, help="data/train.txt, for the copy check")
    parser.add_argument("--out", type=Path, default=Path("out/morning"))
    parser.add_argument("--date", help="YYYY-MM-DD (default: today, UTC)")
    parser.add_argument("--run", default="run4", help="model name recorded with the dream")
    parser.add_argument("--candidates", type=int, default=24)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--ip_scale", type=float, default=0.0,
                        help="Corva as a style reference (0 = off: dream paintings change style)")
    parser.add_argument("--no_paint", action="store_true", help="skip SDXL (CPU tests): canonical Corva as the painting")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    from PIL import Image

    from render.wallpaper import render

    day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(dt.timezone.utc).date()
    number = (day - GENESIS).days + 1
    seed = int(day.strftime("%Y%m%d"))
    out = args.out / day.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    timings = {}
    t0 = time.time()

    print(f"Morning {number} ({day}), seed {seed}, on {args.device}", flush=True)
    print("1-2. dreaming and selecting", flush=True)
    train = args.train.read_text(encoding="utf-8")
    ranked = dream(args.ckpt, train, args.candidates, seed, args.device)
    del train
    timings["dream"] = round(time.time() - t0, 1)

    print("2b-3. judging and remembering", flush=True)
    t = time.time()
    editor = Rememberer(device=args.device)
    # 2b. Coherence is a FLOOR, not the decider (engine/memory/novelty.py): every survivor is rated,
    #     those that clear the floor are scored for novelty, and the winner is drawn at random,
    #     weighted towards the most novel. All of it is logged in the record.
    for c in ranked:
        if c["score"] is not None:
            c["coherence"] = round(judge(editor, c["text"]), 2)
    judged = sorted((c for c in ranked if c["score"] is not None), key=lambda c: -c["coherence"])
    eligible = [c for c in judged if c["coherence"] >= novelty.COHERENCE_FLOOR]
    if len(eligible) < novelty.MIN_ELIGIBLE:
        eligible = judged[:novelty.MIN_ELIGIBLE] or ranked[:1]
    for c in ranked:
        c["eligible"] = c in eligible
    selection = novelty.score_novelty(eligible, day.isoformat(), args.device)
    winner, order = novelty.pick(eligible, seed)
    selection.update({"floor": novelty.COHERENCE_FLOOR, "temperature": novelty.TEMPERATURE,
                      "eligible": [c["i"] for c in eligible], "winner": winner["i"]})
    for c in order:
        print(f"  {'WIN ' if c is winner else '    '}candidate {c['i']:2d} <{c['tag']}> coherence {c['coherence']} "
              f"novelty {c['novelty']} (embedding {c['emb_novelty']} + symbols {c['symbol_bonus']}) "
              f"chance {c['chance']:.0%}", flush=True)
    chosen, remembered, edit_log = remember_best(editor, order)
    caption = best_sentence(editor, remembered or chosen["text"])
    print(f"  caption: {caption}", flush=True)
    del editor
    gc.collect()
    if args.device == "cuda":
        torch.cuda.empty_cache()
    # The painting prompt is written from the remembered text when there is one (it reads better).
    painter = Rememberer(model_id=PAINT_MODEL, device=args.device)
    scene = painter.chat(PAINT_SYSTEM, remembered or chosen["text"], max_new_tokens=80).strip()
    # The small editor sometimes ignores "one line" and goes on to retell the story (Morning 1 did).
    # The first sentence is the scene; the rest is narrative. Then cap it inside the 77-token window.
    scene = re.split(r"(?<=[.!?])\s", scene, maxsplit=1)[0].strip().rstrip(".")
    # If it still came out as a long comma list (Morning 1 test: seven items, SDXL used two),
    # keep the first four: SDXL paints the start of a prompt most faithfully anyway.
    parts = [x.strip() for x in scene.split(",")]
    if len(parts) > 4 and all(len(x.split()) <= 4 for x in parts):
        scene = ", ".join(parts[:4])
    scene = " ".join(scene.split()[:45])
    print(f"  painting prompt: {scene}", flush=True)
    del painter
    gc.collect()
    if args.device == "cuda":
        torch.cuda.empty_cache()  # give the GPU back before SDXL arrives
    timings["remember"] = round(time.time() - t, 1)

    style = choose_style(chosen.get("tag", "dream"), seed)
    print(f"4. painting: {style['name']} ({style['pool']} pool{', wildcard' if style['wildcard'] else ''})", flush=True)
    t = time.time()
    if args.no_paint:
        corva = Image.open(ROOT / STYLE_REFERENCE).convert("RGB")
        paintings = {"desktop": corva, "phone": corva}
    else:
        paintings = paint(scene, style, seed, args.device, args.steps, args.ip_scale)
    for name, img in paintings.items():
        img.save(out / f"painting_{name}.png")
    timings["paint"] = round(time.time() - t, 1)

    print("5. wallpapers", flush=True)
    sizes = {"desktop": (2560, 1440), "phone": (1290, 2796)}
    for name, size in sizes.items():
        render(caption, chosen["text"], out / f"wallpaper_{name}.png", size=size, background=paintings[name],
               label=f"Dream {number} · Corva")
    timings["total"] = round(time.time() - t0, 1)

    record = {
        "day": day.isoformat(), "number": number, "run": args.run, "seed": seed, "device": args.device,
        "raw": chosen["text"], "as_remembered": remembered, "opening": chosen["opening"],
        "chosen": chosen["i"], "tag": chosen.get("tag", "dream"), "caption": caption, "label": f"Dream {number} · Corva",
        "style": style, "painting_prompt": scene, "paint_model": PAINT_MODEL,
        "prompt_sent": f"{scene}, {style['description']}", "prompt_2_sent": f"{style['description']}: {scene}",
        "steps": args.steps, "ip_scale": args.ip_scale,
        "style_reference": STYLE_REFERENCE, "painted": not args.no_paint, "settings": SETTINGS,
        "edit": edit_log, "selection": selection, "candidates": ranked, "timings_s": timings,
    }
    (out / "morning.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "morning.md").write_text(markdown(record), encoding="utf-8")
    remember_in_memory(record, out, args.device)
    print(f"done in {timings['total']:.0f}s -> {out}", flush=True)


def remember_in_memory(record: dict, out: Path, device: str) -> None:
    """Phase 2: embed this morning's dreams (the chosen one and every candidate) and note their symbols,
    for the Sky. Runs after the wallpapers and the record exist, and can never fail the morning:
    any problem is printed and the memory simply waits for the next full sync (daily/memory_sync.py)."""
    try:
        from engine.memory.collect import morning_dreams
        from engine.memory.embed import embed
        from engine.memory.symbols import extract

        dreams = morning_dreams(record)
        vecs = embed([d["text"] for d in dreams], device=device)
        for d, v in zip(dreams, vecs):
            d["embedding"] = [round(float(x), 6) for x in v]
            d["symbols"] = extract(d.get("remembered") or d["text"])
        (out / "memory.json").write_text(json.dumps(dreams) + "\n", encoding="utf-8")
        print(f"memory: embedded {len(dreams)} dreams", flush=True)
    except Exception as err:  # noqa: BLE001
        print(f"memory: skipped ({type(err).__name__}: {err})", flush=True)


def markdown(r: dict) -> str:
    lines = [f"# {r.get('label', 'Dream ' + str(r['number']))} ({r['day']})", "",
             f"Dreamed by {r['run']} in its <{r.get('tag', 'dream')}> voice (seed {r['seed']}), "
             f"candidate {r['chosen']} of {len(r['candidates'])}"
             + (f", opening: *{r['opening']}*" if r["opening"] else ", no opening") + ".", ""]
    if r["as_remembered"]:
        lines += ["## As remembered", "", r["as_remembered"], ""]
    else:
        lines += ["*(No edit passed the retention checks; the dream is shown as dreamed.)*", ""]
    style = r.get("style") or {}
    lines += ["## As dreamed", "", r["raw"], "", "## Caption", "", r.get("caption", ""), "",
              "## Painting", "", f"> {r['painting_prompt']}", "",
              f"Style: **{style.get('name', '?')}** ({style.get('pool', '?')} pool"
              f"{', wildcard' if style.get('wildcard') else ''})", "",
              "## Candidates", "", "| # | tag | words | closed | trigrams | copied | coherence | eligible | novelty (emb + symbols) | new / rare images | chance | rejected |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in sorted(r["candidates"], key=lambda c: (-c.get("chance", -1), -(c.get("coherence") or 0))):
        nov = f"{c['novelty']} ({c['emb_novelty']} + {c['symbol_bonus']})" if "novelty" in c else ""
        images = " / ".join(", ".join(c.get(k, [])) or "–" for k in ("new_symbols", "rare_symbols")) if "novelty" in c else ""
        chance = f"{c['chance']:.0%}" if "chance" in c else ""
        lines.append(f"| {c['i']}{' ★' if c['i'] == r['chosen'] else ''} | {c.get('tag', 'dream')} | {c['words']} "
                     f"| {'yes' if c['closed'] else 'no'} | {c['distinct_trigrams']} | {c['copied_words']} "
                     f"| {c.get('coherence', '')} | {'yes' if c.get('eligible') else ''} | {nov} | {images} | {chance} "
                     f"| {c.get('rejected', '')} |")
    sel = r.get("selection")
    if sel:
        lines += ["", f"Selection: coherence floor {sel['floor']}, temperature {sel['temperature']}; novelty measured "
                      f"against {sel['reference_size']} {sel['reference']}; embeddings {sel['embeddings']}."]
    lines += ["", f"Timings (s): {r['timings_s']}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
