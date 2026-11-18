// Corva, living: the island. Wires the pieces together and runs the loop.
//
//   world/   pure data: the island's terrain function, the city layout, the day cycle (no rendering)
//   scene/   builders that turn that data into three.js objects (the ground in tiles, sky and sea,
//            the city, life, the distant islands)
//   render/  the painterly post-process
//   camera.js the fly rig: drag, pinch, twist, tap to travel; "Corva" flies home
//
// Step B added the island's villages, rivers, roads, forests and olive groves (made from the seed:
// world/features.js); next (step C) the map is stored in the world tables so the simulation can
// change it.

import * as THREE from "../vendor/three.module.min.js";
import { QUALITY, params, chooseQuality, safeSet, DAY_SECONDS, START_TIME } from "./config.js";
import { generateLayout, addVillages } from "./world/layout.js";
import { generateFeatures } from "./world/features.js";
import { setFeatures } from "./world/featuremap.js";
import { makeRivers } from "./scene/rivers.js";
import { makeLabels } from "./scene/labels.js";
import { dayState, TIMES } from "./world/daycycle.js";
import { makeSky, makeSea, shoreTexture, islandShoreTexture } from "./scene/skysea.js";
import { heightAt, CITY } from "./world/terrain.js";
import { Terrain } from "./scene/terrain.js";
import { makeDistantIslands } from "./scene/horizon.js";
import { makeCity, makeTrees } from "./scene/city.js";
import { makeShips, makeSmoke, Lanterns, makeClouds } from "./scene/life.js";
import { Painter } from "./render/painterly.js";
import { FlyRig } from "./camera.js";
import { loadManifest, loadBackdrops, loadTextures, loadObject } from "./scene/aiassets.js";
import { at } from "./world/layout.js";

const qualityName = chooseQuality();
const Q = QUALITY[qualityName];
const seed = Number(params.get("seed")) || 1717;
const fixedTime = params.has("t") ? Number(params.get("t")) : null;

// --- renderer, scene, camera --------------------------------------------------------------------
const canvas = document.getElementById("view");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, Q.pixelRatio));
renderer.shadowMap.enabled = Q.shadows;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xffffff, 0.00018);   // light: the painter adds the real haze
const camera = new THREE.PerspectiveCamera(38, 1, 1, 60000);
const rig = new FlyRig(camera, canvas, { still: params.get("still") === "1" });
// ?view=x,z,dist,az,el: start somewhere else (for screenshots and links to a place)
if (params.has("view")) {
  const [x, z, dist, az, el] = params.get("view").split(",").map(Number);
  rig.jump({ x, z, dist, az, el });
}
const painter = new Painter(renderer, Q);

// --- the world ----------------------------------------------------------------------------------
// The island's villages, rivers and roads: saved for the default seed (tools/make_features.mjs),
// made here for any other. They must be in place before anything asks the ground's height, since
// the rivers carve their valleys into it.
const features = await fetch(`assets/island/features-${seed}.json`).then(r => (r.ok ? r.json() : null)).catch(() => null)
                 ?? generateFeatures(seed);
setFeatures(features);
const layout = addVillages(generateLayout(seed, qualityName), features.villages, seed);
// AI-made assets (render/make_assets.py): textures by default (?ai=0 for none). The image-to-3D
// objects of the test round lost to the modelled buildings and boats; ?aiobjects=1 still shows them.
const useAI = params.get("ai") !== "0";
const manifest = useAI ? await loadManifest() : null;
const tex = useAI ? await loadTextures(manifest) : {};
const sky = makeSky(), sea = makeSea(shoreTexture(heightAt));
const city = makeCity(layout, Q, seed, { plaster: tex.plaster || null, detail: qualityName === "low" ? 0 : 1 });
const ships = makeShips(layout);
// The painted backdrops only work from stage 1's fixed viewpoint; with free flight the real
// terrain and the distant islands take their place. ?backdrop=sdxl still shows them, to compare.
const backdrops = useAI ? await loadBackdrops(params.get("backdrop") || "none", manifest,
                                             { paintedSky: params.get("paintedsky") === "1" }) : null;
