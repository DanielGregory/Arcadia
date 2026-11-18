// The island's villages, rivers and roads, made from the seed. (No three.js.)
//
//   villages  2-4, in the hills: gentle ground, out of sight of each other, 1.7+ km from Corva,
//             not up on the mountain. Each gets a name.
//   rivers    from springs on the mountain's flanks down to the sea: each step goes mostly
//             downhill, partly toward the nearest coast (so a river can't get stuck in a hollow),
//             with a little meander. Their water height is made to fall all the way, and the
//             terrain then carves their valleys (terrain.js). A river that runs into another
//             joins it there.
//   roads     Corva to the villages and the villages to each other: the cheapest route over a
//             30 m grid (A* search), where steep ground costs much more than flat, the sea can't
//             be crossed and rivers only at a price (a bridge); a stretch of existing road is
//             cheap, so roads share their way out of town. Then smoothed.
//
// Made once and saved for the default seed (assets/island/features-1717.json, by
// site/world/tools/make_features.mjs), so the browser just loads it; any other seed is made live.

import { heightAt, inland, slopeAt, fbm, CITY, PEAK, BOUNDS } from "./terrain.js";
import { setFeatures } from "./featuremap.js";
import { rng } from "./layout.js";

const NAMES = ["Elaia", "Ampelos", "Kryoneri", "Platanos", "Melissa", "Lithari", "Agrilia", "Kastri"];
// (olive tree, vine, cold water, plane tree, bee, little stone, wild olive, little fort)

export function generateFeatures(seed = 1717) {
  setFeatures(null);                                 // work on the bare land, without old carving
  const r = rng(seed * 7 + 3);
  const villages = placeVillages(r);
  const rivers = traceRivers(r);
  setFeatures({ villages, rivers, roads: [] });      // roads should see the river valleys
  const roads = buildRoads(villages, rivers);
  const f = { seed, villages, rivers, roads, mountain: { name: "Mount Aetos", x: PEAK.x, z: PEAK.z } };
  setFeatures(f);
  return f;
}

// --- villages ------------------------------------------------------------------------------------
function placeVillages(r) {
  const cands = [];
  for (let z = BOUNDS.minZ; z < BOUNDS.maxZ; z += 150) for (let x = BOUNDS.minX; x < BOUNDS.maxX; x += 150) {
    const s = inland(x, z);
    if (s < 600 || s > 3200) continue;
    if (Math.hypot(x - CITY.x, z - CITY.z) < 1700 || Math.hypot(x - PEAK.x, z - PEAK.z) < 1100) continue;
    const y = heightAt(x, z);
    if (y < 50 || y > 420) continue;
    // gentle over the whole village, not just at its middle
    let slope = 0;
    for (const [a, b] of [[0, 0], [70, 0], [-70, 0], [0, 70], [0, -70]]) slope += slopeAt(x + a, z + b);
    slope /= 5;
    if (slope > 0.32) continue;
    cands.push({ x, z, y, score: -slope * 3 + y / 500 + r() * 0.35 });
  }
  cands.sort((a, b) => b.score - a.score);
  const out = [];
  for (const c of cands) {
    if (out.length >= 4) break;
    if (out.some(v => Math.hypot(v.x - c.x, v.z - c.z) < 1600)) continue;
    out.push(c);
  }
  return out.map((v, i) => ({ name: NAMES[i % NAMES.length], x: Math.round(v.x), z: Math.round(v.z), y: Math.round(v.y),
                              r: 85 + Math.round(r() * 45) }));
}

// --- rivers -------------------------------------------------------------------------------------
// Smoothed height (averaged over ~120 m) so a river follows the lie of the land, not every bump.
function broad(x, z) {
  let h = 0;
  for (const [a, b] of [[0, 0], [60, 0], [-60, 0], [0, 60], [0, -60]]) h += heightAt(x + a, z + b);
  return h / 5;
}

