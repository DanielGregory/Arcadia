"""Generate the Arcadia images listed in render/image_prompts.json with SDXL.

    python -m render.generate_images --out /kaggle/working/images               # all 14, on a GPU
    python -m render.generate_images --out out/test --only corva_01 --steps 4    # one image, quick

For every image it writes <id>.png and <id>.json side by side. The JSON holds
everything needed to make the same image again: prompts, seed, model, VAE,
steps, guidance, size, and the source dream (for dream images), plus how
long it took.

Model: SDXL base 1.0 in float16, with the "fp16-fix" VAE (the stock SDXL VAE
produces black or noisy images in float16). Fits a 16 GB T4.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import torch

SPEC = Path(__file__).with_name("image_prompts.json")


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_pipeline(model: str, vae: str | None, device: str, safetensors: bool = True):
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline

    dtype = torch.float16 if device == "cuda" else torch.float32
    kwargs = {"torch_dtype": dtype, "use_safetensors": safetensors}
    if vae:
        kwargs["vae"] = AutoencoderKL.from_pretrained(vae, torch_dtype=dtype)
    if device == "cuda" and safetensors:
        kwargs["variant"] = "fp16"  # download the half-size fp16 weights
    pipe = StableDiffusionXLPipeline.from_pretrained(model, **kwargs).to(device)
    pipe.set_progress_bar_config(disable=True)
    return pipe


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="+", help="image ids to generate (default: all)")
    parser.add_argument("--model", help="override the spec's model (e.g. a tiny test pipeline)")
    parser.add_argument("--no_vae", action="store_true", help="use the model's own VAE")
    parser.add_argument("--steps", type=int, help="override the spec's number of steps")
    parser.add_argument("--size", help="override WIDTHxHEIGHT (for quick tests)")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    model = args.model or spec["model"]
    vae = None if (args.no_vae or args.model) else spec.get("vae")
    steps = args.steps or spec["steps"]
    images = [i for i in spec["images"] if not args.only or i["id"] in args.only]
    args.out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    pipe = load_pipeline(model, vae, args.device, safetensors=not args.model)
    print(f"loaded {model} on {args.device} in {time.time() - t0:.0f}s; generating {len(images)} images", flush=True)

    commit = git_commit()
    for img in images:
        width, height = (int(v) for v in args.size.split("x")) if args.size else (img["width"], img["height"])
        t = time.time()
        # A fixed seed on its own generator makes each image reproducible
        # regardless of which other images are generated in the same run.
        generator = torch.Generator(device=args.device).manual_seed(img["seed"])
        result = pipe(
            prompt=img["prompt"],
            prompt_2=img.get("prompt_2"),
            negative_prompt=img.get("negative_prompt"),
            negative_prompt_2=img.get("negative_prompt"),
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=spec["guidance_scale"],
            generator=generator,
        ).images[0]
        result.save(args.out / f"{img['id']}.png")
        meta = {
            **img,
            "model": model,
            "vae": vae,
            "steps": steps,
            "guidance_scale": spec["guidance_scale"],
            "width": width,
            "height": height,
            "seconds": round(time.time() - t, 1),
            "git_commit": commit,
            "reference": spec.get("reference"),
        }
        (args.out / f"{img['id']}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{img['id']}: {meta['seconds']}s", flush=True)
    print(f"done: {len(images)} images in {time.time() - t0:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
