// Make the island's villages, rivers and roads for a seed and save them, so the browser doesn't
// have to work them out on every visit (it takes ~1 s). Also draws a map to check them by eye.
//
//   node site/world/tools/make_features.mjs [seed] [map.ppm]
//
// Writes site/world/assets/island/features-<seed>.json. The browser loads that file when it
// exists for the seed being shown, and makes the features itself otherwise.

import { writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { generateFeatures } from "../js/world/features.js";
import { heightAt, BOUNDS } from "../js/world/terrain.js";

const seed = Number(process.argv[2]) || 1717;
const t0 = performance.now();
const f = generateFeatures(seed);
const ms = performance.now() - t0;
const out = fileURLToPath(new URL(`../assets/island/features-${seed}.json`, import.meta.url));
writeFileSync(out, JSON.stringify(f));
console.log(`features for seed ${seed} in ${ms.toFixed(0)} ms -> ${out}`);
console.log("villages:", f.villages.map(v => `${v.name} (${v.x}, ${v.z}) ${v.y} m`).join("; "));
console.log("rivers:", f.rivers.map(r => `${(r.pts.length * 30 / 1000).toFixed(1)} km${r.joins ? " (joins)" : ""}`).join(", "));
console.log("roads:", f.roads.map(r => `${r.from}-${r.to} ${r.pts.length} pts`).join(", "));

const map = process.argv[3];
if (map) {   // a hillshaded map with the features drawn on (heights include the carved valleys)
  const N = 700, B = BOUNDS, S = Math.max(B.maxX - B.minX, B.maxZ - B.minZ);
  const H = new Float32Array(N * N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) H[j * N + i] = heightAt(B.minX + (S * i) / N, B.minZ + (S * j) / N);
  const buf = Buffer.alloc(N * N * 3);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const h = H[j * N + i], k = (j * N + i) * 3;
    const hx = H[j * N + Math.min(N - 1, i + 1)] - h, hz = H[Math.min(N - 1, j + 1) * N + i] - h;
    const shade = Math.max(0.4, Math.min(1.3, 1 - (hx - hz) * 0.6 / (S / N)));
    let c = h < 0 ? [40, 80, Math.max(50, 110 + h * 4)] : h < 3 ? [210, 190, 140] : h < 150 ? [130, 145, 80] : h < 400 ? [100, 115, 65] : h < 700 ? [140, 120, 90] : [190, 185, 180];
    if (h >= 0) c = c.map(v => Math.min(255, v * shade));
    buf.set(c, k);
  }
  const px = (x, z) => [Math.round(((x - B.minX) / S) * N), Math.round(((z - B.minZ) / S) * N)];
  const dot = (x, z, col, r = 1) => { const [i, j] = px(x, z); for (let b = -r; b <= r; b++) for (let a = -r; a <= r; a++) { const ii = i + a, jj = j + b; if (ii >= 0 && jj >= 0 && ii < N && jj < N) buf.set(col, (jj * N + ii) * 3); } };
  const line = (pts, col) => { for (let i = 0; i + 1 < pts.length; i++) { const a = pts[i], b = pts[i + 1], n = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / 8); for (let t = 0; t <= n; t++) dot(a.x + (b.x - a.x) * t / n, a.z + (b.z - a.z) * t / n, col, 0); } };
  for (const r of f.rivers) line(r.pts, [60, 140, 230]);
  for (const r of f.roads) line(r.pts, [240, 220, 160]);
  for (const v of f.villages) dot(v.x, v.z, [230, 60, 40], 4);
  dot(-60, 0, [255, 255, 255], 4);
  writeFileSync(map, Buffer.concat([Buffer.from(`P6 ${N} ${N} 255\n`), buf]));
}
