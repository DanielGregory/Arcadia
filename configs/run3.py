"""Run 3: source tags, a bigger library, more regularisation.

    python -m engine.data_prep.build_corpus --tags --dreambank_reports 2529
    python -m engine.tokenizer --vocab_size 8000 --tags
    python -m engine.train --config configs/run3.py --out_dir /kaggle/working/run3

Changes from run 2:
- Source tags: every book passage (~1,000 characters) is wrapped in its tier's
  tag, <myth> (core), <tale> (dream books) or <saga> (seasoning); DreamBank
  reports keep <dream>. The tags are reserved single tokens in a retrained 8k
  BPE tokenizer (bpe8000_tags). At sampling time the tag picks the voice.
- 22 more books: the Iliad, Aeneid, Argonautica, Golden Ass, Lucian's True
  History, Plato's Atlantis and Er myths, Euripides, Sophocles, Aeschylus and
  Longus (core); five more Dunsany books, Morris's The Wood Beyond the World
  and Eddison's The Worm Ouroboros (dream).
- DreamBank keeps run 2's 2,529 reports (now cleaned of date stamps), so its
  share falls to ~14% of a 14.3M-character corpus. Seasoning stays capped at
  4% per book.
- Training set ~3.3M tokens: one pass is ~204 steps, so 3000 steps is ~15
  passes (run 2: 26).
- Dropout 0.3 (run 2: 0.2) and early-stopping patience 2 evals (500 steps).
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
max_steps = 3000
learning_rate = 3e-4
min_lr = 3e-5
warmup_steps = 100
weight_decay = 0.1
eval_every = 250
eval_batches = 50
tier_eval_batches = 20
early_stop_evals = 2

# Hardware
device = "cuda"
amp = True
