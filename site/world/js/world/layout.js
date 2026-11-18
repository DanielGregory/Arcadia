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
import { riverAt, roadDist } from "./featuremap.js";

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

// How far the city reaches along the coast at s metres inland: ~150 m north along the quay and
// ~95 m south (beyond that is the slope the first view looks from), narrowing up the hill.
const cityHalf = (s, z = -1) => (z > 0 ? 95 : 150) - s * 0.55;

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
  // (wider than stage 1's: the capital should be the biggest place on the island by far)
  for (let s = 12; s <= 160; s += 9) {
    const street = [];
    for (let z = -cityHalf(s); z <= cityHalf(s, 1); ) {   // the city narrows towards the top
      const w = 4.5 + r() * 4, d = 4 + r() * 3.5, h = 3.2 + r() * 3.6 + (r() < 0.25 ? 3 : 0);
      const jitter = r() * 1.5;
      const p = at(s + jitter, z);
      if (r() < 0.9 && grid.free(p.x, p.z, d + 1, w + 1) && slopeAt(p.x, p.z) < 1.4 && inland(p.x, p.z) > 6) {
        // a third of the houses get a smaller upper storey set back from the street
        const upper = r() < 0.35 ? { w: w * (0.45 + r() * 0.25), d: d * (0.45 + r() * 0.2), h: 2.4 + r() * 1.4, off: (r() - 0.5) * w * 0.3 } : null;
        L.houses.push({ x: p.x, z: p.z, y: p.y, w, d, h, rot: facing(z), upper });
        grid.take(p.x, p.z, d + 1, w + 1);
        if (r() < 0.12) L.chimneys.push({ x: p.x, y: p.y + h + 0.6, z: p.z });
      }
      const q = at(s - 5, z);                             // the street runs just below each terrace
      street.push({ x: q.x, y: q.y + 1.1, z: q.z });
      z += w + 1.7 + r() * 1.8;                           // (enough that the next house clears this one's margin)
    }
    if (street.length > 3) L.streets.push(street);
  }
  // a few farm houses scattered beyond the city
  for (let i = 0; i < 26; i++) {
    const z = (r() - 0.5) * 300, s = 30 + r() * 120;
    const p = at(s, z);
    if (Math.abs(z) < cityHalf(s, z) && s < 165) continue;  // (that is the city)
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
    const inCity = Math.abs(z) < cityHalf(s, z) && s < 165;
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

// --- villages ------------------------------------------------------------------------------------
// Each village of the island's features (features.js) is laid out the way real ones grew: lanes
// winding out from a square (one of them down to the harbour on the coast), crossed by a ring lane
// or two, with houses lining both sides of every lane, fronts to the lane. A small temple stands on
// the uphill side of the square. Coastal villages also get a row of houses along the waterfront, a
// quay, a stone mole curving out to shelter the harbour, and fishing boats (and a trader) moored
// inside it. Everything goes into the same layout lists as Corva's, so the same builders draw it.
const VILLAGE_KINDS = [["cube", 0.3], ["gable", 0.25], ["hip", 0.14], ["twostorey", 0.13], ["courtyard", 0.15], ["tower", 0.03]];

export function addVillages(L, villages, seed = 1717) {
  const r = rng(seed + 41);
  const grid = new Grid();
  const kindOf = () => { let x = r(); for (const [k, w] of VILLAGE_KINDS) { x -= w; if (x <= 0) return k; } return "cube"; };
  // can a house stand here? on land, not too steep, clear of rivers and the middle of roads
  const buildable = (x, z, w, d) => {
    if (!grid.free(x, z, d + 1.5, w + 1.5)) return false;
    if (inland(x, z) < 9 || heightAt(x, z) < 2.5 || slopeAt(x, z) > 0.8) return false;
    const rv = riverAt(x, z);
    if (rv && rv.d < rv.w + 7) return false;
    return roadDist(x, z) > 4.5;
  };
  const addHouse = (x, z, frontX, frontZ, w, d) => {
    const y = heightAt(x, z), h = 3.2 + r() * 2.4;
    L.houses.push({ x, z, y, w, d, h, rot: -Math.atan2(frontZ - z, frontX - x), style: kindOf() });
    grid.take(x, z, d + 1.5, w + 1.5);
    if (r() < 0.22) L.chimneys.push({ x, y: y + h + 0.6, z });
  };
  L.villages = [];
  for (const v of villages) {
    const R = v.r, before = L.houses.length;
    // the temple on the uphill side of the square, facing it
    const ex = heightAt(v.x + 10, v.z) - heightAt(v.x - 10, v.z), ez = heightAt(v.x, v.z + 10) - heightAt(v.x, v.z - 10);
    const upA = Math.atan2(ez, ex), tx = v.x + Math.cos(upA) * 28, tz = v.z + Math.sin(upA) * 28;
    L.temples.push({ x: tx, z: tz, y: heightAt(tx, tz), w: 9, d: 13, cols: [4, 6], rot: -(upA + Math.PI), scale: 0.62 });
    grid.take(tx, tz, 18, 18);
    grid.take(v.x, v.z, 24, 24);                                   // the square stays open

    // the lanes: out from the square, bending as they go; one aimed at the harbour
    const lanes = [];
    const n = v.coastal ? 7 : 5, base = v.harbour ? Math.atan2(v.harbour.dz, v.harbour.dx) : r() * 6.28;
    for (let k = 0; k < n; k++) {
      let a = base + (k / n) * Math.PI * 2 + (k ? (r() - 0.5) * 0.5 : 0);
      const pts = [];
      let x = v.x + Math.cos(a) * 14, z = v.z + Math.sin(a) * 14;
      for (let d = 14; d < R * 1.1; d += 4) {
        pts.push({ x, z });
        a += (fbm(x * 0.02 + k, z * 0.02, 1) - 0.5) * 0.35;
        x += Math.cos(a) * 4; z += Math.sin(a) * 4;
        if (inland(x, z) < 8) break;                               // reached the water
      }
      lanes.push(pts);
    }
    for (const ringR of v.coastal ? [R * 0.45, R * 0.8] : [R * 0.55]) {
      const pts = [];
      for (let k = 0; k <= 64; k++) {
        const a = (k / 64) * Math.PI * 2, rr = ringR * (1 + (fbm(Math.cos(a) * 2 + v.x, Math.sin(a) * 2, 2) - 0.5) * 0.25);
        const x = v.x + Math.cos(a) * rr, z = v.z + Math.sin(a) * rr;
        if (inland(x, z) > 8) pts.push({ x, z }); else if (pts.length) { lanes.push(pts.splice(0)); }
      }
      if (pts.length > 2) lanes.push(pts);
    }
    // houses along both sides of each lane, fronts to the lane
    for (const pts of lanes) {
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i], dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz) || 1;
        for (const side of [1, -1]) {
          if (r() < (v.coastal ? 0.62 : 0.6)) continue;            // gaps: gardens, yards
          const w = 4.5 + r() * 3.5, d = 4 + r() * 2.5, off = 3 + d / 2 + r() * 0.8;
          const x = b.x + (-dz / len) * side * off, z = b.z + (dx / len) * side * off;
          if (Math.hypot(x - v.x, z - v.z) > R * 1.15) continue;
          if (buildable(x, z, w, d)) addHouse(x, z, b.x, b.z, w, d);
        }
      }
      if (pts.length > 4 && L.streets.length < 60) L.streets.push(pts.map(p => ({ x: p.x, y: heightAt(p.x, p.z) + 1.1, z: p.z })));
    }

    if (v.harbour) addHarbour(L, v, r, grid, buildable, addHouse);
    L.villages.push({ name: v.name, x: v.x, z: v.z, y: heightAt(v.x, v.z), coastal: !!v.coastal, houses: L.houses.length - before });
  }
  return L;
}

