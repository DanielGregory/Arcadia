// What moves: ships rocking at anchor, smoke from chimneys, lanterns carried along the streets at
// dusk and night, and clouds drifting over the bay.
//
// Stage 3 hook: lanterns follow `layout.streets`; when people come from the world tables, each
// lantern becomes a person walking a route (the same Lanterns class, fed their paths).

import * as THREE from "../../vendor/three.module.min.js";
import { rng } from "../world/layout.js";

// A soft round glow drawn on a canvas, used for lanterns, smoke and clouds.
function glowTexture(size = 64, stops = [[0, "rgba(255,255,255,1)"], [1, "rgba(255,255,255,0)"]]) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, col] of stops) grad.addColorStop(o, col);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// --- ships --------------------------------------------------------------------------------------
function hullGeometry() {
  const g = new THREE.BoxGeometry(2.4, 1.3, 9, 2, 2, 8);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i), e = Math.abs(z) / 4.5;
    p.setX(i, x * (1 - 0.85 * e * e) * (y < 0 ? 0.55 : 1));   // pointed bow and stern, narrow keel
    p.setY(i, y + 0.7 * e * e);                                // the sheer: ends rise
  }
  g.computeVertexNormals();
  return g;
}

export function makeShips(L, makeAiShip = null) {
  const group = new THREE.Group();
  const hull = hullGeometry(), wood = new THREE.MeshLambertMaterial({ color: "#5b3d27" });
  const mast = new THREE.CylinderGeometry(0.12, 0.15, 10, 6).translate(0, 5, 0);
  const sailGeo = new THREE.PlaneGeometry(6.5, 5, 6, 1);
  const sp = sailGeo.attributes.position;
  for (let i = 0; i < sp.count; i++) sp.setZ(i, Math.cos((sp.getX(i) / 6.5) * Math.PI) * 0.8);   // billowing
  sailGeo.rotateY(Math.PI / 2).translate(0.4, 6.2, 0);
  const sailMat = new THREE.MeshLambertMaterial({ color: "#eadfc4", side: THREE.DoubleSide });
  const ships = L.ships.map((s, i) => {
    const ship = new THREE.Group();
    if (makeAiShip) ship.add(makeAiShip());   // the image-to-3D ship, already the right size
    else {
      ship.add(new THREE.Mesh(hull, wood), new THREE.Mesh(mast, wood));
      if (s.sail) ship.add(new THREE.Mesh(sailGeo, sailMat));
    }
    ship.position.set(s.x, 0.15, s.z);
    ship.rotation.y = s.rot;
    ship.scale.setScalar(s.size);
    ship.traverse(o => { o.castShadow = true; });
    group.add(ship);
    return { ship, phase: i * 1.7, speed: 0.6 + (i % 5) * 0.12 };
  });
  return {
    group,
    update(time) {   // rocking on the swell
      for (const s of ships) {
        s.ship.rotation.z = Math.sin(time * s.speed + s.phase) * 0.045;
        s.ship.rotation.x = Math.sin(time * s.speed * 0.7 + s.phase * 2) * 0.025;
        s.ship.position.y = 0.15 + Math.sin(time * s.speed * 1.3 + s.phase) * 0.12;
      }
    },
  };
}

