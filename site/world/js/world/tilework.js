// Building one tile of ground as plain arrays (no three.js), so it can run in a worker.
//
// A tile is a square of land `size` metres across, sampled on a (res + 1) x (res + 1) grid. Round
// its edge hangs a "skirt": a strip of wall going straight down. Neighbouring tiles at different
// levels of detail don't quite meet (one has more points along the shared edge); the skirt fills
// the sliver of gap so the sky never shows through.
//
// Normals (which way the ground faces, for the lighting) are worked out from the heights,
// including one ring of points beyond the tile's edge, so two neighbours agree at their seam and
// the light doesn't show a line where they meet.

import { heightAt, fbm } from "./terrain.js";
import { groundColor, woodAt, groveAt, cityNear, cityCore } from "./ground.js";
import { roadDist, riverAt, villageNear, pathClearance } from "./featuremap.js";

export function buildTile(x0, z0, size, res) {
  const n = res + 1, step = size / res;
  // heights on the grid plus a one-point border all round
  const H = new Float32Array((n + 2) * (n + 2));
  for (let j = -1; j <= n; j++) for (let i = -1; i <= n; i++) H[(j + 1) * (n + 2) + (i + 1)] = heightAt(x0 + i * step, z0 + j * step, step);
  const h = (i, j) => H[(j + 1) * (n + 2) + (i + 1)];

  const verts = n * n + 4 * n;                       // the grid, then the skirt (4 edges of n points)
  const pos = new Float32Array(verts * 3), nor = new Int8Array(verts * 3), col = new Uint8Array(verts * 3), uv = new Float32Array(verts * 2);
  const c = [0, 0, 0];
  let minY = Infinity, maxY = -Infinity;
  const put = (k, x, y, z, nx, ny, nz, r, g, b) => {
    pos[k * 3] = x; pos[k * 3 + 1] = y; pos[k * 3 + 2] = z;
    nor[k * 3] = nx; nor[k * 3 + 1] = ny; nor[k * 3 + 2] = nz;
    col[k * 3] = r; col[k * 3 + 1] = g; col[k * 3 + 2] = b;
    uv[k * 2] = x / 24; uv[k * 2 + 1] = z / 24;      // one detail-texture tile every 24 m
  };
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const x = x0 + i * step, z = z0 + j * step, y = h(i, j);
    const dx = (h(i + 1, j) - h(i - 1, j)) / (2 * step), dz = (h(i, j + 1) - h(i, j - 1)) / (2 * step);
    const len = Math.hypot(dx, 1, dz);
    groundColor(x, z, y, Math.hypot(dx, dz), c, step);
    put(j * n + i, x, y, z, Math.round(-dx / len * 127), Math.round(1 / len * 127), Math.round(-dz / len * 127),
        Math.min(255, c[0] * 255), Math.min(255, c[1] * 255), Math.min(255, c[2] * 255));
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  // the skirt: a copy of each edge point, dropped well below the ground
  const drop = 8 + step * 3;
  const edges = [[i => i, () => 0], [() => n - 1, j => j], [i => n - 1 - i, () => n - 1], [() => 0, j => n - 1 - j]];
  let k = n * n;
  for (const [fi, fj] of edges) for (let t = 0; t < n; t++, k++) {
    const g = fj(t) * n + fi(t);
    put(k, pos[g * 3], pos[g * 3 + 1] - drop, pos[g * 3 + 2], nor[g * 3], nor[g * 3 + 1], nor[g * 3 + 2], col[g * 3], col[g * 3 + 1], col[g * 3 + 2]);
  }
  return { pos, nor, col, uv, minY: minY - drop, maxY };
}

