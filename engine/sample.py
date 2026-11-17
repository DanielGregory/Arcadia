"""Generate text from a checkpoint saved by engine/train.py or engine/train_char.py.

    python -m engine.sample --ckpt checkpoints/run2/best.pt --dreams 5
    python -m engine.sample --ckpt ... --dreams 5 --prompt "The old shepherd told me of a tomb"
    python -m engine.sample --ckpt ... --temperature 0.7 0.9 1.1          # free text, no <dream> wrapper
    python -m engine.sample --ckpt checkpoints/run3/best.pt --dreams 3 --tag myth   # run 3: ask for a voice

Sampling controls (all applied at every step, in this order):
  --repetition_penalty  makes tokens already used in this dream a little less likely
                        (1.0 = off, 1.1 = light). Stops "I go back to the door" loops.
  --temperature         divides the scores: below 1 safer, above 1 stranger.
  --top_k               only the k likeliest tokens may be picked (off by default).
  --top_p               "nucleus" sampling: only the smallest set of tokens whose
                        probabilities add up to p may be picked (0.9 by default).
                        Cuts off the long tail of unlikely tokens that produce
                        invented words, while keeping variety where the model is unsure.

Lengths: --tokens for BPE models (one token is ~4 characters), --chars for
character models (run 1). With --dreams, each dream stops at </dream> or at
the length limit; with --cut_sentence, a dream that hits the limit is cut back
to its last full sentence.
"""

from __future__ import annotations

import argparse
import re

import torch
from torch.nn import functional as F

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


@torch.no_grad()
def sample(
    model: GPT,
    idx: torch.Tensor,
    max_new_tokens: int,
    temperature: float = 0.9,
    top_k: int | None = None,
    top_p: float | None = 0.9,
    repetition_penalty: float = 1.1,
    stop_token: int | None = None,
    no_penalty_ids: set[int] = frozenset(),
) -> torch.Tensor:
    """Continue idx (1, T) by up to max_new_tokens tokens; return the full sequence."""
    prompt_len = idx.shape[1]
    for _ in range(max_new_tokens):
        # 1. Predict the next token from (at most) the last block_size tokens.
        logits, _ = model(idx[:, -model.config.block_size:])
        logits = logits[0, -1, :].float()                        # (vocab_size,)

        # 2. Repetition penalty (CTRL-style): every token already generated in
        #    this sample has its score pushed towards "less likely". Positive
        #    scores are divided by the penalty, negative ones multiplied, so the
        #    token always becomes less likely. Structural tokens (newline,
        #    </dream>) are exempt so paragraphs and endings aren't discouraged.
        if repetition_penalty != 1.0:
            used = set(idx[0, prompt_len:].tolist()) - set(no_penalty_ids)
            if used:
                u = torch.tensor(sorted(used), device=logits.device)
                s = logits[u]
                logits[u] = torch.where(s > 0, s / repetition_penalty, s * repetition_penalty)

        # 3. Temperature.
        logits = logits / temperature

        # 4. Top-k: drop everything below the k-th best score.
        if top_k is not None:
            kth = torch.topk(logits, min(top_k, logits.numel())).values[-1]
            logits[logits < kth] = float("-inf")

        # 5. Top-p (nucleus): sort by probability, keep the smallest prefix whose
        #    probabilities sum to top_p (always at least the single best token).
        probs = F.softmax(logits, dim=-1)
        if top_p is not None and top_p < 1.0:
            sorted_probs, order = torch.sort(probs, descending=True)
            cumulative = torch.cumsum(sorted_probs, dim=0)
            drop = cumulative - sorted_probs > top_p   # tokens entirely past the top_p mass
            sorted_probs[drop] = 0.0
            probs = torch.zeros_like(probs).scatter(0, order, sorted_probs)
            probs = probs / probs.sum()

        # 6. Sample one token and append it.
        next_token = torch.multinomial(probs, num_samples=1)     # (1,)
        idx = torch.cat((idx, next_token.view(1, 1)), dim=1)
        if stop_token is not None and next_token.item() == stop_token:
            break
    return idx


_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*(?=\s|$)")


def cut_to_last_sentence(text: str) -> str:
    """Trim text after its last full sentence (., ! or ?, plus any closing quote)."""
    ends = list(_SENTENCE_END.finditer(text))
    return text[: ends[-1].end()] if ends else text


