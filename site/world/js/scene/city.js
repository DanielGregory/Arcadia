// Corva's buildings (and the villages'), built from layout data with the architecture kit
// (architecture.js): houses of eight kinds in three sizes, coloured by their town, stamped out as instances (one draw call per
// kind and size, however many houses); a Doric temple modelled whole for each temple; the
// stairway, and the quay walls and harbour moles.

import * as THREE from "../../vendor/three.module.min.js";
import { rng } from "../world/layout.js";
import { houseKit, HOUSE_SIZES, templeGeometry, buildingMaterial } from "./architecture.js";

// Place a unit box (base at y = 0) with a transform.
const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
function place(mesh, i, x, y, z, rot, sx, sy, sz) {
  q.setFromAxisAngle(up, rot);
  m4.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(sx, sy, sz));
  mesh.setMatrixAt(i, m4);
}

// Each town has its own character (a house's `town` comes from the layout):
//   corva    the capital: every kind, rich houses with towers and balconies, ochre and pink washes
//   harbour  the fishing towns: whitewashed, flat-roofed Cycladic cubes, blue and green shutters
//   river    the valley villages: tiled gables and hips, warm ochre and cream walls, green shutters
//   hill     the mountain village: stone-built, weathered brown-grey roofs, plain wooden shutters
// kinds: how often each kind of house appears; walls / trims / roofs: colours to pick from.
const C3 = hex => new THREE.Color(hex);
const TOWNS = {
  corva: {
    kinds: { cube: 0.16, gable: 0.15, hip: 0.12, twostorey: 0.18, courtyard: 0.1, tower: 0.1, lshape: 0.11, stair: 0.08 },
    walls: ["#f3ede0", "#efe4cc", "#ecd6ad", "#ecd2c0", "#f1e3c4", "#e9e2d6"], trims: ["#3f6f8f", "#4f7254", "#7a3b2e", "#5a3f2a", "#2f5f6f"],
    roofs: ["#b0603d", "#a8573a", "#bf7350", "#9c5034"],
  },
  harbour: {
    kinds: { cube: 0.4, stair: 0.2, courtyard: 0.14, twostorey: 0.1, gable: 0.08, lshape: 0.08 },
    walls: ["#f6f3ec", "#f4f1ea", "#f2efe8", "#eef0ef", "#f1ebdc"], trims: ["#2f6fa0", "#3a86a8", "#2f5f8f", "#4f8a6a", "#a83a2e"],
    roofs: ["#b0603d", "#a8573a"],
  },
  river: {
    kinds: { gable: 0.3, hip: 0.18, twostorey: 0.18, lshape: 0.16, courtyard: 0.12, cube: 0.06 },
    walls: ["#e8cf9e", "#ecdcb8", "#e6c79a", "#efe2c6", "#e2c6a8"], trims: ["#4f7254", "#5f7a3a", "#5a3f2a", "#7a3b2e"],
    roofs: ["#b0603d", "#9c5034", "#a86a48", "#c07a52"],
  },
  hill: {
    kinds: { gable: 0.28, hip: 0.22, courtyard: 0.18, lshape: 0.14, tower: 0.08, cube: 0.1 },
    walls: ["#b9ab94", "#a99c88", "#c2b49c", "#b0a28c", "#9f937f"], trims: ["#5a3f2a", "#6b4e35", "#4a3a2c"],
    roofs: ["#8a6a58", "#7d6a5e", "#94735c", "#6f6258"],
  },
};
for (const t of Object.values(TOWNS)) for (const k of ["walls", "trims", "roofs"]) t[k] = t[k].map(C3);

function pickKind(r, town) {
  let x = r();
  for (const [k, w] of Object.entries(town.kinds)) { x -= w; if (x <= 0) return k; }
  return "cube";
}
const pickOf = (r, list) => list[Math.floor(r() * list.length)];

// options: { plaster: texture for the walls, detail: 0 (phones) or 1 }
export function makeCity(L, quality, seed = 1717, { plaster = null, detail = 1 } = {}) {
  const r = rng(seed + 1);
  const group = new THREE.Group();
  const lambert = c => new THREE.MeshLambertMaterial({ color: c });
  const material = buildingMaterial(plaster);                        // temples
  const houseMat = buildingMaterial(plaster, { instanced: true });   // houses, with their own colours

  // --- houses: sort them into kind x size, then one instanced mesh for each -------------------
  // Each house keeps its own proportions (a little wider or deeper, taller or lower than the
  // model), a slight turn off the line, and its town's colours for walls, shutters and roof.
  const kit = houseKit(detail);
  const buckets = {};
  for (const h of L.houses) {
    const town = TOWNS[h.town || "corva"];
    const kind = h.style && kit[h.style] && (!h.town || town.kinds[h.style]) ? h.style : pickKind(r, town);
    const area = h.w * h.d, size = area < 28 ? 0 : area < 46 ? 1 : 2;
    const S = HOUSE_SIZES[size], base = THREE.MathUtils.clamp(Math.sqrt(area / (S.w * S.d)), 0.85, 1.2);
    // a weathered house now and then: its colours a little darker
    const age = r() < 0.2 ? 0.86 + r() * 0.08 : 1;
    (buckets[`${kind}:${size}`] ||= []).push({
      h, sx: base * (0.88 + r() * 0.26), sy: base * (0.9 + r() * 0.25), sz: base * (0.88 + r() * 0.26), turn: (r() - 0.5) * 0.12,
      wall: pickOf(r, town.walls).clone().multiplyScalar(age), trim: pickOf(r, town.trims), roof: pickOf(r, town.roofs).clone().multiplyScalar(0.92 + r() * 0.12),
    });
  }
  for (const [key, list] of Object.entries(buckets)) {
    const [kind, size] = key.split(":");
    const geo = kit[kind][size].clone();
    const iWall = new Float32Array(list.length * 3), iTrim = new Float32Array(list.length * 3), iRoof = new Float32Array(list.length * 3);
    list.forEach((b, i) => { b.wall.toArray(iWall, i * 3); b.trim.toArray(iTrim, i * 3); b.roof.toArray(iRoof, i * 3); });
    geo.setAttribute("iWall", new THREE.InstancedBufferAttribute(iWall, 3));
    geo.setAttribute("iTrim", new THREE.InstancedBufferAttribute(iTrim, 3));
    geo.setAttribute("iRoof", new THREE.InstancedBufferAttribute(iRoof, 3));
    const mesh = new THREE.InstancedMesh(geo, houseMat, list.length);
    list.forEach(({ h, sx, sy, sz, turn }, i) => place(mesh, i, h.x, h.y, h.z, h.rot + turn, sx, sy, sz));
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
    materials: { houses: houseMat, temples: material, stairs: stairs.material, walls: walls.material },
    update(state) { material.userData.night.value = houseMat.userData.night.value = state.night; },   // windows glow as night falls
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
