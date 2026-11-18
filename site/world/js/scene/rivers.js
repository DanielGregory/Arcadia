// The rivers' water: a ribbon along each river, as wide as its channel, at the water's height
// (which falls steadily from the spring to the sea: features.js), lying in the valley the terrain
// carved for it.
//
// The water reflects the sky (more at grazing angles), catches the sun, and ripples with lines
// that run downstream: the ribbon's length coordinate moves with time, so the water flows.
// It is drawn slightly "in front" of the ground (a depth bias), so on far, coarse tiles that don't
// quite show the channel, the river still shows as a thread of light.

import * as THREE from "../../vendor/three.module.min.js";

export function makeRivers(rivers) {
  const uniforms = {
    time: { value: 0 }, sunDir: { value: new THREE.Vector3() }, sunColor: { value: new THREE.Color() },
    sunUp: { value: 1 }, zenith: { value: new THREE.Color() }, horizon: { value: new THREE.Color() },
    ambient: { value: new THREE.Color() }, fogColor: { value: new THREE.Color() }, fogDensity: { value: 0.0002 },
    deep: { value: new THREE.Color("#2c5a5c") },
  };
  const material = new THREE.ShaderMaterial({
    uniforms, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -8,
    vertexShader: /* glsl */`
      attribute float along;          // metres from the spring
      attribute float across;         // -1 .. 1 from bank to bank
      varying vec3 vWorld; varying float vAlong, vAcross;
      void main() {
        vec4 w = modelMatrix * vec4(position, 1.0);
        vWorld = w.xyz; vAlong = along; vAcross = across;
        gl_Position = projectionMatrix * viewMatrix * w;
      }`,
    fragmentShader: /* glsl */`
      uniform float time, sunUp, fogDensity;
      uniform vec3 sunDir, sunColor, zenith, horizon, ambient, fogColor, deep;
      varying vec3 vWorld; varying float vAlong, vAcross;
      void main() {
        vec3 view = cameraPosition - vWorld;
        float dist = length(view);
        view /= dist;
        // ripples: bands moving downstream, bent a little across the stream
        float flow = vAlong * 0.35 - time * 1.6 + sin(vAcross * 3.0 + vAlong * 0.05) * 1.5;
        vec3 n = normalize(vec3(sin(flow) * 0.08, 1.0, cos(flow * 1.3 + vAcross) * 0.08));
        float fres = 0.04 + 0.96 * pow(1.0 - max(dot(n, view), 0.0), 5.0);
        vec3 r = reflect(-view, n);
        vec3 sky = mix(horizon, zenith, pow(clamp(r.y, 0.0, 1.0), 0.42));
        vec3 col = mix(deep * (ambient * 1.2 + sunColor * 0.15 * sunUp), sky, clamp(fres, 0.0, 0.9));
        col += sunColor * pow(max(dot(r, sunDir), 0.0), 120.0) * 1.8 * sunUp;
        // the edges darken into the banks
        col *= 0.75 + 0.25 * (1.0 - vAcross * vAcross);
        float f = 1.0 - exp(-pow(fogDensity * dist, 2.0));
        gl_FragColor = vec4(mix(col, fogColor, f), 1.0);
      }`,
  });
  const group = new THREE.Group();
  for (const rv of rivers) {
    const pts = rv.pts, pos = [], along = [], across = [], idx = [];
    let run = 0;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i], a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
      if (i > 0) run += Math.hypot(p.x - a.x, p.z - a.z);
      let dx = b.x - a.x, dz = b.z - a.z;
      const len = Math.hypot(dx, dz) || 1;
      dx /= len; dz /= len;
      const w = p.w * 0.95, y = Math.max(p.h - 0.45, 0.05);       // just below the brim of the channel
      pos.push(p.x - dz * w, y, p.z + dx * w, p.x + dz * w, y, p.z - dx * w);
      along.push(run, run);
      across.push(-1, 1);
      if (i + 1 < pts.length) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("along", new THREE.Float32BufferAttribute(along, 1));
    g.setAttribute("across", new THREE.Float32BufferAttribute(across, 1));
    g.setIndex(idx);
    g.computeBoundingSphere();
    const mesh = new THREE.Mesh(g, material);
    mesh.matrixAutoUpdate = false;
    group.add(mesh);
  }
  return {
    group,
    update(state, time, fogDensity) {
      const u = uniforms;
      u.time.value = time;
      u.sunDir.value.copy(state.sun); u.sunColor.value.copy(state.sunColor); u.sunUp.value = state.sunUp;
      u.zenith.value.copy(state.zenith); u.horizon.value.copy(state.horizon); u.ambient.value.copy(state.skyAmbient);
      u.fogColor.value.copy(state.fog); u.fogDensity.value = fogDensity;
    },
  };
}
