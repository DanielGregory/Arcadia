"""CPU smoke test: a tiny model for 500 steps (about a minute on 4 cores).

    python -m engine.train_char --config configs/smoke.py --out_dir checkpoints/smoke
"""

n_layer = 4
n_head = 4
n_embd = 128
block_size = 128
dropout = 0.0          # 500 steps is far too short to overfit

batch_size = 32
max_steps = 500
learning_rate = 1e-3
min_lr = 1e-3          # constant learning rate
eval_every = 50
eval_batches = 20

device = "cpu"
amp = False
