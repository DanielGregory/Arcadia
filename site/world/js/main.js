// Corva, living: stage 1. Wires the pieces together and runs the loop.
//
//   world/   pure data: terrain function, city layout, day cycle (no rendering)
//   scene/   builders that turn that data into three.js objects
//   render/  the painterly post-process
//   camera.js the drift rig
//
// Stage 2 (a larger land to fly over) swaps the rig and widens the terrain; stage 3 (buildings,
// people and weather from the world tables) swaps generateLayout() for a layout read from
// Supabase. Neither needs this file restructured.

import * as THREE from "../vendor/three.module.min.js";
import { QUALITY, params, chooseQuality, safeSet, DAY_SECONDS, START_TIME } from "./config.js";
import { generateLayout } from "./world/layout.js";
import { dayState, TIMES } from "./world/daycycle.js";
import { makeSky, makeSea, shoreTexture } from "./scene/skysea.js";
import { heightAt } from "./world/terrain.js";
import { makeLand } from "./scene/land.js";
import { makeCity, makeTrees } from "./scene/city.js";
import { makeShips, makeSmoke, Lanterns, makeClouds } from "./scene/life.js";
import { Painter } from "./render/painterly.js";
import { DriftRig } from "./camera.js";
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
const camera = new THREE.PerspectiveCamera(38, 1, 1, 9000);
const rig = new DriftRig(camera, canvas, { still: params.get("still") === "1" });
const painter = new Painter(renderer, Q);

// --- the world ----------------------------------------------------------------------------------
const layout = generateLayout(seed, qualityName);
// AI-made assets (render/make_assets.py): ?ai=1 (default) or ?ai=0 for the hand-built world only;
// ?backdrop=sdxl|corva|none picks the painted backdrop set.
const useAI = params.get("ai") !== "0";
const manifest = useAI ? await loadManifest() : null;
const objModel = params.get("model") || "triposr";
const aiObj = {};
for (const name of ["temple", "ship", "statue", "fountain"]) {
  const pick = manifest?.objects?.[objModel] && Object.keys(manifest.objects[objModel]).find(k => k.startsWith(name));
  aiObj[name] = pick ? await loadObject(objModel, pick) : null;
}
const sky = makeSky(), sea = makeSea(shoreTexture(heightAt));
// the AI temple replaces the hand-built summit temple (the first in the layout)
const city = makeCity(aiObj.temple ? { ...layout, temples: layout.temples.slice(1) } : layout, Q, seed);
const ships = makeShips(layout, aiObj.ship ? () => { const s = aiObj.ship(5.5); s.rotation.y = Math.PI / 2; return s; } : null);
const backdrops = useAI ? await loadBackdrops(params.get("backdrop") || "sdxl", manifest) : null;
if (backdrops) scene.add(backdrops.group);
if (aiObj.temple) {
  const t = layout.temples[0];
  const temple = aiObj.temple(11 * t.scale);
  temple.position.set(t.x, t.y - 0.5, t.z);
  temple.rotation.y = t.rot + Math.PI / 2;
  scene.add(temple);
}
if (aiObj.statue) {   // on the quay in front of the quay temple
  const p = at(6, -27), s = aiObj.statue(4.2);
  s.position.set(p.x, p.y, p.z);
  s.rotation.y = Math.PI / 2;
  scene.add(s);
}
if (aiObj.fountain) {   // in a little square halfway up the town
  const p = at(37, 6), f = aiObj.fountain(2.6);
  f.position.set(p.x, p.y - 0.2, p.z);
  scene.add(f);
}
const smoke = makeSmoke(layout, Q.smoke);
const lanterns = new Lanterns(layout.streets, 25, Q.lights);
const clouds = makeClouds(qualityName === "low" ? 10 : 18);
const land = makeLand(Q.terrain);
const tex = useAI ? await loadTextures(manifest) : {};
if (tex.plaster) for (const k of ["houses", "uppers"]) city.materials[k].map = tex.plaster;
if (tex.terracotta) city.materials.roofs.map = tex.terracotta, city.materials.roofs.color.set("#ffffff");
if (tex.stone) for (const k of ["stairs", "walls", "blocks"]) city.materials[k].map = tex.stone;
if (tex.hillside) { land.material.map = tex.hillside; land.material.color.setScalar(2.0); }   // a detail map, mean 0.5
for (const m of Object.values(city.materials)) m.needsUpdate = true;
land.material.needsUpdate = true;
scene.add(sky.mesh, sea.mesh, land, city.group, makeTrees(layout), ships.group,
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

  sunLight.position.copy(sunLight.target.position).addScaledVector(state.light, 500);
  sunLight.color.copy(state.sunColor);
  sunLight.intensity = state.sunPower * (state.sunUp > 0.02 ? 1.4 : 0.9);
  hemi.color.copy(state.skyAmbient);
  hemi.groundColor.copy(state.groundAmbient);
  hemi.intensity = 1.6;
  scene.fog.color.copy(state.fog);
  // a little denser haze at dawn and golden hour, when the light lies along the bay
  scene.fog.density = 0.00018;
}

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
  city.update(state);
  ships.update(clock);
  smoke.update(clock, state);
  lanterns.update(dt, clock, state);
  clouds.update(dt, state);
  if (backdrops) backdrops.update(state, rig.target);
  fpsCount(dt);
  // aerial perspective: near haze is the light in the air, far haze cools toward violet-blue
  hazeNear.copy(state.fog).lerp(state.horizon, 0.5);
  hazeFar.copy(state.horizon).lerp(VIOLET, 0.32).multiplyScalar(0.55 + 0.45 * state.sunUp);
  painter.render(scene, camera, { exposure: 1.12 + 0.9 * state.night, night: state.night, hazeNear, hazeFar,
                                  hazeScale: 0.00055 + 0.00025 * (1 - Math.abs(state.sun.y)) });
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
// ?fps=1: an on-screen frame counter (frames per second, averaged over a second)
const fpsEl = params.get("fps") === "1" ? Object.assign(document.createElement("div"), { id: "fps" }) : null;
if (fpsEl) document.body.append(fpsEl);
let fpsFrames = 0, fpsTime = 0, fpsValue = 0;
function fpsCount(dt) {
  fpsFrames++; fpsTime += dt;
  if (fpsTime >= 1) { fpsValue = fpsFrames / fpsTime; fpsFrames = 0; fpsTime = 0; if (fpsEl) fpsEl.textContent = `${fpsValue.toFixed(0)} fps · ${qualityName}`; }
}
window.__corva = { layout, renderer, fps: () => fpsValue, setTime: t => { live = false; dayT = t; } };   // for tests