function traceRivers(r) {
  const rivers = [];
  const springs = 6, step = 30;
  for (let k = 0; k < springs; k++) {
    // springs round the mountain's flanks, ~1.2-1.6 km out from the peak
    const a = (k / springs) * Math.PI * 2 + r() * 0.6, d = 1200 + r() * 400;
    let x = PEAK.x + Math.cos(a) * d, z = PEAK.z + Math.sin(a) * d * 1.2;
    if (inland(x, z) < 400) continue;
    const pts = [];
    let dirx = Math.cos(a), dirz = Math.sin(a), joined = false;
    let reached = false;
    for (let i = 0; i < 360; i++) {                               // at most ~11 km
      pts.push({ x, z });
      const s = inland(x, z);
      if (s < -15) { reached = true; break; }                     // out at sea
      // which way is downhill, and which way is the coast
      const e = 40;
      const gx = (broad(x + e, z) - broad(x - e, z)) / (2 * e), gz = (broad(x, z + e) - broad(x, z - e)) / (2 * e);
      const cx = -(inland(x + e, z) - inland(x - e, z)), cz = -(inland(x, z + e) - inland(x, z - e));
      const cl = Math.hypot(cx, cz) || 1, gl = Math.hypot(gx, gz) || 1;
      // the pull toward the coast grows the further the river has run, so it can't circle forever in
      // the ring of low ground round the mountain
      const toSea = 0.45 + i * 0.012;
      let nx = -gx / gl * 1.0 + cx / cl * toSea + dirx * 1.2, nz = -gz / gl * 1.0 + cz / cl * toSea + dirz * 1.2;
      // meander, and keep clear of Corva
      const m = (fbm(x * 0.003 + k * 9, z * 0.003, 2) - 0.5) * 1.6;
      nx += -nz * m; nz += nx * m;
      const tc = Math.hypot(x - CITY.x, z - CITY.z);
      if (tc < 1300) { nx += (x - CITY.x) / tc * 2.5 * (1 - tc / 1300); nz += (z - CITY.z) / tc * 2.5 * (1 - tc / 1300); }
      const nl = Math.hypot(nx, nz) || 1;
      dirx = nx / nl; dirz = nz / nl;
      x += dirx * step; z += dirz * step;
      // run into an earlier river? join it there
      for (const other of rivers) {
        if (other.pts.some(p => Math.hypot(p.x - x, p.z - z) < 45)) { pts.push({ x, z }); joined = true; break; }
      }
      if (joined) { reached = true; break; }
    }
    if (!reached || pts.length * step < 1300) continue;           // never got to the sea, or too short
    // the water's height: the land's (smoothed) height along the way, never rising, ending below the sea
    let h = broad(pts[0].x, pts[0].z) - 2;
    pts.forEach((p, i) => {
      h = Math.min(h - 0.15, broad(p.x, p.z) - 1.5);
      p.h = Math.max(h, -1.5);
      p.w = 3 + 9 * (i / (pts.length - 1));                       // half-width: a stream widening to a river
      p.x = Math.round(p.x * 10) / 10; p.z = Math.round(p.z * 10) / 10; p.h = Math.round(p.h * 100) / 100; p.w = Math.round(p.w * 10) / 10;
    });
    rivers.push({ name: null, pts, joins: joined });
  }
  return rivers;
}

// --- roads --------------------------------------------------------------------------------------
class Heap {   // a small binary min-heap of [cost, index]
  constructor() { this.a = []; }
  push(c, i) { const a = this.a; a.push([c, i]); let k = a.length - 1; while (k > 0) { const p = (k - 1) >> 1; if (a[p][0] <= a[k][0]) break; [a[p], a[k]] = [a[k], a[p]]; k = p; } }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) { a[0] = last; let k = 0; for (;;) { const l = 2 * k + 1, rr = l + 1; let m = k;
      if (l < a.length && a[l][0] < a[m][0]) m = l; if (rr < a.length && a[rr][0] < a[m][0]) m = rr; if (m === k) break; [a[m], a[k]] = [a[k], a[m]]; k = m; } }
    return top;
  }
  get size() { return this.a.length; }
}

