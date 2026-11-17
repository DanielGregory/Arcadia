"""Run 5: the bigger reading list, five voices, and a bigger model.

    python -m engine.data_prep.build_corpus --tags --dreambank_share 0.135 --out_dir data/run5
    python -m engine.tokenizer --data_dir data/run5 --vocab_size 8000 --run5
    python -m engine.train --config configs/run5.py --out_dir /kaggle/working/run5

What changes from run 4:
- corpus: 35.0M characters (run 4: 14.3M), 90 public-domain works under five tags
  (<myth> <tale> <poem> <wisdom> <chronicle>) plus DreamBank as <dream> at 13.3%;
  every work capped at 4% (out/run5/corpus_table.txt)
- tokenizer: retrained on the new train split with the new tags reserved (bpe8000_run5)
- model: ~25M parameters, up from ~11M (8 layers, 8 heads, 512 wide; run 4: 6 x 6 x 384).
  More text can feed a bigger model without it just memorising: run 4's train/val gap
  was small, and this corpus is 2.5x larger
- up to 8000 steps, stopping early after 2 evals without a new best
Same: dropout 0.3, weight decay 0.1, block 256, learning-rate schedule.
"""

tokenizer = "bpe"
bpe_vocab_size = 8000
bpe_model = "bpe8000_run5"
data_dir = "data/run5"

n_layer = 8
n_head = 8
n_embd = 512
block_size = 256
dropout = 0.3

batch_size = 64
max_steps = 8000
learning_rate = 3e-4
min_lr = 3e-5
warmup_steps = 200
weight_decay = 0.1
eval_every = 250
eval_batches = 50
tier_eval_batches = 20
early_stop_evals = 2

device = "cuda"
amp = True
