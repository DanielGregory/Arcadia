// The sky dome and the sea: two custom shaders driven by the day cycle.
//
// Sky: a gradient from the horizon colour up to the zenith colour; layered clouds (two decks of
// drifting noise, flattened toward the horizon, lit gold at the edges facing the sun and shaded
// underneath); a small bright sun with a wide soft glow; a pale moon and twinkling stars at night.
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
      float h21(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
      float vn(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
        return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
      float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { s += a * vn(p); p = p * 2.03 + 7.1; a *= 0.5; } return s; }
      // one deck of cloud, seen in direction d: puffs on a plane above, stretched along the horizon
      vec2 deck(vec3 d, float height, float scale, vec2 drift, float cover) {
        vec2 p = d.xz / (d.y + 0.06) * height * scale + drift;
        p.y *= 1.8;
        float n = fbm(p);
        float dens = smoothstep(cover, cover + 0.22, n);
        float thick = smoothstep(cover, cover + 0.45, fbm(p + vec2(0.35, 0.2)));   // a step toward the sun's side
        return vec2(dens, thick);
      }
      void main() {
        vec3 d = normalize(vDir);
        float h = d.y;
        vec3 col = mix(horizon, zenith, pow(smoothstep(0.0, 0.42, h), 0.75));   // the warm band hugs the horizon; blue above
        col = mix(col, horizon * 0.82, smoothstep(0.0, -0.25, h));              // below the horizon
        float s = max(dot(d, sunDir), 0.0);
        float above = smoothstep(-0.12, 0.02, sunDir.y);
        col *= 0.74;                                                             // (keeps the gold saturated, not washed out)
        col += sunColor * (pow(s, 6.0) * 0.1 + pow(s, 60.0) * 0.22 + pow(s, 6000.0) * 0.25) * above;  // the glow
        // clouds: two decks; dark undersides, bright gold edges where they face the sun
        if (h > 0.0) {
          float fade = smoothstep(0.0, 0.12, h);
          // (at night: dim grey-blue, just lit by the moon)
          vec3 shade = mix(zenith * 0.5 + horizon * 0.28 + vec3(0.05, 0.03, 0.06), vec3(0.035, 0.045, 0.08), stars);
          vec3 lit = mix(horizon * 1.2 + sunColor * 0.7, vec3(0.1, 0.12, 0.19), stars);
          float toward = pow(s, 3.0);
          for (int k = 0; k < 2; k++) {
            float fk = float(k);
            vec2 c = deck(d, 1.0 + fk * 0.6, 0.26 + fk * 0.34, vec2(time * (0.004 + fk * 0.003), fk * 3.7), 0.45 + fk * 0.07);
            float edge = c.x * (1.0 - c.y);                                       // thin edges catch the light
            vec3 cc = mix(shade, lit, 0.35 + 0.65 * (1.0 - c.y) * (0.4 + 0.6 * sunUp));
            cc += sunColor * (edge * 1.4 + toward * 0.6) * sunUp * (1.0 - stars);
            col = mix(col, cc, c.x * fade * (0.85 - fk * 0.2));
          }
        }
        col += vec3(1.0, 0.95, 0.85) * 5.0 * smoothstep(0.99990, 0.99995, s) * above;    // the disk: small and white-hot
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
    deep: { value: new THREE.Color("#0f3a62") }, shallow: { value: new THREE.Color("#2b6c8a") },
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
      float h21(vec2 q) { q = fract(q * vec2(123.34, 456.21)); q += dot(q, q + 45.32); return fract(q.x * q.y); }
      float vn(vec2 q) { vec2 i = floor(q), f = fract(q); f = f * f * (3.0 - 2.0 * f);
        return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y); }
      // the surface's slope (d height / dx, d height / dz): seven travelling waves of different
      // lengths from different directions (no two in step, so no stripes), plus drifting noise
      // ripples that break up what regularity is left
      vec2 waves(vec2 p) {
        vec2 g = vec2(0.0);
        for (int i = 0; i < 7; i++) {
          float fi = float(i), ang = fi * 2.399 + 0.4;                             // golden-angle spread
          vec2 dir = vec2(cos(ang), sin(ang));
          float k = 0.07 * pow(1.55, fi), sp = sqrt(9.8 * k) * 0.9;              // deep-water speed
          float a = 0.55 / (k * 26.0);
          g += dir * a * k * cos(dot(dir, p) * k + time * sp + fi * 1.7);
        }
        vec2 q = p * 0.35 + vec2(time * 0.22, time * 0.13);
        float e = 0.6;
        g += vec2(vn(q + vec2(e, 0.0)) - vn(q - vec2(e, 0.0)), vn(q + vec2(0.0, e)) - vn(q - vec2(0.0, e))) * 0.09;
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
        vec3 col = mix(body * light, sky, clamp(fres * 0.8, 0.0, 1.0) * mix(1.0, 0.55, smoothstep(5.0, 0.5, depth)));
        // foam: bands that run up the beach and fade, broken into patches along the shore (noise
        // that drifts with the waves), so it is never one even white line
        float wave = sin(depth * 5.0 - time * 1.6 + g.x * 40.0 + vn(vWorld.xz * 0.04) * 6.0) * 0.5 + 0.5;
        float patches = smoothstep(0.3, 0.7, vn(vWorld.xz * 0.06 + vec2(time * 0.05, 0.0)) * 0.7 + vn(vWorld.xz * 0.21) * 0.3);
        float foam = (smoothstep(1.6, 0.15, depth) * (0.25 + 0.75 * wave) + smoothstep(0.35, 0.0, depth) * 0.5) * (0.3 + 0.7 * patches);
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