// A coastal village's waterfront: houses facing the sea, a quay wall along the shore, a mole of
// stone blocks curving out to shelter the harbour, and boats moored inside it.
function addHarbour(L, v, r, grid, buildable, addHouse) {
  const dx = v.harbour.dx, dz = v.harbour.dz;
  // where the shore is, straight out from the square
  let sx = v.x, sz = v.z;
  for (let k = 0; k < 200 && heightAt(sx, sz) > 0.6; k++) { sx += dx * 3; sz += dz * 3; }
  const along = { x: -dz, z: dx };                                // the shoreline's direction
  // the waterfront: a row of houses a little back from the water, looking out to sea, and the quay
  for (let t = -v.r; t <= v.r; t += 7 + r() * 3) {
    const qx = sx + along.x * t, qz = sz + along.z * t;
    // find the shore here, then step back inland
    let x = qx, z = qz;
    for (let k = 0; k < 40 && heightAt(x, z) < 1; k++) { x -= dx * 2; z -= dz * 2; }
    for (let k = 0; k < 40 && heightAt(x, z) > 1; k++) { x += dx * 2; z += dz * 2; }
    L.walls.push({ x: x + dx, z: z + dz, y: 0, len: 7.5, rot: Math.atan2(along.x, along.z), h: 1.3 });
    const hx = x - dx * 13, hz = z - dz * 13, w = 5 + r() * 3, d = 4.5 + r() * 2;
    if (r() < 0.85 && buildable(hx, hz, w, d)) addHouse(hx, hz, x + dx * 10, z + dz * 10, w, d);
  }
  // the mole: out from the shore, bending to one side to wrap round the harbour
  let mx = sx + along.x * v.r * 0.55, mz = sz + along.z * v.r * 0.55, a = Math.atan2(dz, dx);
  const turn = -Math.sign(r() - 0.5 || 1) * 0.022;
  for (let k = 0; k < 26; k++) {
    if (k > 8) a += turn * 4.4;
    const nx = mx + Math.cos(a) * 4.4, nz = mz + Math.sin(a) * 4.4;
    L.walls.push({ x: (mx + nx) / 2, z: (mz + nz) / 2, y: 0, len: 4.6, rot: Math.atan2(nx - mx, nz - mz), h: 2.0, wide: 5 });
    mx = nx; mz = nz;
  }
  // boats inside the mole: fishing boats in a row, a trader at the end
  const boats = 4 + Math.floor(r() * 4);
  for (let k = 0; k < boats; k++) {
    const t = -v.r * 0.2 + (k / boats) * v.r * 0.65;
    const bx = sx + along.x * t + dx * (14 + r() * 10), bz = sz + along.z * t + dz * (14 + r() * 10);
    if (heightAt(bx, bz) > -1.2) continue;
    L.ships.push({ x: bx, z: bz, rot: Math.atan2(along.x, along.z) + (r() - 0.5) * 0.4, size: 1, sail: false, kind: "fishing" });
  }
  if (heightAt(mx - Math.cos(a) * 12, mz - Math.sin(a) * 12) < -2.5) {
    L.ships.push({ x: mx - Math.cos(a) * 12 - Math.sin(a) * 8, z: mz - Math.sin(a) * 12 + Math.cos(a) * 8,
                   rot: a, size: 1, sail: r() < 0.5, kind: "merchant" });
  }
}

export { at, facing, inland };