if (backdrops) scene.add(backdrops.group);
if (params.get("aiobjects") === "1") {
  const BEST = { temple: "temple_12", ship: "ship_11", statue: "statue_12", fountain: "fountain_12" };
  const have = Object.keys(manifest?.objects?.triposr || {});
  const load = name => (have.includes(BEST[name]) ? loadObject("triposr", BEST[name]) : null);
  const [statue, fountain] = [await load("statue"), await load("fountain")];
  if (statue) { const p = at(6, -27), s = statue(4.2); s.position.set(p.x, p.y, p.z); s.rotation.y = Math.PI / 2; scene.add(s); }
  if (fountain) { const p = at(37, 6), f = fountain(2.6); f.position.set(p.x, p.y - 0.2, p.z); scene.add(f); }
}
const smoke = makeSmoke(layout, Q.smoke);
const lanterns = new Lanterns(layout.streets, 25, Q.lights);
const clouds = makeClouds(qualityName === "low" ? 10 : 18, qualityName === "low" ? 16 : 34);
// the ground, in tiles; the first batch is built right away so the first frame is complete
const terrain = new Terrain({ finest: Q.tileRes, levels: 5, treeSpacing: Q.treeSpacing, treeLevels: Q.treeLevels });
const rivers = makeRivers(features.rivers);
const land = terrain.group;
rig.update(0, 0);
terrain.update(camera.position, { sync: true });
// the island-wide shallows for the sea, worked out in the background (waited for in screenshots)
const shoreReady = terrain.shoreMap().then(m => sea.setIslandShore(islandShoreTexture(m)));
if (params.get("shot") === "1") await shoreReady;
const distant = makeDistantIslands();
if (tex.stone) for (const k of ["stairs", "walls"]) { city.materials[k].map = tex.stone; city.materials[k].needsUpdate = true; }
if (tex.hillside) {
  // A detail map (mean 0.5, doubled), faded out beyond ~400 m: further away its 24 m repeat would
  // show as a grid of squares, and at that distance it can't be seen as texture anyway.
  terrain.material.map = tex.hillside;
  terrain.material.onBeforeCompile = shader => {
    shader.fragmentShader = shader.fragmentShader.replace("#include <map_fragment>", `
      #ifdef USE_MAP
        float detailFade = smoothstep(420.0, 160.0, length(vViewPosition));
        diffuseColor.rgb *= mix(vec3(1.0), texture2D(map, vMapUv).rgb * 2.0, detailFade);
      #endif`);
  };
}
for (const m of Object.values(city.materials)) m.needsUpdate = true;
terrain.material.needsUpdate = true;
scene.add(sky.mesh, sea.mesh, land, distant, rivers.group, city.group, makeTrees(layout), ships.group,
          smoke.points, lanterns.points, clouds.group, ...lanterns.lights);

const sunLight = new THREE.DirectionalLight(0xffffff, 2);
const hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1);
scene.add(sunLight, sunLight.target, hemi);
sunLight.target.position.set(-50, 20, -10);
if (Q.shadows) {
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(Q.shadowSize, Q.shadowSize);
  Object.assign(sunLight.shadow.camera, { left: -170, right: 170, top: 170, bottom: -170, near: 10, far: 900 });
  sunLight.shadow.bias = -0.0008;
  sunLight.shadow.normalBias = 0.6;
}

// --- per-frame updates --------------------------------------------------------------------------
function applyDay(state, time) {
  sky.uniforms.zenith.value.copy(state.zenith);
  sky.uniforms.horizon.value.copy(state.horizon);
  sky.uniforms.sunDir.value.copy(state.sun);
  sky.uniforms.sunColor.value.copy(state.sunColor);
  sky.uniforms.sunUp.value = state.sunUp;
  sky.uniforms.stars.value = state.stars;
  sky.uniforms.moonDir.value.copy(state.light);
  sky.uniforms.time.value = time;

  const s = sea.uniforms;
  s.time.value = time;
  s.sunDir.value.copy(state.sun); s.sunColor.value.copy(state.sunColor); s.sunUp.value = state.sunUp;
  s.zenith.value.copy(state.zenith); s.horizon.value.copy(state.horizon); s.ambient.value.copy(state.skyAmbient);
  s.fogColor.value.copy(state.fog); s.fogDensity.value = scene.fog.density;
  s.lightDir.value.copy(state.light); s.night.value = state.night;

  // (the sun light's position follows the camera's target: set in frame())
  sunLight.color.copy(state.sunColor);
  sunLight.intensity = state.sunPower * (state.sunUp > 0.02 ? 1.4 : 0.9);
  hemi.color.copy(state.skyAmbient);
  hemi.groundColor.copy(state.groundAmbient);
  hemi.intensity = 1.6;
  scene.fog.color.copy(state.fog);
  // the air thins as you climb: from high up the whole island should be visible, so the haze
  // fades with the camera's height (stage 1's view, ~60 m up, is unchanged)
  scene.fog.density = 0.00018 * airAbove();
}
// 1 near the ground, about a third by 1 km up, a tenth by 3 km
function airAbove() { return 1 / (1 + Math.max(0, camera.position.y - 150) / 350); }

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  camera.aspect = w / h;
  // tall phone screens: a wider lens, and aim at the city itself (there's no room for the whole bay)
  const portrait = w / h < 0.8;
  camera.fov = portrait ? 56 : 38;
  rig.setPortrait(portrait);
  camera.updateProjectionMatrix();
  painter.setSize(w, h);
}
addEventListener("resize", resize);
resize();

