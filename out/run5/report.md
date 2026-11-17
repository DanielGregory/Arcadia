# Run 5 report (not in production; run 4 still dreams the mornings)

Model: 8 layers x 8 heads x 512 wide, 29.4M parameters (run 4: 13.8M). Corpus 35.0M characters,
tokenizer bpe8000_run5. Kaggle T4, 62.3 GPU minutes; early stop at step 7500, best at step 7000.

## Fixed benchmark: run 4's val set, all tags removed (both models read the same plain text)

| bits per character | run 4 | run 5 | change |
|---|---:|---:|---:|
| overall | 1.533 | **1.379** | -0.154 (-10%) |
| <dream> passages (DreamBank) | 1.539 | 1.358 | -0.181 |
| <myth> passages (core: Homer, Ovid, Virgil...) | 1.538 | 1.408 | -0.130 |
| <tale> passages (dream books: Dunsany, MacDonald...) | 1.538 | 1.382 | -0.156 |
| <saga> passages (seasoning: Grimm, Poe, Njal...) | 1.509 | 1.334 | -0.175 |

(The rows are run 4's own tags, which were tiers: <myth> core, <tale> dream books, <saga> seasoning,
<dream> DreamBank.)

## Run 5 on its own val set (with tags)

| tag | bpc |
|---|---:|
| chronicle | 1.305 |
| myth | 1.371 |
| dream (DreamBank) | 1.397 |
| tale | 1.424 |
| wisdom | 1.430 |
| poem | 1.756 |
| **overall** | **1.433** |

Poetry is hardest (line breaks, rhyme, archaic diction); history easiest (regular prose).

## Train/val gap at the best step

| | train bpc | val bpc | gap |
|---|---:|---:|---:|
| run 4 | 1.386 | 1.500 | 0.114 |
| run 5 | 1.334 | 1.432 | 0.098 |

A bigger model with a smaller gap: the larger corpus is doing its job.

## Read test (same 20 prompts and seeds as runs 2 and 4) and copy check

- run 5: 18/20 dreams closed themselves (run 4: 20/20); out/read_test/run5.md
- longest run copied from its own training text: 8 words (run 4: 7); none flagged (>= 12)
- every voice, unprimed and primed with "In Corva, the city by the sea,": out/read_test/run5_voices.json;
  all closed but one <poem>, longest copied run 7 words. Each voice is recognisable:
  <poem> writes in verse lines, <chronicle> like Thucydides, <wisdom> like a dialogue of Plato.

Checkpoint: Hugging Face DannyGregs/arcadia-dreams, run5/.
