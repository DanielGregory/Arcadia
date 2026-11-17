"""Split the canonical Corva painting into depth layers for the Godot "living painting".

    python -m render.make_layers                          # assets/canonical/corva.png -> world/godot/art/corva/
    python -m render.make_layers --cuts 0.03 0.13 0.40     # tune the depth thresholds

How it works:
1. Depth Anything V2 (small, runs on CPU in ~10 s) estimates how far away every
   pixel is. Its output is relative "nearness": 0 = farthest (sky, sea), 1 = nearest.
2. Three depth cuts split the picture into four layers, back to front:
     0 sky_sea   sky, sun and sea          (full frame, opaque)
     1 far       distant mountains, cliffs
     2 mid       the town
     3 near      foreground walls, path, columns
   The sea is separated from the sky by the horizon line and saved as its own
   mask (sea_mask.png) so a shader can make only the water shimmer.
3. Each layer except the nearest is extended a band of BAND px UNDER the nearer
   layers and that hidden strip is filled by inpainting (OpenCV Telea), so when
   Godot moves the layers against each other no holes open up. The backdrop
   (sky_sea) is filled across the whole frame.
4. Writes one PNG per layer, depth.png, sea_mask.png and layers.json (order,
   suggested parallax strength, cuts) for the Godot scene.

The inpainting is the quick classical kind: blurry if seen up close, but only
thin strips of it are ever revealed by the gentle parallax. A later pass can
replace it with SDXL inpainting on the GPU.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

LAYERS = ["sky_sea", "far", "mid", "near"]
PARALLAX = {"sky_sea": 0.02, "far": 0.08, "mid": 0.25, "near": 0.6}  # fraction of camera motion each layer follows
BAND = 48  # px each layer extends under nearer layers (max parallax shift in Godot stays below this)


def estimate_depth(img: Image.Image) -> np.ndarray:
    from transformers import pipeline

    pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device="cpu")
    d = pipe(img)["predicted_depth"].squeeze().numpy()
    d = np.array(Image.fromarray(d).resize(img.size, Image.BILINEAR))
    return (d - d.min()) / (d.max() - d.min())


def find_horizon(rgb: np.ndarray, far: np.ndarray) -> int:
    """Row where sky meets sea on the far-left side: the strongest brightness edge in the far region."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    w = rgb.shape[1]
    strip = gray[:, : w // 4]
    mask = far[:, : w // 4]
    rows = np.array([strip[y][mask[y]].mean() if mask[y].any() else np.nan for y in range(len(strip))])
    grad = np.abs(np.diff(np.nan_to_num(rows, nan=np.nanmean(rows))))
    h = len(rows)
    lo, hi = int(h * 0.3), int(h * 0.75)  # the horizon is somewhere in the middle band
    return lo + int(np.argmax(grad[lo:hi]))


def find_sea(rgb: np.ndarray, level: np.ndarray, horizon: int) -> np.ndarray:
    """Water: below the horizon, not in the town or foreground, and smooth (low local texture).

    The depth model sees the sea as slightly nearer than the sky, so depth alone
    puts it with the cliffs; texture separates calm water from rock.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mean = cv2.blur(gray, (15, 15))
    texture = np.sqrt(np.maximum(cv2.blur(gray * gray, (15, 15)) - mean * mean, 0))
    rows = np.arange(rgb.shape[0])[:, None]
    candidate = (rows > horizon) & (level <= 1) & (texture < 9)
    # keep only the region connected to the far-left edge just below the horizon
    n, labels = cv2.connectedComponents(candidate.astype(np.uint8))
    seeds = {labels[y, 2] for y in range(horizon + 2, min(horizon + 40, rgb.shape[0])) if candidate[y, 2]}
    sea = np.isin(labels, list(seeds - {0}))
    return cv2.morphologyEx(sea.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)).astype(bool)


def feather(mask: np.ndarray, px: int = 2) -> np.ndarray:
    a = mask.astype(np.float32)
    return cv2.GaussianBlur(a, (0, 0), px) if px else a


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", type=Path, default=Path("assets/canonical/corva.png"))
    parser.add_argument("--out", type=Path, default=Path("world/godot/art/corva"))
    parser.add_argument("--cuts", type=float, nargs=3, default=[0.03, 0.13, 0.40],
                        help="depth thresholds between sky_sea|far|mid|near (0 = far, 1 = near)")
    args = parser.parse_args()

    img = Image.open(args.image).convert("RGB")
    rgb = np.array(img)
    depth = estimate_depth(img)
    c1, c2, c3 = args.cuts
    level = np.digitize(depth, [c1, c2, c3])  # 0..3, one layer index per pixel
    horizon = find_horizon(rgb, level == 0)
    sea = find_sea(rgb, level, horizon)
    level[sea] = 0  # the water belongs with the sky, behind everything

    args.out.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    info = {"source": str(args.image), "size": list(img.size), "cuts": args.cuts, "horizon_y": horizon, "layers": []}
    for i, name in enumerate(LAYERS):
        own = level == i
        nearer = level > i
        if i == len(LAYERS) - 1:
            colour, alpha = rgb, feather(own)
        else:
            # Fill what nearer layers hide, so the layer can slide out from under them.
            # Only a band of BAND px under the nearer layers is ever revealed by the gentle
            # parallax, so only that band is filled (filling everything just smears).
            band = nearer & cv2.dilate(own.astype(np.uint8), np.ones((2 * BAND + 1, 2 * BAND + 1), np.uint8)).astype(bool)
            if i == 0:
                band = nearer  # the backdrop must cover the whole frame
            hole = cv2.dilate(band.astype(np.uint8), np.ones((5, 5), np.uint8))
            filled = cv2.cvtColor(cv2.inpaint(bgr, hole, 7, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
            colour = np.where(own[..., None], rgb, filled)
            alpha = np.ones(own.shape, np.float32) if i == 0 else feather(own | band)
        rgba = np.dstack([colour, (np.clip(alpha, 0, 1) * 255).astype(np.uint8)])
        Image.fromarray(rgba.astype(np.uint8), "RGBA").save(args.out / f"layer_{i}_{name}.png", optimize=True)
        info["layers"].append({"index": i, "name": name, "file": f"layer_{i}_{name}.png",
                               "parallax": PARALLAX[name], "coverage": round(float(own.mean()), 3)})
        print(f"layer {i} {name:8s} covers {own.mean():5.1%} of the picture")

    Image.fromarray((depth * 255).astype(np.uint8)).save(args.out / "depth.png", optimize=True)
    Image.fromarray((feather(sea, 1) * 255).astype(np.uint8)).save(args.out / "sea_mask.png", optimize=True)
    # Where the sun is (brightest point in the upper part of the picture), for the glow in Godot.
    blur = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), 6)
    top = blur[: int(rgb.shape[0] * 0.6)]
    sy, sx = np.unravel_index(np.argmax(top), top.shape)
    info["sun"] = [int(sx), int(sy)]
    (args.out / "layers.json").write_text(json.dumps(info, indent=1) + "\n")
    print(f"horizon at y={horizon}; sea covers {sea.mean():.1%}; wrote {args.out}")


if __name__ == "__main__":
    main()
