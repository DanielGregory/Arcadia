// The camera: fly freely over the island, the way a map app works.
//
// The camera always looks at a point on the ground (the "target") from some distance, at some
// compass bearing (azimuth) and some tilt above the horizontal (elevation):
//
//   drag (one finger / left mouse)         slide the land under you (pan)
//   pinch / mouse wheel                    zoom in and out (from 25 m to 16 km away)
//   twist with two fingers / right-drag    turn round the target
//   two fingers up-down / right-drag up-down  tilt: from looking along the horizon to straight down
//   tap / click a place                    fly there
//   arrow keys or WASD, Q / E, + / -       pan, turn, zoom from the keyboard
//
// home() flies back to Corva, to the framing of stage 1: from the hill of the south shore,
// looking up the coast at the city with the bay opening to the sunset. While you leave it alone the
// view breathes with the same slow drift as before.
//
// The camera never goes underground: if a move would put it below the hills, it is lifted.

import * as THREE from "../vendor/three.module.min.js";
import { heightAt, BOUNDS } from "./world/terrain.js";

const clamp = THREE.MathUtils.clamp;
const ground = (x, z) => Math.max(0, heightAt(x, z));          // the sea counts as ground at 0

// Stage 1's two framings: wide screens see the city and the sunset; tall ones the city from the bay.
// The lowest tilt allowed at a given distance: free up to 1.5 km, then rising to ~40 degrees by 16 km.
const minTilt = dist => clamp((dist - 1500) / 20000, 0, 0.7);

const HOME = {
  wide: { x: 25, z: -70, az: 1.47, el: 0.085, dist: 320 },
  tall: { x: -35, z: -40, az: 0.62, el: 0.13, dist: 270 },
};

export class FlyRig {
  constructor(camera, dom, { still = false } = {}) {
    this.camera = camera;
    this.dom = dom;
    this.still = still;
    this.portrait = false;
    // `view` is where the camera is; `goal` is where the controls want it; it eases toward the goal
    this.view = { ...HOME.wide };
    this.goal = { ...HOME.wide };
    this.target = new THREE.Vector3();
    this.flight = null;                  // a flight in progress (tap-to-travel or home)
    this.idle = 99;                      // seconds since the viewer last touched anything
    this.pointers = new Map();
    this.onTravel = null;                // called with (x, z) when a tap starts a flight
    this.listen(dom);
  }

