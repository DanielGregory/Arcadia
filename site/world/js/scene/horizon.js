// Other islands, far out at sea: shapes on the horizon, 12 to 30 km away.
//
// Each is a low mesh in rings round its own centre: a wobbly coastline (noise read round a circle,
// so it closes on itself) and a hump of hills, higher toward the middle. They are not part of
// heightAt(): you can't fly to them yet, they are there so the sea has a far shore. At that
// distance the painter's aerial perspective turns them into soft blue-violet silhouettes, one
// layer behind another; one sits near the line of the sunset, so at golden hour it stands dark
// against the glow.

import * as THREE from "../../vendor/three.module.min.js";
import { fbm } from "../world/terrain.js";

// x, z: centre (metres); r: radius; h: highest point; seed: its own noise
const ISLANDS = [
  { x: 15000, z: -24000, r: 3400, h: 620, seed: 1 },     // near the sunset, to the north-north-west
  { x: 4000, z: -29000, r: 2600, h: 420, seed: 2 },      // beyond it, a lower one
  { x: -9000, z: -21000, r: 2200, h: 520, seed: 3 },     // north
  { x: 24000, z: 2000, r: 1600, h: 300, seed: 4 },       // a small one out west
  { x: 17000, z: 19000, r: 3800, h: 780, seed: 5 },      // south-west, large
  { x: -6000, z: 23000, r: 2400, h: 460, seed: 6 },      // south
  { x: -24000, z: 6000, r: 4200, h: 900, seed: 7 },      // east, behind the island: the mainland's edge
];

function islandMesh({ x, z, r, h, seed }) {
  const rings = 14, segs = 64, pos = [], col = [], idx = [];
  const base = new THREE.Color("#55604a"), rock = new THREE.Color("#7a7068"), c = new THREE.Color();
  const coast = a => r * (0.75 + 0.5 * fbm(Math.cos(a) * 1.6 + seed * 7.1, Math.sin(a) * 1.6 - seed * 3.3, 3));
  pos.push(x, h, z);
  col.push(rock.r, rock.g, rock.b);
  for (let i = 1; i <= rings; i++) {
    const f = i / rings;                                     // 0 middle .. 1 shore
    for (let j = 0; j < segs; j++) {
      const a = (j / segs) * Math.PI * 2, R = coast(a) * f;
      const px = x + Math.cos(a) * R, pz = z + Math.sin(a) * R;
      const bump = 0.65 + 0.7 * fbm(px * 0.0006 + seed, pz * 0.0006 - seed, 3);
      const y = i === rings ? -30 : h * Math.pow(1 - f * f, 1.4) * bump;   // the last ring dips under the sea
      pos.push(px, y, pz);
      c.copy(base).lerp(rock, Math.min(1, y / h));
      col.push(c.r, c.g, c.b);
    }
  }
  for (let j = 0; j < segs; j++) idx.push(0, 1 + ((j + 1) % segs), 1 + j);   // the cap
  for (let i = 1; i < rings; i++) for (let j = 0; j < segs; j++) {
    const a = 1 + (i - 1) * segs + j, b = 1 + (i - 1) * segs + ((j + 1) % segs), d = a + segs, e = b + segs;
    idx.push(a, b, d, b, e, d);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

export function makeDistantIslands() {
  const group = new THREE.Group();
  // no scene fog on these (at 20 km it would wash them out entirely): the painter's aerial
  // perspective, which knows the real distance, does the fading instead
  const material = new THREE.MeshLambertMaterial({ vertexColors: true, fog: false });
  for (const isl of ISLANDS) {
    const m = new THREE.Mesh(islandMesh(isl), material);
    m.matrixAutoUpdate = false;
    group.add(m);
  }
  return group;
}
