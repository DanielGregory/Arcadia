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
import { riverAt, roadDist, getFeatures } from "./featuremap.js";

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

  // --- stairways: one main zigzag from the quay to the summit, and three narrower winding ones
  // (each a list of steps; lanterns walk them at night)
  const stairway = (z0, amp, period, s0, s1) => {
    const path = [];
    for (let s = s0; s <= s1; s += 1.0) path.push(at(s, z0 + amp * Math.sin((s / period) * Math.PI) + 3 * Math.sin(s / 7)));
    for (let i = 0; i < path.length; i++) {
      const a = path[i], b = path[Math.min(i + 1, path.length - 1)];
      L.stairs.push({ x: a.x, z: a.z, y: a.y, rot: Math.atan2(b.x - a.x, b.z - a.z) });
      grid.take(a.x, a.z, 4, 4);
    }
    L.streets.push(path.map(p => ({ x: p.x, y: p.y + 1.2, z: p.z })));
  };
  stairway(-12, 11, 26, 6, 112);
  stairway(-98, 7, 18, 14, 140);
  stairway(48, 6, 17, 8, 120);
  stairway(-58, 6, 21, 10, 132);
  const stairCount = L.streets.length;

  // --- terraces of houses -------------------------------------------------------------------
  // Stacked up the hill as in the painting: rows only 7 m apart that wander with the slope, so the
  // houses of each row stand above the roofs of the one below; one, two or three storeys; clustered
  // together with gaps for gardens; a stone retaining wall under each house's front where it stands
  // above the street; a street along the foot of every row.
  L.retaining = [];
  for (let s = 10; s <= 165; s += 7) {
    const street = [];
    for (let z = -cityHalf(s); z <= cityHalf(s, 1); ) {   // the city narrows towards the top
      const sr = s + 2.5 * Math.sin(z / 19 + s * 0.37) + (fbm(z * 0.05, s * 0.05, 2) - 0.5) * 4;
      const cluster = fbm(z * 0.035 + 3, sr * 0.035 - 1, 2);
      const w = 4.2 + r() * 3.6, d = 4.5 + r() * 3.5;
      let h = 3.2 + r() * 2.6;
      if (r() < 0.35) h += 2.8;                           // two storeys
      if (r() < 0.12) h += 2.8;                           // three
      const p = at(sr + r() * 1.2, z);
      // (only the front part of each house is reserved: on the slope its back is under the next
      // row's fronts, which is what makes the stacked look)
      if (cluster > 0.27 && grid.free(p.x, p.z, d * 0.55, w + 1) && slopeAt(p.x, p.z) < 1.8 && inland(p.x, p.z) > 6) {
        L.houses.push({ x: p.x, z: p.z, y: p.y, w, d, h, rot: facing(z) + (r() - 0.5) * 0.15 });
        grid.take(p.x, p.z, d * 0.55, w + 1);
        if (r() < 0.12) L.chimneys.push({ x: p.x, y: p.y + h + 0.6, z: p.z });
        const f = at(sr - d / 2 - 1.4, z);
        if (p.y - f.y > 0.6) L.retaining.push({ x: f.x, z: f.z, y: f.y, top: p.y + 0.35, len: w + 1.4, rot: facing(z) });
      }
      // the street along the foot of the row; it breaks off where the slope turns to cliff
      const q = at(sr - d / 2 - 3, z);
      if (slopeAt(q.x, q.z) < 0.9 && inland(q.x, q.z) > 4) street.push({ x: q.x, y: q.y + 1.1, z: q.z });
      else if (street.length) { if (street.length > 3) L.streets.push(street.splice(0)); else street.length = 0; }
      z += w + 1.2 + r() * 1.4;
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

  // --- ships: a few, at their real size, clustered along the quay by the harbour wall ----------
  // (merchantmen and galleys tied up alongside, fishing boats inside the mole, two traders at anchor)
  const moored = ["merchant", "galley", "merchant", "merchant", "galley"];
  moored.forEach((kind, i) => {
    const z = -44 + i * 19 + r() * 4, x = coastX(z) + 7 + r() * 1.5;
    if (heightAt(x, z) < -1.2) L.ships.push({ x, z, rot: facing(z) + Math.PI / 2, kind, scale: 0.5, sail: false });
  });
  for (let i = 0; i < 6; i++) {
    const z = 28 + r() * 26, x = coastX(z) + 12 + r() * 14;
    if (heightAt(x, z) < -1.2) L.ships.push({ x, z, rot: r() * 6.28, kind: "fishing", scale: 0.8, sail: false });
  }
  for (let i = 0; i < 2; i++) {
    const z = -40 + r() * 90, x = coastX(z) + 70 + r() * 90;
    if (heightAt(x, z) < -3) L.ships.push({ x, z, rot: r() * 6.28, kind: "merchant", scale: 0.55, sail: true });
  }
  // --- sea stacks: rock pillars standing in the water below the cliffs -------------------------
  L.rocks = [];
  for (let i = 0; i < 14; i++) {
    const north = i < 10, z = north ? -130 - r() * 300 : 150 + r() * 160;
    const x = Math.min(coastX(z), 420) + 10 + r() * 55;
    if (heightAt(x, z) > -2) continue;
    L.rocks.push({ x, z, w: 4 + r() * 8, h: 7 + r() * 20, rot: r() * 6.28 });
  }
  // Corva's streets are paved (the stairways have their own steps)
  L.paths = L.streets.slice(stairCount).map(st => ({ pts: st.map(p => ({ x: p.x, z: p.z })), width: 3.2, surface: "paving" }));
  L.squares = [];
  L.grid = grid;
  return L;
}

// --- villages ------------------------------------------------------------------------------------
// Each village of the island's features (features.js) is laid out as its kind of place grew:
//   harbour  lanes winding out from the square, one down to the harbour, crossed by an irregular
//            ring lane; a waterfront row, quay, mole and boats (addHarbour)
//   river    a main street running along the river through the square, cross lanes off it
//   hill     a compact knot of crooked lanes round the square, packed tight on the slope
// Houses line both sides of every lane, fronts to the lane, and each is tagged with its town's
// character (city.js picks kinds and colours from it). A small temple stands on the uphill side of
// the square. Lanes, squares and every house's footpath are kept in L.paths and L.squares, to be
// drawn (paths.js) and kept clear of trees.
const TOWN_OF = { coast: "harbour", river: "river", hill: "hill" };

// A lane that wanders: from (x, z) heading a, 4 m at a time, bending by `bend`, until it reaches the
// sea (if stopAtWater) or a river.
function wander(x, z, a, length, bend, seed, stopAtWater = true) {
  const pts = [];
  for (let d = 0; d < length; d += 4) {
    pts.push({ x, z });
    a += (fbm(x * 0.02 + seed, z * 0.02, 1) - 0.5) * bend;
    x += Math.cos(a) * 4; z += Math.sin(a) * 4;
    if (stopAtWater && inland(x, z) < 8) break;
    const rv = riverAt(x, z);                       // lanes stop at the river bank (the roads have the bridges)
    if (rv && rv.d < rv.w + 4) break;
  }
  return pts;
}

export function addVillages(L, villages, seed = 1717) {
  const r = rng(seed + 41);
  const grid = L.grid || new Grid();
  L.paths ||= []; L.squares ||= [];
  // can a house stand here? on land, not too steep, clear of rivers and the middle of roads
  const buildable = (x, z, w, d) => {
    if (!grid.free(x, z, d + 1.5, w + 1.5)) return false;
    if (inland(x, z) < 9 || heightAt(x, z) < 2.5 || slopeAt(x, z) > 0.8) return false;
    const rv = riverAt(x, z);
    if (rv && rv.d < rv.w + 7) return false;
    return roadDist(x, z) > 4.5;
  };
  let town = "corva";
  const addHouse = (x, z, frontX, frontZ, w, d) => {
    const y = heightAt(x, z), h = 3.2 + r() * 2.4;
    L.houses.push({ x, z, y, w, d, h, rot: -Math.atan2(frontZ - z, frontX - x), town });
    grid.take(x, z, d + 1.5, w + 1.5);
    if (r() < 0.22) L.chimneys.push({ x, y: y + h + 0.6, z });
  };
  L.villages = [];
  for (const v of villages) {
    town = TOWN_OF[v.kind || (v.coastal ? "coast" : "hill")];
    const R = v.r, before = L.houses.length;
    // the temple on the uphill side of the square, facing it
    const ex = heightAt(v.x + 10, v.z) - heightAt(v.x - 10, v.z), ez = heightAt(v.x, v.z + 10) - heightAt(v.x, v.z - 10);
    const upA = Math.atan2(ez, ex), tx = v.x + Math.cos(upA) * 28, tz = v.z + Math.sin(upA) * 28;
    L.temples.push({ x: tx, z: tz, y: heightAt(tx, tz), w: 9, d: 13, cols: [4, 6], rot: -(upA + Math.PI), scale: 0.62 });
    grid.take(tx, tz, 18, 18);
    grid.take(v.x, v.z, 24, 24);                                   // the square stays open
    L.squares.push({ x: v.x, z: v.z, r: 13, surface: town === "hill" ? "earth" : town === "harbour" ? "stone" : "paving" });

    const lanes = [];
    if (town === "harbour") {
      const n = 7, base = Math.atan2(v.harbour.dz, v.harbour.dx);
      for (let k = 0; k < n; k++) {
        const a = base + (k / n) * Math.PI * 2 + (k ? (r() - 0.5) * 0.5 : 0);
        lanes.push(wander(v.x + Math.cos(a) * 14, v.z + Math.sin(a) * 14, a, R * 1.05, 0.35, k));
      }
      // a ring lane, broken and irregular (arcs between some of the spokes, not a full circle)
      for (let k = 0; k < n; k++) {
        if (r() < 0.35) continue;
        const a0 = base + (k / n) * Math.PI * 2, a1 = a0 + (Math.PI * 2) / n, rr = R * (0.45 + r() * 0.3), pts = [];
        for (let t = 0; t <= 8; t++) {
          const a = a0 + ((a1 - a0) * t) / 8, q = rr * (1 + (fbm(Math.cos(a) * 3 + k, Math.sin(a) * 3, 2) - 0.5) * 0.4);
          const x = v.x + Math.cos(a) * q, z = v.z + Math.sin(a) * q;
          if (inland(x, z) > 8) pts.push({ x, z });
        }
        if (pts.length > 2) lanes.push(pts);
      }
    } else if (town === "river") {
      // which way the river runs here: along the contours of "distance from the river"
      const e = 12, dr = (x, z) => riverAt(x, z)?.d ?? 999;
      const gx = dr(v.x + e, v.z) - dr(v.x - e, v.z), gz = dr(v.x, v.z + e) - dr(v.x, v.z - e);
      const along = Math.atan2(gx, -gz);
      for (const dir of [0, Math.PI]) lanes.push(wander(v.x, v.z, along + dir, R * 1.3, 0.15, 3 + dir, false));
      const main = [...lanes[0].slice().reverse(), ...lanes[1]];
      lanes.length = 0;
      lanes.push(main);
      for (let k = 2; k < main.length - 2; k += 9) {                 // cross lanes off the main street
        const p0 = main[k], q = main[k + 1], a = Math.atan2(q.z - p0.z, q.x - p0.x);
        for (const side of [Math.PI / 2, -Math.PI / 2]) if (r() < 0.8) lanes.push(wander(p0.x, p0.z, a + side, R * (0.4 + r() * 0.3), 0.5, k, false));
      }
    } else {                                                          // hill: compact and crooked
      const n = 5;
      for (let k = 0; k < n; k++) {
        const a = (k / n) * Math.PI * 2 + r() * 0.8;
        const lane = wander(v.x + Math.cos(a) * 13, v.z + Math.sin(a) * 13, a, R * 0.85, 0.9, k * 7, false);
        lanes.push(lane);
        const mid = lane[Math.floor(lane.length / 2)];                // a short branch from its middle
        if (mid) lanes.push(wander(mid.x, mid.z, a + (r() < 0.5 ? 1.2 : -1.2), R * 0.35, 0.9, k * 7 + 3, false));
      }
    }
    // houses along both sides of each lane, fronts to the lane
    const gap = town === "hill" ? 0.38 : town === "river" ? 0.5 : 0.6;
    for (const pts of lanes) {
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i], dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz) || 1;
        for (const side of [1, -1]) {
          if (r() < gap) continue;                                    // gaps: gardens, yards
          const w = 4.5 + r() * 3.5, d = 4 + r() * 2.5, off = 2.8 + d / 2 + r() * 0.8;
          const x = b.x + (-dz / len) * side * off, z = b.z + (dx / len) * side * off;
          if (Math.hypot(x - v.x, z - v.z) > R * 1.3) continue;
          if (buildable(x, z, w, d)) addHouse(x, z, b.x, b.z, w, d);
        }
      }
      if (pts.length > 1) L.paths.push({ pts, width: town === "harbour" ? 2.6 : 2.8, surface: town === "harbour" ? "stone" : "earth" });
      if (pts.length > 4 && L.streets.length < 60) L.streets.push(pts.map(p => ({ x: p.x, y: heightAt(p.x, p.z) + 1.1, z: p.z })));
    }

    if (v.harbour) addHarbour(L, v, r, grid, buildable, addHouse);
    L.villages.push({ name: v.name, x: v.x, z: v.z, y: heightAt(v.x, v.z), kind: v.kind, town, houses: L.houses.length - before });
  }
  addFootpaths(L);
  return L;
}

