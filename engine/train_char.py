"""A tiny character-level training run on CPU, to check the model learns at all.

This is a smoke test, not the real training run: the model is small, the run
is short, and every character (not a tiktoken token) is one token. If the
validation loss falls steadily and the sample at the end starts to look like
English, the model, the data and the training loop are all wired up correctly.

Usage (after `python -m engine.data_prep.build_corpus`):
    python -m engine.train_char
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import torch

from engine.model import GPT, GPTConfig

# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
DATA_DIR = Path("data")
CHECKPOINT = Path("checkpoints/char_smoke.pt")

BATCH_SIZE = 32       # sequences per training step
BLOCK_SIZE = 128      # characters per sequence (the model's context window)
MAX_STEPS = 500       # training steps
LEARNING_RATE = 1e-3
EVAL_EVERY = 50       # print train/val loss this often
EVAL_BATCHES = 20     # batches averaged for each loss estimate
SAMPLE_CHARS = 500
TEMPERATURE = 0.8
SEED = 1337

DEVICE = "cpu"


def main() -> None:
    t_start = time.time()
    torch.manual_seed(SEED)

    # -------------------------------------------------------------------------
    # 1. Load the text and build the character vocabulary
    # -------------------------------------------------------------------------
    train_text = (DATA_DIR / "train.txt").read_text(encoding="utf-8")
    val_text = (DATA_DIR / "val.txt").read_text(encoding="utf-8")

    # Every distinct character in the corpus becomes one token id.
    chars = sorted(set(train_text) | set(val_text))
    stoi = {ch: i for i, ch in enumerate(chars)}  # "string to integer"
    itos = {i: ch for ch, i in stoi.items()}      # "integer to string"

    def encode(s: str) -> list[int]:
        return [stoi[c] for c in s]

    def decode(ids: list[int]) -> str:
        return "".join(itos[i] for i in ids)

    # The whole corpus as one long tensor of ids.
    train_data = torch.tensor(encode(train_text), dtype=torch.long)
    val_data = torch.tensor(encode(val_text), dtype=torch.long)
    print(f"vocab: {len(chars)} characters | train: {len(train_data):,} | val: {len(val_data):,}")

    # -------------------------------------------------------------------------
    # 2. Batches: random windows of the text, and the same windows shifted by one
    # -------------------------------------------------------------------------
    def get_batch(split: str) -> tuple[torch.Tensor, torch.Tensor]:
        data = train_data if split == "train" else val_data
        # BATCH_SIZE random start positions, each leaving room for BLOCK_SIZE + 1 chars.
        starts = torch.randint(len(data) - BLOCK_SIZE - 1, (BATCH_SIZE,))
        x = torch.stack([data[s : s + BLOCK_SIZE] for s in starts])          # inputs  (B, T)
        y = torch.stack([data[s + 1 : s + 1 + BLOCK_SIZE] for s in starts])  # targets (B, T): the next char at each position
        return x.to(DEVICE), y.to(DEVICE)

    # -------------------------------------------------------------------------
    # 3. The model: small config, vocabulary = our characters
    # -------------------------------------------------------------------------
    config = GPTConfig(
        block_size=BLOCK_SIZE,
        vocab_size=len(chars),
        n_layer=4,
        n_head=4,
        n_embd=128,
        dropout=0.0,  # 500 steps is far too short to overfit, so dropout would only slow learning
    )
    model = GPT(config).to(DEVICE)
    print(f"model: {model.num_params() / 1e6:.2f}M parameters")

    # AdamW: the standard optimiser for transformers. It keeps a running
    # average of each weight's gradient and adjusts each weight's step size.
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)

    # -------------------------------------------------------------------------
    # 4. Loss estimate: average over several batches so the number is stable
    # -------------------------------------------------------------------------
    @torch.no_grad()
    def estimate_loss() -> dict[str, float]:
        model.eval()  # turns dropout off
        out = {}
        for split in ("train", "val"):
            losses = [model(*get_batch(split))[1].item() for _ in range(EVAL_BATCHES)]
            out[split] = sum(losses) / len(losses)
        model.train()
        return out

    # -------------------------------------------------------------------------
    # 5. The training loop
    # -------------------------------------------------------------------------
    print(f"random-guess loss would be ln({len(chars)}) = {math.log(len(chars)):.2f}")
    history = []
    t_train = time.time()
    for step in range(MAX_STEPS + 1):
        if step % EVAL_EVERY == 0:
            losses = estimate_loss()
            history.append((step, losses["train"], losses["val"]))
            print(f"step {step:4d} | train loss {losses['train']:.4f} | val loss {losses['val']:.4f}"
                  f" | {time.time() - t_train:6.1f}s")
        if step == MAX_STEPS:
            break

        x, y = get_batch("train")
        _, loss = model(x, y)                  # forward pass: predictions and loss
        optimizer.zero_grad(set_to_none=True)  # clear the previous step's gradients
        loss.backward()                        # backward pass: gradient of the loss for every weight
        optimizer.step()                       # nudge every weight against its gradient
    train_seconds = time.time() - t_train

    # -------------------------------------------------------------------------
    # 6. Sample some text
    # -------------------------------------------------------------------------
    model.eval()
    start = torch.tensor([encode("\n")], dtype=torch.long, device=DEVICE)  # begin from a newline
    ids = model.generate(start, max_new_tokens=SAMPLE_CHARS, temperature=TEMPERATURE)
    print(f"\n----- sample ({SAMPLE_CHARS} chars, temperature {TEMPERATURE}) -----")
    print(decode(ids[0, 1:].tolist()))
    print("-----")

    # -------------------------------------------------------------------------
    # 7. Save a checkpoint: weights, config and vocabulary (needed to decode)
    # -------------------------------------------------------------------------
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"model": model.state_dict(), "config": config.__dict__, "chars": chars, "history": history},
        CHECKPOINT,
    )

    first_val, last_val = history[0][2], history[-1][2]
    print(f"\nsaved {CHECKPOINT}")
    print(f"training: {train_seconds:.1f}s for {MAX_STEPS} steps | total: {time.time() - t_start:.1f}s")
    print(f"val loss {first_val:.4f} -> {last_val:.4f} ({'down' if last_val < first_val else 'NOT down'})")


if __name__ == "__main__":
    main()
