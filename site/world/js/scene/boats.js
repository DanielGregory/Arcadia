// Boats, modelled from their lines: a hull is "lofted" through a row of cross-sections from stern to
// bow (each a rounded U, deepest and widest amidships, narrowing to the posts), with the sheer (the
// line of the top edge) rising toward both ends, as ancient ships' did.
//
//   merchant  a round-bellied trader with one mast and a big square sail with stripes
//   galley    long and narrow, a bronze ram at the bow, the stern curling up, a painted eye, a row
//             of oars each side and a furled sail
//   fishing   a small bright caique with a short mast and a little triangular sail
//
// Each kind is built once and shared by every boat of that kind (hull and fittings merged into one
// mesh; the sail separate, so it can be seen from both sides).

import * as THREE from "../../vendor/three.module.min.js";
import { mergeGeometries } from "../../vendor/addons/utils/BufferGeometryUtils.js";
import { PALETTE } from "./architecture.js";

const C = hex => new THREE.Color(hex);

function colored(geo, color) {
  const g = geo.index ? geo.toNonIndexed() : geo;
  g.deleteAttribute("uv");
  if (!g.attributes.normal) g.computeVertexNormals();
  const n = g.attributes.position.count, col = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) col.set([color.r, color.g, color.b], i * 3);
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  return g;
}

// The hull: length L (along z, bow at +z), beam B, depth D, sheer rise at the ends; colours by
// height: the bottom, a painted band below the rail, the rail itself.
function hull({ L, B, D, sheer, fullness, bottom, band, rail }) {
  const sections = 24, around = 10, pos = [], col = [], idx = [];
  const cb = new THREE.Color(), cBottom = C(bottom), cBand = C(band), cRail = C(rail);
  for (let i = 0; i <= sections; i++) {
    const u = i / sections, zz = (u - 0.5) * L, e = Math.abs(u - 0.5) * 2;       // e: 0 amidships .. 1 at the posts
    const half = (B / 2) * Math.pow(Math.max(0, 1 - Math.pow(e, fullness)), 0.55);
    const top = D * 0.35 + sheer * e * e, keel = -D * 0.65 * (1 - 0.35 * e * e);
    for (let j = 0; j <= around; j++) {
      // round the section from one rail (a = 0) under the keel to the other (a = pi)
      const a = (j / around) * Math.PI, down = Math.pow(Math.sin(a), 0.7);
      const y = top - (top - keel) * down;
      pos.push(Math.cos(a) * half, y, zz);
      const f = (y - keel) / (top - keel);                                     // 0 at the keel .. 1 at the rail
      cb.copy(f > 0.9 ? cRail : f > 0.7 ? cBand : cBottom);
      col.push(cb.r, cb.g, cb.b);
    }
  }
  for (let i = 0; i < sections; i++) for (let j = 0; j < around; j++) {
    const a = i * (around + 1) + j, b = a + 1, c = a + around + 1, d = c + 1;
    idx.push(a, c, b, b, c, d);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g.toNonIndexed();
}

// A square sail hanging from a yard across the ship (as ancient sails did), bellied forward with
// vertical stripes; or a small triangular one set fore and aft (along the hull).
function sail({ w, h, stripes, a, b, triangle = false }) {
  const g = triangle ? new THREE.BufferGeometry() : new THREE.PlaneGeometry(w, h, 8, 4);
  if (triangle) {
    g.setAttribute("position", new THREE.Float32BufferAttribute([0, h / 2, 0, 0, -h / 2, 0, w, -h / 2, 0].map((v, i) => (i % 3 === 0 ? v - w * 0.1 : v)), 3));
    g.computeVertexNormals();
  }
  const p = g.attributes.position, col = new Float32Array(p.count * 3), ca = C(a), cb = C(b);
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i);
    if (!triangle) p.setZ(i, Math.cos((x / w) * Math.PI) * w * 0.12 * (0.6 + 0.4 * (0.5 - y / h)));   // the belly
    const c = stripes && Math.floor(((x / w) + 0.5) * stripes) % 2 ? cb : ca;
    col.set([c.r, c.g, c.b], i * 3);
  }
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.computeVertexNormals();
  return triangle ? g.rotateY(Math.PI / 2) : g;
}

