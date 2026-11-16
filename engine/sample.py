"""Generate text from a checkpoint saved by engine/train_char.py.

    python -m engine.sample --ckpt /kaggle/working/run1/best.pt --chars 2000 --temperature 0.7 0.9 1.1

Each temperature gets its own sample. Lower temperatures give safer, more
repetitive text; higher ones give stranger, riskier text.
"""

from __future__ import annotations

import argparse

import torch

from engine.model import GPT, GPTConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ckpt", required=True, help="checkpoint file (ckpt.pt or best.pt)")
    parser.add_argument("--chars", type=int, default=2000, help="characters to generate per sample")
    parser.add_argument("--temperature", type=float, nargs="+", default=[0.8])
    parser.add_argument("--top_k", type=int, default=None, help="only sample from the k likeliest characters")
    parser.add_argument("--start", default="\n", help='text to start from, e.g. "<dream>\\n"')
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    # 1. Rebuild the model exactly as it was trained, then load its weights.
    ckpt = torch.load(args.ckpt, map_location=args.device)
    model = GPT(GPTConfig(**ckpt["model_config"])).to(args.device)
    model.load_state_dict(ckpt["model"])
    model.eval()  # turns dropout off
    print(f"{args.ckpt}: step {ckpt['step']}, val loss {ckpt['val_loss']:.4f}")

    # 2. The character vocabulary saved with the checkpoint.
    chars = ckpt["chars"]
    stoi = {ch: i for i, ch in enumerate(chars)}
    start_text = args.start.encode().decode("unicode_escape") if "\\" in args.start else args.start
    start = torch.tensor([[stoi[c] for c in start_text]], dtype=torch.long, device=args.device)

    # 3. One sample per temperature, each from the same seed so they're comparable.
    for t in args.temperature:
        torch.manual_seed(args.seed)
        ids = model.generate(start, max_new_tokens=args.chars, temperature=t, top_k=args.top_k)
        text = "".join(chars[i] for i in ids[0].tolist())
        print(f"\n===== temperature {t} =====\n{text}")


if __name__ == "__main__":
    main()
