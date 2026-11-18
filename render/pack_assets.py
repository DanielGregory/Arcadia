"""Turn the AI test-round assets (assets/ai/, from Kaggle) into web assets for /world (site/world/assets/).

    python -m render.pack_assets                     # everything
    python -m render.pack_assets --faces 5000        # target triangle count per object

Runs on the CPU. Steps:
  backdrops/sdxl   the three SDXL panoramas. "far" and "mid" get their skies cut out to transparency:
                   Depth Anything V2 marks the farthest pixels (the sky) and a soft threshold turns
                   them clear. "sky" stays opaque.
  backdrops/corva  the canonical Corva cut into layers by the same depth model (render/make_layers.py
                   with cuts 0.03 0.075 0.13): sky = the backdrop above the horizon, far = the
                   distant mountains, mid = the middle distance; each cropped to its opaque rows.
  textures         resized to 512 px JPEGs (phones), "hillside" turned into a detail map: its
                   colour divided out so it only adds texture to the land's own colours.
  objects          every mesh (TripoSR, and TRELLIS if it ran): stood upright, centred, scaled to
                   1 unit tall, shrunk to a phone-friendly triangle count (quadric decimation, which
                   removes the least noticeable triangles first) and saved as .glb with its colours.
Writes site/world/assets/manifest.json listing what exists.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets/ai"
OUT = ROOT / "site/world/assets"


def depth(img: Image.Image) -> np.ndarray:
    from render.make_layers import estimate_depth
    return estimate_depth(img)                       # 0 = farthest .. 1 = nearest


def cut_sky(img: Image.Image) -> Image.Image:
    """Make the sky (the farthest pixels) transparent, with a soft edge."""
    rgb = img.convert("RGB")
    d = depth(rgb)
    lo, hi = np.percentile(d, 25), np.percentile(d, 45)   # the sky is the far quarter or so
    alpha = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
    # anything in the lowest third is ground, never sky
    alpha[int(alpha.shape[0] * 0.66):] = 1.0
    rgba = np.dstack([np.array(rgb), (alpha * 255).astype(np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def crop_rows(img: Image.Image, keep: tuple[int, int] | None = None) -> Image.Image:
    a = np.array(img)
    rows = np.where(a[..., 3].max(axis=1) > 20)[0] if a.shape[2] == 4 else np.arange(a.shape[0])
    top, bottom = (rows.min(), rows.max() + 1) if keep is None else keep
    return img.crop((0, top, img.width, bottom))


def save_web(img: Image.Image, path: Path, width: int = 1536) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    img.save(path, optimize=True)


def backdrops(manifest: dict) -> None:
    src = SRC / "backdrops"
    if src.exists():
        for name in ("sky", "far", "mid"):
            img = Image.open(src / f"{name}.png")
            save_web(img.convert("RGB") if name == "sky" else cut_sky(img), OUT / "backdrops/sdxl" / f"{name}.png")
        manifest["backdrops"]["sdxl"] = ["sky", "far", "mid"]
        print("backdrops/sdxl: sky, far, mid")
    canon = Path(manifest.get("_canon_cut", ""))
    if canon.exists():
        info = json.loads((canon / "layers.json").read_text())
        sky = Image.open(canon / "layer_0_sky_sea.png").convert("RGB")
        save_web(sky.crop((0, 0, sky.width, info["horizon_y"])), OUT / "backdrops/corva/sky.png")
        save_web(crop_rows(Image.open(canon / "layer_1_far.png")), OUT / "backdrops/corva/far.png")
        save_web(crop_rows(Image.open(canon / "layer_2_mid.png")), OUT / "backdrops/corva/mid.png")
        manifest["backdrops"]["corva"] = ["sky", "far", "mid"]
        print("backdrops/corva: sky, far, mid")


def textures(manifest: dict) -> None:
    src = SRC / "textures"
    for path in sorted(src.glob("*.png")) if src.exists() else []:
        img = Image.open(path).convert("RGB").resize((512, 512), Image.LANCZOS)
        if path.stem == "hillside":   # a detail map: the land keeps its own colours, this adds texture
            a = np.asarray(img).astype(np.float32)
            a = a / a.reshape(-1, 3).mean(axis=0) * 0.5 * 255     # mean 0.5 per channel; shaders double it
            img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        (OUT / "textures").mkdir(parents=True, exist_ok=True)
        img.save(OUT / "textures" / f"{path.stem}.jpg", quality=86)
        manifest["textures"].append(path.stem)
    print("textures:", manifest["textures"])


def objects(manifest: dict, faces: int) -> None:
    import trimesh

    for model in ("triposr", "trellis"):
        src = SRC / "meshes" / model if model == "triposr" else SRC / "trellis"
        for path in sorted(src.glob("*.obj")) if src.exists() else []:
            mesh = trimesh.load(path, process=False, force="mesh")
            n0 = len(mesh.faces)
            # TripoSR's meshes come out lying on their side (its up axis is +z); stand them up.
            if model == "triposr":
                mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
            colors = mesh.visual.vertex_colors if mesh.visual.kind == "vertex" else None
            if len(mesh.faces) > faces:
                import fast_simplification
                v, f, collapses = fast_simplification.simplify(mesh.vertices.astype(np.float32), mesh.faces,
                                                               target_reduction=1 - faces / len(mesh.faces),
                                                               return_collapses=True)
                if colors is not None:   # carry each surviving vertex's colour across
                    _, _, mapping = fast_simplification.replay_simplification(mesh.vertices.astype(np.float32),
                                                                              mesh.faces, collapses)
                    new_colors = np.zeros((len(v), 4), dtype=np.uint8)
                    new_colors[mapping] = colors
                    mesh = trimesh.Trimesh(v, f, vertex_colors=new_colors, process=False)
                else:
                    mesh = trimesh.Trimesh(v, f, process=False)
            # base on y = 0, centred, 1 unit tall
            b = mesh.bounds
            mesh.apply_translation([-(b[0][0] + b[1][0]) / 2, -b[0][1], -(b[0][2] + b[1][2]) / 2])
            mesh.apply_scale(1.0 / max(1e-6, mesh.bounds[1][1] - mesh.bounds[0][1]))
            dest = OUT / "objects" / model / f"{path.stem}.glb"
            dest.parent.mkdir(parents=True, exist_ok=True)
            mesh.export(dest)
            manifest["objects"].setdefault(model, {})[path.stem] = {"faces": len(mesh.faces), "faces_before": n0,
                                                                     "kb": round(dest.stat().st_size / 1024)}
            print(f"objects/{model}/{path.stem}: {n0:,} -> {len(mesh.faces):,} faces, {dest.stat().st_size // 1024} KB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--faces", type=int, default=5000)
    parser.add_argument("--canon_cut", default="", help="output folder of render.make_layers with cuts 0.03 0.075 0.13")
    args = parser.parse_args()
    if OUT.exists():
        shutil.rmtree(OUT)
    manifest = {"backdrops": {}, "textures": [], "objects": {}, "_canon_cut": args.canon_cut}
    backdrops(manifest)
    textures(manifest)
    objects(manifest, args.faces)
    manifest.pop("_canon_cut")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print("wrote", OUT / "manifest.json")


if __name__ == "__main__":
    main()
