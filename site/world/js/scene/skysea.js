// The sky dome and the sea: two custom shaders driven by the day cycle.
//
// Sky: a gradient from the horizon colour up to the zenith colour, a glow and a disk for the sun,
// a pale moon and twinkling stars at night.
// Sea: a flat plane whose surface normal is bent by a few moving sine waves; it reflects the sky
// (more at grazing angles, the Fresnel effect) and catches the sun in a glittering path of
// highlights: the "glint" that runs from the horizon to the shore at golden hour.

import * as THREE from "../../vendor/three.module.min.js";

export function makeSky() {
  const uniforms = {
    zenith: { value: new THREE.Color() }, horizon: { value: new THREE.Color() },
    sunDir: { value: new THREE.Vector3() }, sunColor: { value: new THREE.Color() },
    sunUp: { value: 1 }, stars: { value: 0 }, moonDir: { value: new THREE.Vector3() }, time: { value: 0 },
  };
  const material = new THREE.ShaderMaterial({
    uniforms, side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false,   // drawn first, behind everything
    vertexShader: /* glsl */`
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_Position = p.xyww;                       // always at the far plane
      }`,
    fragmentShader: /* glsl */`
      uniform vec3 zenith, horizon, sunDir, sunColor, moonDir;
      uniform float sunUp, stars, time;
      varying vec3 vDir;
      float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
      void main() {
        vec3 d = normalize(vDir);
        float h = d.y;
        vec3 col = mix(horizon, zenith, pow(clamp(h, 0.0, 1.0), 0.42));
        col = mix(col, horizon * 0.82, smoothstep(0.0, -0.25, h));              // below the horizon
        float s = max(dot(d, sunDir), 0.0);
        float above = smoothstep(-0.12, 0.02, sunDir.y);
        col += sunColor * (pow(s, 6.0) * 0.28 + pow(s, 48.0) * 0.5) * above;    // the glow
        col += sunColor * 6.0 * smoothstep(0.99955, 0.99975, s) * above;         // the disk
        // night: stars on a fixed grid of directions, twinkling
        vec3 g = floor(d * 260.0);
        float star = step(0.9975, hash(g)) * (0.6 + 0.4 * sin(time * 2.0 + hash(g + 1.0) * 30.0));
        col += vec3(0.9, 0.92, 1.0) * star * stars * smoothstep(0.02, 0.2, h);
        float m = max(dot(d, moonDir), 0.0);
        col += vec3(0.85, 0.88, 1.0) * (smoothstep(0.9993, 0.9996, m) * 1.6 + pow(m, 200.0) * 0.12) * stars;
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(4000, 48, 24), material);
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;
  // the dome is centred on the camera wherever it goes (it is drawn at the far plane anyway)
  return { mesh, uniforms, follow(camera) { mesh.position.copy(camera.position); } };
}

// The sea needs to know how deep the water is under each point, for the turquoise shallows and the
// foam along the shore. Bake heightAt() near the coast into a small texture once, at startup.
// (Bytes, not floats: every phone can filter them smoothly.) height = value * 16 - 8 metres.
export function shoreTexture(heightAt, rect = { x: -40, z: -560, w: 420, d: 1000 }, nx = 192, nz = 448) {
  const data = new Uint8Array(nx * nz);
  for (let j = 0; j < nz; j++) for (let i = 0; i < nx; i++) {
    const h = heightAt(rect.x + (rect.w * i) / (nx - 1), rect.z + (rect.d * j) / (nz - 1));
    data[j * nx + i] = Math.round(Math.min(1, Math.max(0, (h + 8) / 16)) * 255);
  }
  const tex = new THREE.DataTexture(data, nx, nz, THREE.RedFormat, THREE.UnsignedByteType);
  tex.minFilter = tex.magFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return { tex, rect: new THREE.Vector4(rect.x, rect.z, rect.w, rect.d) };
}

// The same for the whole island, but coarser (about 16 m per texel): made in a worker after
// startup, so until it arrives the sea away from the city is simply deep.
export function islandShoreTexture({ data, rect, nx, nz }) {
  const tex = new THREE.DataTexture(data, nx, nz, THREE.RedFormat, THREE.UnsignedByteType);
  tex.minFilter = tex.magFilter = THREE.LinearFilter;
  tex.needsUpdate = true;
  return { tex, rect: new THREE.Vector4(rect.x, rect.z, rect.w, rect.d) };
}

export function makeSea(shore) {
  const none = new THREE.DataTexture(new Uint8Array([0]), 1, 1, THREE.RedFormat, THREE.UnsignedByteType);
  none.needsUpdate = true;
  const uniforms = {
    shoreTex: { value: shore.tex }, shoreRect: { value: shore.rect },
    islandTex: { value: none }, islandRect: { value: new THREE.Vector4(0, 0, 0, 0) },
    time: { value: 0 }, sunDir: { value: new THREE.Vector3() }, sunColor: { value: new THREE.Color() },
    sunUp: { value: 1 }, zenith: { value: new THREE.Color() }, horizon: { value: new THREE.Color() },
    ambient: { value: new THREE.Color() }, fogColor: { value: new THREE.Color() }, fogDensity: { value: 0.0012 },
    lightDir: { value: new THREE.Vector3() }, night: { value: 0 },
    deep: { value: new THREE.Color("#1d4a5c") }, shallow: { value: new THREE.Color("#3f7f86") },
    turquoise: { value: new THREE.Color("#5fb3ad") },
  };
  const material = new THREE.ShaderMaterial({
    uniforms, fog: false,
    vertexShader: /* glsl */`
      varying vec3 vWorld;
      void main() {
        vec4 w = modelMatrix * vec4(position, 1.0);
        vWorld = w.xyz;
        gl_Position = projectionMatrix * viewMatrix * w;
      }`,
    fragmentShader: /* glsl */`
      uniform float time, sunUp, fogDensity, night;
      uniform vec3 sunDir, sunColor, zenith, horizon, ambient, fogColor, lightDir, deep, shallow, turquoise;
      uniform sampler2D shoreTex, islandTex; uniform vec4 shoreRect, islandRect;
      varying vec3 vWorld;
      // depth of water here, from the baked land heights: the fine map round the city, else the
      // coarse one round the whole island, else deep
      float waterDepth(vec2 p) {
        vec2 uv = (p - shoreRect.xy) / shoreRect.zw;
        if (all(greaterThanEqual(uv, vec2(0.0))) && all(lessThanEqual(uv, vec2(1.0))))
          return -(texture2D(shoreTex, uv).r * 16.0 - 8.0);
        if (islandRect.z > 0.0) {
          uv = (p - islandRect.xy) / islandRect.zw;
          if (all(greaterThanEqual(uv, vec2(0.0))) && all(lessThanEqual(uv, vec2(1.0))))
            return -(texture2D(islandTex, uv).r * 16.0 - 8.0);
        }
        return 30.0;
      }
      // sum of a few travelling waves: returns the slope (d height / dx, d height / dz)
      vec2 waves(vec2 p) {
        vec2 g = vec2(0.0);
        vec4 dirs[4];
        dirs[0] = vec4(normalize(vec2(1.0, 0.3)), 0.11, 0.9);
        dirs[1] = vec4(normalize(vec2(0.7, -0.8)), 0.19, 1.3);
        dirs[2] = vec4(normalize(vec2(-0.2, 1.0)), 0.37, 1.9);
        dirs[3] = vec4(normalize(vec2(0.9, 0.9)), 0.83, 2.7);
        for (int i = 0; i < 4; i++) {
          vec2 dir = dirs[i].xy; float k = dirs[i].z, sp = dirs[i].w;
          float a = 0.6 / (k * 22.0);
          g += dir * a * k * cos(dot(dir, p) * k + time * sp);
        }
        return g;
      }
      void main() {
        vec3 view = cameraPosition - vWorld;
        float dist = length(view);
        view /= dist;
        vec2 g = waves(vWorld.xz) * mix(1.0, 0.25, smoothstep(200.0, 1600.0, dist));   // calmer far away
        vec3 n = normalize(vec3(-g.x, 1.0, -g.y));
        float fres = 0.02 + 0.98 * pow(1.0 - max(dot(n, view), 0.0), 5.0);
        vec3 r = reflect(-view, n);
        vec3 sky = mix(horizon, zenith, pow(clamp(r.y, 0.0, 1.0), 0.42));
        float depth = waterDepth(vWorld.xz);
        vec3 light = ambient * 1.25 + sunColor * 0.12 * sunUp;
        vec3 body = mix(deep, shallow, 0.25);
        body = mix(body, turquoise, smoothstep(7.0, 0.8, depth) * mix(0.35, 1.0, sunUp));   // sand showing through the shallows
        vec3 col = mix(body * light, sky, clamp(fres * 0.95, 0.0, 1.0) * mix(1.0, 0.55, smoothstep(5.0, 0.5, depth)));
        // foam: bands that run up the beach and fade, broken by the waves
        float wave = sin(depth * 5.0 - time * 1.6 + g.x * 40.0) * 0.5 + 0.5;
        float foam = smoothstep(1.6, 0.15, depth) * (0.35 + 0.65 * wave) + smoothstep(0.35, 0.0, depth) * 0.6;
        // foam is lit like everything else: bright in sun, a faint grey line by moonlight
        col = mix(col, (ambient * mix(0.7, 1.6, sunUp) + sunColor * 0.6 * sunUp) * 0.95, clamp(foam, 0.0, mix(0.45, 0.85, sunUp)));
        float s = max(dot(r, sunDir), 0.0);
        col += sunColor * (pow(s, 420.0) * 9.0 + pow(s, 60.0) * 0.55) * sunUp;   // the sun's path
        float m = max(dot(r, lightDir), 0.0);
        col += vec3(0.75, 0.8, 1.0) * pow(m, 300.0) * 2.5 * night;              // the moon's path
        float f = 1.0 - exp(-pow(fogDensity * dist, 2.0));
        gl_FragColor = vec4(mix(col, fogColor, f), 1.0);
      }`,
  });
  // 120 km across, and it follows the camera (see follow()), so the sea reaches the horizon from
  // wherever you fly. The waves are worked out from world positions, so they don't slide with it.
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(120000, 120000, 1, 1), material);
  mesh.rotation.x = -Math.PI / 2;
  mesh.frustumCulled = false;
  return {
    mesh, uniforms,
    follow(camera) { mesh.position.set(camera.position.x, 0, camera.position.z); },
    setIslandShore(t) { uniforms.islandTex.value = t.tex; uniforms.islandRect.value.copy(t.rect); },
  };
}
