// Corva's buildings (and the villages'), built from layout data with the architecture kit
// (architecture.js): houses of six kinds in three sizes, stamped out as instances (one draw call per
// kind and size, however many houses); a Doric temple modelled whole for each temple; the
// stairway, and the quay walls and harbour moles.

import * as THREE from "../../vendor/three.module.min.js";
import { rng } from "../world/layout.js";
import { houseKit, HOUSE_KINDS, HOUSE_SIZES, templeGeometry, buildingMaterial } from "./architecture.js";

// Place a unit box (base at y = 0) with a transform.
const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
function place(mesh, i, x, y, z, rot, sx, sy, sz) {
  q.setFromAxisAngle(up, rot);
  m4.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(sx, sy, sz));
  mesh.setMatrixAt(i, m4);
}

// Which kind of house: set by the layout (villages) or picked here. Corva mixes all kinds; the
// tall merchants' houses and walled courtyards are rarer.
const WEIGHTS = { cube: 0.24, gable: 0.2, hip: 0.14, twostorey: 0.22, courtyard: 0.1, tower: 0.1 };
function pickKind(r) {
  let x = r();
  for (const k of HOUSE_KINDS) { x -= WEIGHTS[k]; if (x <= 0) return k; }
  return "cube";
}
// slight differences in the whitewash: white, cream, warm ochre, faded pink
const TINTS = [[1, 1, 1], [1, 0.975, 0.92], [1, 0.95, 0.84], [1, 0.95, 0.92], [0.98, 0.98, 0.97]].map(c => new THREE.Color(...c));

// options: { plaster: texture for the walls, detail: 0 (phones) or 1 }
export function makeCity(L, quality, seed = 1717, { plaster = null, detail = 1 } = {}) {
  const r = rng(seed + 1);
  const group = new THREE.Group();
  const lambert = c => new THREE.MeshLambertMaterial({ color: c });
  const material = buildingMaterial(plaster);

  // --- houses: sort them into kind x size, then one instanced mesh for each -------------------
  const kit = houseKit(detail);
  const buckets = {};
  for (const h of L.houses) {
    const kind = h.style || pickKind(r);
    const area = h.w * h.d, size = area < 28 ? 0 : area < 46 ? 1 : 2;
    const S = HOUSE_SIZES[size], scale = THREE.MathUtils.clamp(Math.sqrt(area / (S.w * S.d)), 0.85, 1.2);
    (buckets[`${kind}:${size}`] ||= []).push({ h, scale, tint: TINTS[Math.floor(r() * TINTS.length)] });
  }
  for (const [key, list] of Object.entries(buckets)) {
    const [kind, size] = key.split(":");
    const mesh = new THREE.InstancedMesh(kit[kind][size], material, list.length);
    list.forEach(({ h, scale, tint }, i) => {
      place(mesh, i, h.x, h.y, h.z, h.rot, scale, scale, scale);
      mesh.setColorAt(i, tint);
    });
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.computeBoundingSphere();
    group.add(mesh);
  }

  // --- temples ---------------------------------------------------------------------------------
  for (const t of L.temples) {
    const mesh = new THREE.Mesh(templeGeometry(t, detail), material);
    mesh.position.set(t.x, t.y, t.z);
    mesh.rotation.y = t.rot;
    mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh);
  }

  // --- stairway, quay walls, harbour moles -------------------------------------------------------
  const box = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
  const stairs = new THREE.InstancedMesh(box, lambert("#d9cbb2"), L.stairs.length);
  L.stairs.forEach((s, i) => place(stairs, i, s.x, s.y - 0.9, s.z, s.rot, 3.2, 1.2, 1.3));
  const walls = new THREE.InstancedMesh(box, lambert("#b5a387"), L.walls.length);
  L.walls.forEach((w, i) => place(walls, i, w.x, -3, w.z, w.rot, w.wide || 2.6, w.h + 3, w.len));
  stairs.receiveShadow = walls.receiveShadow = true;
  group.add(stairs, walls);

  return {
    group,
    // the materials, so AI textures can be laid on them (aiassets.js)
    materials: { houses: material, stairs: stairs.material, walls: walls.material },
    update(state) { material.userData.night.value = state.night; },   // windows glow as night falls
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