def generate_dream(model, tok, prompt: str, max_tokens: int, device: str, cut_sentence: bool = True,
                   tag: str = "dream", **kw) -> tuple[str, bool]:
    """One passage: <tag>\\n + prompt, sampled until </tag> or max_tokens.

    tag is "dream" for a dream; run 3 models also know "myth", "tale" and "saga".
    Returns (text without the tags, whether the model closed it itself).
    """
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    if tok.sp.id_to_piece(tok.token_id(close_tag)) != close_tag:
        raise SystemExit(f"this model's tokenizer has no {open_tag} tag (source tags need a run 3 model)")
    start_text = f"{open_tag}\n" + prompt
    start = torch.tensor([tok.encode(start_text)], dtype=torch.long, device=device)
    end_id = tok.token_id(close_tag)
    ids = sample(model, start, max_tokens, stop_token=end_id,
                 no_penalty_ids={tok.newline_id, end_id}, **kw)[0].tolist()
    closed = ids[-1] == end_id
    text = tok.decode(ids[:-1] if closed else ids)
    text = text.removeprefix(f"{open_tag}\n").strip()
    if not closed and cut_sentence:
        text = cut_to_last_sentence(text)
    return text, closed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ckpt", required=True, help="checkpoint file (ckpt.pt or best.pt)")
    parser.add_argument("--chars", type=int, default=2000, help="length for character models")
    parser.add_argument("--tokens", type=int, default=250, help="length for BPE models")
    parser.add_argument("--temperature", type=float, nargs="+", default=[0.9])
    parser.add_argument("--top_k", type=int, default=None)
    parser.add_argument("--top_p", type=float, default=0.9, help="nucleus sampling mass (1.0 = off)")
    parser.add_argument("--repetition_penalty", type=float, default=1.1, help="1.0 = off")
    parser.add_argument("--dreams", type=int, default=0, help="BPE models: generate this many whole dreams")
    parser.add_argument("--tag", default="dream", choices=["dream", "myth", "tale", "saga"],
                        help="with --dreams: which source tag to generate under (run 3 models)")
    parser.add_argument("--prompt", default="", help='opening of each dream, after "<dream>\\n" (with --dreams)')
    parser.add_argument("--start", default="\n", help="raw starting text for free (non --dreams) sampling")
    parser.add_argument("--no_cut_sentence", action="store_true", help="keep a dream's unfinished last sentence")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    model, tok, ckpt = load(args.ckpt, args.device)
    print(f"{args.ckpt}: step {ckpt['step']}, val loss {ckpt['val_loss']:.4f}"
          + (f" ({ckpt['val_bpc']:.3f} bits/char)" if "val_bpc" in ckpt else ""))
    knobs = dict(top_k=args.top_k, top_p=args.top_p, repetition_penalty=args.repetition_penalty)

    for t in args.temperature:
        torch.manual_seed(args.seed)  # same seed per temperature, so they're comparable
        print(f"\n===== temperature {t} | top_p {args.top_p} | repetition penalty {args.repetition_penalty} =====")
        if args.dreams:
            if not isinstance(tok, BPETokenizer):
                raise SystemExit("--dreams needs a BPE checkpoint (run 2 or later)")
            # Backwards compatible: an old-style --start "<dream>\n..." still works as a prompt.
            prompt = args.prompt or (args.start.encode().decode("unicode_escape").removeprefix("<dream>\n")
                                     if args.start.startswith("<dream>") else "")
            for _ in range(args.dreams):
                text, closed = generate_dream(model, tok, prompt, args.tokens, args.device,
                                              cut_sentence=not args.no_cut_sentence, tag=args.tag,
                                              temperature=t, **knobs)
                print(f"<{args.tag}>\n{text}\n</{args.tag}>{'' if closed else '  [length limit]'}\n")
        else:
            start_text = args.start.encode().decode("unicode_escape") if "\\" in args.start else args.start
            start = torch.tensor([tok.encode(start_text)], dtype=torch.long, device=args.device)
            length = args.tokens if isinstance(tok, BPETokenizer) else args.chars
            ids = sample(model, start, length, temperature=t, **knobs)
            print(tok.decode(ids[0].tolist()))


if __name__ == "__main__":
    main()