const hazeNear = new THREE.Color(), hazeFar = new THREE.Color(), VIOLET = new THREE.Color("#8d92b8");
let dayT = fixedTime ?? START_TIME, live = fixedTime === null, clock = 0, lastNow = performance.now(), frames = 0;
const shot = params.get("shot") === "1";
if (shot) clock = 40;   // as if the scene had been running a while
function frame(now) {
  const dt = Math.min(0.1, (now - lastNow) / 1000);
  lastNow = now;
  clock += dt;
  if (live) dayT = (dayT + dt / DAY_SECONDS) % 1;
  const state = dayState(dayT);
  applyDay(state, clock);
  rig.update(dt, clock);
  sky.follow(camera);
  sea.follow(camera);
  terrain.update(camera.position);
  // the sun's shadows cover the area round what you're looking at, wider when far away
  const reach = THREE.MathUtils.clamp(rig.view.dist * 0.55, 170, 1400);
  sunLight.target.position.copy(rig.target);
  Object.assign(sunLight.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, far: 1800 + reach * 2 });
  sunLight.shadow.camera.updateProjectionMatrix();
  sunLight.position.copy(rig.target).addScaledVector(state.light, 900 + reach);
  city.update(state);
  ships.update(clock);
  smoke.update(clock, state);
  lanterns.update(dt, clock, state);
  clouds.update(dt, state, camera);
  rivers.update(state, clock, scene.fog.density);
  labels.update(camera, rig.view.dist);
  if (backdrops) backdrops.update(state, rig.target);
  fpsCount(dt);
  // aerial perspective: near haze is the light in the air, far haze cools toward violet-blue
  hazeNear.copy(state.fog).lerp(state.horizon, 0.5);
  hazeFar.copy(state.horizon).lerp(VIOLET, 0.32).multiplyScalar(0.55 + 0.45 * state.sunUp);
  painter.render(scene, camera, { exposure: 1.12 + 0.9 * state.night, night: state.night, hazeNear, hazeFar,
                                  hazeScale: (0.00055 + 0.00025 * (1 - Math.abs(state.sun.y))) * airAbove() });
  document.getElementById("clock").textContent = timeLabel(dayT);
  frames++;
  // ?shot=1: draw a few frames (so smoke and lanterns settle), then stop, for screenshots
  if (shot && frames >= 6) { window.__corvaDone = true; return; }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// --- the little control bar ---------------------------------------------------------------------
function timeLabel(t) {
  const m = Math.round(t * 24 * 60), hh = Math.floor(m / 60) % 24, mm = m % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}
for (const btn of document.querySelectorAll("[data-time]")) {
  btn.addEventListener("click", () => {
    const k = btn.dataset.time;
    if (k === "live") live = true;
    else { live = false; dayT = TIMES[k]; }
    document.querySelectorAll("[data-time]").forEach(b => b.setAttribute("aria-pressed", b === btn));
  });
}
const qsel = document.getElementById("quality");
qsel.value = qualityName;
qsel.addEventListener("change", () => { safeSet("corva-quality", qsel.value); location.search = `?q=${qsel.value}`; });
// ?fps (or ?fps=1): an on-screen frame counter (frames per second, averaged over a second).
// It shows "measuring…" at once, so you can tell the counter is on before the first second is up.
const fpsEl = params.has("fps") && params.get("fps") !== "0"
  ? Object.assign(document.createElement("div"), { id: "fps", textContent: "measuring…" }) : null;
if (fpsEl) document.body.append(fpsEl);
let fpsFrames = 0, fpsTime = 0, fpsValue = 0;
function fpsCount(dt) {
  fpsFrames++; fpsTime += dt;
  if (fpsTime >= 1) { fpsValue = fpsFrames / fpsTime; fpsFrames = 0; fpsTime = 0; if (fpsEl) fpsEl.textContent = `${fpsValue.toFixed(0)} fps · ${qualityName}`; }
}
// Place names: tap one to fly there
const labels = makeLabels([
  { name: "Corva", kind: "city", x: CITY.x, z: CITY.z, y: heightAt(CITY.x, CITY.z) + 30 },
  ...features.villages.map(v => ({ name: v.name, kind: "village", x: v.x, z: v.z, y: heightAt(v.x, v.z) })),
  { name: features.mountain.name, kind: "mountain", x: features.mountain.x, z: features.mountain.z,
    y: heightAt(features.mountain.x, features.mountain.z) },
], p => (p.kind === "city" ? rig.home() : rig.flyTo({ x: p.x, z: p.z, dist: p.kind === "mountain" ? 2600 : 520, el: 0.3 })));
// "Corva": fly home to the city
document.getElementById("home")?.addEventListener("click", () => rig.home());
// a one-time hint on how to fly, gone after the first touch (or 9 s)
const hint = document.getElementById("hint");
if (hint && !shot) {
  const hide = () => hint.classList.add("gone");
  canvas.addEventListener("pointerdown", hide, { once: true });
  setTimeout(hide, 9000);
} else hint?.remove();
window.__corva = { layout, features, renderer, rig, terrain, fps: () => fpsValue, setTime: t => { live = false; dayT = t; } };   // for tests
