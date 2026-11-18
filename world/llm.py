"""The instruct models the world engine talks to, with schema-guided JSON.

    llm = Instruct("Qwen/Qwen2.5-3B-Instruct")
    llm.chat(system, user)                      # plain text
    llm.json(system, user, schema)              # a dict that is guaranteed to match the JSON schema

Schema-guided decoding: at every step of generation, only tokens that keep the output a valid prefix
of something matching the schema are allowed (lm-format-enforcer's character-level JSON-schema
parser). So the model cannot write broken JSON, leave out a required field, or pick an actor id that
isn't in the list (ids are given as an enum). If it runs out of room mid-object anyway, the reply is
parsed forgivingly as a fallback (world.tick.parse_json).

(lm-format-enforcer's own transformers adapter doesn't import under transformers 5, so the small
adapter it needs is written here, after its code.)
"""

from __future__ import annotations

import functools
import json
import time

import torch
from lmformatenforcer import JsonSchemaParser, TokenEnforcer, TokenEnforcerTokenizerData
from transformers import AutoModelForCausalLM, AutoTokenizer


def _tokenizer_data(tok) -> TokenEnforcerTokenizerData:
    """For every token: its id, its text (with a leading space if it starts a word), whether it starts a word."""
    token_0 = tok.encode("0")[-1]
    special = set(tok.all_special_ids)
    regular = []
    for i in range(len(tok)):
        if i in special:
            continue
        after_0 = tok.decode([token_0, i])[1:]
        alone = tok.decode([i])
        regular.append((i, after_0, len(after_0) > len(alone)))
    decode = lambda ids: tok.decode(ids).rstrip("�")
    return TokenEnforcerTokenizerData(regular, decode, tok.eos_token_id, False, len(tok))


class Instruct:
    def __init__(self, model_id: str, threads: int | None = None, dtype: str = "float32"):
        if threads:
            torch.set_num_threads(threads)
        t = time.time()
        self.model_id = model_id
        self.tok = AutoTokenizer.from_pretrained(model_id)
        # float32 by default; bfloat16 halves the memory (the 3B storyteller needs it on a 15 GB machine)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=getattr(torch, dtype))
        self.model.eval()
        self._tdata = None
        self.load_seconds = time.time() - t

    def _generate(self, system: str, user: str, max_new_tokens: int, allowed=None, repetition_penalty: float = 1.0) -> str:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(prompt, return_tensors="pt")
        kw = {"prefix_allowed_tokens_fn": allowed} if allowed else {}
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, repetition_penalty=repetition_penalty, **kw)
        return self.tok.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    def chat(self, system: str, user: str, max_new_tokens: int = 200, repetition_penalty: float = 1.0) -> str:
        """Plain text. A repetition penalty above 1 (e.g. 1.12) keeps long prose from going round in circles."""
        return self._generate(system, user, max_new_tokens, repetition_penalty=repetition_penalty)

    def json(self, system: str, user: str, schema: dict, max_new_tokens: int = 300):
        """A reply that matches the schema (dict), or None if even the forgiving parse fails."""
        from world.tick import parse_json
        if self._tdata is None:
            self._tdata = _tokenizer_data(self.tok)
        enforcer = TokenEnforcer(self._tdata, JsonSchemaParser(schema))
        n_prompt = None

        def allowed(batch_id, sent):
            nonlocal n_prompt
            ids = sent.tolist()
            if n_prompt is None:
                n_prompt = len(ids)
            return enforcer.get_allowed_tokens(ids).allowed_tokens

        raw = self._generate(system, user, max_new_tokens, allowed)
        self.last_raw = raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return parse_json(raw)

    def free(self):
        del self.model
        import gc
        gc.collect()
