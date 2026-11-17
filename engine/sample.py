"""Generate text from a checkpoint saved by engine/train.py or engine/train_char.py.

    python -m engine.sample --ckpt /kaggle/working/run2/best.pt --temperature 0.7 0.9 1.1
    python -m engine.sample --ckpt ... --dreams 3              # three whole dreams, each ending at </dream>

Each temperature gets its own sample. Lower temperatures give safer, more
repetitive text; higher ones give stranger, riskier text.

--chars and --tokens set the length: --chars for character models (run 1),
--tokens for BPE models (one token is ~4 characters).
"""

from __future__ import annotations

import argparse

import torch

from engine.model import GPT, GPTConfig
from engine.tokenizer import BPETokenizer, CharTokenizer, tokenizer_from_state


def load(ckpt_path: str, device: str):
    """Rebuild the model and tokenizer exactly as they were trained."""
    ckpt = torch.load(ckpt_path, map_location=device)
    model = GPT(GPTConfig(**ckpt["model_config"])).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()  # turns dropout off
    # Run 1 checkpoints stored only the character list; later ones store the tokenizer.
    tok = tokenizer_from_state(ckpt["tokenizer"]) if "tokenizer" in ckpt else CharTokenizer(ckpt["chars"])
    return model, tok, ckpt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ckpt", required=True, help="checkpoint file (ckpt.pt or best.pt)")
    parser.add_argument("--chars", type=int, default=2000, help="length for character models")
    parser.add_argument("--tokens", type=int, default=500, help="length for BPE models")
    parser.add_argument("--temperature", type=float, nargs="+", default=[0.8])
    parser.add_argument("--top_k", type=int, default=None, help="only sample from the k likeliest tokens")
    parser.add_argument("--start", default="\n", help='text to start from, e.g. "<dream>\\n"')
    parser.add_argument("--dreams", type=int, default=0,
                        help="BPE models: generate this many whole dreams per temperature instead")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    model, tok, ckpt = load(args.ckpt, args.device)
    print(f"{args.ckpt}: step {ckpt['step']}, val loss {ckpt['val_loss']:.4f}"
          + (f" ({ckpt['val_bpc']:.3f} bits/char)" if "val_bpc" in ckpt else ""))

    start_text = args.start.encode().decode("unicode_escape") if "\\" in args.start else args.start
    is_bpe = isinstance(tok, BPETokenizer)
    length = args.tokens if is_bpe else args.chars

    # One sample per temperature, each from the same seed so they're comparable.
    for t in args.temperature:
        torch.manual_seed(args.seed)
        print(f"\n===== temperature {t} =====")
        if args.dreams and is_bpe:
            # Start each dream at <dream> and stop when the model writes </dream>.
            start = torch.tensor([tok.encode("<dream>\n")], dtype=torch.long, device=args.device)
            for _ in range(args.dreams):
                ids = model.generate(start, max_new_tokens=length, temperature=t, top_k=args.top_k,
                                     stop_token=tok.token_id("</dream>"))
                print(tok.decode(ids[0].tolist()) + "\n")
        else:
            start = torch.tensor([tok.encode(start_text)], dtype=torch.long, device=args.device)
            ids = model.generate(start, max_new_tokens=length, temperature=t, top_k=args.top_k)
            print(tok.decode(ids[0].tolist()))


if __name__ == "__main__":
    main()
