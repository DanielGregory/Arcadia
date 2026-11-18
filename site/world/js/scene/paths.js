// Roads, lanes, quays, squares and footpaths, laid on the ground.
//
// Each path is a ribbon draped over the land: its centre line is resampled every couple of metres,
// and at each sample two points are set out to either side, each at the ground's own height there
// (plus a hand's breadth), so the ribbon follows the slope across as well as along. Squares are
// discs draped the same way. Everything goes into one mesh with a colour per vertex:
//   road    packed dusty earth, the island's roads (4.5 m)
//   earth   village lanes and footpaths, a little browner
//   paving  Corva's streets and the village squares, pale stone
//   stone   the harbour towns' lanes and quays, whitewashed-edged flagstones
// Its edges are darkened a little, as worn paths are, and the middle of the ribbon a little lighter.
// Where a path meets a river it doesn't dip into the water: it rides over it as a bridge deck, a
// little above the water, on stone piers at each bank.
// The mesh is drawn slightly "in front" of the ground (a depth bias) so it never flickers into it.

import * as THREE from "../../vendor/three.module.min.js";
import { heightAt } from "../world/terrain.js";
import { riverAt } from "../world/featuremap.js";

const SURFACE = {
  road: new THREE.Color("#b39a74"), earth: new THREE.Color("#a68c68"),
  paving: new THREE.Color("#bcae92"), stone: new THREE.Color("#c6b9a0"), bridge: new THREE.Color("#a99a80"),
};

// paths: [{ pts: [{x, z}], width, surface }]; squares: [{ x, z, r, surface }]
export function makePaths(paths, squares = []) {
  const pos = [], col = [], idx = [];
  const c = new THREE.Color(), lift = 0.18;
  // the ground's height, or over a river the bridge deck: 1.6 m above the water, ramping down to
  // the land over the last few metres of each bank
  const ground = (x, z) => {
    const h = Math.max(heightAt(x, z), 0.05) + lift, rv = riverAt(x, z);
    if (!rv || rv.d > rv.w + 8) return h;
    const deck = rv.h + 1.6, f = 1 - Math.min(1, Math.max(0, (rv.d - rv.w) / 8));
    return Math.max(h, h + (deck - h) * f);
  };
  const onBridge = (x, z) => { const rv = riverAt(x, z); return rv && rv.d < rv.w + 2; };

  for (const p of paths) {
    // resample the centre line every ~2 m (footpaths are short: keep at least their ends)
    const pts = [], step = p.width > 2 ? 2.5 : 1.5;
    for (let i = 0; i + 1 < p.pts.length; i++) {
      const a = p.pts[i], b = p.pts[i + 1], n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / step));
      for (let k = 0; k < n; k++) pts.push({ x: a.x + ((b.x - a.x) * k) / n, z: a.z + ((b.z - a.z) * k) / n });
    }
    pts.push(p.pts[p.pts.length - 1]);
    if (pts.length < 2) continue;
    const base = SURFACE[p.surface] || SURFACE.earth, half = p.width / 2, start = pos.length / 3;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
      let dx = b.x - a.x, dz = b.z - a.z;
      const len = Math.hypot(dx, dz) || 1;
      dx /= len; dz /= len;
      const q = pts[i];
      // three across: edge, middle, edge (the middle a little lighter: worn smooth)
      for (const [o, shade] of [[-1, 0.86], [0, 1.06], [1, 0.86]]) {
        const x = q.x - dz * half * o, z = q.z + dx * half * o;
        pos.push(x, ground(x, z), z);
        c.copy(onBridge(q.x, q.z) ? SURFACE.bridge : base).multiplyScalar(shade * (0.95 + ((i * 7919) % 13) / 130));
        col.push(c.r, c.g, c.b);
      }
      if (i + 1 < pts.length) {
        const k = start + i * 3;
        idx.push(k, k + 3, k + 1, k + 1, k + 3, k + 4, k + 1, k + 4, k + 2, k + 2, k + 4, k + 5);
      }
    }
  }
  for (const s of squares) {                                   // squares: draped discs
    const rings = 5, segs = 28, start = pos.length / 3, base = SURFACE[s.surface] || SURFACE.paving;
    pos.push(s.x, ground(s.x, s.z), s.z);
    col.push(base.r, base.g, base.b);
    for (let i = 1; i <= rings; i++) for (let j = 0; j < segs; j++) {
      const a = (j / segs) * Math.PI * 2, rr = (s.r * i) / rings, x = s.x + Math.cos(a) * rr, z = s.z + Math.sin(a) * rr;
      pos.push(x, ground(x, z), z);
      c.copy(base).multiplyScalar(i === rings ? 0.86 : 1 - ((i + j) % 2) * 0.04);   // flagstones, a darker rim
      col.push(c.r, c.g, c.b);
    }
    for (let j = 0; j < segs; j++) idx.push(start, start + 1 + ((j + 1) % segs), start + 1 + j);
    for (let i = 1; i < rings; i++) for (let j = 0; j < segs; j++) {
      const a = start + 1 + (i - 1) * segs + j, b = start + 1 + (i - 1) * segs + ((j + 1) % segs);
      idx.push(a, b, a + segs, b, b + segs, a + segs);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({
    vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -6,
  }));
  mesh.receiveShadow = true;
  group.add(mesh);
  // stone piers under the bridges: one at each bank where a path crosses a river
  const piers = [];
  for (const p of paths) {
    if (p.width < 2.5) continue;
    let was = false, last = null;                       // last: the river under the previous point
    for (let i = 0; i + 1 < p.pts.length; i++) {
      const a = p.pts[i], b = p.pts[i + 1], n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / 1.5));
      for (let k = 0; k <= n; k++) {
        const x = a.x + ((b.x - a.x) * k) / n, z = a.z + ((b.z - a.z) * k) / n, on = onBridge(x, z);
        const rv = riverAt(x, z) || last;
        if (on !== was && rv) piers.push({ x, z, top: rv.h + 1.5, rot: Math.atan2(b.x - a.x, b.z - a.z), w: p.width });
        was = on;
        if (rv) last = rv;
      }
    }
  }
  if (piers.length) {
    const pm = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), new THREE.MeshLambertMaterial({ color: "#9d8f78" }), piers.length);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
    piers.forEach((pr, i) => {
      m4.compose(new THREE.Vector3(pr.x, pr.top - 4, pr.z), q.setFromAxisAngle(up, pr.rot + Math.PI / 2), new THREE.Vector3(1.4, 4, pr.w + 0.8));
      pm.setMatrixAt(i, m4);
    });
    pm.castShadow = pm.receiveShadow = true;
    group.add(pm);
  }
  return group;
}
