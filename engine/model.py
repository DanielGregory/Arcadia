"""The Arcadia dream model: a small transformer that generates dreams for the world.

This is a decoder-only transformer in the GPT style (the architecture from
"Attention Is All You Need", minus the encoder, as built in Karpathy's
"Let's build GPT" walkthrough). It reads a sequence of tokens and, at every
position, predicts which token comes next. To generate text it runs that
prediction over and over, appending each new token to its own input.

The whole model, top to bottom:

    token ids  (B, T)                      B = batch size, T = sequence length
       |
       |  token embedding  + position embedding
       v
    vectors    (B, T, C)                   C = n_embd, the width of the model
       |
       |  Block x n_layer:
       |     x = x + attention(layer_norm(x))    tokens look at earlier tokens
       |     x = x + mlp(layer_norm(x))          each token "thinks" on its own
       v
    final layer norm
       |
       |  linear "lm_head": C -> vocab_size
       v
    logits     (B, T, vocab_size)          one score per possible next token

Shapes are written in comments as (B, T, C) throughout; following them is the
easiest way to understand what each line does.

Run this file directly for a quick self-test:
    python -m engine.model
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
import torch.nn as nn
from torch.nn import functional as F


# =============================================================================
# 1. Configuration
# =============================================================================
@dataclass
class GPTConfig:
    """All the numbers that decide the size and shape of the model.

    The defaults are a small model (~30M parameters, most of them in the token
    embedding) that suits a corpus of a few million tokens.
    """

    # How many tokens the model can see at once (its "context window").
    # Text longer than this is cut into windows of this length for training.
    block_size: int = 256

    # How many different tokens exist. GPT-2's tiktoken encoding has 50,257;
    # we round up to 50,304 (a multiple of 64), which makes the matrix maths
    # a little faster on GPUs. The extra 47 ids are simply never used.
    vocab_size: int = 50304

    # Number of transformer blocks stacked on top of each other.
    n_layer: int = 6

    # Number of attention heads in each block. Each head looks for a different
    # kind of relationship between tokens; n_embd must divide evenly by n_head.
    n_head: int = 6

    # The width of every token's vector ("embedding dimension"). Bigger = more
    # capacity, more memory, slower.
    n_embd: int = 384

    # Dropout randomly zeroes this fraction of values during training, which
    # stops the model from memorising the corpus (overfitting). Set to 0.0
    # for generation (model.eval() turns it off automatically anyway).
    dropout: float = 0.2

    # Whether the Linear and LayerNorm layers get a learnable bias term.
    # Leaving it out is slightly faster and works just as well.
    bias: bool = False


# =============================================================================
# 2. Causal self-attention: how tokens share information
# =============================================================================
class CausalSelfAttention(nn.Module):
    """Every token asks a question, every earlier token offers an answer.

    For each token we compute three vectors:
      - query (q): "what am I looking for?"
      - key   (k): "what do I contain?"
      - value (v): "what will I pass on if you pick me?"

    The score between token i and token j is how well i's query matches j's
    key (their dot product). After a softmax those scores become weights, and
    token i's output is the weighted sum of the values of the tokens it picked.

    "Causal" means a token may only look at itself and tokens *before* it:
    when predicting the next word, peeking at the answer would be cheating.

    "Multi-head" means we do this n_head times in parallel, each head with its
    own smaller q/k/v vectors (head_size = n_embd / n_head), then glue the
    heads' outputs back together.
    """

    def __init__(self, config: GPTConfig):
        super().__init__()
        assert config.n_embd % config.n_head == 0, "n_embd must be divisible by n_head"
        self.n_head = config.n_head
        self.n_embd = config.n_embd
        self.head_size = config.n_embd // config.n_head

        # One Linear layer produces q, k and v for all heads at once:
        # C inputs -> 3*C outputs, which we split into three C-wide pieces.
        # (Equivalent to three separate Linear layers, just faster.)
        self.qkv = nn.Linear(config.n_embd, 3 * config.n_embd, bias=config.bias)

        # After the heads are glued back together, one more Linear layer mixes
        # their results ("output projection").
        self.proj = nn.Linear(config.n_embd, config.n_embd, bias=config.bias)

        self.attn_dropout = nn.Dropout(config.dropout)   # on the attention weights
        self.resid_dropout = nn.Dropout(config.dropout)  # on the output

        # The causal mask: a lower-triangular matrix of ones.
        #   1 0 0 0
        #   1 1 0 0      row i = the tokens that token i is allowed to see
        #   1 1 1 0
        #   1 1 1 1
        # register_buffer stores it with the model (it moves to the GPU with
        # .to(device)) without making it a trainable parameter.
        mask = torch.tril(torch.ones(config.block_size, config.block_size))
        self.register_buffer("mask", mask.view(1, 1, config.block_size, config.block_size))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape  # batch, time (sequence length), channels (n_embd)

        # --- Step 1: compute queries, keys and values -------------------------
        q, k, v = self.qkv(x).split(self.n_embd, dim=2)  # each (B, T, C)

        # --- Step 2: split the channels into heads ----------------------------
        # (B, T, C) -> (B, T, n_head, head_size) -> (B, n_head, T, head_size)
        # Moving the head dimension forward lets every head be processed in
        # parallel, as if it were part of the batch.
        q = q.view(B, T, self.n_head, self.head_size).transpose(1, 2)
        k = k.view(B, T, self.n_head, self.head_size).transpose(1, 2)
        v = v.view(B, T, self.n_head, self.head_size).transpose(1, 2)

        # --- Step 3: attention scores -----------------------------------------
        # q @ k^T gives, for every pair of positions (i, j), how much token i
        # cares about token j:  (B, nh, T, hs) @ (B, nh, hs, T) -> (B, nh, T, T)
        # Dividing by sqrt(head_size) keeps the scores from growing with the
        # head size; without it the softmax becomes too "peaky" and training
        # stalls.
        att = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_size)

        # --- Step 4: hide the future ------------------------------------------
        # Wherever the mask is 0 (token j comes after token i), set the score
        # to -infinity. softmax turns -inf into exactly 0 weight.
        att = att.masked_fill(self.mask[:, :, :T, :T] == 0, float("-inf"))

        # --- Step 5: scores -> weights ----------------------------------------
        # softmax makes each row positive and sum to 1, so each token's
        # weights over the earlier tokens form a probability distribution.
        att = F.softmax(att, dim=-1)
        att = self.attn_dropout(att)

        # --- Step 6: weighted sum of values -----------------------------------
        # (B, nh, T, T) @ (B, nh, T, hs) -> (B, nh, T, hs)
        y = att @ v

        # --- Step 7: glue the heads back together -----------------------------
        # (B, nh, T, hs) -> (B, T, nh, hs) -> (B, T, C)
        # .contiguous() is needed because transpose only changes how memory is
        # read, and .view() needs the memory laid out in order.
        y = y.transpose(1, 2).contiguous().view(B, T, C)

        # --- Step 8: mix the heads' results ------------------------------------
        return self.resid_dropout(self.proj(y))


# =============================================================================
# 3. The MLP (feed-forward network): each token thinks on its own
# =============================================================================
class MLP(nn.Module):
    """A small two-layer network applied to every token separately.

    Attention moves information *between* tokens; the MLP then processes what
    each token has gathered. It widens the vector 4x, applies a non-linearity,
    and narrows it back, which gives it room to compute.
    """

    def __init__(self, config: GPTConfig):
        super().__init__()
        self.up = nn.Linear(config.n_embd, 4 * config.n_embd, bias=config.bias)    # C -> 4C
        self.gelu = nn.GELU()  # a smooth version of ReLU: lets the network bend, not just scale
        self.down = nn.Linear(4 * config.n_embd, config.n_embd, bias=config.bias)  # 4C -> C
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # (B, T, C) -> (B, T, 4C) -> (B, T, 4C) -> (B, T, C)
        return self.dropout(self.down(self.gelu(self.up(x))))


# =============================================================================
# 4. A transformer block: attention + MLP, with residual connections
# =============================================================================
class Block(nn.Module):
    """One layer of the transformer: communicate (attention), then compute (MLP).

    Two tricks make deep stacks of these blocks trainable:

    - Residual connections (x = x + f(x)): each sub-layer only adds a
      correction to x instead of replacing it. Gradients can then flow
      straight back through the "+" to the earliest layers.

    - Layer normalisation: before each sub-layer, rescale every token's vector
      to mean 0 and variance 1 (then apply a learned scale). This keeps the
      numbers in a healthy range however deep the stack. Normalising *before*
      the sub-layer ("pre-norm") is what GPT-2 and later models do.
    """

    def __init__(self, config: GPTConfig):
        super().__init__()
        self.ln1 = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.attn = CausalSelfAttention(config)
        self.ln2 = nn.LayerNorm(config.n_embd, bias=config.bias)
        self.mlp = MLP(config)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.ln1(x))  # tokens gather information from earlier tokens
        x = x + self.mlp(self.ln2(x))   # each token processes what it gathered
        return x                        # shape unchanged: (B, T, C)


# =============================================================================
# 5. The full model
# =============================================================================
class GPT(nn.Module):
    """Embeddings -> n_layer Blocks -> final norm -> scores over the vocabulary."""

    def __init__(self, config: GPTConfig):
        super().__init__()
        self.config = config

        # Token embedding: a lookup table with one learned C-wide vector per
        # token id. Row 464 is "the vector for token 464".
        self.tok_emb = nn.Embedding(config.vocab_size, config.n_embd)

        # Position embedding: one learned vector per position 0..block_size-1.
        # Attention by itself has no idea of order (it treats its input as a
        # set), so we add "you are at position t" into each token's vector.
        self.pos_emb = nn.Embedding(config.block_size, config.n_embd)

        self.drop = nn.Dropout(config.dropout)

        # The stack of transformer blocks. nn.ModuleList registers each one so
        # its parameters are trained and saved.
        self.blocks = nn.ModuleList([Block(config) for _ in range(config.n_layer)])

        # A last layer norm before reading out the predictions.
        self.ln_f = nn.LayerNorm(config.n_embd, bias=config.bias)

        # The "language modelling head": turns each C-wide vector into one score
        # (logit) per vocabulary entry. The highest score = the likeliest next token.
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)

        # Weight tying: the input embedding and the output head share one matrix.
        # Both map between "token id" and "meaning vector", just in opposite
        # directions, so sharing works well and saves vocab_size * n_embd
        # parameters (~19M here, more than all the blocks put together).
        self.lm_head.weight = self.tok_emb.weight

        # Give every weight a sensible random starting value (see _init_weights).
        self.apply(self._init_weights)

        # GPT-2 trick: the layers that write back into the residual stream
        # (attention's proj and the MLP's down) start smaller, scaled by
        # 1/sqrt(2 * n_layer). Each block adds two contributions to x, so
        # without this the sum would grow with depth at the start of training.
        for name, param in self.named_parameters():
            if name.endswith("proj.weight") or name.endswith("down.weight"):
                torch.nn.init.normal_(param, mean=0.0, std=0.02 / math.sqrt(2 * config.n_layer))

    def _init_weights(self, module: nn.Module) -> None:
        """Small random weights (normal, std 0.02) and zero biases, as in GPT-2."""
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if module.bias is not None:
                torch.nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def num_params(self, non_embedding: bool = True) -> int:
        """Count the trainable numbers in the model.

        By convention the position embedding is left out of the headline count.
        The token embedding is counted once: because of weight tying it is
        also the output layer, so it does real work.
        """
        n = sum(p.numel() for p in self.parameters())
        if non_embedding:
            n -= self.pos_emb.weight.numel()
        return n

    def forward(
        self, idx: torch.Tensor, targets: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        """Run the model.

        idx:     (B, T) token ids, the input text.
        targets: (B, T) token ids, the same text shifted one to the left, i.e.
                 the correct "next token" for every position. Only passed in
                 during training.

        Returns (logits, loss). loss is None when no targets are given.
        """
        B, T = idx.shape
        assert T <= self.config.block_size, f"sequence of {T} tokens is longer than block_size {self.config.block_size}"

        # --- Step 1: look up the embeddings ----------------------------------
        positions = torch.arange(T, device=idx.device)  # [0, 1, ..., T-1]
        tok = self.tok_emb(idx)                          # (B, T, C)  what each token is
        pos = self.pos_emb(positions)                    # (T, C)     where each token is
        x = self.drop(tok + pos)                         # (B, T, C)  pos is broadcast over the batch

        # --- Step 2: run the transformer blocks ------------------------------
        for block in self.blocks:
            x = block(x)                                 # (B, T, C)
        x = self.ln_f(x)                                 # (B, T, C)

        if targets is None:
            # Generating: only the last position's prediction is needed, which
            # saves computing scores for every position.
            logits = self.lm_head(x[:, [-1], :])         # (B, 1, vocab_size)
            return logits, None

        # --- Step 3: scores for every position, and the loss -----------------
        logits = self.lm_head(x)                         # (B, T, vocab_size)

        # Cross-entropy measures how much probability the model gave to the
        # correct next token (lower is better). F.cross_entropy wants a flat
        # list of predictions, so fold batch and time together:
        #   logits (B*T, vocab_size), targets (B*T,)
        # A model guessing uniformly at random scores ln(vocab_size) ≈ 10.8.
        loss = F.cross_entropy(logits.view(B * T, -1), targets.view(B * T))
        return logits, loss

    @torch.no_grad()  # no gradients are needed when generating: saves memory and time
    def generate(
        self,
        idx: torch.Tensor,
        max_new_tokens: int,
        temperature: float = 1.0,
        top_k: int | None = None,
        stop_token: int | None = None,
    ) -> torch.Tensor:
        """Continue the token sequence idx (B, T) by up to max_new_tokens tokens.

        temperature: divides the logits before sampling. Below 1.0 the model
                     plays it safe (more predictable text); above 1.0 it takes
                     more risks (stranger text).
        top_k:       if set, only the k likeliest tokens may be picked, which
                     stops rare nonsense tokens from slipping in.
        stop_token:  if set, stop once every sequence in the batch has produced
                     this token (for example the first token of "</dream>").
        """
        for _ in range(max_new_tokens):
            # --- Step 1: crop to the context window --------------------------
            # The model can only look at the last block_size tokens.
            idx_cond = idx[:, -self.config.block_size:]

            # --- Step 2: predict the next token ------------------------------
            logits, _ = self(idx_cond)                   # (B, 1, vocab_size)
            logits = logits[:, -1, :] / temperature      # (B, vocab_size)

            # --- Step 3 (optional): keep only the top k candidates -----------
            if top_k is not None:
                kth_best = torch.topk(logits, min(top_k, logits.size(-1))).values[:, [-1]]
                logits[logits < kth_best] = float("-inf")

            # --- Step 4: turn scores into probabilities and sample one -------
            # Sampling (instead of always taking the most likely token) is what
            # makes each generated dream different.
            probs = F.softmax(logits, dim=-1)            # (B, vocab_size)
            next_token = torch.multinomial(probs, num_samples=1)  # (B, 1)

            # --- Step 5: append it and go again ------------------------------
            idx = torch.cat((idx, next_token), dim=1)    # (B, T+1)

            if stop_token is not None and (next_token == stop_token).all():
                break
        return idx


# =============================================================================
# Self-test: python -m engine.model
# =============================================================================
if __name__ == "__main__":
    torch.manual_seed(0)
    config = GPTConfig()
    model = GPT(config)
    print(f"default model: {model.num_params() / 1e6:.1f}M parameters")

    # A random batch: 2 sequences of 16 token ids. targets are the inputs
    # shifted by one, exactly as the training data will be built.
    data = torch.randint(0, 50257, (2, 17))
    x, y = data[:, :-1], data[:, 1:]
    logits, loss = model(x, y)
    print(f"logits shape: {tuple(logits.shape)}   (batch, time, vocab)")
    print(f"loss before any training: {loss.item():.2f}   (random guessing = ln(50304) = {math.log(50304):.2f})")

    model.eval()
    out = model.generate(x[:1, :4], max_new_tokens=8, top_k=50)
    print(f"generated {out.shape[1] - 4} new tokens: {out[0, 4:].tolist()}  (random, since untrained)")
