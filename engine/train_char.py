"""Train the Arcadia model at the character level.

Every character in the corpus is one token, so the vocabulary is small (~120)
and no tokenizer is needed. Settings come from a config file in configs/:

    python -m engine.train_char --config configs/smoke.py --out_dir checkpoints/smoke   # CPU, ~1 min
    python -m engine.train_char --config configs/full.py  --out_dir /kaggle/working/run1  # GPU

What ends up in --out_dir:
    ckpt.pt        the latest checkpoint (written at every evaluation)
    best.pt        the checkpoint with the lowest validation loss so far
    loss_log.csv   step, train loss, val loss, learning rate, elapsed seconds
    sample.txt     a sample generated at the end of training

Run `python -m engine.data_prep.build_corpus` first to create data/train.txt and data/val.txt.
"""

from __future__ import annotations

import argparse
import csv
import math
import runpy
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import torch

from engine.model import GPT, GPTConfig


# -----------------------------------------------------------------------------
# 1. Settings
# -----------------------------------------------------------------------------
@dataclass
class TrainConfig:
    """Defaults for every setting. A config file only lists what it changes."""

    # Model shape (passed on to GPTConfig)
    n_layer: int = 4
    n_head: int = 4
    n_embd: int = 128
    block_size: int = 128
    dropout: float = 0.0

    # Training
    batch_size: int = 32
    max_steps: int = 500
    learning_rate: float = 1e-3  # peak learning rate
    min_lr: float = 1e-3         # learning rate at the last step (cosine decay from the peak)
    warmup_steps: int = 0        # optional linear warm-up before the cosine decay
    weight_decay: float = 0.1
    grad_clip: float = 1.0       # cap on the gradient norm; 0 turns clipping off
    eval_every: int = 50
    eval_batches: int = 20       # batches averaged for each loss estimate

    # Sample written at the end of training
    sample_chars: int = 500
    temperature: float = 0.8

    # Hardware
    device: str = "cpu"
    amp: bool = False            # float16 mixed precision (CUDA only)
    seed: int = 1337
    data_dir: str = "data"


def load_config(path: str | None) -> TrainConfig:
    """Read a config file (plain Python assignments) over the defaults."""
    cfg = TrainConfig()
    if path is None:
        return cfg
    values = {k: v for k, v in runpy.run_path(path).items() if not k.startswith("_")}
    known = {f.name for f in fields(TrainConfig)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"{path}: unknown settings {sorted(unknown)}")
    for k, v in values.items():
        setattr(cfg, k, v)
    return cfg


