"""Paint the principals' portraits on Kaggle's GPU (the GPU half of world/portraits.py; sandbox only).

    python -m world.portrait_job --batch portraits.json --out out/portraits

SDXL base with the fp16-safe VAE, 832x1024 (portrait), 30 steps, guidance 6.5: the same settings and the same
style text for everyone, and each person's own seed, so the gallery looks like one painter's work and a
person always looks the same. Output: p<id>.png and portraits.json.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/portraits"))
    ap.add_argument("--steps", type=int, default=30)
    args = ap.parse_args()
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=torch.float16, use_safetensors=True, variant="fp16",
        vae=AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    done = []
    for b in batch:
        t = time.time()
        img = pipe(prompt=f"{b['prompt']}, {b['style']}", prompt_2=f"{b['style']}: {b['prompt']}",
                   negative_prompt=b["negative"], negative_prompt_2=b["negative"], width=832, height=1024,
                   num_inference_steps=args.steps, guidance_scale=6.5,
                   generator=torch.Generator(device="cuda").manual_seed(b["seed"])).images[0]
        img.save(args.out / f"p{b['id']}.png")
        done.append({"id": b["id"], "name": b["name"], "sex": b["sex"], "prompt": b["prompt"], "seed": b["seed"]})
        print(f"  p{b['id']} {b['name']} in {time.time() - t:.0f}s", flush=True)
    (args.out / "portraits.json").write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
