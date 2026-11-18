// Corva's buildings, built from layout data with instanced meshes (one draw call per kind of
// thing, however many there are): white houses, terracotta roofs, windows that light up at night,
// columned temples with pediments, the stairway, and the quay wall and harbour mole.

import * as THREE from "../../vendor/three.module.min.js";
import { rng } from "../world/layout.js";

const WHITES = ["#f1e8d6", "#e9dec8", "#f4eee0", "#e2d4bc", "#ece2cf"].map(c => new THREE.Color(c));
const MARBLE = new THREE.Color("#efe6d3"), CELLA = new THREE.Color("#a8987e");

// Place a unit box (base at y = 0) with a transform.
const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
function place(mesh, i, x, y, z, rot, sx, sy, sz) {
  q.setFromAxisAngle(up, rot);
  m4.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(sx, sy, sz));
  mesh.setMatrixAt(i, m4);
}
// local (lx, lz) -> world, for a thing at (x, z) rotated by rot
function local(x, z, rot, lx, lz) {
  const c = Math.cos(rot), s = Math.sin(rot);
  return [x + lx * c + lz * s, z - lx * s + lz * c];
}

export function makeCity(L, quality, seed = 1717) {
  const r = rng(seed + 1);
  const group = new THREE.Group();
  const box = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
  const lambert = c => new THREE.MeshLambertMaterial({ color: c });

  // --- houses ---------------------------------------------------------------------------------
  const houses = new THREE.InstancedMesh(box, lambert("#ffffff"), L.houses.length);
  const roofed = L.houses.filter(() => r() < 0.3);
  const roofs = new THREE.InstancedMesh(new THREE.ConeGeometry(0.75, 1, 4).rotateY(Math.PI / 4).translate(0, 0.5, 0),
                                        lambert("#a65a3a"), roofed.length);
  const lit = [], dark = [];
  L.houses.forEach((h, i) => {
    place(houses, i, h.x, h.y - 2.5, h.z, h.rot, h.d, h.h + 2.5, h.w);
    houses.setColorAt(i, WHITES[Math.floor(r() * WHITES.length)]);
    // one or two windows on the sea-facing side
    const n = h.w > 6 ? 2 : 1;
    for (let k = 0; k < n; k++) {
      const [wx, wz] = local(h.x, h.z, h.rot, h.d / 2 + 0.03, (k - (n - 1) / 2) * h.w * 0.4);
      (r() < 0.5 ? lit : dark).push({ x: wx, y: h.y + h.h * (0.35 + r() * 0.25), z: wz, rot: h.rot });
    }
  });
  roofed.forEach((h, i) => place(roofs, i, h.x, h.y + h.h, h.z, h.rot, h.d * 1.45, 1.6, h.w * 1.45));
  // upper storeys, set back from the front; and a door on the sea side of every house
  const tops = L.houses.filter(h => h.upper);
  const uppers = new THREE.InstancedMesh(box, lambert("#ffffff"), tops.length);
  tops.forEach((h, i) => {
    const [ux, uz] = local(h.x, h.z, h.rot, -h.d * 0.18, h.upper.off);
    place(uppers, i, ux, h.y + h.h, uz, h.rot, h.upper.d, h.upper.h, h.upper.w);
    uppers.setColorAt(i, WHITES[Math.floor(r() * WHITES.length)]);
  });
  uppers.castShadow = uppers.receiveShadow = true;
  group.add(uppers);
  const doorGeo = new THREE.PlaneGeometry(1.1, 2.1).rotateY(Math.PI / 2).translate(0, 1.05, 0);
  const doors = new THREE.InstancedMesh(doorGeo, new THREE.MeshLambertMaterial({ color: "#4a3627" }), L.houses.length);
  L.houses.forEach((h, i) => {
    const [dx, dz] = local(h.x, h.z, h.rot, h.d / 2 + 0.04, (r() - 0.5) * h.w * 0.5);
    place(doors, i, dx, h.y - 0.05, dz, h.rot, 1, 1, 1);
  });
  group.add(doors);
  houses.castShadow = houses.receiveShadow = true;
  group.add(houses, roofs);

  const winGeo = new THREE.PlaneGeometry(0.75, 1.05).rotateY(Math.PI / 2);
  const winDark = new THREE.InstancedMesh(winGeo, new THREE.MeshBasicMaterial({ color: "#3b3027" }), dark.length);
  const winLit = new THREE.InstancedMesh(winGeo, new THREE.MeshBasicMaterial({ color: "#3b3027" }), lit.length);
  dark.forEach((w, i) => place(winDark, i, w.x, w.y, w.z, w.rot, 1, 1, 1));
  lit.forEach((w, i) => place(winLit, i, w.x, w.y, w.z, w.rot, 1, 1, 1));
  group.add(winDark, winLit);

  // --- temples --------------------------------------------------------------------------------
  const nCols = L.temples.reduce((n, t) => n + 2 * (t.cols[0] + t.cols[1]) - 4, 0);
  const cols = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.55, 0.66, 1, 10).translate(0, 0.5, 0),
                                       lambert(MARBLE), nCols);
  const blocks = new THREE.InstancedMesh(box, lambert(MARBLE), L.temples.length * 4);
  const tri = new THREE.Shape([new THREE.Vector2(-0.5, 0), new THREE.Vector2(0.5, 0), new THREE.Vector2(0, 1)]);
  const pedGeo = new THREE.ExtrudeGeometry(tri, { depth: 1, bevelEnabled: false }).translate(0, 0, -0.5).rotateY(Math.PI / 2);
  const peds = new THREE.InstancedMesh(pedGeo, lambert("#e8dcc6"), L.temples.length);
  let ci = 0, bi = 0;
  L.temples.forEach((t, ti) => {
    const S = t.scale, H = 7 * S, base = t.y + 1.6;
    // stepped podium, the inner hall, the beam on the columns
    place(blocks, bi++, t.x, t.y - 4, t.z, t.rot, t.d + 2.4, 5.6, t.w + 2.4);
    blocks.setColorAt(bi, CELLA);   // the inner hall, darker so the columns stand out against it
    place(blocks, bi++, t.x, base, t.z, t.rot, t.d * 0.5, H * 0.92, t.w * 0.4);
    place(blocks, bi++, t.x, base + H, t.z, t.rot, t.d + 0.8, 1.3 * S, t.w + 0.8);
    place(blocks, bi++, t.x, base + H + 1.3 * S, t.z, t.rot, t.d + 1.0, 0.35 * S, t.w + 1.0);
    place(peds, ti, t.x, base + H + 1.65 * S, t.z, t.rot, t.d + 1.0, 2.4 * S, t.w + 1.0);
    // columns round the edge: nShort across the front and back, nLong down the sides
    const [nShort, nLong] = t.cols, hx = t.d / 2, hz = t.w / 2;
    const ring = [];
    for (let i = 0; i < nShort; i++) { const lz = -hz + (2 * hz * i) / (nShort - 1); ring.push([hx, lz], [-hx, lz]); }
    for (let i = 1; i < nLong - 1; i++) { const lx = -hx + (2 * hx * i) / (nLong - 1); ring.push([lx, hz], [lx, -hz]); }
    for (const [lx, lz] of ring) {
      const [x, z] = local(t.x, t.z, t.rot, lx, lz);
      place(cols, ci++, x, base, z, t.rot, S, H, S);
    }
  });
  cols.count = ci;
  for (const m of [cols, blocks, peds]) { m.castShadow = m.receiveShadow = true; group.add(m); }

  // --- stairway, quay wall, harbour mole --------------------------------------------------------
  const stairs = new THREE.InstancedMesh(box, lambert("#d9cbb2"), L.stairs.length);
  L.stairs.forEach((s, i) => place(stairs, i, s.x, s.y - 0.9, s.z, s.rot, 3.2, 1.2, 1.3));
  const walls = new THREE.InstancedMesh(box, lambert("#b5a387"), L.walls.length);
  L.walls.forEach((w, i) => place(walls, i, w.x, -3, w.z, w.rot, 2.6, w.h + 3, w.len));
  stairs.receiveShadow = walls.receiveShadow = true;
  group.add(stairs, walls);

  const litColor = new THREE.Color("#ffb45c"), darkColor = new THREE.Color("#3b3027");
  return {
    group,
    // the materials, so AI textures can be laid on them (aiassets.js)
    materials: { houses: houses.material, uppers: uppers.material, roofs: roofs.material, blocks: blocks.material,
                 stairs: stairs.material, walls: walls.material },
    update(state) {  // windows glow as night falls
      winLit.material.color.copy(darkColor).lerp(litColor, state.night).multiplyScalar(1 + state.night * 1.8);
    },
  };
}

