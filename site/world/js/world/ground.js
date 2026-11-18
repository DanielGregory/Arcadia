// The colour of the ground at a point, as plain numbers (no three.js), so a worker can use it.
//
// Sand by the water; dry golden grass and olive-dark scrub on the lower slopes; bare rock where
// it's steep; pale grey-violet stone high on the mountain. All broken up with noise so it reads
// as painted, not flat. Colours are linear RGB (0..1), the space the renderer lights in.

import { fbm } from "./terrain.js";

// sRGB hex -> linear RGB
function lin(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => {
    v /= 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
}
const SAND = lin("#c9a874"), GRASS = lin("#8a7d47"), SCRUB = lin("#4f5531"), ROCK = lin("#8d7b69"),
      HIGH = lin("#9a8e84"), FOREST = lin("#3c4a2c"), MAQUIS = lin("#5a5f3a");

const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);
const sstep = (v, a, b) => { const t = clamp01((v - a) / (b - a)); return t * t * (3 - 2 * t); };
function mix(out, c, f) { out[0] += (c[0] - out[0]) * f; out[1] += (c[1] - out[1]) * f; out[2] += (c[2] - out[2]) * f; }

// y: height, slope: steepness (0 flat .. 1+ steep), step: the spacing of the points being coloured
// (metres). Noise finer than the spacing can't be shown, only aliased into a checkerboard, so
// it fades out on coarse tiles. Writes into out = [r, g, b].
export function groundColor(x, z, y, slope, out = [0, 0, 0], step = 1) {
  if (y < 2.2) { out[0] = SAND[0]; out[1] = SAND[1]; out[2] = SAND[2]; }
  else {
    const n = 0.5 + (fbm(x * 0.03, z * 0.03, 3) - 0.5) * (1 - sstep(step, 12, 30));
    out[0] = GRASS[0]; out[1] = GRASS[1]; out[2] = GRASS[2];
    mix(out, SCRUB, clamp01(n * 1.6 - 0.35));
    // maquis (dark evergreen scrub) takes over from the dry grass as you climb
    mix(out, MAQUIS, sstep(y, 160, 420) * 0.8);
    // darker wooded patches on the island's middle slopes (the forests to come in the next stage)
    const wood = fbm(x * 0.0024 + 13.7, z * 0.0024 - 6.2, 3);
    mix(out, FOREST, sstep(wood, 0.52, 0.66) * sstep(y, 60, 140) * (1 - sstep(y, 700, 900)) * 0.85);
    mix(out, ROCK, sstep(slope, 0.7, 1.4));
    // bare grey limestone only near the top of the mountain, and on its steeper upper slopes first
    mix(out, HIGH, sstep(y + slope * 150, 850, 1250) * 0.85);
    mix(out, SAND, 1 - sstep(y, 2.2, 4.5));
  }
  const v = 1 + (0.24 * fbm(x * 0.15, z * 0.15, 2) - 0.12) * (1 - sstep(step, 3, 9));   // brush-stroke variation
  out[0] *= v; out[1] *= v; out[2] *= v;
  return out;
}
