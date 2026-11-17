"""Run 2: same model shape as run 1, but with an 8,000-token BPE tokenizer.

    python -m engine.tokenizer --vocab_size 8000
    python -m engine.train --config configs/run2.py --out_dir /kaggle/working/run2

With BPE the training set is ~1.9M tokens, so one pass is only ~115 steps.
3000 steps is ~26 passes, and the model will start overfitting before the
end: best.pt keeps the lowest-val-loss checkpoint, and early stopping ends
the run once val loss has not improved for 4 evaluations (1000 steps).
"""

tokenizer = "bpe"
bpe_vocab_size = 8000

# Model: identical to run 1, so the tokenizer is the only real difference
n_layer = 6
n_head = 6
n_embd = 384
block_size = 256       # tokens; ~985 characters of text
dropout = 0.2

# Training
batch_size = 64
max_steps = 3000
learning_rate = 3e-4
min_lr = 3e-5
warmup_steps = 100
eval_every = 250
eval_batches = 50
tier_eval_batches = 20
early_stop_evals = 4

# Hardware
device = "cuda"
amp = True