export function makeTrees(L) {
  const group = new THREE.Group();
  const cyp = L.trees.filter(t => t.kind === "cypress"), oli = L.trees.filter(t => t.kind === "olive");
  const cypress = new THREE.InstancedMesh(new THREE.ConeGeometry(1, 1, 7).translate(0, 0.5, 0),
                                          new THREE.MeshLambertMaterial({ color: "#ffffff" }), cyp.length);
  const olive = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1),
                                        new THREE.MeshLambertMaterial({ color: "#ffffff" }), oli.length);
  const c = new THREE.Color(), r = rng(99);
  cyp.forEach((t, i) => {
    place(cypress, i, t.x, t.y - 0.4, t.z, 0, 1.0 * t.s, 9 * t.s, 1.0 * t.s);
    cypress.setColorAt(i, c.set("#2c3a20").multiplyScalar(0.8 + r() * 0.4));
  });
  oli.forEach((t, i) => {
    place(olive, i, t.x, t.y + 1.3 * t.s, t.z, r() * 6, 1.7 * t.s, 1.3 * t.s, 1.7 * t.s);
    olive.setColorAt(i, c.set("#5e6a44").lerp(new THREE.Color("#7d7a52"), r() * 0.6).multiplyScalar(0.85 + r() * 0.3));
  });
  cypress.castShadow = olive.castShadow = true;
  group.add(cypress, olive);
  return group;
}
