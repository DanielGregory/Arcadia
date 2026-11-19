"""Simple OpenPose skeletons for the character cards: the body each person holds while doing their thing.

    python -m world.poses     # draws world/poses/<name>.png (832x1024, the cards' size), for ControlNet OpenPose

A pose is the 18 OpenPose body keypoints (COCO order) on a 0..1 canvas, drawn the way OpenPose draws them
(coloured limbs on black), so an OpenPose ControlNet reads them as a person. Only the body is fixed; who it is,
their clothes and the scene come from the prompt. Missing points (None) are not drawn (e.g. legs out of frame).

Keypoints: 0 nose, 1 neck, 2 r-shoulder, 3 r-elbow, 4 r-wrist, 5 l-shoulder, 6 l-elbow, 7 l-wrist, 8 r-hip,
9 r-knee, 10 r-ankle, 11 l-hip, 12 l-knee, 13 l-ankle, 14 r-eye, 15 l-eye, 16 r-ear, 17 l-ear
("right" is the figure's own right, which is on the left of the picture when they face us).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "world/poses"
SIZE = (832, 1024)

LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
         (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
          (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
          (255, 0, 255), (255, 0, 170), (255, 0, 85)]


def head(nx, ny, turn=0.0):
    """Nose, eyes and ears around a nose position; turn > 0 faces the picture's right."""
    return {0: (nx, ny), 14: (nx - 0.025 + turn * 0.01, ny - 0.02), 15: (nx + 0.025 + turn * 0.01, ny - 0.02),
            16: (nx - 0.06 + turn * 0.03, ny - 0.01) if turn < 0.5 else None,
            17: (nx + 0.06 + turn * 0.03, ny - 0.01) if turn > -0.5 else None}


POSES = {
    # seated high on a bench, upright, both hands resting on a staff before him, knees forward
    "seated_high": {**head(0.5, 0.2), 1: (0.5, 0.3), 2: (0.4, 0.32), 3: (0.38, 0.45), 4: (0.47, 0.54), 5: (0.6, 0.32),
                    6: (0.62, 0.45), 7: (0.53, 0.54), 8: (0.44, 0.6), 9: (0.4, 0.74), 10: (0.41, 0.92), 11: (0.56, 0.6),
                    12: (0.6, 0.74), 13: (0.59, 0.92)},
    # drawing a bow to the picture's left: bow arm straight out, string hand drawn back to the cheek
    "bow": {**head(0.5, 0.22, turn=-0.6), 1: (0.52, 0.32), 2: (0.42, 0.33), 3: (0.29, 0.32), 4: (0.16, 0.31),
            5: (0.62, 0.34), 6: (0.6, 0.3), 7: (0.5, 0.25), 8: (0.48, 0.66), 9: None, 10: None, 11: (0.58, 0.66),
            12: None, 13: None},
    # at the tiller: half turned, both hands together on the steering oar at waist height to the picture's right
    "helm": {**head(0.45, 0.2, turn=0.6), 1: (0.47, 0.3), 2: (0.38, 0.32), 3: (0.45, 0.45), 4: (0.6, 0.5), 5: (0.56, 0.32),
             6: (0.64, 0.42), 7: (0.66, 0.5), 8: (0.42, 0.64), 9: None, 10: None, 11: (0.53, 0.64), 12: None, 13: None},
    # pointing up and out at a scaffold with one arm, the other hand low holding a plumb line
    "point_up": {**head(0.48, 0.24, turn=0.4), 1: (0.48, 0.34), 2: (0.38, 0.36), 3: (0.37, 0.5), 4: (0.4, 0.62),
                 5: (0.58, 0.35), 6: (0.68, 0.24), 7: (0.78, 0.12), 8: (0.43, 0.68), 9: None, 10: None, 11: (0.54, 0.68),
                 12: None, 13: None},
    # kneeling, leaning toward a flame low in front, both hands reaching forward to it
    "kneel": {**head(0.55, 0.32, turn=0.5), 1: (0.5, 0.4), 2: (0.42, 0.42), 3: (0.48, 0.55), 4: (0.6, 0.62),
              5: (0.56, 0.42), 6: (0.64, 0.52), 7: (0.7, 0.6), 8: (0.44, 0.7), 9: (0.5, 0.86), 10: (0.32, 0.9),
              11: (0.52, 0.7), 12: (0.6, 0.86), 13: (0.4, 0.92)},
}


def draw(points: dict) -> Image.Image:
    W, H = SIZE
    im = Image.new("RGB", SIZE, (0, 0, 0))
    g = ImageDraw.Draw(im, "RGBA")
    P = {k: (v[0] * W, v[1] * H) for k, v in points.items() if v}
    for i, (a, b) in enumerate(LIMBS):
        if a in P and b in P:
            (x1, y1), (x2, y2) = P[a], P[b]
            length, angle = math.hypot(x2 - x1, y2 - y1), math.atan2(y2 - y1, x2 - x1)
            # an ellipse along the limb, as OpenPose draws them (a polygon here)
            pts = [((x1 + x2) / 2 + math.cos(angle) * length / 2 * math.cos(t) - math.sin(angle) * 6 * math.sin(t),
                    (y1 + y2) / 2 + math.sin(angle) * length / 2 * math.cos(t) + math.cos(angle) * 6 * math.sin(t))
                   for t in [j * math.pi / 18 for j in range(36)]]
            g.polygon(pts, fill=COLORS[i % 18] + (153,))
    for k, (x, y) in P.items():
        g.ellipse((x - 6, y - 6, x + 6, y + 6), fill=COLORS[k])
    return im


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, pts in POSES.items():
        draw(pts).save(OUT / f"{name}.png")
    print(f"{len(POSES)} poses in {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
