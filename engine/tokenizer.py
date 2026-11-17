"""Tokenizers: turn text into a list of integer ids and back.

Two kinds, with the same interface (encode, decode, vocab_size):

- CharTokenizer: one id per character (what run 1 used). ~120 ids.
- BPETokenizer:  a SentencePiece BPE model trained on our own corpus. Common
  chunks ("the", " dream", "ing") become single tokens, so the same 256-token
  context window covers ~4x more text than with characters.

Train the BPE model (from data/train.txt only, so val stays unseen):
    python -m engine.tokenizer --vocab_size 8000
which writes data/tokenizer/bpe8000.model and prints how many characters an
average token covers.

How the BPE tokenizer handles a few special cases:
- "<dream>" and "</dream>" are reserved as single tokens, never split.
- Newlines: SentencePiece works line by line and never sees "\n", so each line
  is encoded separately and a reserved "<n>" token goes between lines.
- byte_fallback: a character the model never saw is spelled out as raw UTF-8
  bytes instead of becoming "unknown", so every text round-trips exactly.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

NEWLINE = "<n>"
SPECIAL_TOKENS = ["<dream>", "</dream>", NEWLINE]


class CharTokenizer:
    """Every distinct character is one token."""

    kind = "char"

    def __init__(self, chars: list[str]):
        self.chars = chars
        self.stoi = {ch: i for i, ch in enumerate(chars)}

    @classmethod
    def from_text(cls, text: str) -> "CharTokenizer":
        return cls(sorted(set(text)))

    @property
    def vocab_size(self) -> int:
        return len(self.chars)

    def encode(self, text: str) -> list[int]:
        return [self.stoi[c] for c in text]

    def decode(self, ids: list[int]) -> str:
        return "".join(self.chars[i] for i in ids)

    def state(self) -> dict:
        """What a checkpoint stores to rebuild this tokenizer."""
        return {"kind": self.kind, "chars": self.chars}


class BPETokenizer:
    """A SentencePiece BPE model, with newlines handled as a reserved token."""

    kind = "bpe"

    def __init__(self, model_proto: bytes):
        import sentencepiece as spm

        self.model_proto = model_proto
        self.sp = spm.SentencePieceProcessor(model_proto=model_proto)
        self.newline_id = self.sp.piece_to_id(NEWLINE)

    @classmethod
    def load(cls, path: str | Path) -> "BPETokenizer":
        return cls(Path(path).read_bytes())

    @property
    def vocab_size(self) -> int:
        return self.sp.get_piece_size()

    def token_id(self, piece: str) -> int:
        """The id of a reserved piece such as "</dream>"."""
        return self.sp.piece_to_id(piece)

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        for i, line in enumerate(text.split("\n")):
            if i:
                ids.append(self.newline_id)  # the "\n" that separated this line from the last
            if line:
                ids.extend(self.sp.encode(line))
        return ids

    def decode(self, ids: list[int]) -> str:
        # Decode each run of ids between newline tokens separately, then rejoin.
        lines, current = [], []
        for i in ids:
            if i == self.newline_id:
                lines.append(self.sp.decode(current))
                current = []
            else:
                current.append(i)
        lines.append(self.sp.decode(current))
        return "\n".join(lines)

    def state(self) -> dict:
        # The whole model is a few hundred KB, so it travels inside the checkpoint.
        return {"kind": self.kind, "model_proto": self.model_proto}


def tokenizer_from_state(state: dict) -> CharTokenizer | BPETokenizer:
    """Rebuild a tokenizer from what a checkpoint stored."""
    if state["kind"] == "char":
        return CharTokenizer(state["chars"])
    return BPETokenizer(state["model_proto"])


def train_bpe(train_file: Path, vocab_size: int, out_path: Path) -> BPETokenizer:
    """Train a SentencePiece BPE model on one text file."""
    import sentencepiece as spm

    text = train_file.read_text(encoding="utf-8")
    # SentencePiece reads one "sentence" per line; give it every non-empty line.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as f:
        for line in text.split("\n"):
            if line.strip():
                f.write(line + "\n")
        lines_path = f.name

    out_path.parent.mkdir(parents=True, exist_ok=True)
    spm.SentencePieceTrainer.train(
        input=lines_path,
        model_prefix=str(out_path.with_suffix("")),
        model_type="bpe",
        vocab_size=vocab_size,
        user_defined_symbols=SPECIAL_TOKENS,  # reserved: never split, always in the vocabulary
        byte_fallback=True,                   # unseen characters become raw bytes, not <unk>
        character_coverage=0.9995,            # very rare characters are left to byte fallback
        normalization_rule_name="identity",   # keep the text exactly as it is (no Unicode folding)
        remove_extra_whitespaces=False,       # keep spacing exactly as it is
        add_dummy_prefix=False,               # don't invent a space at the start of each line
        split_digits=True,                    # numbers are spelled digit by digit
        max_sentence_length=1 << 16,          # some paragraphs are long
        num_threads=4,
        minloglevel=2,                        # quiet
    )
    Path(lines_path).unlink()
    return BPETokenizer.load(out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data_dir", type=Path, default=Path("data"))
    parser.add_argument("--vocab_size", type=int, default=8000)
    args = parser.parse_args()

    out_path = args.data_dir / "tokenizer" / f"bpe{args.vocab_size}.model"
    tok = train_bpe(args.data_dir / "train.txt", args.vocab_size, out_path)
    print(f"wrote {out_path} ({tok.vocab_size} tokens)")

    # Check: every val text must survive encode -> decode unchanged, and report
    # how many characters an average token covers.
    for path in sorted(args.data_dir.glob("val*.txt")):
        text = path.read_text(encoding="utf-8")
        ids = tok.encode(text)
        assert tok.decode(ids) == text, f"{path.name} does not round-trip"
        print(f"  {path.name:<18} {len(text):>9,} chars -> {len(ids):>8,} tokens  ({len(text) / len(ids):.2f} chars/token)")
    sample = "<dream>\nI was walking by the wine-dark sea with Telemachus.\n</dream>"
    print("  example:", [tok.sp.id_to_piece(i) for i in tok.encode(sample)])


if __name__ == "__main__":
    main()
