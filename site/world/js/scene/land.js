// The ground: a grid mesh lifted to heightAt(), coloured by height and slope.
// Sand by the water, dry golden grass and olive-dark scrub on the hill, bare rock on steep ground
// and high up, all broken up with noise so it reads as painted, not flat.

import * as THREE from "../../vendor/three.module.min.js";
import { heightAt, slopeAt, fbm } from "../world/terrain.js";

const SAND = new THREE.Color("#c9a874"), GRASS = new THREE.Color("#8a7d47"), SCRUB = new THREE.Color("#4f5531"),
      ROCK = new THREE.Color("#8d7b69"), HIGH = new THREE.Color("#a49aa6");

export function makeLand(resolution, { minX = -900, maxX = 420, minZ = -800, maxZ = 800 } = {}) {
  const nx = resolution, nz = Math.round(resolution * (maxZ - minZ) / (maxX - minX));
  const pos = new Float32Array((nx + 1) * (nz + 1) * 3), col = new Float32Array(pos.length);
  const c = new THREE.Color();
  let i = 0;
  for (let iz = 0; iz <= nz; iz++) {
    for (let ix = 0; ix <= nx; ix++, i += 3) {
      // denser near the city: squeeze the grid toward x = -60, z = 0 with a gentle curve
      const u = ix / nx, v = iz / nz;
      const x = minX + (maxX - minX) * u, z = minZ + (maxZ - minZ) * v;
      const y = heightAt(x, z);
      pos[i] = x; pos[i + 1] = y; pos[i + 2] = z;
      const slope = slopeAt(x, z), n = fbm(x * 0.03, z * 0.03, 3);
      if (y < 2.2) c.copy(SAND);
      else {
        c.copy(GRASS).lerp(SCRUB, THREE.MathUtils.clamp(n * 1.6 - 0.35, 0, 1));
        c.lerp(ROCK, THREE.MathUtils.smoothstep(slope, 0.7, 1.4));
        c.lerp(HIGH, THREE.MathUtils.smoothstep(y, 140, 320));
        c.lerp(SAND, 1 - THREE.MathUtils.smoothstep(y, 2.2, 4.5));
      }
      c.multiplyScalar(0.88 + 0.24 * fbm(x * 0.15, z * 0.15, 2));   // brush-stroke variation
      col[i] = c.r; col[i + 1] = c.g; col[i + 2] = c.b;
    }
  }
  const index = [];
  for (let iz = 0; iz < nz; iz++) for (let ix = 0; ix < nx; ix++) {
    const a = iz * (nx + 1) + ix, b = a + 1, d = a + nx + 1, e = d + 1;
    index.push(a, d, b, b, d, e);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setIndex(index);
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true }));
  mesh.receiveShadow = true;
  return mesh;
}
