"""Paint portrait candidates on Kaggle's GPU (the GPU half of world/portraits.py; sandbox only).

    python -m world.portrait_job --batch portraits.json --out out/portraits

The batch has one item per candidate: {id, k, name, sex, prompt, style, negative, seed, reference}. SDXL base with
the fp16-safe VAE, 832x1024, 30 steps, guidance 6.5: the same settings and style text for everyone, each
candidate its own seed, so the gallery looks like one painter's work.

A person who already has a chosen portrait has a REFERENCE image (its URL in "reference"): their candidates are
painted with it as an image prompt (IP-Adapter, the same one the morning job can use for style), at a moderate
scale, so a later portrait keeps their face while the text still sets their age and clothes.
Output: p<id>_<k>.png for each candidate, and portraits.json.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

import torch

REFERENCE_SCALE = 0.55   # how strongly a person's reference image holds their face


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/portraits"))
    ap.add_argument("--steps", type=int, default=30)
    args = ap.parse_args()
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline
    from PIL import Image
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    with_ref = any(b.get("reference") for b in batch)
    extra = {}
    if with_ref:
        from transformers import CLIPVisionModelWithProjection
        from render.generate_images import IP_ADAPTER
        extra["image_encoder"] = CLIPVisionModelWithProjection.from_pretrained(
            IP_ADAPTER["repo"], subfolder=IP_ADAPTER["image_encoder"], torch_dtype=torch.float16)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=torch.float16, use_safetensors=True, variant="fp16",
        vae=AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16), **extra).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    if with_ref:
        pipe.load_ip_adapter(IP_ADAPTER["repo"], subfolder=IP_ADAPTER["subfolder"], weight_name=IP_ADAPTER["weight_name"])
    refs = {}
    done = []
    for b in batch:
        t = time.time()
        call = {}
        if with_ref:
            if b.get("reference"):
                if b["reference"] not in refs:
                    import requests
                    refs[b["reference"]] = Image.open(io.BytesIO(requests.get(b["reference"], timeout=60).content)).convert("RGB")
                pipe.set_ip_adapter_scale(REFERENCE_SCALE)
                call["ip_adapter_image"] = refs[b["reference"]]
            else:   # no reference for this person: the adapter is loaded but must not steer them
                pipe.set_ip_adapter_scale(0.0)
                call["ip_adapter_image"] = Image.new("RGB", (224, 224), (40, 32, 24))
        p1 = b["prompt"] if b.get("prompt_2") else f"{b['prompt']}, {b['style']}"
        p2 = b.get("prompt_2") or f"{b['style']}: {b['prompt']}"
        img = pipe(prompt=p1, prompt_2=p2,
                   negative_prompt=b["negative"], negative_prompt_2=b["negative"], width=832, height=1024,
                   num_inference_steps=args.steps, guidance_scale=6.5,
                   generator=torch.Generator(device="cuda").manual_seed(b["seed"]), **call).images[0]
        k = b.get("k", 0)
        img.save(args.out / f"p{b['id']}_{k}.png")
        done.append({"id": b["id"], "k": k, "name": b["name"], "sex": b["sex"], "prompt": b["prompt"], "seed": b["seed"],
                     "reference": b.get("reference")})
        print(f"  p{b['id']} {b['name']} #{k} in {time.time() - t:.0f}s", flush=True)
    (args.out / "portraits.json").write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