// --- chimney smoke ----------------------------------------------------------------------------
export function makeSmoke(L, perChimney) {
  const chimneys = L.chimneys.slice(0, 12), n = chimneys.length * Math.max(4, Math.round(perChimney / 8));
  const pos = new Float32Array(n * 3), age = new Float32Array(n);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("age", new THREE.BufferAttribute(age, 1));
  const uniforms = { map: { value: glowTexture(64) }, tint: { value: new THREE.Color() }, scale: { value: 300 } };
  const mat = new THREE.ShaderMaterial({
    uniforms, transparent: true, depthWrite: false,
    vertexShader: /* glsl */`
      attribute float age; varying float vAge; uniform float scale;
      void main() {
        vAge = age;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = scale * (0.6 + age * 2.4) / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */`
      uniform sampler2D map; uniform vec3 tint; varying float vAge;
      void main() {
        float a = texture2D(map, gl_PointCoord).a * (1.0 - vAge) * smoothstep(0.0, 0.1, vAge) * 0.35;
        gl_FragColor = vec4(tint, a);
      }`,
  });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  const r = rng(5);
  const seeds = Array.from({ length: n }, (_, i) => ({ c: chimneys[i % chimneys.length], off: r(), drift: r() }));
  return {
    points: pts,
    update(time, state) {
      for (let i = 0; i < n; i++) {
        const s = seeds[i], a = (time * 0.07 + s.off) % 1;   // each puff lives ~14 s
        age[i] = a;
        pos[i * 3] = s.c.x + a * 9 + Math.sin(time * 0.5 + s.drift * 9) * a * 1.5;   // the breeze pushes it west
        pos[i * 3 + 1] = s.c.y + a * 14;
        pos[i * 3 + 2] = s.c.z + a * 3 * (s.drift - 0.5);
      }
      geo.attributes.position.needsUpdate = geo.attributes.age.needsUpdate = true;
      uniforms.tint.value.copy(state.skyAmbient).multiplyScalar(1.1).lerp(state.sunColor, 0.25 * state.sunUp);
    },
  };
}

// --- lanterns -----------------------------------------------------------------------------------
export class Lanterns {
  constructor(streets, count, realLights) {
    const r = rng(77);
    this.paths = streets.filter(s => s.length > 2).map(pts => {
      const len = [0];
      for (let i = 1; i < pts.length; i++) len.push(len[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].z - pts[i - 1].z));
      return { pts, len, total: len[len.length - 1] };
    });
    this.walkers = Array.from({ length: count }, (_, i) => ({
      path: this.paths[i % this.paths.length], u: r(), speed: (0.7 + r() * 0.7) * (r() < 0.5 ? -1 : 1), flick: r() * 10,
    }));
    const pos = new Float32Array(count * 3), bright = new Float32Array(count);
    this.geo = new THREE.BufferGeometry();
    this.geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.geo.setAttribute("bright", new THREE.BufferAttribute(bright, 1));
    this.uniforms = { map: { value: glowTexture(64, [[0, "rgba(255,240,200,1)"], [0.25, "rgba(255,170,80,0.7)"], [1, "rgba(255,120,40,0)"]]) },
                      night: { value: 0 } };
    this.points = new THREE.Points(this.geo, new THREE.ShaderMaterial({
      uniforms: this.uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      vertexShader: /* glsl */`
        attribute float bright; varying float vB;
        void main() { vB = bright; vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = 2200.0 / -mv.z; gl_Position = projectionMatrix * mv; }`,
      fragmentShader: /* glsl */`
        uniform sampler2D map; uniform float night; varying float vB;
        void main() { vec4 t = texture2D(map, gl_PointCoord); gl_FragColor = vec4(t.rgb * 1.6, t.a * night * vB); }`,
    }));
    this.points.frustumCulled = false;
    this.lights = Array.from({ length: realLights }, () => new THREE.PointLight("#ffb062", 0, 28, 1.6));
  }
  at(path, u) {  // the point a fraction u along a path
    const d = u * path.total;
    let i = 1;
    while (i < path.len.length - 1 && path.len[i] < d) i++;
    const a = path.pts[i - 1], b = path.pts[i], f = (d - path.len[i - 1]) / Math.max(1e-6, path.len[i] - path.len[i - 1]);
    return [a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.z + (b.z - a.z) * f];
  }
  update(dt, time, state) {
    const pos = this.geo.attributes.position.array, bright = this.geo.attributes.bright.array;
    this.walkers.forEach((w, i) => {
      w.u += (w.speed * dt) / w.path.total;
      if (w.u > 1 || w.u < 0) { w.speed *= -1; w.u = Math.min(1, Math.max(0, w.u)); }   // turn round at the end
      const [x, y, z] = this.at(w.path, w.u);
      pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
      bright[i] = 0.75 + 0.25 * Math.sin(time * 7 + w.flick) * Math.sin(time * 3.1 + w.flick * 2);
      const L = this.lights[i];
      if (L) { L.position.set(x, y + 0.5, z); L.intensity = state.night * 60 * bright[i]; }
    });
    this.geo.attributes.position.needsUpdate = this.geo.attributes.bright.needsUpdate = true;
    this.uniforms.night.value = state.night;
  }
}

// --- clouds -------------------------------------------------------------------------------------
function cloudTexture() {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 128;
  const g = c.getContext("2d"), r = rng(11);
  for (let i = 0; i < 14; i++) {
    const x = 40 + r() * 176, y = 50 + r() * 40, rad = 20 + r() * 34;
    const grad = g.createRadialGradient(x, y, 0, x, y, rad);
    grad.addColorStop(0, "rgba(255,255,255,0.55)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 256, 128);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// `count` low clouds over the bay in front of the city (stage 1's), plus `wide` bigger, higher ones
// spread over the whole island and the sea round it. All drift slowly south on the breeze.
export function makeClouds(count = 16, wide = 0) {
  const r = rng(3), tex = cloudTexture(), group = new THREE.Group();
  const clouds = Array.from({ length: count + wide }, (_, i) => {
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, fog: true });
    const s = new THREE.Sprite(mat);
    const big = i >= count;
    const w = big ? 500 + r() * 900 : 160 + r() * 240;
    s.scale.set(w, w * 0.32, 1);
    if (big) s.position.set(-9500 + r() * 12500, 600 + r() * 1100, -8000 + r() * 16000);
    else s.position.set(150 + r() * 1500, 190 + r() * 200, -1100 + r() * 2200);
    group.add(s);
    return { s, speed: big ? 4 + r() * 5 : 2 + r() * 3, shade: 0.8 + r() * 0.3, big };
  });
  const col = new THREE.Color();
  return {
    group,
    // camera: clouds fade when they would only get in the way: the low ones over the bay once
    // you're above them (from the air they'd hide the city), any one you're about to fly through
    update(dt, state, camera = null) {
      for (const c of clouds) {
        if (camera) {
          const above = c.big ? 1 : 1 - THREE.MathUtils.smoothstep(camera.position.y, 320, 650);
          const inside = THREE.MathUtils.smoothstep(camera.position.distanceTo(c.s.position), c.s.scale.x * 0.3, c.s.scale.x * 0.9);
          c.s.material.opacity = above * inside;
          c.s.visible = c.s.material.opacity > 0.01;
        }
        c.s.position.z += c.speed * dt;
        if (c.big ? c.s.position.z > 8000 : c.s.position.z > 1100) c.s.position.z = c.big ? -8000 : -1100;
        col.copy(state.horizon).lerp(state.sunColor, 0.45 * state.sunUp).multiplyScalar(c.shade * (0.35 + 0.65 * state.sunUp));
        c.s.material.color.copy(col);
      }
    },
  };
}
