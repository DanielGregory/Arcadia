// The island's ground, in tiles, with more detail near the camera and less far away.
//
// The island (about 10 x 13 km with its shallows) is cut into square tiles. Each frame, every tile
// works out how far it is from the camera and picks a level of detail: the nearest get the full
// grid (one point every 5 m or so on high quality), each step further away halves it. A tile
// whose level changes is rebuilt in a background worker and swapped in when ready, so flying
// doesn't stutter; until then it keeps its old mesh. Tiles that are all sea are never built (the
// sea plane covers them).
//
// Every tile shares one material, so the hillside detail texture and the lighting apply to the
// whole island at once.

import * as THREE from "../../vendor/three.module.min.js";
import { BOUNDS, heightAt } from "../world/terrain.js";
import { buildTile, tileIndex, shoreBytes } from "../world/tilework.js";

export class Terrain {
  // finest: grid points per tile edge at the finest level; size: tile size in metres
  constructor({ finest = 96, size = 640, levels = 4 } = {}) {
    this.size = size;
    this.finest = finest;
    this.levels = levels;                           // finest, /2, /4, /8 ...
    this.group = new THREE.Group();
    this.material = new THREE.MeshLambertMaterial({ vertexColors: true });
    this.indices = new Map();                       // res -> shared index buffer
    this.tiles = [];
    this.pending = 0;
    const nx = Math.ceil((BOUNDS.maxX - BOUNDS.minX) / size), nz = Math.ceil((BOUNDS.maxZ - BOUNDS.minZ) / size);
    for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
      const x0 = BOUNDS.minX + i * size, z0 = BOUNDS.minZ + j * size;
      // skip tiles that are all open sea: sample them coarsely and keep any that reach near the surface
      let top = -Infinity;
      for (let b = 0; b <= 8; b++) for (let a = 0; a <= 8; a++) top = Math.max(top, heightAt(x0 + (a * size) / 8, z0 + (b * size) / 8));
      if (top < -1.5) continue;
      this.tiles.push({ id: this.tiles.length, x0, z0, cx: x0 + size / 2, cz: z0 + size / 2, top,
                        mesh: null, level: -1, want: -1, busy: false });
    }
    // Workers: as many as the device has cores to spare (at least one). If module workers aren't
    // supported, tiles are built on the main thread instead.
    this.workers = [];
    try {
      const n = Math.max(1, Math.min(3, (navigator.hardwareConcurrency || 2) - 1));
      for (let k = 0; k < n; k++) {
        const w = new Worker(new URL("../world/tileworker.js", import.meta.url), { type: "module" });
        w.onmessage = e => this.receive(e.data);
        w.onerror = () => {                            // fall back to the main thread
          this.workers = [];
          this.pending = 0;
          for (const t of this.tiles) t.busy = false;
        };
        this.workers.push(w);
      }
    } catch { this.workers = []; }
    this.nextWorker = 0;
  }

  // Detail level for a tile, from the camera's distance to it (0 = finest).
  // scale > 1 counts the tile as that much nearer (used to make coarsening a little reluctant).
  levelFor(t, cam, scale = 1) {
    const dx = Math.max(Math.abs(cam.x - t.cx) - this.size / 2, 0), dz = Math.max(Math.abs(cam.z - t.cz) - this.size / 2, 0);
    const dy = Math.max(0, cam.y - Math.max(t.top, 0));
    const d = Math.hypot(dx, dz, dy * 0.8) / scale;
    // each level covers twice the distance of the one before: < 0.9 tile, < 1.8, < 3.6 ...
    const l = Math.floor(Math.log2(Math.max(1, d / (this.size * 0.9))) + (d > this.size * 0.9 ? 1 : 0));
    return Math.min(this.levels - 1, l);
  }

  resFor(level) { return Math.max(8, this.finest >> level); }

  // Ask for the tiles that need a new level. sync = true builds everything right now (startup and
  // screenshots); otherwise at most a few requests are in flight at once, nearest first.
  update(cam, { sync = false } = {}) {
    const todo = [];
    for (const t of this.tiles) {
      let want = this.levelFor(t, cam);
      // a little reluctance to coarsen (15% further), so a tile on a boundary doesn't flip back and forth
      if (t.level >= 0 && want === t.level + 1 && this.levelFor(t, cam, 1.15) === t.level) want = t.level;
      t.want = want;
      if (want !== t.level && !t.busy) todo.push(t);
    }
    todo.sort((a, b) => a.want - b.want);           // finest (nearest) first
    if (sync || this.workers.length === 0) {
      const budget = sync ? Infinity : 6;           // ms of main-thread work per frame without workers
      const t0 = performance.now();
      for (const t of todo) {
        const res = this.resFor(t.want);
        this.receive({ id: t.id, res, ...buildTile(t.x0, t.z0, this.size, res) }, t.want);
        if (performance.now() - t0 > budget) break;
      }
      return;
    }
    for (const t of todo) {
      if (this.pending >= this.workers.length * 2) break;
      t.busy = true;
      t.asked = t.want;
      this.pending++;
      const res = this.resFor(t.want);
      this.workers[this.nextWorker++ % this.workers.length].postMessage({ id: t.id, x0: t.x0, z0: t.z0, size: this.size, res });
    }
  }

  receive(m, level = null) {
    const t = this.tiles[m.id];
    if (level === null) { this.pending--; t.busy = false; level = t.asked; }
    let index = this.indices.get(m.res);
    if (!index) this.indices.set(m.res, index = new THREE.BufferAttribute(tileIndex(m.res), 1));
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3));
    g.setAttribute("normal", new THREE.BufferAttribute(m.nor, 3, true));
    g.setAttribute("color", new THREE.BufferAttribute(m.col, 3, true));
    g.setAttribute("uv", new THREE.BufferAttribute(m.uv, 2));
    g.setIndex(index);
    g.boundingBox = new THREE.Box3(new THREE.Vector3(t.x0, m.minY, t.z0), new THREE.Vector3(t.x0 + this.size, m.maxY, t.z0 + this.size));
    g.boundingSphere = g.boundingBox.getBoundingSphere(new THREE.Sphere());
    if (t.mesh) { this.group.remove(t.mesh); t.mesh.geometry.dispose(); }
    t.mesh = new THREE.Mesh(g, this.material);
    t.mesh.receiveShadow = true;
    t.mesh.matrixAutoUpdate = false;
    this.group.add(t.mesh);
    t.level = level;
  }

  // How many tiles still want a different level (0 = all settled), for tests and screenshots.
  get unsettled() { return this.tiles.filter(t => t.want !== t.level).length + this.pending; }

  // The island-wide map of water depth near every coast, for the sea's shallows and foam.
  // Resolves with { data, rect, nx, nz } (worker if available).
  shoreMap(nx = 640, nz = 768) {
    const rect = { x: BOUNDS.minX, z: BOUNDS.minZ, w: BOUNDS.maxX - BOUNDS.minX, d: BOUNDS.maxZ - BOUNDS.minZ };
    if (!this.workers.length) return Promise.resolve({ data: shoreBytes(rect, nx, nz), rect, nx, nz });
    return new Promise(resolve => {
      const w = new Worker(new URL("../world/tileworker.js", import.meta.url), { type: "module" });
      w.onmessage = e => { resolve({ data: e.data.data, rect, nx, nz }); w.terminate(); };
      w.onerror = () => resolve({ data: shoreBytes(rect, nx, nz), rect, nx, nz });
      w.postMessage({ kind: "shore", rect, nx, nz });
    });
  }
}
