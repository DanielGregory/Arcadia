"""AI-made assets for the 3D Corva (/world), test round. Runs on Kaggle's T4 (notebooks/kaggle_assets.ipynb).

    python -m render.make_assets --out /kaggle/working/assets            # everything
    python -m render.make_assets --out ... --only sdxl                    # just the SDXL images
    python -m render.make_assets --out ... --only triposr                 # just image-to-3D on concepts/

What it makes (all in Corva's style, with the canonical painting as a style-only reference):
  backdrops/  three wide paintings to stand far behind the 3D world, back to front:
              sky (golden-hour clouds), far (distant mountain range), mid (wooded ridges).
              Their skies are cut out to transparency later, on the CPU (render/cut_backdrops.py).
  concepts/   one object per picture on a plain background, for image-to-3D: the summit temple,
              a ship, a statue, a fountain (two seeds each)
  textures/   seamless (tileable) surfaces: weathered plaster, stone, terracotta roof tiles,
              hillside. Made tileable by switching every convolution in SDXL to "circular"
              padding, so the picture wraps round at its edges.
  meshes/     TripoSR (MIT licence, fast, fits a T4): each concept -> a 3D mesh with colours,
              saved as .obj (shrunk to phone size later, on the CPU)

Every file gets a .json beside it with its prompt, seed and settings.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
STYLE = "Claude Lorrain oil painting, warm golden haze, soft light"
NEG = "text, watermark, signature, frame, border, photograph, modern buildings, cars, people, blurry, lowres"

BACKDROPS = {
    "sky": "a wide golden hour sky over the sea, soft clouds lit gold and peach, pale blue above, no land, "
           "no sea visible, wide panorama, " + STYLE,
    "far": "a distant range of tall mountains at golden hour, layered hazy violet-blue peaks, sunlit ridges, "
           "seen from far across a bay, wide panorama, pale empty sky above, " + STYLE,
    "mid": "rolling wooded hills and ridges at golden hour, olive groves and dark cypress trees, warm light, "
           "wide panorama, pale empty sky above, " + STYLE,
}
CONCEPTS = {
    "temple": "a single ancient greek temple of white marble, a row of columns and a triangular pediment on a "
              "stepped stone base, isolated object, centred, three-quarter view from slightly above, plain white "
              "background, soft even light",
    "ship": "a single ancient greek wooden galley ship with one mast and a square cream sail, oars along the side, "
            "isolated object, centred, three-quarter side view, plain white background, soft even light",
    "statue": "a single white marble statue of a robed standing figure on a square stone pedestal, isolated "
              "object, centred, full figure, three-quarter view, plain white background, soft even light",
    "fountain": "a single ancient stone fountain, a round basin with a carved central column and a small bowl on "
                "top, isolated object, centred, three-quarter view from slightly above, plain white background, "
                "soft even light",
}
TEXTURES = {
    "plaster": "weathered whitewashed lime plaster wall, cream white with faint cracks and stains, flat front "
               "view, even light, seamless texture",
    "stone": "worn limestone ashlar blocks with thin mortar joints, warm cream grey, flat front view, even light, "
             "seamless texture",
    "terracotta": "overlapping curved terracotta roof tiles, warm red orange clay, top-down view, even light, "
                  "seamless texture",
    "hillside": "dry mediterranean hillside ground seen from above, golden dry grass, low green scrub and small "
                "stones, even light, seamless texture",
}


def save(img, path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"  {path.relative_to(path.parents[1])}", flush=True)


def sdxl(out: Path) -> None:
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline
    from PIL import Image
    from transformers import CLIPVisionModelWithProjection

    from render.generate_images import IP_ADAPTER

    dt = torch.float16
    enc = CLIPVisionModelWithProjection.from_pretrained(IP_ADAPTER["repo"], subfolder=IP_ADAPTER["image_encoder"], torch_dtype=dt)
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0", torch_dtype=dt, variant="fp16", use_safetensors=True,
        vae=AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dt), image_encoder=enc).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    pipe.load_ip_adapter(IP_ADAPTER["repo"], subfolder=IP_ADAPTER["subfolder"], weight_name=IP_ADAPTER["weight_name"])
    ref = Image.open(ROOT / "assets/canonical/corva.png").convert("RGB")
    gen = lambda s: torch.Generator("cuda").manual_seed(s)

    def run(prompt, w, h, seed, style, steps=30):
        # style-only reference (InstantStyle): Corva's palette and brushwork, not its buildings
        pipe.set_ip_adapter_scale({"up": {"block_0": [0.0, style, 0.0]}})
        return pipe(prompt=prompt, prompt_2=prompt, negative_prompt=NEG, negative_prompt_2=NEG, width=w, height=h,
                    num_inference_steps=steps, guidance_scale=6.5, ip_adapter_image=ref, generator=gen(seed)).images[0]

    t = time.time()
    for name, prompt in BACKDROPS.items():   # 1536 x 640: a wide strip, 2.4 : 1
        save(run(prompt, 1536, 640, 900 + len(name), 0.7), out / "backdrops" / f"{name}.png",
             {"prompt": prompt, "seed": 900 + len(name), "style_scale": 0.7})
    for name, prompt in CONCEPTS.items():    # plain backgrounds, weak style: image-to-3D wants a clean object
        for seed in (11, 12):
            save(run(prompt, 1024, 1024, seed, 0.3), out / "concepts" / f"{name}_{seed}.png",
                 {"prompt": prompt, "seed": seed, "style_scale": 0.3})
    print(f"backdrops and concepts: {time.time() - t:.0f}s", flush=True)

    # Tileable textures: circular padding in every convolution of the UNet and the VAE
    t = time.time()
    for module in [*pipe.unet.modules(), *pipe.vae.modules()]:
        if isinstance(module, torch.nn.Conv2d):
            module.padding_mode = "circular"
    for name, prompt in TEXTURES.items():
        save(run(prompt, 1024, 1024, 31, 0.25, steps=28), out / "textures" / f"{name}.png",
             {"prompt": prompt, "seed": 31, "style_scale": 0.25, "tileable": "circular padding"})
    print(f"textures: {time.time() - t:.0f}s", flush=True)
    del pipe
    torch.cuda.empty_cache()


def _triposr_weights_for_new_transformers(out: Path) -> Path:
    """TripoSR's checkpoint names its image encoder (a ViT) the way transformers 4.x did. transformers 5
    renamed the insides of ViT (encoder.layer.N.attention.attention.query -> layers.N.attention.q_proj, ...),
    so the saved weights no longer load. Download the checkpoint once, rename its keys, and point
    TripoSR at the renamed copy."""
    import re
    import shutil

    from huggingface_hub import hf_hub_download

    local = out / "_triposr_weights"
    if (local / "model.ckpt").exists():
        return local
    local.mkdir(parents=True, exist_ok=True)
    shutil.copy(hf_hub_download("stabilityai/TripoSR", "config.yaml"), local / "config.yaml")
    sd = torch.load(hf_hub_download("stabilityai/TripoSR", "model.ckpt"), map_location="cpu")
    renames = [(r"encoder\.layer\.(\d+)\.attention\.attention\.query", r"layers.\1.attention.q_proj"),
               (r"encoder\.layer\.(\d+)\.attention\.attention\.key", r"layers.\1.attention.k_proj"),
               (r"encoder\.layer\.(\d+)\.attention\.attention\.value", r"layers.\1.attention.v_proj"),
               (r"encoder\.layer\.(\d+)\.attention\.output\.dense", r"layers.\1.attention.o_proj"),
               (r"encoder\.layer\.(\d+)\.intermediate\.dense", r"layers.\1.mlp.fc1"),
               (r"encoder\.layer\.(\d+)\.output\.dense", r"layers.\1.mlp.fc2"),
               (r"encoder\.layer\.(\d+)\.layernorm_", r"layers.\1.layernorm_")]
    import transformers
    if int(transformers.__version__.split(".")[0]) >= 5:
        new = {}
        for k, v in sd.items():
            for a, b in renames:
                k = re.sub(a, b, k)
            new[k] = v
        sd = new
    torch.save(sd, local / "model.ckpt")
    return local


def triposr(out: Path) -> None:
    """TripoSR: one picture -> a 3D mesh with vertex colours, in about a second on a T4."""
    import numpy as np
    from PIL import Image

    repo = Path("/kaggle/working/TripoSR") if Path("/kaggle").exists() else ROOT.parent / "TripoSR"
    if not repo.exists():
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/VAST-AI-Research/TripoSR", str(repo)], check=True)
    # TripoSR's marching cubes comes from torchmcubes, which has to be compiled. A stand-in with the
    # same interface, built on scikit-image, saves the compile. (torchmcubes returns vertices in
    # z, y, x order, which TripoSR then reverses; the stand-in matches that.)
    (repo / "torchmcubes.py").write_text(
        "import torch\nfrom skimage.measure import marching_cubes as _mc\n"
        "def marching_cubes(vol, thresh):\n"
        "    v, f, _, _ = _mc(vol.detach().cpu().numpy(), thresh)\n"
        "    return torch.from_numpy(v[:, ::-1].copy()).float(), torch.from_numpy(f.astype('int64'))\n")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "omegaconf", "einops", "trimesh", "rembg",
                    "onnxruntime", "scikit-image"], check=True)
    sys.path.insert(0, str(repo))
    import rembg
    from tsr.system import TSR
    from tsr.utils import remove_background, resize_foreground

    model = TSR.from_pretrained(str(_triposr_weights_for_new_transformers(out)), config_name="config.yaml",
                                weight_name="model.ckpt")
    model.renderer.set_chunk_size(8192)
    model.to("cuda")
    session = rembg.new_session()
    for path in sorted((out / "concepts").glob("*.png")):
        t = time.time()
        img = resize_foreground(remove_background(Image.open(path), session), 0.85)
        a = np.array(img).astype(np.float32) / 255.0
        a = a[:, :, :3] * a[:, :, 3:4] + (1 - a[:, :, 3:4]) * 0.5   # on mid grey, as TripoSR was trained
        img = Image.fromarray((a * 255).astype(np.uint8))
        with torch.no_grad():
            codes = model([img], device="cuda")
        mesh = model.extract_mesh(codes, True, resolution=256)[0]
        dest = out / "meshes" / "triposr" / f"{path.stem}.obj"
        dest.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(dest)
        img.save(dest.with_suffix(".input.png"))
        print(f"  triposr {path.stem}: {len(mesh.faces):,} faces, {time.time() - t:.1f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=["sdxl", "triposr"])
    args = parser.parse_args()
    t0 = time.time()
    if args.only in (None, "sdxl"):
        sdxl(args.out)
    if args.only in (None, "triposr"):
        triposr(args.out)
    print(f"all done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
