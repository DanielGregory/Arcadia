// The colour of the ground at a point, as plain numbers (no three.js), so a worker can use it.
//
// Sand by the water; dry golden grass and olive-dark scrub on the lower slopes; bare rock where
// it's steep; pale grey-violet stone high on the mountain. All broken up with noise so it reads
// as painted, not flat. Colours are linear RGB (0..1), the space the renderer lights in.
//
// Step B adds the island's features: dusty roads, greener river banks, the pale tilled earth of
// olive groves, and the trodden ground of the villages. woodAt() and groveAt() say where forests
// and olive groves are; the tree placement (tilework.js) uses the same functions, so the trees
// stand where the ground is coloured for them.

import { fbm, CITY, inland } from "./terrain.js";
import { roadDist, riverAt, villageNear } from "./featuremap.js";

// sRGB hex -> linear RGB
function lin(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => {
    v /= 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
}
const SAND = lin("#c9a874"), GRASS = lin("#8a7d47"), SCRUB = lin("#4f5531"), ROCK = lin("#8d7b69"),
      HIGH = lin("#9a8e84"), FOREST = lin("#3c4a2c"), MAQUIS = lin("#5a5f3a"),
      ROAD = lin("#b49a72"), EARTH = lin("#a68e66"), RIPARIAN = lin("#4d6230"), TRODDEN = lin("#9c8a6c");

const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);
const sstep = (v, a, b) => { const t = clamp01((v - a) / (b - a)); return t * t * (3 - 2 * t); };
function mix(out, c, f) { out[0] += (c[0] - out[0]) * f; out[1] += (c[1] - out[1]) * f; out[2] += (c[2] - out[2]) * f; }

// How wooded a place is, 0..1: patches on the middle slopes, none in Corva (it has its own trees)
// or high on the bare mountain.
export function woodAt(x, z, y) {
  const wood = fbm(x * 0.0024 + 13.7, z * 0.0024 - 6.2, 3);
  return sstep(wood, 0.5, 0.64) * sstep(y, 50, 130) * (1 - sstep(y, 650, 850));
}
// How much a place is olive grove, 0..1: gentle low ground, mostly round the villages and in patches
// of the basins.
export function groveAt(x, z, y, slope) {
  if (y < 6 || y > 330 || slope > 0.35) return 0;
  const v = villageNear(x, z);
  const nearVillage = v ? 1 - sstep(v.d, v.v.r * 1.2, v.v.r * 7) : 0;
  const patches = sstep(fbm(x * 0.0035 - 4.1, z * 0.0035 + 2.9, 3), 0.55, 0.66);
  const inVillage = v ? sstep(v.d, v.v.r * 0.9, v.v.r * 1.2) : 1;   // not in the streets
  return Math.min(1, nearVillage * 0.9 + patches) * (1 - sstep(slope, 0.2, 0.35)) * inVillage * (1 - cityNear(x, z));
}
// Inside Corva's built-up area itself (its terraces), where nothing wild grows.
export function cityCore(x, z) {
  const s = inland(x, z);
  return s > -5 && s < 172 && z > -(150 - s * 0.55) - 8 && z < 95 - s * 0.55 + 8;
}
// 1 inside Corva's own area (its hand-placed trees and streets), fading out by ~600 m
export function cityNear(x, z) { return 1 - sstep(Math.hypot(x - CITY.x, z - CITY.z), 420, 600); }

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
    // forest floor under the woods (the trees themselves are placed on the nearer tiles)
    mix(out, FOREST, woodAt(x, z, y) * (1 - cityNear(x, z)) * 0.85);
    mix(out, ROCK, sstep(slope, 0.7, 1.4));
    // bare grey limestone only near the top of the mountain, and on its steeper upper slopes first
    mix(out, HIGH, sstep(y + slope * 150, 850, 1250) * 0.85);
    mix(out, SAND, 1 - sstep(y, 2.2, 4.5));
    // the island's features. Each fades out on coarse tiles where it would be thinner than the
    // spacing of the points (it could only flicker in and out there).
    const thin = w => Math.min(1, (w * 2.5) / Math.max(step, 1));
    const g = groveAt(x, z, y, slope);
    if (g > 0) mix(out, EARTH, sstep(g, 0.3, 0.7) * 0.55);
    const rv = riverAt(x, z);
    if (rv) mix(out, RIPARIAN, (1 - sstep(rv.d, rv.w + 10, rv.w + 45)) * 0.7);   // greener banks
    const v = villageNear(x, z);
    if (v) mix(out, TRODDEN, (1 - sstep(v.d, v.v.r * 0.5, v.v.r * 1.05)) * 0.6);
    const rd = roadDist(x, z);
    if (rd < 20) mix(out, ROAD, (1 - sstep(rd, 2.2, 4.2)) * thin(4) * 0.9);
  }
  const v = 1 + (0.24 * fbm(x * 0.15, z * 0.15, 2) - 0.12) * (1 - sstep(step, 3, 9));   // brush-stroke variation
  out[0] *= v; out[1] *= v; out[2] *= v;
  return out;
}