// A footpath from every house's door to the nearest lane or street, if one is within ~45 m; houses
// out in the country (farms) get a track to the nearest road instead, if one is within ~350 m.
function addFootpaths(L) {
  const lanes = L.paths.slice();
  const cell = 50, cells = new Map();
  lanes.forEach((ln, li) => ln.pts.forEach((p, pi) => {
    if (pi === 0) return;
    const k = `${Math.floor(p.x / cell)},${Math.floor(p.z / cell)}`;
    (cells.get(k) || cells.set(k, []).get(k)).push([li, pi]);
  }));
  const nearestLane = (x, z) => {
    let best = null, bd = 45;
    const cx = Math.floor(x / cell), cz = Math.floor(z / cell);
    for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) for (const [li, pi] of cells.get(`${cx + i},${cz + j}`) || []) {
      const a = lanes[li].pts[pi - 1], b = lanes[li].pts[pi], dx = b.x - a.x, dz = b.z - a.z, L2 = dx * dx + dz * dz || 1;
      const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (z - a.z) * dz) / L2)), px = a.x + dx * t, pz = a.z + dz * t;
      const d = Math.hypot(px - x, pz - z);
      if (d < bd) { bd = d; best = { x: px, z: pz }; }
    }
    return best;
  };
  const roadPts = (getFeatures()?.roads || []).flatMap(rd => rd.pts);
  for (const h of L.houses) {
    const fx = Math.cos(h.rot), fz = -Math.sin(h.rot);                // the house's front
    const door = { x: h.x + fx * (h.d / 2 + 0.6), z: h.z + fz * (h.d / 2 + 0.6) };
    const to = nearestLane(door.x, door.z);
    if (to) {
      if (Math.hypot(to.x - door.x, to.z - door.z) > 1.2) L.paths.push({ pts: [door, to], width: 1.3, surface: "earth" });
      continue;
    }
    // a farm track to the nearest road, gently curved
    let best = null, bd = 350;
    for (const p of roadPts) { const d = Math.hypot(p.x - door.x, p.z - door.z); if (d < bd) { bd = d; best = p; } }
    if (!best) continue;
    const mid = { x: (door.x + best.x) / 2 + (best.z - door.z) * 0.15, z: (door.z + best.z) / 2 - (best.x - door.x) * 0.15 };
    L.paths.push({ pts: [door, mid, { x: best.x, z: best.z }], width: 1.8, surface: "earth" });
  }
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
  const quay = [];
  for (let t = -v.r; t <= v.r; t += 7 + r() * 3) {
    const qx = sx + along.x * t, qz = sz + along.z * t;
    // find the shore here, then step back inland
    let x = qx, z = qz;
    for (let k = 0; k < 40 && heightAt(x, z) < 1; k++) { x -= dx * 2; z -= dz * 2; }
    for (let k = 0; k < 40 && heightAt(x, z) > 1; k++) { x += dx * 2; z += dz * 2; }
    L.walls.push({ x: x + dx, z: z + dz, y: 0, len: 7.5, rot: Math.atan2(along.x, along.z), h: 1.3 });
    quay.push({ x: x - dx * 3, z: z - dz * 3 });                    // the quayside walk, just behind the wall
    const hx = x - dx * 13, hz = z - dz * 13, w = 5 + r() * 3, d = 4.5 + r() * 2;
    if (r() < 0.85 && buildable(hx, hz, w, d)) addHouse(hx, hz, x + dx * 10, z + dz * 10, w, d);
  }
  if (quay.length > 2) L.paths.push({ pts: quay, width: 4.5, surface: "stone" });
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