  // --- input ---------------------------------------------------------------------------------
  listen(dom) {
    dom.addEventListener("contextmenu", e => e.preventDefault());
    dom.addEventListener("pointerdown", e => {
      dom.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: performance.now(),
                                       turn: e.button === 2 || e.shiftKey || e.ctrlKey });
      this.prevPair = this.pair();
      this.touched();
    });
    dom.addEventListener("pointermove", e => {
      const p = this.pointers.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      if (this.pointers.size === 1) {
        if (p.turn) this.turn(dx, dy);
        else this.pan(dx, dy);
      } else if (this.pointers.size === 2) {
        const now = this.pair(), was = this.prevPair;
        if (was && now) {
          this.goal.dist = clamp(this.goal.dist * (was.span / Math.max(now.span, 1)), 25, 16000);   // pinch
          let da = now.angle - was.angle;
          da = Math.atan2(Math.sin(da), Math.cos(da));
          this.goal.az -= da;                                                                        // twist
          this.goal.el = clamp(this.goal.el + (now.y - was.y) * 0.004, 0.02, 1.5);                  // two-finger tilt
        }
        this.prevPair = now;
      }
      this.touched();
    });
    const up = e => {
      const p = this.pointers.get(e.pointerId);
      this.pointers.delete(e.pointerId);
      this.prevPair = this.pair();
      // a tap: short and barely moved, one finger
      if (p && this.pointers.size === 0 && performance.now() - p.t0 < 300 && Math.hypot(p.x - p.x0, p.y - p.y0) < 8) {
        this.tap(e.clientX, e.clientY);
      }
    };
    dom.addEventListener("pointerup", up);
    dom.addEventListener("pointercancel", e => { this.pointers.delete(e.pointerId); this.prevPair = this.pair(); });
    dom.addEventListener("wheel", e => {
      // trackpad pinches arrive as wheel events with ctrlKey; both zoom
      this.goal.dist = clamp(this.goal.dist * Math.exp(e.deltaY * (e.ctrlKey ? 0.01 : 0.0012)), 25, 16000);
      this.touched();
      e.preventDefault();
    }, { passive: false });
    this.keys = new Set();
    addEventListener("keydown", e => { if (!e.target.closest?.("select,input")) this.keys.add(e.key.toLowerCase()); });
    addEventListener("keyup", e => this.keys.delete(e.key.toLowerCase()));
  }

  pair() {
    if (this.pointers.size !== 2) return null;
    const [a, b] = [...this.pointers.values()];
    return { span: Math.hypot(b.x - a.x, b.y - a.y), angle: Math.atan2(b.y - a.y, b.x - a.x), y: (a.y + b.y) / 2 };
  }

  touched() { this.idle = 0; this.flight = null; }

  // Slide the ground so the point under the finger follows it. One pixel is worth this many metres
  // at the target's distance.
  pan(dx, dy) {
    const g = this.goal, h = this.dom.clientHeight || 800;
    const m = (2 * g.dist * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))) / h;
    // screen right and screen "up" laid flat on the ground (up is foreshortened when looking low)
    const rx = Math.sin(g.az), rz = -Math.cos(g.az);         // screen right (forward x up)
    const fx = -Math.cos(g.az), fz = -Math.sin(g.az);        // away from the camera
    const fy = 1 / Math.max(0.25, Math.sin(Math.max(g.el, 0.05)) + 0.2);
    g.x += (-dx * rx + dy * fx * fy) * m;
    g.z += (-dx * rz + dy * fz * fy) * m;
    this.keepInside(g);
  }
  turn(dx, dy) {
    this.goal.az -= dx * 0.005;
    this.goal.el = clamp(this.goal.el + dy * 0.004, 0.02, 1.5);
  }
  keepInside(g) {
    g.x = clamp(g.x, BOUNDS.minX - 3000, BOUNDS.maxX + 3000);
    g.z = clamp(g.z, BOUNDS.minZ - 3000, BOUNDS.maxZ + 3000);
  }

  // Where a screen point meets the ground: march along the ray from the camera until it goes
  // below the land (or the sea). Works at any distance, whatever detail the tiles happen to have.
  pick(clientX, clientY) {
    const rect = this.dom.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const o = ray.ray.origin, d = ray.ray.direction;
    let prev = 0, t = 1;
    for (let i = 0; i < 400 && t < 40000; i++) {
      const x = o.x + d.x * t, y = o.y + d.y * t, z = o.z + d.z * t;
      if (y <= ground(x, z)) {
        // refine between the last point above and this one below
        let a = prev, b = t;
        for (let k = 0; k < 12; k++) {
          const m = (a + b) / 2;
          if (o.y + d.y * m <= ground(o.x + d.x * m, o.z + d.z * m)) b = m; else a = m;
        }
        return { x: o.x + d.x * b, z: o.z + d.z * b };
      }
      prev = t;
      t += Math.max(2, t * 0.02);
    }
    return null;
  }

  tap(clientX, clientY) {
    const p = this.pick(clientX, clientY);
    if (!p) return;
    // arrive a little closer than we are now (but never closer than 180 m), looking the same way
    this.flyTo({ x: p.x, z: p.z, dist: clamp(this.goal.dist * 0.6, 180, 4000) });
    this.onTravel?.(p.x, p.z);
  }

  // Fly to a place: { x, z, dist?, az?, el? }. The camera rises in an arc on long journeys, so you
  // see where you're going.
  flyTo(to, seconds = null) {
    const from = { ...this.view };
    const end = { x: to.x, z: to.z, dist: to.dist ?? from.dist, az: to.az ?? from.az, el: to.el ?? from.el };
    let da = end.az - from.az;
    end.az = from.az + Math.atan2(Math.sin(da), Math.cos(da));      // turn the short way round
    const far = Math.hypot(end.x - from.x, end.z - from.z);
    this.flight = { from, end, t: 0, dur: seconds ?? clamp(1.2 + far / 2500, 1.4, 4.5), lift: far * 0.35 };
    this.idle = 0;
  }

  home() { this.flyTo({ ...(this.portrait ? HOME.tall : HOME.wide) }); }

  setPortrait(portrait) {
    const was = this.portrait;
    this.portrait = portrait;
    if (was !== portrait && this.atHome()) { Object.assign(this.view, portrait ? HOME.tall : HOME.wide); Object.assign(this.goal, this.view); }
  }
  atHome() {
    const h = this.portrait ? HOME.tall : HOME.wide, o = this.portrait ? HOME.wide : HOME.tall;
    const near = v => Math.hypot(this.goal.x - v.x, this.goal.z - v.z) < 5 && Math.abs(this.goal.dist - v.dist) < 5;
    return near(h) || near(o);
  }

  // Set the view at once (for tests and screenshots): { x, z, dist, az, el }
  jump(v) { Object.assign(this.view, v); Object.assign(this.goal, this.view); this.flight = null; }

  // --- each frame ------------------------------------------------------------------------------
  update(dt, time) {
    this.idle += dt;
    this.keyboard(dt);
    const v = this.view, g = this.goal;
    if (this.flight) {
      const f = this.flight;
      f.t = Math.min(1, f.t + dt / f.dur);
      const e = f.t * f.t * (3 - 2 * f.t);                         // ease in and out
      for (const k of ["x", "z", "az", "el"]) v[k] = f.from[k] + (f.end[k] - f.from[k]) * e;
      // distance: log-blend (feels even when zooming a long way) plus the arc's lift
      v.dist = Math.exp(Math.log(f.from.dist) + (Math.log(f.end.dist) - Math.log(f.from.dist)) * e) + f.lift * Math.sin(Math.PI * f.t);
      Object.assign(g, v);
      if (f.t >= 1) this.flight = null;
    } else {
      const k = 1 - Math.exp(-dt * 9);                             // quick but smooth
      v.x += (g.x - v.x) * k; v.z += (g.z - v.z) * k;
      v.az += (g.az - v.az) * k; v.el += (g.el - v.el) * k;
      v.dist = Math.exp(Math.log(v.dist) + (Math.log(g.dist) - Math.log(v.dist)) * k);
    }
    // the slow breathing drift of stage 1, once left alone for a while (and not in still mode)
    const drift = this.still ? 0 : THREE.MathUtils.smoothstep(this.idle, 6, 14);
    const az = v.az + drift * 0.16 * Math.sin(time / 47);
    // the further out you zoom, the more the view tips down toward a map: from far away and low,
    // all you would see is haze over the sea
    const el = Math.max(minTilt(v.dist), 0.01, v.el + drift * 0.025 * Math.sin(time / 31 + 1));
    const dist = v.dist * (1 + drift * 0.05 * Math.sin(time / 59));

    // the point we look at sits a little above the ground (more when far away), as in stage 1
    this.target.set(v.x, ground(v.x, v.z) + Math.min(30, dist * 0.09), v.z);
    const c = this.camera.position;
    c.set(this.target.x + dist * Math.cos(el) * Math.cos(az), this.target.y + dist * Math.sin(el),
          this.target.z + dist * Math.cos(el) * Math.sin(az));
    const floor = ground(c.x, c.z) + 6 + dist * 0.01;              // stay clear of the hills
    if (c.y < floor) c.y = floor;
    this.camera.lookAt(this.target);
    // the near clipping plane moves out as the view widens, which keeps the depth buffer sharp
    // enough that distant shallows don't flicker through the sea
    this.camera.near = clamp(dist * 0.008, 0.8, 40);
    this.camera.far = 60000;
    this.camera.updateProjectionMatrix();
  }

  keyboard(dt) {
    if (!this.keys.size) return;
    const k = this.keys, s = 400 * dt;
    if (k.has("arrowleft") || k.has("a")) this.pan(s, 0);
    if (k.has("arrowright") || k.has("d")) this.pan(-s, 0);
    if (k.has("arrowup") || k.has("w")) this.pan(0, s);
    if (k.has("arrowdown") || k.has("s")) this.pan(0, -s);
    if (k.has("q")) this.goal.az += dt * 1.2;
    if (k.has("e")) this.goal.az -= dt * 1.2;
    if (k.has("+") || k.has("=")) this.goal.dist = clamp(this.goal.dist * Math.exp(-dt * 1.5), 25, 16000);
    if (k.has("-")) this.goal.dist = clamp(this.goal.dist * Math.exp(dt * 1.5), 25, 16000);
    this.touched();
  }

  // Height of the camera above the sea, for the haze (thinner the higher you fly).
  get altitude() { return this.camera.position.y; }
}
