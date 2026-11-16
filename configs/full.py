"""Full training run: Kaggle GPU (T4).

    python -m engine.train_char --config configs/full.py --out_dir /kaggle/working/run1

Any setting not listed here keeps its default from TrainConfig in engine/train_char.py.
"""

# Model
n_layer = 6
n_head = 6
n_embd = 384
block_size = 256
dropout = 0.2

# Training
batch_size = 64
max_steps = 5000
learning_rate = 3e-4   # peak learning rate ...
min_lr = 3e-5          # ... cosine-decayed to this by the last step
eval_every = 250
eval_batches = 50

# Hardware
device = "cuda"
amp = True             # float16 mixed precision: roughly 2x faster on a T4
