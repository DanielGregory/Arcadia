// The world engine's sandbox, shown on the island: /world/?world=sandbox
//
// Everything here READS the sandbox_* tables (Supabase, publishable key: read-only). The engine
// writes them (world/publish.py, after each season); this page never writes anything.
//
//   estates   each house's land: a coloured ring draped on the ground, and its name. The positions
//             are PROPOSED (world/placements.py), so every estate label says so.
//   lanterns  one per person who is on the island, at the place the engine says they are now,
//             in their house's colour. Tap one: name, house, latest dream, beliefs about the Flight.
//   season    the engine's current season sets the light (a pale spring sun, a hard summer one, a
//             low amber autumn, a grey winter) and the colour of the leaves and grass.
//   events    what happened this season, where it happened: guards with torches at a gate, a
//             search party with lights, a crowd at the council hall, a fire for a feast. Little
//             figures in the actors' house colours, and a label you can tap for the event's words.
//
// The absent (Livia and Soren) have no lantern: where they are is sealed.

import * as THREE from "../vendor/three.module.min.js";
import { heightAt } from "./world/terrain.js";

const SUPABASE_URL = "https://dbrtvwhslxkdpmuawrgd.supabase.co";
const SUPABASE_KEY = "sb_publishable_NVNYh69hEq2uJKfWOvlAkg_9RCInRey";

async function table(name, query = "select=*") {
  const out = [];
  for (let from = 0; ; from += 1000) {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/${name}?${query}`, {
      headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}`, Range: `${from}-${from + 999}` } });
    if (!r.ok) throw new Error(`${name}: ${r.status}`);
    const page = await r.json();
    out.push(...page);
    if (page.length < 1000) return out;
  }
}

export async function loadSandbox() {
  const [world, places, houses, people, events, beliefs, dreams] = await Promise.all([
    table("sandbox_world"), table("sandbox_places"), table("sandbox_houses"), table("sandbox_people"),
    table("sandbox_events", "select=*&order=id"), table("sandbox_beliefs", "select=*&order=id"),
    table("sandbox_dreams", "select=id,year,season,dreamer_id,text,retelling,recalled,discussed&order=id"),
  ]);
  return { world: world[0], places, houses, people, events, beliefs, dreams };
}

// --- the season: light and foliage -------------------------------------------------------------
// sun: multiplies the sun's colour; power: its strength; foliage: the colour green things lean to,
// and how far (0..1). Spring's green is fresh, summer's is burnt gold, autumn's is rust, winter's grey.
const SEASONS = {
  spring: { sun: "#fff4e6", power: 0.95, ambient: 1.05, foliage: "#6fae4a", amount: 0.35 },
  summer: { sun: "#fff0c8", power: 1.12, ambient: 1.0, foliage: "#b9a35a", amount: 0.4 },
  autumn: { sun: "#ffc890", power: 0.9, ambient: 0.95, foliage: "#b8682e", amount: 0.5 },
  winter: { sun: "#d8e2ff", power: 0.7, ambient: 0.9, foliage: "#8a8c7c", amount: 0.55 },
};

// Patch a material so its green parts (leaves, grass) lean toward the season's colour. "Green" is
// measured from the colour itself: how much the green channel stands above red and blue. Stone,
// plaster and earth are left alone. Any existing onBeforeCompile (the hillside detail map) is kept.
export function seasonize(material, season) {
  const S = SEASONS[season] || SEASONS.spring;
  const before = material.onBeforeCompile;
  material.onBeforeCompile = (shader, renderer) => {
    before?.call(material, shader, renderer);
    shader.uniforms.seasonColor = { value: new THREE.Color(S.foliage) };
    shader.uniforms.seasonAmount = { value: S.amount };
    shader.fragmentShader = "uniform vec3 seasonColor;\nuniform float seasonAmount;\n" + shader.fragmentShader.replace(
      "#include <color_fragment>", `#include <color_fragment>
      {
        float green = clamp((diffuseColor.g - max(diffuseColor.r, diffuseColor.b) * 0.92) * 6.0, 0.0, 1.0);
        float lum = dot(diffuseColor.rgb, vec3(0.3, 0.55, 0.15));
        diffuseColor.rgb = mix(diffuseColor.rgb, seasonColor * (lum / 0.42), green * seasonAmount);
      }`);
  };
  material.customProgramCacheKey = () => "season-" + season + (material.map ? "-map" : "");
  material.needsUpdate = true;
}