// The triangles of a tile: the same for every tile with the same resolution, so it is built once.
export function tileIndex(res) {
  const n = res + 1, idx = [];
  for (let j = 0; j < res; j++) for (let i = 0; i < res; i++) {
    const a = j * n + i, b = a + 1, d = a + n, e = d + 1;
    idx.push(a, d, b, b, d, e);
  }
  // skirt quads: each edge's top points (on the grid) joined to their dropped copies
  const edgeGrid = [t => t, t => t * n + (n - 1), t => (n - 1) * n + (n - 1 - t), t => (n - 1 - t) * n];
  for (let e = 0; e < 4; e++) for (let t = 0; t < n - 1; t++) {
    const a = edgeGrid[e](t), b = edgeGrid[e](t + 1), sa = n * n + e * n + t, sb = sa + 1;
    idx.push(a, sa, b, b, sa, sb, a, b, sa, b, sb, sa);   // both faces, so it hides the gap from either side
  }
  return n * n + 4 * n > 65535 ? new Uint32Array(idx) : new Uint16Array(idx);
}

// The depth of water near the coasts, baked into a byte map for the sea's shallows and foam.
// value = (height + 8) / 16 * 255, so 0..255 covers 8 m below to 8 m above the sea.
export function shoreBytes(rect, nx, nz) {
  const data = new Uint8Array(nx * nz);
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const hh = heightAt(rect.x + (rect.w * i) / (nx - 1), rect.z + (rect.d * j) / (nz - 1));
    data[j * nx + i] = Math.round(Math.min(1, Math.max(0, (hh + 8) / 16)) * 255);
  }
  return data;
}

// --- trees ---------------------------------------------------------------------------------------
// The trees standing on one tile, as flat lists per kind: [x, y, z, size, turn, shade] for each.
//   pine     dark cones in the forests (higher up)
//   oak      round dark crowns in the forests (lower down) and along the rivers (plane trees)
//   olive    silver-green, in straight rows in the groves
//   cypress  tall narrow spires by the villages and lining the roads
//   scrub    low dark bushes of the maquis on open hillsides (nearest tiles only)
//   boulder  grey rocks scattered on the slopes, more where it's steep (nearest tiles only)
// `spacing` sets how dense the forests are (it's coarser on phones). `step` is the tile's point
// spacing: trees are stood on the same height the tile shows, so they don't float or sink.

