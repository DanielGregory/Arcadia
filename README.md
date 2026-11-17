# Arcadia

In Poussin's painting, shepherds find an inscription they can't agree on. Arcadia is a world built the same way: it records what happens, never what it means.

See [docs/VISION.md](docs/VISION.md) for the master vision: world engine, storyteller, inhabitants and transformer, with no master narrator.

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
| **DreamBank** (25% of the corpus) | Real dream reports from [DReAMy-lib/DreamBank-dreams-en](https://huggingface.co/datasets/DReAMy-lib/DreamBank-dreams-en), 50–400 words, each wrapped in `<dream>…</dream>` |

```bash
# Download, clean, cap seasoning, write data/arcadia.txt + data/train.txt + data/val.txt
python -m engine.data_prep.build_corpus

# Fetch arbitrary Gutenberg books as plain text, headers/footers stripped
python -m engine.data_prep.fetch_gutenberg 1727 8395 11 --out data/gutenberg

# Fetch and cache DreamBank reports on their own (build_corpus does this too)
python -m engine.data_prep.fetch_dreambank
```

Cleaning removes Gutenberg headers and footers, translator prefaces and introductions, commentary, indexes and footnotes. The val split is made of whole book sections (about 10% of each book) and about 10% of the sampled dream reports, not random lines.

## Training

Character-level training with settings from `configs/`:

```bash
# CPU smoke test (about a minute)
python -m engine.train_char --config configs/smoke.py --out_dir checkpoints/smoke

# Full run on a GPU (configs/full.py: 6 layers, 6 heads, 384 wide, context 256, 5000 steps)
python -m engine.train_char --config configs/full.py --out_dir checkpoints/full

# Sample from a checkpoint
python -m engine.sample --ckpt checkpoints/full/best.pt --chars 2000 --temperature 0.7 0.9 1.1
```

Each run writes `ckpt.pt` (latest), `best.pt` (lowest val loss), `loss_log.csv` and `sample.txt` to its `--out_dir`.
To train on Kaggle's free T4 GPU, upload `notebooks/kaggle_train.ipynb` to Kaggle, turn on GPU and Internet, and run all cells.

## Hugging Face Hub

Trained runs are stored in a private model repo, one folder per run:

```bash
export HF_TOKEN=...   # a Hugging Face access token with write access
python -m engine.hub push --repo <user>/arcadia-dreams --run_dir checkpoints/full
python -m engine.hub pull --repo <user>/arcadia-dreams --run full
```

The Kaggle notebook's last cell does the push, using a Kaggle Secret named `HF_TOKEN`.

## Run 2: BPE tokenizer

```bash
python -m engine.data_prep.build_corpus
python -m engine.tokenizer --vocab_size 8000            # SentencePiece BPE, trained on train.txt
python -m engine.train --config configs/run2.py --out_dir checkpoints/run2
python -m engine.sample --ckpt checkpoints/run2/best.pt --dreams 3 --temperature 0.9
```

`engine/train.py` reports loss per token and bits per character, overall and for each tier (core, dream, seasoning, dreambank), so runs with different tokenizers can be compared. On Kaggle use `notebooks/kaggle_train_run2.ipynb`. `engine/train_char.py` and `notebooks/kaggle_train.ipynb` are kept unchanged as the run 1 baseline.