// --- helpers ---------------------------------------------------------------------------------------
function hash(n) { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); }
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// a ribbon round a circle, lying on the ground (so an estate's edge follows hills and valleys)
function ringRibbon(cx, cz, r, width, color) {
  const n = Math.max(48, Math.min(240, Math.round(r / 6))), pos = [], idx = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2;
    for (const k of [-0.5, 0.5]) {
      const rr = r + k * width, x = cx + Math.cos(a) * rr, z = cz + Math.sin(a) * rr;
      pos.push(x, Math.max(heightAt(x, z), 0) + 0.8 + r * 0.002, z);
    }
    if (i < n) { const j = i * 2; idx.push(j, j + 1, j + 2, j + 1, j + 3, j + 2); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.75, depthWrite: false, side: THREE.DoubleSide,
                                          polygonOffset: true, polygonOffsetFactor: -4 });
  return new THREE.Mesh(g, m);
}

// a soft round dot for the lanterns (drawn once into a canvas)
function dotTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d"), grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(255,255,255,1)"); grad.addColorStop(0.25, "rgba(255,255,255,.95)");
  grad.addColorStop(0.5, "rgba(255,255,255,.35)"); grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// how many figures an event of each kind puts on the ground, how they stand, and whether there's a fire
const EVENT_LOOK = {
  guard: { n: 6, form: "line", torches: 2, verb: "Guards" },
  search: { n: 8, form: "scatter", torches: 4, verb: "A search" },
  gathering: { n: 14, form: "ring", fire: true, verb: "A gathering" },
  festival: { n: 18, form: "ring", fire: true, verb: "A festival" },
  feast: { n: 16, form: "ring", fire: true, verb: "A feast" },
  petition: { n: 9, form: "crowd", verb: "A petition" },
  testimony: { n: 7, form: "crowd", verb: "Testimony" },
  judgment: { n: 10, form: "crowd", verb: "A judgment" },
  accuse: { n: 7, form: "crowd", verb: "An accusation" },
  pray: { n: 6, form: "line", torches: 1, verb: "Prayers" },
  work_land: { n: 8, form: "scatter", verb: "Work on the land" },
  default: { n: 5, form: "crowd", verb: "" },
};

