// The camera: by default a slow cinematic drift, as if someone were standing on the south shore
// looking up the coast at Corva. Dragging (mouse or finger) orbits gently; pinch or wheel zooms
// a little; after a few idle seconds the camera eases back into its drift.
//
// Stage 2 hook: a fly-over is another rig with the same update(dt, time) interface.

import * as THREE from "../vendor/three.module.min.js";

export class DriftRig {
  constructor(camera, dom, { target = new THREE.Vector3(25, 30, -70), still = false } = {}) {
    this.camera = camera;
    this.target = target.clone();
    this.wideTarget = target.clone();                         // landscape: the city and the sunset
    this.portraitTarget = new THREE.Vector3(-35, 30, -40);    // portrait: the city, seen from out on the bay
    this.wideBase = { az: 1.47, el: 0.085, dist: 320 };
    this.portraitBase = { az: 0.62, el: 0.13, dist: 270 };
    this.still = still;
    // where the drift centres: on the hill of the south shore, looking north up the coast, the city
    // climbing its hill on the left and the bay opening to the setting sun on the right
    this.base = { az: 1.47, el: 0.085, dist: 320 };
    this.user = { az: 0, el: 0, zoom: 1 };      // the viewer's offset, eased back to 0 when idle
    this.goal = { az: 0, el: 0, zoom: 1 };
    this.idle = 99;
    let last = null;
    dom.addEventListener("pointerdown", e => { last = [e.clientX, e.clientY]; dom.setPointerCapture(e.pointerId); });
    dom.addEventListener("pointermove", e => {
      if (!last) return;
      this.goal.az = THREE.MathUtils.clamp(this.goal.az - (e.clientX - last[0]) * 0.004, -0.9, 0.9);
      this.goal.el = THREE.MathUtils.clamp(this.goal.el + (e.clientY - last[1]) * 0.003, -0.08, 0.35);
      last = [e.clientX, e.clientY];
      this.idle = 0;
    });
    const end = () => { last = null; };
    dom.addEventListener("pointerup", end);
    dom.addEventListener("pointercancel", end);
    dom.addEventListener("wheel", e => {
      this.goal.zoom = THREE.MathUtils.clamp(this.goal.zoom * (1 + Math.sign(e.deltaY) * 0.08), 0.55, 1.35);
      this.idle = 0;
      e.preventDefault();
    }, { passive: false });
  }
  setPortrait(portrait) {
    this.target.copy(portrait ? this.portraitTarget : this.wideTarget);
    this.base = { ...(portrait ? this.portraitBase : this.wideBase) };
  }
  update(dt, time) {
    this.idle += dt;
    if (this.idle > 8) {   // drift home after 8 idle seconds
      const k = 1 - Math.exp(-dt * 0.25);
      this.goal.az *= 1 - k; this.goal.el *= 1 - k; this.goal.zoom += (1 - this.goal.zoom) * k;
    }
    const k = 1 - Math.exp(-dt * 3);
    for (const key of ["az", "el", "zoom"]) this.user[key] += (this.goal[key] - this.user[key]) * k;
    const drift = this.still ? 0 : 1;
    const az = this.base.az + this.user.az + drift * 0.16 * Math.sin(time / 47);
    const el = this.base.el + this.user.el + drift * 0.025 * Math.sin(time / 31 + 1);
    const dist = this.base.dist * this.user.zoom * (1 + drift * 0.05 * Math.sin(time / 59));
    // az measured from +x (the sea side) toward +z (south); the camera sits out over the water
    this.camera.position.set(
      this.target.x + dist * Math.cos(el) * Math.cos(az),
      this.target.y + dist * Math.sin(el),
      this.target.z + dist * Math.cos(el) * Math.sin(az),
    );
    this.camera.lookAt(this.target);
  }
}
