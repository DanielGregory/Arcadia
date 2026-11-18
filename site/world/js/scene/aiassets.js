// AI-made assets for /world (the test round, render/make_assets.py + render/pack_assets.py):
//
//   backdrops  painted panoramas standing far behind the 3D land, on curved cards: a sky, a distant
//              mountain range and nearer ridges. Two sets to compare: "sdxl" (painted for the
//              purpose by SDXL) and "corva" (cut from the canonical painting by depth).
//              They don't write depth, so the painter's haze leaves them alone: they come with their
//              own painted atmosphere.
//   textures   seamless plaster, stone, terracotta and a hillside detail map
//   objects    image-to-3D models (TripoSR): the summit temple, a ship, a statue and a fountain
//
// Everything here is optional: if a file is missing the world simply keeps its hand-built version.

import * as THREE from "../../vendor/three.module.min.js";
import { GLTFLoader } from "../../vendor/addons/loaders/GLTFLoader.js";

const BASE = "assets/";
const texLoader = new THREE.TextureLoader();

export async function loadManifest() {
  try { return await (await fetch(BASE + "manifest.json")).json(); } catch { return null; }
}

function loadTexture(url, srgb = true) {
  return new Promise(resolve => texLoader.load(url, t => {
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    resolve(t);
  }, undefined, () => resolve(null)));
}

// --- backdrops --------------------------------------------------------------------------------
// A card is a piece of a cylinder round the city, facing inward, spanning from the east (inland,
// behind the mountains) round to just short of the sunset in the north-north-west.
// Angles are atan2(z, x). The arc stands where the viewer sees open horizon: out over the sea from the
// north-north-east round to the west-north-west, so the painted ranges are the far shore of the bay,
// low on the horizon under the setting sun (as in the reference). Its ends fade out softly.
const ARC_FROM = Math.atan2(-1, -0.35), ARC_TO = Math.atan2(-0.3, 1);
function card(texture, radius, bottom, height, order) {
  let a0 = ARC_FROM, a1 = ARC_TO;
  if (a1 < a0) a1 += Math.PI * 2;
  const segs = 48, pos = [], uv = [], idx = [];
  for (let i = 0; i <= segs; i++) {
    const a = a0 + ((a1 - a0) * i) / segs, x = Math.cos(a) * radius, z = Math.sin(a) * radius;
    // the picture is repeated twice across the arc so it isn't stretched too wide
    const u = (i / segs) * 2;
    pos.push(x, bottom, z, x, bottom + height, z);
    uv.push(u, 0, u, 1);
    if (i < segs) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  geo.setIndex(idx);
  texture.wrapS = THREE.MirroredRepeatWrapping;
  const uniforms = { map: { value: texture }, tint: { value: new THREE.Color(1, 1, 1) }, opacity: { value: 1 },
                     fadeTop: { value: order === 0 ? 0.35 : 0.0 } };
  const mat = new THREE.ShaderMaterial({
    uniforms, transparent: true, depthWrite: false, side: THREE.DoubleSide, fog: false,
    vertexShader: /* glsl */`varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */`
      uniform sampler2D map; uniform vec3 tint; uniform float opacity, fadeTop; varying vec2 vUv;
      void main() {
        vec4 c = texture2D(map, vUv);
        float fade = fadeTop > 0.0 ? smoothstep(1.0, 1.0 - fadeTop, vUv.y) : 1.0;   // the painted sky melts into the dome
        fade *= smoothstep(0.0, 0.25, vUv.x) * smoothstep(2.0, 1.75, vUv.x);         // soft ends of the arc
        // painted textures are sRGB; the painter expects linear light
        // the paintings are already graded and warm: calm them a little so the painter's own grade
        // (and glow) doesn't push them to saturated orange
        vec3 lin = pow(c.rgb, vec3(2.2));
        lin = mix(vec3(dot(lin, vec3(0.299, 0.587, 0.114))), lin, 0.8) * 0.82;
        gl_FragColor = vec4(lin * tint, c.a * opacity * fade);
      }`,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.renderOrder = order;          // sky card, then far, then mid: back to front
  mesh.frustumCulled = false;
  return { mesh, uniforms, isSky: order === 0 };
}

export async function loadBackdrops(set, manifest, { paintedSky = false } = {}) {
  if (!set || set === "none" || !manifest?.backdrops?.[set]) return null;
  const group = new THREE.Group();
  // The painted sky is off unless asked for (?paintedsky=1): a fixed golden-hour painting fights the
  // day cycle's own sky, so in the test it read as an orange panel.
  const layers = [...(paintedSky ? [["sky", 3600, -200, 1900, 0]] : []),
                  ["far", 2900, -200, 560, 1], ["mid", 2100, -140, 300, 2]];
  const cards = [];
  for (const [name, radius, bottom, height, order] of layers) {
    const tex = await loadTexture(`${BASE}backdrops/${set}/${name}.png`);
    if (!tex) continue;
    const c = card(tex, radius, bottom, height, order);
    group.add(c.mesh);
    cards.push(c);
  }
  const night = new THREE.Color("#3b4a7a"), col = new THREE.Color();
  return {
    group,
    update(state, center) {
      group.position.set(center.x, 0, center.z);
      for (const c of cards) {
        // painted at golden hour: tinted toward the day's light, deep blue at night
        col.setRGB(1, 1, 1).lerp(state.sunColor, 0.25).multiplyScalar(0.45 + 0.75 * state.sunUp).lerp(night, state.night * 0.85);
        c.uniforms.tint.value.copy(col);
        // the painted sky belongs to golden hour; outside it the procedural sky takes over
        if (c.isSky) c.uniforms.opacity.value = 1 - THREE.MathUtils.smoothstep(Math.abs(state.t - 0.745), 0.03, 0.085);
      }
    },
  };
}

// --- textures -----------------------------------------------------------------------------------
export async function loadTextures(manifest) {
  const out = {};
  for (const name of manifest?.textures || []) {
    const t = await loadTexture(`${BASE}textures/${name}.jpg`, name !== "hillside");
    if (!t) continue;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 4;
    out[name] = t;
  }
  return out;
}

// --- objects -------------------------------------------------------------------------------------
// Loads a .glb made by pack_assets.py (base at y = 0, 1 unit tall, vertex colours) and returns a
// function that makes copies at a given height in metres.
export async function loadObject(model, name) {
  try {
    const gltf = await new GLTFLoader().loadAsync(`${BASE}objects/${model}/${name}.glb`);
    const src = gltf.scene;
    src.traverse(o => {
      if (o.isMesh) {
        o.material = new THREE.MeshLambertMaterial({ vertexColors: !!o.geometry.attributes.color, side: THREE.DoubleSide });
        o.castShadow = o.receiveShadow = true;
      }
    });
    return (height, footprint = null) => {
      const copy = src.clone(true);
      copy.scale.setScalar(height);
      if (footprint) {   // stretch to fill a footprint (width along x, depth along z), keeping it upright
        const box = new THREE.Box3().setFromObject(copy), size = box.getSize(new THREE.Vector3());
        copy.scale.set(height * footprint[0] / size.x, height, height * footprint[1] / size.z);
      }
      return copy;
    };
  } catch { return null; }
}