// --- the whole sandbox layer -----------------------------------------------------------------------
export function makeSandbox(data, { onFly } = {}) {
  const { world, places, houses, people, events, beliefs, dreams } = data;
  const group = new THREE.Group();
  const placeById = new Map(places.map(p => [p.id, p]));
  const houseById = new Map(houses.map(h => [h.id, h]));
  const color = id => houseById.get(id)?.color || "#f4e3b0";
  const flight = events.find(e => e.kind === "departure");

  // estates: a ring round each house's land, with its name above it
  const labels = [];
  for (const h of houses) {
    if (h.estate_x == null) continue;
    const r = h.estate_radius || 20;
    group.add(ringRibbon(h.estate_x, h.estate_z, r, Math.max(1.2, r * 0.018), h.color));
    labels.push({ kind: "estate", x: h.estate_x, z: h.estate_z, y: heightAt(h.estate_x, h.estate_z) + Math.min(60, 12 + r * 0.08),
                  near: Math.max(120, r * 1.5), far: Math.max(2500, r * 12),
                  html: `<i style="background:${esc(h.color)}"></i>House ${esc(h.name)}<small>estate · proposed</small>`,
                  pick: () => showHouse(h) });
  }

  // lanterns: everyone on the island, at their place (a little scatter so a household isn't one dot)
  const present = people.filter(p => !p.absent && p.alive && p.place_id != null && placeById.get(p.place_id)?.x != null);
  const atPlace = new Map();
  const pos = [], col = [], lit = [];
  const c = new THREE.Color();
  for (const p of present) {
    const pl = placeById.get(p.place_id);
    const k = atPlace.get(pl.id) || 0;
    atPlace.set(pl.id, k + 1);
    const city = Math.hypot(pl.x, pl.z) < 400;                  // inside Corva everything is close together
    const a = k * 2.399 + hash(p.id) * 0.6, rr = (city ? 2.2 : 9) * Math.sqrt(k + 0.5);
    const x = pl.x + Math.cos(a) * rr, z = pl.z + Math.sin(a) * rr;
    const y = Math.max(heightAt(x, z), 0.5) + 2.4;
    pos.push(x, y, z);
    c.set(color(p.house_id));
    col.push(c.r, c.g, c.b);
    lit.push({ p, v: new THREE.Vector3(x, y, z) });
  }
  const lg = new THREE.BufferGeometry();
  lg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  lg.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  const lanternMat = new THREE.PointsMaterial({ size: 13, sizeAttenuation: false, map: dotTexture(), vertexColors: true,
                                                transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const lanterns = new THREE.Points(lg, lanternMat);
  lanterns.renderOrder = 5;
  group.add(lanterns);

  // this season's events, where they happened
  const latest = events.filter(e => e.year === world.year && e.season === world.season);
  const figGeo = new THREE.CylinderGeometry(0.28, 0.36, 1.7, 6);
  figGeo.translate(0, 0.85, 0);
  const figures = [], torches = [], fires = [];
  const seenPlace = new Map();
  for (const e of latest) {
    const pl = placeById.get(e.place_id);
    if (!pl || pl.x == null) continue;
    const L = EVENT_LOOK[e.kind] || EVENT_LOOK.default;
    const k = seenPlace.get(pl.id) || 0;                   // a second event at the same place stands beside the first
    seenPlace.set(pl.id, k + 1);
    const city = Math.hypot(pl.x, pl.z) < 400;
    const ox = pl.x + (k ? Math.cos(k * 2.1) * (city ? 9 : 30) : 0), oz = pl.z + (k ? Math.sin(k * 2.1) * (city ? 9 : 30) : 0);
    const hc = color(e.houses?.[0]);
    for (let i = 0; i < L.n; i++) {
      let dx, dz;
      if (L.form === "line") { dx = (i - L.n / 2) * 1.4; dz = 0; }
      else if (L.form === "ring") { const a = (i / L.n) * Math.PI * 2; dx = Math.cos(a) * 4.5; dz = Math.sin(a) * 4.5; }
      else if (L.form === "scatter") { dx = (hash(e.id * 31 + i) - 0.5) * 26; dz = (hash(e.id * 17 + i) - 0.5) * 26; }
      else { dx = (hash(e.id * 7 + i) - 0.5) * 7; dz = (hash(e.id * 13 + i) - 0.5) * 7; }
      const x = ox + dx, z = oz + dz;
      figures.push({ x, y: Math.max(heightAt(x, z), 0.3), z, color: i < 2 ? hc : (i % 3 ? "#5b4a3a" : hc) });
      if (i < (L.torches || 0)) torches.push(new THREE.Vector3(x + 0.4, Math.max(heightAt(x, z), 0.3) + 2.3, z));
    }
    if (L.fire) fires.push(new THREE.Vector3(ox, Math.max(heightAt(ox, oz), 0.3), oz));
    labels.push({ kind: "event", x: ox, z: oz, y: Math.max(heightAt(ox, oz), 0) + 9, near: 30, far: 1800,
                  html: `⚑ ${esc(L.verb || e.kind)}<small>${esc(pl.name)}</small>`, pick: () => showEvent(e, pl) });
  }
  if (figures.length) {
    const fm = new THREE.MeshLambertMaterial({ color: "#ffffff" });
    const inst = new THREE.InstancedMesh(figGeo, fm, figures.length);
    const m = new THREE.Matrix4();
    figures.forEach((f, i) => { m.makeTranslation(f.x, f.y, f.z); inst.setMatrixAt(i, m); inst.setColorAt(i, c.set(f.color)); });
    inst.castShadow = true;
    group.add(inst);
  }
  // torches and fires: small hot points (and the fires a cone of flame)
  if (torches.length) {
    const tg = new THREE.BufferGeometry().setFromPoints(torches);
    group.add(new THREE.Points(tg, new THREE.PointsMaterial({ size: 7, sizeAttenuation: false, map: lanternMat.map, color: "#ffb347",
                                                              transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })));
  }
  const flames = [];
  for (const f of fires) {
    const flame = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.6, 7), new THREE.MeshBasicMaterial({ color: "#ffa040" }));
    flame.position.set(f.x, f.y + 1.3, f.z);
    group.add(flame);
    flames.push(flame);
  }

  // --- labels (estates and events): HTML pinned to the world -------------------------------------
  const layer = document.createElement("div");
  layer.className = "labels sandbox-labels";
  document.body.append(layer);
  for (const l of labels) {
    l.el = document.createElement("button");
    l.el.className = `sb-label ${l.kind}`;
    l.el.innerHTML = l.html;
    l.el.addEventListener("click", ev => { ev.stopPropagation(); l.pick(); });
    layer.append(l.el);
  }

  // --- the panel (a person, a house, an event) ----------------------------------------------------
  const panel = document.createElement("aside");
  panel.id = "sbPanel";
  panel.hidden = true;
  document.body.append(panel);
  const show = html => { panel.innerHTML = `<button class="close" aria-label="Close">×</button>${html}`; panel.hidden = false;
                         panel.querySelector(".close").onclick = () => (panel.hidden = true); };

  function showPerson(p) {
    const h = houseById.get(p.house_id), pl = placeById.get(p.place_id);
    const mine = dreams.filter(d => d.dreamer_id === p.id);
    const dream = mine[mine.length - 1];
    const fb = flight ? beliefs.filter(b => b.holder_id === p.id && b.subject_type === "event" && String(b.subject_id) === String(flight.id))
                              .sort((a, b) => b.confidence - a.confidence) : [];
    show(`
      <p class="who"><i style="background:${esc(h?.color)}"></i>${esc(p.name)}</p>
      <p class="sub">${h ? "House " + esc(h.name) : "no house"}${p.role ? " · " + esc(p.role) : ""}${p.tier ? " · " + esc(p.tier) : ""}
         ${p.proposed ? " · <em>placeholder (proposed)</em>" : ""}</p>
      <p class="sub">Now at ${esc(pl?.name || "?")}</p>
      <h4>Latest dream${dream ? ` <small>${esc(dream.season)}, year ${dream.year}${dream.recalled ? "" : " · forgotten on waking"}</small>` : ""}</h4>
      ${dream ? `<p class="dream">${esc(dream.retelling || dream.text.slice(0, 420) + (dream.text.length > 420 ? "…" : ""))}</p>
                 ${dream.retelling ? `<p class="sub">(as they tell it; the dream itself was stranger)</p>` : ""}`
              : `<p class="sub">No dream yet.</p>`}
      <h4>What they believe about the Flight</h4>
      ${fb.length ? fb.map(b => `<p class="belief"><span>${Math.round(b.confidence * 100)}%</span>${esc(b.interpretation)}</p>`).join("")
                  : `<p class="sub">Nothing they hold to.</p>`}`);
  }
  function showHouse(h) {
    const members = people.filter(p => p.house_id === h.id);
    const head = people.find(p => p.id === h.head_id);
    show(`
      <p class="who"><i style="background:${esc(h.color)}"></i>House ${esc(h.name)}</p>
      <p class="sub">${esc(h.claim)}${h.proposed ? " · <em>placeholder family (proposed)</em>" : ""}</p>
      <p class="sub">${esc(h.land)}</p>
      <p class="sub">Head: ${esc(head?.name || "?")} · ${members.length} in the house · food ${Math.round(h.food)}</p>
      <p class="sub"><em>Where the estate is drawn is PROPOSED: a guess to be moved.</em></p>`);
    onFly?.({ x: h.estate_x, z: h.estate_z, dist: Math.max(260, (h.estate_radius || 20) * 4), el: 0.45 });
  }
  function showEvent(e, pl) {
    const names = (e.actors || []).map(id => people.find(p => p.id === id)?.name).filter(Boolean);
    show(`
      <p class="who">${esc((EVENT_LOOK[e.kind] || {}).verb || e.kind)} at ${esc(pl.name)}</p>
      <p class="sub">${esc(e.season)}, year ${e.year} · ${esc(e.outcome || "")}${names.length ? " · " + esc(names.join(", ")) : ""}</p>
      <p class="dream">${esc(e.text)}</p>`);
  }

  // tap a lantern: the nearest one on screen within a finger's width
  const v = new THREE.Vector3();
  function tap(clientX, clientY, camera) {
    let best = null;
    for (const l of lit) {
      v.copy(l.v).project(camera);
      if (v.z > 1) continue;
      const sx = ((v.x + 1) / 2) * innerWidth, sy = ((1 - v.y) / 2) * innerHeight, d = Math.hypot(sx - clientX, sy - clientY);
      if (d < 22 && (!best || d < best.d)) best = { d, l };
    }
    if (!best) return false;
    showPerson(best.l.p);
    return true;
  }

  // the season's light: applied on top of the day cycle each frame
  const S = SEASONS[world.season] || SEASONS.spring;
  const sunTint = new THREE.Color(S.sun);
  function light({ sunLight, hemi }) {
    sunLight.color.multiply(sunTint);
    sunLight.intensity *= S.power;
    hemi.intensity *= S.ambient;
  }

  function update(camera, state, time) {
    // lanterns are brightest at night, but always visible (they are how you find people)
    lanternMat.size = (11 + 5 * state.night) * Math.min(devicePixelRatio || 1, 2);
    lanternMat.opacity = 0.75 + 0.25 * state.night;
    for (const f of flames) f.scale.y = 0.85 + 0.25 * Math.sin(time * 9 + f.position.x);
    const w = innerWidth, h = innerHeight;
    for (const l of labels) {
      v.set(l.x, l.y, l.z);
      const d = camera.position.distanceTo(v);
      v.project(camera);
      let a = THREE.MathUtils.smoothstep(d, l.near * 0.5, l.near) * (1 - THREE.MathUtils.smoothstep(d, l.far, l.far * 1.6));
      if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) a = 0;
      l.el.style.opacity = a.toFixed(2);
      l.el.style.visibility = a < 0.03 ? "hidden" : "visible";
      if (a >= 0.03) l.el.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px) translate(-50%, -100%)`;
    }
  }

  const title = `Sandbox · ${world.season[0].toUpperCase() + world.season.slice(1)}, year ${world.year} · ${present.length} people`;
  return { group, update, tap, light, title, season: world.season };
}
