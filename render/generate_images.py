"""Generate the Arcadia images listed in render/image_prompts.json with SDXL.

    python -m render.generate_images --out /kaggle/working/images               # all 14, on a GPU
    python -m render.generate_images --out out/test --only corva_01 --steps 4    # one image, quick

For every image it writes <id>.png and <id>.json side by side. The JSON holds
everything needed to make the same image again: prompts, seed, model, VAE,
steps, guidance, size, and the source dream (for dream images), plus how
long it took.

Model: SDXL base 1.0 in float16, with the "fp16-fix" VAE (the stock SDXL VAE
produces black or noisy images in float16). Fits a 16 GB T4.

Refinement (image_prompts_v3.json onwards): an image entry may also have
  "init_image": a picture to start from instead of pure noise (img2img), and
  "strength": how much of it to repaint (0 = keep it, 1 = ignore it), and
  "ip_adapter_image" + "ip_adapter_scale": a reference picture used as a
      *visual* prompt (IP-Adapter), to borrow its light, palette and forms.
If the IP-Adapter can't be loaded, those images are made with img2img alone
and their metadata says so ("ip_adapter_used": false).
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


IP_ADAPTER = {"repo": "h94/IP-Adapter", "subfolder": "sdxl_models",
              "weight_name": "ip-adapter_sdxl_vit-h.safetensors", "image_encoder": "models/image_encoder"}


def load_img2img(pipe, device: str, want_ip_adapter: bool):
    """An img2img pipeline sharing the text-to-image pipeline's weights, plus the IP-Adapter if wanted."""
    from diffusers import StableDiffusionXLImg2ImgPipeline

    image_encoder = None
    if want_ip_adapter:
        try:
            from transformers import CLIPVisionModelWithProjection

            image_encoder = CLIPVisionModelWithProjection.from_pretrained(
                IP_ADAPTER["repo"], subfolder=IP_ADAPTER["image_encoder"], torch_dtype=pipe.dtype).to(device)
        except Exception as err:  # noqa: BLE001
            print(f"IP-Adapter image encoder unavailable ({err}); using img2img only", flush=True)
    img2img = StableDiffusionXLImg2ImgPipeline(**{**pipe.components, "image_encoder": image_encoder}).to(device)
    img2img.set_progress_bar_config(disable=True)
    if image_encoder is not None:
        try:
            img2img.load_ip_adapter(IP_ADAPTER["repo"], subfolder=IP_ADAPTER["subfolder"],
                                    weight_name=IP_ADAPTER["weight_name"])
            return img2img, True
        except Exception as err:  # noqa: BLE001
            print(f"IP-Adapter failed to load ({err}); using img2img only", flush=True)
    return img2img, False


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
    root = args.spec.resolve().parents[1]  # paths in the spec are relative to the repo root
    img2img, ip_ok = None, False
    if any(i.get("init_image") for i in images):
        img2img, ip_ok = load_img2img(pipe, args.device, any(i.get("ip_adapter_image") for i in images))
        print(f"img2img ready; IP-Adapter {'loaded' if ip_ok else 'not used'}", flush=True)

    from PIL import Image

    for img in images:
        width, height = (int(v) for v in args.size.split("x")) if args.size else (img["width"], img["height"])
        t = time.time()
        # A fixed seed on its own generator makes each image reproducible
        # regardless of which other images are generated in the same run.
        generator = torch.Generator(device=args.device).manual_seed(img["seed"])
        common = dict(
            prompt=img["prompt"],
            prompt_2=img.get("prompt_2"),
            negative_prompt=img.get("negative_prompt"),
            negative_prompt_2=img.get("negative_prompt"),
            num_inference_steps=steps,
            guidance_scale=spec["guidance_scale"],
            generator=generator,
        )
        ip_used = False
        if img.get("init_image"):
            init = Image.open(root / img["init_image"]).convert("RGB").resize((width, height))
            extra = {}
            if ip_ok and img.get("ip_adapter_image") and img.get("ip_adapter_scale", 0) > 0:
                img2img.set_ip_adapter_scale(img["ip_adapter_scale"])
                extra["ip_adapter_image"] = Image.open(root / img["ip_adapter_image"]).convert("RGB")
                ip_used = True
            elif ip_ok:
                img2img.set_ip_adapter_scale(0.0)
                extra["ip_adapter_image"] = Image.open(root / (img.get("ip_adapter_image") or img["init_image"])).convert("RGB")
            result = img2img(image=init, strength=img["strength"], **common, **extra).images[0]
        else:
            result = pipe(width=width, height=height, **common).images[0]
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
            **({"ip_adapter_used": ip_used, "ip_adapter": IP_ADAPTER if ip_used else None} if img.get("init_image") else {}),
        }
        (args.out / f"{img['id']}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{img['id']}: {meta['seconds']}s", flush=True)
    print(f"done: {len(images)} images in {time.time() - t0:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()