function buildRoads(villages, rivers) {
  const cell = 30, x0 = BOUNDS.minX, z0 = BOUNDS.minZ;
  const nx = Math.ceil((BOUNDS.maxX - x0) / cell), nz = Math.ceil((BOUNDS.maxZ - z0) / cell);
  const H = new Float32Array(nx * nz), land = new Uint8Array(nx * nz), wet = new Uint8Array(nx * nz), used = new Uint8Array(nx * nz);
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const x = x0 + i * cell, z = z0 + j * cell, k = j * nx + i;
    H[k] = heightAt(x, z);
    land[k] = inland(x, z) > 12 && H[k] > 1.5 ? 1 : 0;
  }
  // mark river cells (crossing them means a bridge)
  for (const rv of rivers) for (const p of rv.pts) {
    const i = Math.round((p.x - x0) / cell), j = Math.round((p.z - z0) / cell);
    if (i >= 0 && j >= 0 && i < nx && j < nz) wet[j * nx + i] = 1;
  }
  const idx = (x, z) => Math.round((z - z0) / cell) * nx + Math.round((x - x0) / cell);
  const N8 = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];

  function route(from, to) {
    const start = idx(from.x, from.z), goal = idx(to.x, to.z);
    const g = new Float32Array(nx * nz).fill(Infinity), came = new Int32Array(nx * nz).fill(-1);
    const gi = goal % nx, gj = Math.floor(goal / nx);
    const heap = new Heap();
    g[start] = 0;
    heap.push(0, start);
    while (heap.size) {
      const [, k] = heap.pop();
      if (k === goal) break;
      const i = k % nx, j = Math.floor(k / nx);
      for (const [di, dj] of N8) {
        const a = i + di, b = j + dj;
        if (a < 0 || b < 0 || a >= nx || b >= nz) continue;
        const n = b * nx + a;
        if (!land[n] && n !== goal) continue;
        const run = cell * Math.hypot(di, dj), grade = Math.abs(H[n] - H[k]) / run;
        let cost = run * (1 + 60 * grade * grade + (grade > 0.22 ? 40 : 0));   // switchbacks beat cliffs
        if (wet[n]) cost += 260;                                             // a bridge
        if (used[n]) cost *= 0.45;                                           // share the road already there
        const ng = g[k] + cost;
        if (ng < g[n]) {
          g[n] = ng; came[n] = k;
          heap.push(ng + Math.hypot(a - gi, b - gj) * cell, n);              // A*: plus the straight-line distance
        }
      }
    }
    if (came[goal] < 0) return null;
    const path = [];
    for (let k = goal; k >= 0; k = came[k]) { path.push({ x: x0 + (k % nx) * cell, z: z0 + Math.floor(k / nx) * cell }); used[k] = 1; if (k === start) break; }
    return path.reverse();
  }

  // Corva's road starts above the town, near the summit temple, heading inland
  const gate = { x: CITY.x - 200, z: CITY.z - 10 };
  const nodes = [{ name: "Corva", ...gate }, ...villages];
  const links = [];
  // each village to the nearest place already on the network (a tree from Corva) ...
  const joined = [nodes[0]], waiting = nodes.slice(1);
  while (waiting.length) {
    let best = null;
    for (const v of waiting) for (const u of joined) {
      const d = Math.hypot(v.x - u.x, v.z - u.z);
      if (!best || d < best.d) best = { v, u, d };
    }
    links.push([best.u, best.v]);
    joined.push(best.v);
    waiting.splice(waiting.indexOf(best.v), 1);
  }
  // ... plus one more link between the two villages furthest apart on it, so there's a loop
  if (villages.length >= 3) {
    let far = null;
    for (const a of villages) for (const b of villages) {
      if (a === b || links.some(([p, q]) => (p === a && q === b) || (p === b && q === a))) continue;
      const d = Math.hypot(a.x - b.x, a.z - b.z);
      if (d < 4200 && (!far || d < far.d)) far = { a, b, d };
    }
    if (far) links.push([far.a, far.b]);
  }
  const roads = [];
  for (const [a, b] of links) {
    const path = route(a, b);
    if (!path || path.length < 3) continue;
    roads.push({ from: a.name, to: b.name, pts: smoothPath(path) });
  }
  return roads;
}

// Chaikin's corner cutting (twice): replaces each corner with two points a quarter of the way
// along each side, which rounds the grid's 45-degree zigzags into curves.
function smoothPath(pts) {
  let p = pts;
  for (let it = 0; it < 2; it++) {
    const q = [p[0]];
    for (let i = 0; i + 1 < p.length; i++) {
      const a = p[i], b = p[i + 1];
      q.push({ x: a.x * 0.75 + b.x * 0.25, z: a.z * 0.75 + b.z * 0.25 }, { x: a.x * 0.25 + b.x * 0.75, z: a.z * 0.25 + b.z * 0.75 });
    }
    q.push(p[p.length - 1]);
    p = q;
  }
  // thin out nearly straight runs, keep a point every ~12 m at most
  const out = [p[0]];
  for (let i = 1; i < p.length - 1; i++) {
    const a = out[out.length - 1], b = p[i], c = p[i + 1];
    const turn = Math.abs(Math.atan2(c.z - b.z, c.x - b.x) - Math.atan2(b.z - a.z, b.x - a.x));
    if (Math.hypot(b.x - a.x, b.z - a.z) > 12 && (turn > 0.04 || Math.hypot(b.x - a.x, b.z - a.z) > 60)) out.push(b);
  }
  out.push(p[p.length - 1]);
  return out.map(q => ({ x: Math.round(q.x * 10) / 10, z: Math.round(q.z * 10) / 10 }));
}