def lr_at(step: int, cfg: TrainConfig) -> float:
    """Learning rate for this step: optional linear warm-up, then cosine decay.

    The cosine curve starts at learning_rate and glides down to min_lr at
    max_steps: big steps early while the model is far from good, small
    careful steps at the end.
    """
    if step < cfg.warmup_steps:
        return cfg.learning_rate * (step + 1) / cfg.warmup_steps
    progress = (step - cfg.warmup_steps) / max(1, cfg.max_steps - cfg.warmup_steps)
    cosine = 0.5 * (1 + math.cos(math.pi * min(progress, 1.0)))  # goes 1 -> 0
    return cfg.min_lr + cosine * (cfg.learning_rate - cfg.min_lr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/smoke.py", help="config file (default: configs/smoke.py)")
    parser.add_argument("--out_dir", default="checkpoints/run", help="where checkpoints and the loss log go")
    args = parser.parse_args()

    cfg = load_config(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if cfg.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("config asks for device 'cuda' but no GPU is available")
    use_amp = cfg.amp and cfg.device == "cuda"
    torch.manual_seed(cfg.seed)
    t_start = time.time()
    print(f"config: {args.config} -> {out_dir}")

    # -------------------------------------------------------------------------
    # 2. Load the text and build the character vocabulary
    # -------------------------------------------------------------------------
    data_dir = Path(cfg.data_dir)
    train_text = (data_dir / "train.txt").read_text(encoding="utf-8")
    val_text = (data_dir / "val.txt").read_text(encoding="utf-8")

    # Every distinct character in the corpus becomes one token id.
    chars = sorted(set(train_text) | set(val_text))
    stoi = {ch: i for i, ch in enumerate(chars)}  # "string to integer"
    itos = {i: ch for ch, i in stoi.items()}      # "integer to string"

    def encode(s: str) -> list[int]:
        return [stoi[c] for c in s]

    def decode(ids: list[int]) -> str:
        return "".join(itos[i] for i in ids)

    # The whole corpus as one long tensor of ids, kept on the training device
    # (a few million ids is only tens of MB, so it fits easily on a GPU).
    train_data = torch.tensor(encode(train_text), dtype=torch.long, device=cfg.device)
    val_data = torch.tensor(encode(val_text), dtype=torch.long, device=cfg.device)
    print(f"vocab: {len(chars)} characters | train: {len(train_data):,} | val: {len(val_data):,}")

    # -------------------------------------------------------------------------
    # 3. Batches: random windows of the text, and the same windows shifted by one
    # -------------------------------------------------------------------------
    def get_batch(split: str) -> tuple[torch.Tensor, torch.Tensor]:
        data = train_data if split == "train" else val_data
        # batch_size random start positions, each leaving room for block_size + 1 chars.
        starts = torch.randint(len(data) - cfg.block_size - 1, (cfg.batch_size,), device=cfg.device)
        offsets = torch.arange(cfg.block_size, device=cfg.device)
        x = data[starts[:, None] + offsets]      # inputs  (B, T)
        y = data[starts[:, None] + offsets + 1]  # targets (B, T): the next char at each position
        return x, y

    # -------------------------------------------------------------------------
    # 4. The model and the optimiser
    # -------------------------------------------------------------------------
    model_config = GPTConfig(
        block_size=cfg.block_size,
        vocab_size=len(chars),
        n_layer=cfg.n_layer,
        n_head=cfg.n_head,
        n_embd=cfg.n_embd,
        dropout=cfg.dropout,
    )
    model = GPT(model_config).to(cfg.device)
    print(f"model: {model.num_params() / 1e6:.2f}M parameters | device: {cfg.device} | amp: {use_amp}")

    # AdamW keeps a running average of each weight's gradient and adapts each
    # weight's step size. Weight decay gently pulls weights towards zero; it is
    # applied only to the 2-D weight matrices, not to biases or LayerNorm scales.
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": cfg.weight_decay}, {"params": no_decay, "weight_decay": 0.0}],
        lr=cfg.learning_rate,
        betas=(0.9, 0.95),
    )

    # Mixed precision: on the GPU, run the big matrix multiplies in float16
    # (faster, half the memory) while keeping the weights in float32. Small
    # float16 gradients can underflow to zero, so GradScaler multiplies the
    # loss up before backward() and divides the gradients back down before
    # the optimiser step. With amp off, both of these do nothing.
    autocast = lambda: torch.autocast(device_type=cfg.device, dtype=torch.float16, enabled=use_amp)  # noqa: E731
    scaler = torch.amp.GradScaler(cfg.device, enabled=use_amp)

    # -------------------------------------------------------------------------
    # 5. Loss estimate: average over several batches so the number is stable
    # -------------------------------------------------------------------------
    @torch.no_grad()
    def estimate_loss() -> dict[str, float]:
        model.eval()  # turns dropout off
        out = {}
        for split in ("train", "val"):
            losses = torch.zeros(cfg.eval_batches)
            for i in range(cfg.eval_batches):
                with autocast():
                    _, loss = model(*get_batch(split))
                losses[i] = loss.item()
            out[split] = losses.mean().item()
        model.train()
        return out

    def save(path: Path, step: int, val_loss: float) -> None:
        # Everything needed to rebuild the model and decode its output.
        torch.save(
            {
                "model": model.state_dict(),
                "model_config": asdict(model_config),
                "train_config": asdict(cfg),
                "chars": chars,
                "step": step,
                "val_loss": val_loss,
            },
            path,
        )

    # -------------------------------------------------------------------------
    # 6. The training loop
    # -------------------------------------------------------------------------
    print(f"random-guess loss would be ln({len(chars)}) = {math.log(len(chars)):.2f}")
    log_path = out_dir / "loss_log.csv"
    with log_path.open("w", newline="") as f:
        csv.writer(f).writerow(["step", "train_loss", "val_loss", "lr", "elapsed_s"])

    best_val = float("inf")
    first_val = None
    t_train = time.time()
    for step in range(cfg.max_steps + 1):
        lr = lr_at(step, cfg)
        for group in optimizer.param_groups:
            group["lr"] = lr

        # --- evaluate, log and checkpoint every eval_every steps (and at the end)
        if step % cfg.eval_every == 0 or step == cfg.max_steps:
            losses = estimate_loss()
            elapsed = time.time() - t_train
            first_val = losses["val"] if first_val is None else first_val
            print(f"step {step:5d} | train loss {losses['train']:.4f} | val loss {losses['val']:.4f}"
                  f" | lr {lr:.2e} | {elapsed:7.1f}s")
            with log_path.open("a", newline="") as f:
                csv.writer(f).writerow([step, f"{losses['train']:.4f}", f"{losses['val']:.4f}", f"{lr:.3e}", f"{elapsed:.1f}"])
            if step > 0:
                save(out_dir / "ckpt.pt", step, losses["val"])
                if losses["val"] < best_val:
                    best_val = losses["val"]
                    save(out_dir / "best.pt", step, best_val)
        if step == cfg.max_steps:
            break

        # --- one training step
        x, y = get_batch("train")
        with autocast():
            _, loss = model(x, y)              # forward pass: predictions and loss
        optimizer.zero_grad(set_to_none=True)  # clear the previous step's gradients
        scaler.scale(loss).backward()          # backward pass: gradient of the loss for every weight
        if cfg.grad_clip > 0:
            scaler.unscale_(optimizer)         # clip the real gradients, not the scaled-up ones
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        scaler.step(optimizer)                 # nudge every weight against its gradient
        scaler.update()
    train_seconds = time.time() - t_train

    # -------------------------------------------------------------------------
    # 7. Sample some text from the final model
    # -------------------------------------------------------------------------
    model.eval()
    start = torch.tensor([encode("\n")], dtype=torch.long, device=cfg.device)  # begin from a newline
    with autocast():
        ids = model.generate(start, max_new_tokens=cfg.sample_chars, temperature=cfg.temperature)
    sample = decode(ids[0, 1:].tolist())
    (out_dir / "sample.txt").write_text(sample, encoding="utf-8")
    print(f"\n----- sample ({cfg.sample_chars} chars, temperature {cfg.temperature}) -----")
    print(sample)
    print("-----")

    last_val = losses["val"]
    print(f"\nsaved {out_dir / 'ckpt.pt'}, {out_dir / 'best.pt'} (val {best_val:.4f}), {log_path}")
    print(f"training: {train_seconds:.1f}s for {cfg.max_steps} steps | total: {time.time() - t_start:.1f}s")
    print(f"val loss {first_val:.4f} -> {last_val:.4f} ({'down' if last_val < first_val else 'NOT down'})")


if __name__ == "__main__":
    main()