export function boatKinds() {
  const mastCol = C("#4e3524");
  const kinds = {};
  // merchant
  {
    const L = 17, B = 5.2, D = 2.6, parts = [hull({ L, B, D, sheer: 1.6, fullness: 2.2, bottom: "#4a3426", band: "#7a3b2e", rail: "#a07a52" })];
    parts.push(colored(new THREE.BoxGeometry(B * 0.85, 0.15, L * 0.75).translate(0, D * 0.3, 0), C("#8a6a48")));      // deck
    parts.push(colored(new THREE.CylinderGeometry(0.24, 0.32, 11, 6).translate(0, D * 0.3 + 5.5, 1), mastCol));        // mast
    parts.push(colored(new THREE.CylinderGeometry(0.14, 0.14, 9.5, 5).rotateX(Math.PI / 2).rotateY(Math.PI / 2).translate(0, D * 0.3 + 9.9, 1), mastCol));   // yard
    parts.push(colored(new THREE.BoxGeometry(1.6, 1.2, 2.2).translate(0, D * 0.3 + 0.6, -L * 0.36), C("#8a6a48")));   // deckhouse aft
    parts.push(colored(new THREE.TorusGeometry(0.9, 0.18, 5, 10, Math.PI).rotateY(Math.PI / 2).translate(0, D * 0.35 + 1.6, -L * 0.5 + 0.3), C("#4a3426")));   // curled stern post
    kinds.merchant = { body: mergeGeometries(parts), sail: sail({ w: 9, h: 6.5, stripes: 6, a: "#ece0c4", b: "#b2694a" }), sailAt: [0.35, D * 0.3 + 6.6, 1], length: L };
  }
  // galley
  {
    const L = 32, B = 4.2, D = 2.2, parts = [hull({ L, B, D, sheer: 2.2, fullness: 3.2, bottom: "#2e2a26", band: "#2f4a62", rail: "#9a7448" })];
    parts.push(colored(new THREE.BoxGeometry(B * 0.7, 0.14, L * 0.8).translate(0, D * 0.32, 0), C("#7a5a3c")));
    parts.push(colored(new THREE.ConeGeometry(0.45, 2.4, 6).rotateX(Math.PI / 2).translate(0, -D * 0.45, L / 2 + 1.0), C("#9a7a3a")));   // bronze ram
    parts.push(colored(new THREE.TorusGeometry(1.4, 0.22, 5, 12, Math.PI * 1.2).rotateY(Math.PI / 2).translate(0, D * 0.35 + 2.4, -L / 2 + 0.4), C("#2e2a26")));   // curling stern
    for (const s of [1, -1]) {                                                                                        // the painted eye
      parts.push(colored(new THREE.CircleGeometry(0.4, 10).rotateY(s * Math.PI / 2).translate(s * B * 0.3, D * 0.05, L * 0.42), C("#f0e8d8")));
      parts.push(colored(new THREE.CircleGeometry(0.18, 8).rotateY(s * Math.PI / 2).translate(s * (B * 0.3 + 0.01), D * 0.05, L * 0.42), C("#1a1612")));
    }
    // oars: a row each side, angled down to the water
    const oar = new THREE.CylinderGeometry(0.05, 0.05, 6, 4).rotateZ(Math.PI / 2 - 0.45);
    for (let k = 0; k < 16; k++) for (const s of [1, -1]) {
      const g = oar.clone();
      if (s < 0) g.scale(-1, 1, 1);
      parts.push(colored(g.translate(s * (B / 2 + 2.6), D * 0.05 - 1.1, -L * 0.33 + (k * L * 0.62) / 15), C("#8a6a48")));
    }
    parts.push(colored(new THREE.CylinderGeometry(0.24, 0.3, 9, 6).translate(0, D * 0.32 + 4.5, 2), mastCol));
    parts.push(colored(new THREE.CylinderGeometry(0.42, 0.42, 7.5, 6).rotateZ(Math.PI / 2).translate(0, D * 0.32 + 8.6, 2), C("#d8ccb0")));   // furled sail on the yard
    kinds.galley = { body: mergeGeometries(parts), sail: null, length: L };
  }
  // fishing caique
  {
    const L = 7.5, B = 2.5, D = 1.3, parts = [hull({ L, B, D, sheer: 0.7, fullness: 2.0, bottom: "#2f5a7a", band: "#f0e8d8", rail: "#b84a32" })];
    parts.push(colored(new THREE.BoxGeometry(B * 0.7, 0.08, L * 0.7).translate(0, D * 0.25, 0), C("#9a7a58")));
    parts.push(colored(new THREE.CylinderGeometry(0.11, 0.13, 4.5, 5).translate(0, D * 0.25 + 2.25, 0.8), mastCol));
    kinds.fishing = { body: mergeGeometries(parts), sail: sail({ w: 2.8, h: 3.6, stripes: 0, a: "#f0e6d0", b: "#f0e6d0", triangle: true }), sailAt: [0, D * 0.25 + 2.4, 0.8], length: L };
  }
  return kinds;
}
