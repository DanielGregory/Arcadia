// Corva as plain data: what stands where. No three.js in here.
//
// generateLayout(seed) builds the city procedurally: terraces of white houses climbing the hill,
// columned temples on the quay, the slopes and the summit, a zigzag stairway between them, a quay
// wall and a harbour mole, trees, ships, chimneys and the streets lanterns walk along at night.
//
// Stage 3 replaces this with a layout read from the world tables (places, objects, people): the
// scene builders in ../scene/ only ever read this shape of data, so they won't need rewriting.
//
//   layout = { houses: [{x, z, y, w, d, h, rot}], temples: [{x, z, y, w, d, cols, rot, scale}],
//              stairs: [{x, z, y, rot}], walls: [{x, z, y, len, rot, h}], trees: [{x, z, y, kind, s}],
//              ships: [{x, z, rot, size, sail}], chimneys: [{x, y, z}], streets: [[{x, y, z}...]...] }

import { coastX, heightAt, inland, slopeAt, fbm } from "./terrain.js";

export function rng(seed) {  // mulberry32: small, fast, repeatable
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The direction the shore faces at z: buildings turn to face the water.
function facing(z) {
  const dc = (coastX(z + 1) - coastX(z - 1)) / 2;   // d(coastX)/dz
  return Math.atan2(dc, 1);                        // rotation about y
}
// A point `s` metres inland from the shore at z.
function at(s, z) { const x = coastX(z) - s; return { x, z, y: heightAt(x, z) }; }

// Occupancy grid (2 m cells) so things don't overlap.
class Grid {
  constructor() { this.cells = new Set(); }
  key(x, z) { return `${Math.round(x / 2)},${Math.round(z / 2)}`; }
  free(x, z, w, d) {
    for (let i = -w / 2; i <= w / 2; i += 2) for (let j = -d / 2; j <= d / 2; j += 2)
      if (this.cells.has(this.key(x + i, z + j))) return false;
    return true;
  }
  take(x, z, w, d) {
    for (let i = -w / 2; i <= w / 2; i += 2) for (let j = -d / 2; j <= d / 2; j += 2) this.cells.add(this.key(x + i, z + j));
  }
}

export function generateLayout(seed = 1717, quality = "medium") {
  const r = rng(seed);
  const grid = new Grid();
  const L = { houses: [], temples: [], stairs: [], walls: [], trees: [], ships: [], chimneys: [], streets: [] };

  // --- temples (placed first: they get the best spots) -------------------------------------
  const temples = [
    { s: 118, z: -14, w: 16, d: 26, cols: [6, 11], scale: 1.25 },  // the summit temple
    { s: 13, z: -38, w: 12, d: 20, cols: [5, 9], scale: 1.0 },     // the temple on the quay
    { s: 16, z: 22, w: 10, d: 34, cols: [4, 14], scale: 0.95 },    // the long colonnade (palace) on the quay
    { s: 58, z: 18, w: 10, d: 16, cols: [4, 7], scale: 0.9 },      // halfway up
    { s: 84, z: -42, w: 10, d: 15, cols: [4, 7], scale: 0.9 },     // high on the north slope
  ];
  for (const t of temples) {
    const p = at(t.s, t.z);
    L.temples.push({ x: p.x, z: p.z, y: p.y, w: t.w, d: t.d, cols: t.cols, rot: facing(t.z), scale: t.scale });
    grid.take(p.x, p.z, t.w + 6, t.d + 6);
  }

  // --- the zigzag stairway from the quay to the summit -------------------------------------
  const path = [];
  for (let s = 6, k = 0; s <= 112; s += 1.0, k++) {
    const zig = 11 * Math.sin((s / 26) * Math.PI);       // switchbacks across the slope
    path.push(at(s, -12 + zig));
  }
  for (let i = 0; i < path.length; i += 1) {
    const a = path[i], b = path[Math.min(i + 1, path.length - 1)];
    L.stairs.push({ x: a.x, z: a.z, y: a.y, rot: Math.atan2(b.x - a.x, b.z - a.z) });
    grid.take(a.x, a.z, 4, 4);
  }
  L.streets.push(path.map(p => ({ x: p.x, y: p.y + 1.2, z: p.z })));

  // --- terraces of houses -------------------------------------------------------------------
  for (let s = 12; s <= 108; s += 9.5) {
    const half = 72 - s * 0.38;                           // the city narrows towards the top
    const street = [];
    for (let z = -half; z <= half; ) {
      const w = 4.5 + r() * 4, d = 4 + r() * 3.5, h = 3.2 + r() * 3.6 + (r() < 0.25 ? 3 : 0);
      const jitter = r() * 3;
      const p = at(s + jitter, z);
      if (r() < 0.86 && grid.free(p.x, p.z, d + 1, w + 1) && slopeAt(p.x, p.z) < 1.4) {
        L.houses.push({ x: p.x, z: p.z, y: p.y, w, d, h, rot: facing(z) });
        grid.take(p.x, p.z, d + 1, w + 1);
        if (r() < 0.12) L.chimneys.push({ x: p.x, y: p.y + h + 0.6, z: p.z });
      }
      const q = at(s - 5, z);                             // the street runs just below each terrace
      street.push({ x: q.x, y: q.y + 1.1, z: q.z });
      z += w + 0.8 + r() * 2.5;
    }
    if (street.length > 3) L.streets.push(street);
  }
  // a few farm houses scattered beyond the city
  for (let i = 0; i < 26; i++) {
    const z = (r() - 0.5) * 300, s = 30 + r() * 120;
    const p = at(s, z);
    if (Math.abs(z) < 60 && s < 110) continue;
    if (grid.free(p.x, p.z, 8, 8) && slopeAt(p.x, p.z) < 0.8 && p.y > 3) {
      L.houses.push({ x: p.x, z: p.z, y: p.y, w: 5 + r() * 3, d: 4 + r() * 2, h: 3 + r() * 2, rot: r() * Math.PI });
      grid.take(p.x, p.z, 8, 8);
    }
  }

  // --- quay wall and harbour mole -----------------------------------------------------------
  for (let z = -60; z < 52; z += 4) {
    const x = coastX(z) + 0.6;
    L.walls.push({ x, z, y: 0, len: 4.2, rot: facing(z), h: 1.6 });
  }
  const moleStart = { x: coastX(58), z: 58 };
  for (let t = 0; t <= 1; t += 0.06) {
    const x = moleStart.x + t * 46, z = moleStart.z - t * 18 - 8 * Math.sin(t * Math.PI);
    L.walls.push({ x, z, y: 0, len: 4.4, rot: Math.atan2(46, -18) + Math.PI / 2, h: 2.4 });
  }

  // --- trees ----------------------------------------------------------------------------------
  const counts = { low: 420, medium: 800, high: 1200 };
  const want = counts[quality] || counts.medium;
  for (let tries = 0; L.trees.length < want && tries < want * 12; tries++) {
    const z = (r() - 0.5) * 520, s = 4 + Math.pow(r(), 1.3) * 230;
    const p = at(s, z);
    if (p.y < 1.5 || p.y > 150 || slopeAt(p.x, p.z) > 1.1) continue;
    if (p.z > 150) continue;                // keep the viewer's own shore (south arm) open
    const dens = fbm(p.x * 0.02 + 7, p.z * 0.02 - 3, 3);
    const inCity = Math.abs(z) < 72 - s * 0.38 && s < 110;
    if (r() > dens * (inCity ? 0.55 : 1.5)) continue;
    if (!grid.free(p.x, p.z, 2, 2)) continue;
    const kind = inCity ? (r() < 0.6 ? "cypress" : "olive") : (r() < 0.25 ? "cypress" : "olive");
    L.trees.push({ x: p.x, z: p.z, y: p.y, kind, s: 0.75 + r() * 0.6 });
    grid.take(p.x, p.z, 2, 2);
  }

  // --- ships: some moored along the quay, the rest out in the bay ---------------------------
  for (let i = 0; i < 16; i++) {
    const moored = i < 6;
    const z = moored ? -40 + i * 13 + r() * 4 : (r() - 0.5) * 230;
    const s = moored ? -(7 + r() * 3) : -(25 + r() * 170);
    const x = coastX(z) - s;
    if (heightAt(x, z) > -2) continue;
    L.ships.push({ x, z, rot: moored ? facing(z) + Math.PI / 2 : r() * Math.PI * 2, size: 0.8 + r() * 0.8,
                   sail: !moored || r() < 0.3 });
  }
  return L;
}

export { at, facing, inland };
