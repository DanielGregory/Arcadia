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

import { heightAt } from "./terrain.js";
import { groundColor } from "./ground.js";

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