function hash2(x, z, s) {
  let h = Math.imul(Math.floor(x) ^ Math.imul(s, 0x9e3779b1), 374761393) + Math.imul(Math.floor(z), 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

export function tileTrees(x0, z0, size, step, spacing, near = false) {
  const kinds = { pine: [], oak: [], olive: [], cypress: [], scrub: [], boulder: [] };
  const ground = (x, z) => heightAt(x, z, step);
  const slopeHere = (x, z) => Math.hypot(ground(x + 3, z) - ground(x - 3, z), ground(x, z + 3) - ground(x, z - 3)) / 6;
  // no trees in the water, on roads, in river channels, in village streets or in Corva
  const clear = (x, z, y) => {
    if (y < 2.5 || cityNear(x, z) > 0.5) return false;
    if (roadDist(x, z) < 5.5 || pathClearance(x, z) < 1.5) return false;
    const rv = riverAt(x, z);
    if (rv && rv.d < rv.w + 3) return false;
    const v = villageNear(x, z);
    return !(v && v.d < v.v.r * 0.85);
  };
  const add = (kind, x, y, z, size) => kinds[kind].push(x, y, z, size, hash2(x, z, 5) * 6.28, 0.8 + hash2(z, x, 6) * 0.4);

  // forests, river trees and the odd lone tree: a jittered grid
  for (let gz = z0; gz < z0 + size; gz += spacing) for (let gx = x0; gx < x0 + size; gx += spacing) {
    const x = gx + hash2(gx, gz, 1) * spacing, z = gz + hash2(gx, gz, 2) * spacing;
    const y = ground(x, z);
    if (!clear(x, z, y)) continue;
    const slope = slopeHere(x, z);
    if (slope > 1.1) continue;
    const r = hash2(gx, gz, 3);
    const rv = riverAt(x, z);
    const byRiver = rv ? 1 - Math.min(1, Math.max(0, (rv.d - rv.w - 4) / 30)) : 0;
    const wood = woodAt(x, z, y);
    if (r < wood * 0.85) add(y > 380 || hash2(gx, gz, 4) < 0.35 ? "pine" : "oak", x, y, z, 0.8 + hash2(gx, gz, 7) * 0.6);
    else if (r < byRiver * 0.7) add("oak", x, y, z, 1.0 + hash2(gx, gz, 7) * 0.5);
    else if (r < 0.025 && groveAt(x, z, y, slope) < 0.3) add(y > 300 ? "pine" : "olive", x, y, z, 0.8 + hash2(gx, gz, 7) * 0.5);
  }
  // olive groves: rows 9 m apart. Each tile's fields run their own way (turned by `turn`): the
  // grid is laid out in the turned frame, over a square big enough to cover the tile.
  const row = 9, turn = fbm(x0 * 0.0015 + 3.3, z0 * 0.0015 - 1.1, 1) * 2.4;
  const c = Math.cos(turn), sn = Math.sin(turn), half = size * 0.75, mx = x0 + size / 2, mz = z0 + size / 2;
  for (let v = -half; v < half; v += row) for (let u = -half; u < half; u += row) {
    const x = mx + u * c - v * sn + (hash2(u + x0, v + z0, 8) - 0.5) * 1.2;
    const z = mz + u * sn + v * c + (hash2(u + x0, v + z0, 9) - 0.5) * 1.2;
    if (x < x0 || z < z0 || x >= x0 + size || z >= z0 + size) continue;
    const y = ground(x, z);
    if (!clear(x, z, y)) continue;
    const g = groveAt(x, z, y, slopeHere(x, z));
    if (g > 0.45 && hash2(x, z, 10) < 0.92) add("olive", x, y, z, 0.75 + hash2(x, z, 11) * 0.4);
  }
  // cypresses: in and round the villages, and lining stretches of the roads
  for (let gz = z0; gz < z0 + size; gz += 14) for (let gx = x0; gx < x0 + size; gx += 14) {
    const x = gx + hash2(gx, gz, 12) * 14, z = gz + hash2(gx, gz, 13) * 14;
    const v = villageNear(x, z), rd = roadDist(x, z);
    const villageRing = v ? v.d > v.v.r * 0.85 && v.d < v.v.r * 1.6 : false;
    const roadside = rd > 5.5 && rd < 9 && fbm(x * 0.01, z * 0.01, 1) > 0.55;
    if (!(villageRing && hash2(gx, gz, 14) < 0.35) && !(roadside && hash2(gx, gz, 15) < 0.6)) continue;
    const y = ground(x, z);
    if (y < 2.5 || cityNear(x, z) > 0.5) continue;
    add("cypress", x, y, z, 0.8 + hash2(gx, gz, 16) * 0.5);
  }
  // scrub and boulders: only on the nearest tiles (they're small), everywhere wild, including the
  // slopes round Corva (not in its streets)
  if (near) {
    const sp = Math.max(6, spacing * 0.45);
    for (let gz = z0; gz < z0 + size; gz += sp) for (let gx = x0; gx < x0 + size; gx += sp) {
      const x = gx + hash2(gx, gz, 21) * sp, z = gz + hash2(gx, gz, 22) * sp;
      const y = ground(x, z);
      if (y < 2 || cityCore(x, z) || roadDist(x, z) < 4 || pathClearance(x, z) < 1) continue;
      const rv = riverAt(x, z);
      if (rv && rv.d < rv.w + 2) continue;
      const slope = slopeHere(x, z), r = hash2(gx, gz, 23);
      const bush = (0.18 + 0.4 * fbm(x * 0.01 + 7, z * 0.01, 2)) * (y < 900 ? 1 : 0.3) * (1 - groveAt(x, z, y, slope));
      if (r < bush) add("scrub", x, y, z, 0.6 + hash2(gx, gz, 24) * 0.9);
      else if (r < bush + 0.03 + Math.min(0.2, slope * 0.15)) add("boulder", x, y, z, 0.6 + Math.pow(hash2(gx, gz, 25), 2) * 1.6);
    }
  }
  const out = {};
  for (const k in kinds) out[k] = new Float32Array(kinds[k]);
  return out;
}
