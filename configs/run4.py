"""Run 4: run 3 with twice the training steps.

    python -m engine.data_prep.build_corpus --tags --dreambank_reports 2529
    python -m engine.tokenizer --vocab_size 8000 --tags
    python -m engine.train --config configs/run4.py --out_dir /kaggle/working/run4

Run 3 was still improving at its last step (best = final, val 1.600 -> 1.594
over the last 250 steps) with a small train/val gap (0.14), so it was limited
by training time, not data. Run 4 changes only:
- max_steps 3000 -> 6000 (~30 passes over the 3.3M training tokens); the
  cosine schedule stretches to match, so the learning rate stays high longer
- early-stopping patience 2 -> 3 evals, so a brief plateau doesn't end a long run
Everything else (corpus, tags, tokenizer, model size, dropout 0.3, weight decay
0.1) is identical to run 3, so the bits-per-character numbers compare directly.
"""

tokenizer = "bpe"
bpe_vocab_size = 8000
bpe_model = "bpe8000_tags"

# Model: identical shape to runs 1 and 2
n_layer = 6
n_head = 6
n_embd = 384
block_size = 256
dropout = 0.3

# Training
batch_size = 64
max_steps = 6000
learning_rate = 3e-4
min_lr = 3e-5
warmup_steps = 100
weight_decay = 0.1
eval_every = 250
eval_batches = 50
tier_eval_batches = 20
early_stop_evals = 3

# Hardware
device = "cuda"
amp = True
