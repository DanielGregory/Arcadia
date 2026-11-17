# Phase 1: the dream engine

Status: **gate passed** (Daniel, Nov 2026). Production dreamer: run 4, with run 5 approved to take over after a
dry run (see "Production" below). Follows `docs/VISION.md`: the transformer supplies language and imagination;
it decides nothing about the world.

## The runs

Every run is a small GPT trained from scratch (`engine/model.py`) on public-domain books plus DreamBank dream
reports. Bits per character (bpc) is the loss converted so that models with different tokenizers compare:
lower is better.

| Run | What changed | Corpus | Model | Steps (best) | Best val bpc* | GPU min |
|---|---|---|---|---|---:|---:|
| 1 | baseline: one token per character (`engine/train_char.py`) | first reading list + DreamBank | 6 x 6 x 384 | — | 1.776 | — |
| 2 | 8,000-token BPE tokenizer; per-tier val loss | same, DreamBank 25% | 6 x 6 x 384 | 3000 | 1.553 | 15.0 |
| 3 | source tags (`<myth>` `<tale>` `<saga>` `<dream>`), more books, dropout 0.3 | 43 books, 14.3M chars | 6 x 6 x 384 (~11M) | 3000 | 1.594 | 18.0 |
| 4 | twice the steps, patience 3 (run 3 was still improving) | same as run 3 | same | 6000 (5750) | 1.500 | 28.4 |
| 5 | the run 5 reading list, five voices, a bigger model | 90 works + DreamBank, 35.0M chars | 8 x 8 x 512 (29.4M) | 8000 → stopped 7500 (7000) | 1.432 | 62.3 |

\* Each run's own validation set, so this column only compares runs that share a corpus (3 vs 4).
Runs 2 and 3 are not directly comparable: run 3's val set adds tags and a bigger library. Use the fixed
benchmark below to compare across corpora.

## Fixed benchmark: run 4's validation set

From run 5 on, every new model is scored on run 4's val set (`data/val.txt`, 1.46M characters) with every tag
removed, so all models read exactly the same plain text (`engine/evaluate.py`). Grouped by the tag each
passage had in run 4's corpus.

| bpc on run 4's val set | run 4 | run 5 | change |
|---|---:|---:|---:|
| **overall** | 1.533 | **1.379** | −0.154 (−10%) |
| `<dream>` DreamBank | 1.539 | 1.358 | −0.181 |
| `<myth>` core (Homer, Ovid, Virgil, Hesiod…) | 1.538 | 1.408 | −0.130 |
| `<tale>` dream books (Dunsany, MacDonald, Carroll…) | 1.538 | 1.382 | −0.156 |
| `<saga>` seasoning (Grimm, Poe, Njal…) | 1.509 | 1.334 | −0.175 |

(Run 4's overall 1.533 here vs 1.500 in its own log: the benchmark removes the tags, which were easy tokens.)

Run 5 on its own val set, by voice: chronicle 1.305 · myth 1.371 · dream 1.397 · tale 1.424 · wisdom 1.430 ·
poem 1.756. Poetry is the hardest voice; history the easiest.

## Overfitting check: train/val gap at the best step

| | train bpc | val bpc | gap |
|---|---:|---:|---:|
| run 4 | 1.386 | 1.500 | 0.114 |
| run 5 | 1.334 | 1.432 | 0.098 |

Twice the parameters and a smaller gap: the 2.5× larger corpus keeps the bigger model honest.

## Quality checks

- **Read test** (`out/read_test/make_read_test.py`): the same 20 prompts and seeds for every run.
  Run 4: 20/20 dreams ended themselves; run 5: 18/20.
- **Copy check** (`engine/copy_check.py`): longest run of words copied from the training text; ≥ 12 is flagged.
  Run 4: 7 words; run 5: 8 words; nothing flagged.
- **Voices** (run 5, `out/read_test/run5_voices.json`): `<poem>` writes verse lines, `<chronicle>` sounds like
  Thucydides, `<wisdom>` like Plato; primed with "In Corva, the city by the sea," each stays in its voice.

## What each run taught

1. Characters are a fine baseline but waste the model's capacity on spelling.
2. BPE: a big drop in bpc for free.
3. Tags let us ask for a voice; dropout 0.3 kept the small model from memorising.
4. Run 3 was under-trained, not over-fitted: doubling the steps helped more than anything else that round.
5. A bigger corpus can carry a bigger model: run 5 is better everywhere and over-fits less.

## Production

- The daily morning job dreams with the model named in `daily/production_model.txt`. Both run 4 and run 5
  are attached to every run, so switching back is a one-word edit (instant rollback).
- Run 5 replaces run 4 after a dry run of the full daily job (`daily/morning.py --model run5 --slot test_run5
  --no_publish`) confirms the runtime and the wallpaper.

Checkpoints: Hugging Face `DannyGregs/arcadia-dreams` (private): `run2/`, `run3/`, `run4/`, `run5/`.
Reports: `out/run5/report.md`, `out/run5/corpus_table.txt`.
