# Arcadia

In Poussin's painting, shepherds find an inscription they can't agree on. Arcadia is a world built the same way: it records what happens, never what it means.

## What it is

Arcadia is a creative ML side project: a small transformer, trained from scratch, that generates dreams for an evolving simulated world. Each day the world changes a little, its inhabitants dream about it, and those dreams are rendered, remembered, and folded back into what the world becomes. The project keeps the record and leaves the meaning to whoever reads it.

## Layout

| Folder | Purpose |
| --- | --- |
| `engine/` | The dream model, training, sampling, and data prep (`engine/data_prep/`) |
| `render/` | Turning dreams into images (wallpapers, skies) |
| `world/` | Simulated world state, memory, and beliefs |
| `daily/` | Daily outputs: the day's dreams and renders |
| `notebooks/` | Exploration and experiments |
| `data/` | Raw downloaded corpora (gitignored) |

## Phases

- **1 · Dream engine:** train a small transformer to generate dream text.
- **1.5 · Morning wallpaper:** render each night's dream as a daily image.
- **2 · Memory and Sky:** the world remembers past dreams, and the sky reflects them.
- **3 · World and beliefs:** inhabitants form beliefs from what they've dreamed and seen.
- **4 · Culture and release:** shared stories, rituals, and a public release.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Data

The reading list lives in `engine/data_prep/books.py`: Gutenberg IDs, translators, and per-book cleaning rules.

| Tier | Books |
| --- | --- |
| **Core** (classical Mediterranean, most of the voice) | *Odyssey* (Butler, prose) · *Metamorphoses* (Riley, prose, 2 vols) · Theocritus, Bion and Moschus (Lang) · *Eclogues* and *Georgics* (Greenough and Rhoades, verse) · Hesiod and the Homeric Hymns (Evelyn-White) · Aesop (Vernon Jones) |
| **Dream layer** | Dunsany, *The Gods of Pegana* and *Time and the Gods* · MacDonald, *Phantastes* and *Lilith* · *Poems of Coleridge* · Carroll, both Alice books · *The Arabian Nights* (Lang's selection) |
| **Seasoning** (capped at 4% each) | *Frankenstein* · *Walden* · Grimms' Fairy Tales · Poe's tales (Raven Edition vol. II) · *Njal's Saga* (Dasent) |

```bash
# Download, clean, cap seasoning, write data/arcadia.txt + data/train.txt + data/val.txt
python -m engine.data_prep.build_corpus

# Fetch arbitrary Gutenberg books as plain text, headers/footers stripped
python -m engine.data_prep.fetch_gutenberg 1727 8395 11 --out data/gutenberg

# DreamBank: placeholder, not yet implemented
python -m engine.data_prep.fetch_dreambank
```

Cleaning removes Gutenberg headers and footers, translator prefaces and introductions, commentary, indexes and footnotes. The val split is made of whole book sections (about 10% of each book), not random lines.
