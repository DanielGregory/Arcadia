"""Train the Arcadia model with either tokenizer (run 2 onwards).

    python -m engine.tokenizer --vocab_size 8000                               # once, after build_corpus
    python -m engine.train --config configs/run2.py --out_dir /kaggle/working/run2

Compared with train_char.py (kept unchanged as the run 1 baseline):
- tokenizer = "char" or "bpe" in the config (BPE uses data/tokenizer/bpe<N>.model)
- per-tier validation loss: core, dream, seasoning and dreambank separately
- bits per character (bpc) next to every loss, so char and BPE runs can be
  compared: loss per token depends on how much text a token holds, bpc doesn't
- optional early stopping when val loss stops improving

What ends up in --out_dir:
    ckpt.pt        latest checkpoint (written at every evaluation)
    best.pt        checkpoint with the lowest validation loss
    loss_log.csv   step, losses, bpc per tier, learning rate, elapsed seconds
    sample.txt     a sample generated at the end of training
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
from engine.tokenizer import BPETokenizer, CharTokenizer

TIERS = ["core", "dream", "seasoning", "dreambank"]


# -----------------------------------------------------------------------------
# 1. Settings
# -----------------------------------------------------------------------------
@dataclass
class TrainConfig:
    """Defaults for every setting. A config file only lists what it changes."""

    # Tokenizer
    tokenizer: str = "bpe"      # "char" or "bpe"
    bpe_vocab_size: int = 8000  # which data/tokenizer/bpe<N>.model to use

    # Model shape (passed on to GPTConfig)
    n_layer: int = 6
    n_head: int = 6
    n_embd: int = 384
    block_size: int = 256
    dropout: float = 0.2

    # Training
    batch_size: int = 64
    max_steps: int = 3000
    learning_rate: float = 3e-4  # peak learning rate
    min_lr: float = 3e-5         # learning rate at max_steps (cosine decay from the peak)
    warmup_steps: int = 100      # linear warm-up from 0 to the peak
    weight_decay: float = 0.1
    grad_clip: float = 1.0       # cap on the gradient norm; 0 turns clipping off
    eval_every: int = 250
    eval_batches: int = 50       # batches averaged for the train and overall val loss
    tier_eval_batches: int = 20  # batches averaged for each tier's val loss
    early_stop_evals: int = 0    # stop after this many evals without a new best val loss (0 = never)

    # Sample written at the end of training
    sample_tokens: int = 300
    temperature: float = 0.9

    # Hardware
    device: str = "cuda"
    amp: bool = True             # float16 mixed precision (CUDA only)
    seed: int = 1337
    data_dir: str = "data"


def load_config(path: str) -> TrainConfig:
    """Read a config file (plain Python assignments) over the defaults."""
    cfg = TrainConfig()
    values = {k: v for k, v in runpy.run_path(path).items() if not k.startswith("_")}
    unknown = set(values) - {f.name for f in fields(TrainConfig)}
    if unknown:
        raise ValueError(f"{path}: unknown settings {sorted(unknown)}")
    for k, v in values.items():
        setattr(cfg, k, v)
    return cfg


def lr_at(step: int, cfg: TrainConfig) -> float:
    """Linear warm-up, then cosine decay from learning_rate down to min_lr at max_steps."""
    if step < cfg.warmup_steps:
        return cfg.learning_rate * (step + 1) / cfg.warmup_steps
    progress = (step - cfg.warmup_steps) / max(1, cfg.max_steps - cfg.warmup_steps)
    cosine = 0.5 * (1 + math.cos(math.pi * min(progress, 1.0)))  # goes 1 -> 0
    return cfg.min_lr + cosine * (cfg.learning_rate - cfg.min_lr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="config file, e.g. configs/run2.py")
    parser.add_argument("--out_dir", required=True, help="where checkpoints and the loss log go")
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
    # 2. Load the text and the tokenizer
    # -------------------------------------------------------------------------
    data_dir = Path(cfg.data_dir)
    train_text = (data_dir / "train.txt").read_text(encoding="utf-8")
    val_texts = {"val": (data_dir / "val.txt").read_text(encoding="utf-8")}
    for tier in TIERS:
        path = data_dir / f"val_{tier}.txt"
        if path.exists():
            val_texts[tier] = path.read_text(encoding="utf-8")

    if cfg.tokenizer == "char":
        tok = CharTokenizer.from_text(train_text + val_texts["val"])
    else:
        tok_path = data_dir / "tokenizer" / f"bpe{cfg.bpe_vocab_size}.model"
        if not tok_path.exists():
            raise SystemExit(f"{tok_path} not found: run `python -m engine.tokenizer --vocab_size {cfg.bpe_vocab_size}` first")
        tok = BPETokenizer.load(tok_path)

    # Encode everything once. chars_per_token converts a loss per token into
    # bits per character: bpc = loss / ln(2) / chars_per_token.
    data, chars_per_token = {}, {}
    for name, text in [("train", train_text), *val_texts.items()]:
        ids = tok.encode(text)
        data[name] = torch.tensor(ids, dtype=torch.long, device=cfg.device)
        chars_per_token[name] = len(text) / len(ids)
    print(f"tokenizer: {cfg.tokenizer}, {tok.vocab_size} tokens | "
          f"train: {len(data['train']):,} tokens ({chars_per_token['train']:.2f} chars/token) | "
          f"val: {len(data['val']):,} tokens")
    tokens_per_step = cfg.batch_size * cfg.block_size
    print(f"one pass over train = {len(data['train']) / tokens_per_step:.0f} steps; "
          f"{cfg.max_steps} steps = {cfg.max_steps * tokens_per_step / len(data['train']):.1f} passes")

    def bpc(name: str, loss: float) -> float:
        return loss / math.log(2) / chars_per_token[name]

    # -------------------------------------------------------------------------
    # 3. Batches: random windows of tokens, and the same windows shifted by one
    # -------------------------------------------------------------------------
    offsets = torch.arange(cfg.block_size, device=cfg.device)

    def get_batch(name: str) -> tuple[torch.Tensor, torch.Tensor]:
        d = data[name]
        starts = torch.randint(len(d) - cfg.block_size - 1, (cfg.batch_size,), device=cfg.device)
        x = d[starts[:, None] + offsets]      # inputs  (B, T)
        y = d[starts[:, None] + offsets + 1]  # targets (B, T): the next token at each position
        return x, y

    # -------------------------------------------------------------------------
    # 4. The model and the optimiser
    # -------------------------------------------------------------------------
    model_config = GPTConfig(
        block_size=cfg.block_size,
        vocab_size=tok.vocab_size,
        n_layer=cfg.n_layer,
        n_head=cfg.n_head,
        n_embd=cfg.n_embd,
        dropout=cfg.dropout,
    )
    model = GPT(model_config).to(cfg.device)
    print(f"model: {model.num_params() / 1e6:.2f}M parameters | device: {cfg.device} | amp: {use_amp}")

    # AdamW; weight decay only on the 2-D weight matrices, not biases or LayerNorm scales.
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": cfg.weight_decay}, {"params": no_decay, "weight_decay": 0.0}],
        lr=cfg.learning_rate,
        betas=(0.9, 0.95),
    )
    # Mixed precision (see train_char.py for the explanation). Both do nothing when amp is off.
    autocast = lambda: torch.autocast(device_type=cfg.device, dtype=torch.float16, enabled=use_amp)  # noqa: E731
    scaler = torch.amp.GradScaler(cfg.device, enabled=use_amp)

    # -------------------------------------------------------------------------
    # 5. Loss estimates: train, overall val, and each tier's val
    # -------------------------------------------------------------------------
    @torch.no_grad()
    def estimate_losses() -> dict[str, float]:
        model.eval()  # turns dropout off
        out = {}
        for name in data:
            n = cfg.eval_batches if name in ("train", "val") else cfg.tier_eval_batches
            total = 0.0
            for _ in range(n):
                with autocast():
                    _, loss = model(*get_batch(name))
                total += loss.item()
            out[name] = total / n
        model.train()
        return out

    def save(path: Path, step: int, val_loss: float) -> None:
        torch.save(
            {
                "model": model.state_dict(),
                "model_config": asdict(model_config),
                "train_config": asdict(cfg),
                "tokenizer": tok.state(),
                "step": step,
                "val_loss": val_loss,
                "val_bpc": bpc("val", val_loss),
            },
            path,
        )

    # -------------------------------------------------------------------------
    # 6. The training loop
    # -------------------------------------------------------------------------
    print(f"random-guess loss would be ln({tok.vocab_size}) = {math.log(tok.vocab_size):.2f}")
    tiers = [t for t in TIERS if t in data]
    log_path = out_dir / "loss_log.csv"
    with log_path.open("w", newline="") as f:
        csv.writer(f).writerow(["step", "train_loss", "val_loss", "val_bpc", *[f"{t}_bpc" for t in tiers], "lr", "elapsed_s"])

    best_val, best_step, evals_since_best = float("inf"), 0, 0
    first_val = None
    t_train = time.time()
    step = 0
    for step in range(cfg.max_steps + 1):
        lr = lr_at(step, cfg)
        for group in optimizer.param_groups:
            group["lr"] = lr

        # --- evaluate, log and checkpoint every eval_every steps (and at the end)
        if step % cfg.eval_every == 0 or step == cfg.max_steps:
            losses = estimate_losses()
            elapsed = time.time() - t_train
            first_val = losses["val"] if first_val is None else first_val
            tier_str = " ".join(f"{t} {bpc(t, losses[t]):.3f}" for t in tiers)
            print(f"step {step:5d} | train {losses['train']:.4f} | val {losses['val']:.4f}"
                  f" ({bpc('val', losses['val']):.3f} bpc) | {tier_str} | lr {lr:.2e} | {elapsed:6.0f}s")
            with log_path.open("a", newline="") as f:
                csv.writer(f).writerow([step, f"{losses['train']:.4f}", f"{losses['val']:.4f}",
                                        f"{bpc('val', losses['val']):.4f}",
                                        *[f"{bpc(t, losses[t]):.4f}" for t in tiers], f"{lr:.3e}", f"{elapsed:.1f}"])
            if step > 0:
                save(out_dir / "ckpt.pt", step, losses["val"])
                if losses["val"] < best_val:
                    best_val, best_step, evals_since_best = losses["val"], step, 0
                    save(out_dir / "best.pt", step, best_val)
                else:
                    evals_since_best += 1
                    if cfg.early_stop_evals and evals_since_best >= cfg.early_stop_evals:
                        print(f"early stop: val loss hasn't improved for {evals_since_best} evals (best at step {best_step})")
                        break
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
    # 7. Sample a dream from the best checkpoint
    # -------------------------------------------------------------------------
    model.load_state_dict(torch.load(out_dir / "best.pt", map_location=cfg.device)["model"])
    model.eval()
    start = torch.tensor([tok.encode("<dream>\n")], dtype=torch.long, device=cfg.device)
    stop = tok.token_id("</dream>") if isinstance(tok, BPETokenizer) else None
    with autocast():
        ids = model.generate(start, max_new_tokens=cfg.sample_tokens, temperature=cfg.temperature, stop_token=stop)
    sample = tok.decode(ids[0].tolist())
    (out_dir / "sample.txt").write_text(sample, encoding="utf-8")
    print(f"\n----- sample (temperature {cfg.temperature}, best checkpoint) -----\n{sample}\n-----")

    print(f"\nsaved {out_dir / 'ckpt.pt'}, {out_dir / 'best.pt'} (step {best_step}), {log_path}")
    print(f"training: {train_seconds:.0f}s for {step} steps | total: {time.time() - t_start:.0f}s")
    print(f"best val loss {best_val:.4f} = {bpc('val', best_val):.3f} bits/char "
          f"(started at {first_val:.4f}; run 1 char baseline: 1.776 bits/char)")


if __name__ == "__main__":
    main()
