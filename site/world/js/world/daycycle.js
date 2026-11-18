// The day: time 0..1 (0 = midnight, 0.25 = sunrise, 0.5 = noon, 0.75 = sunset) -> the light.
//
// The sun rises behind the mountains and sets at the far end of the bay, low over the water, as in
// the reference painting; the viewer looks up the coast toward it with the city on the left. Colours are
// keyframes, blended smoothly; they were picked from the reference and the canonical Corva.

import * as THREE from "../../vendor/three.module.min.js";

const KEYS = [
  // t,    zenith,    horizon,   sun colour, sun power, ambient sky, ambient ground, fog colour
  [0.00, "#0a1430", "#24305a", "#9fb2e8", 0.55, "#33497e", "#141822", "#1e2a4c"],  // midnight (moonlight)
  [0.20, "#0e1834", "#323556", "#9aaadc", 0.45, "#34466f", "#151820", "#262c4a"],
  [0.25, "#2c3f6e", "#c98a7c", "#ff9a6a", 0.55, "#4a5272", "#2a2420", "#9c7d82"],  // first light
  [0.29, "#4b6c9e", "#f0b08c", "#ffb27e", 1.25, "#7d8aa8", "#4a3c30", "#d6aa90"],  // dawn
  [0.36, "#5d8cc0", "#e6d3b2", "#fff0d6", 2.20, "#9ab0cc", "#5c5240", "#cfc8b8"],  // morning
  [0.50, "#6a9acb", "#dcd9c8", "#fff8ec", 2.70, "#a8bfd6", "#6a604c", "#cfd2cc"],  // noon
  [0.66, "#4a80bd", "#ead6a8", "#ffe7bc", 2.40, "#a2b2c6", "#6c5c44", "#d8ccb0"],
  [0.73, "#2f6db8", "#ffc785", "#ffbc70", 2.60, "#9aa6c0", "#6a5238", "#e6c6a2"],  // golden hour (a clear blue overhead, as in the painting)
  [0.785, "#3e507f", "#f28d5c", "#ff8448", 1.10, "#6a6888", "#4a3428", "#c8866a"], // sunset
  [0.83, "#1e2650", "#704a6e", "#b07090", 0.35, "#38375a", "#1e1a20", "#4c3a52"],  // dusk
  [0.90, "#0b1430", "#262f58", "#9fb2e8", 0.50, "#304476", "#13161f", "#1e2a4a"],  // night
  [1.00, "#0a1430", "#24305a", "#9fb2e8", 0.55, "#33497e", "#141822", "#1e2a4c"],
];
const COLS = KEYS.map(k => k.map(v => (typeof v === "string" ? new THREE.Color(v) : v)));

const tmp = new THREE.Color();
function lerpKey(t, index) {
  let i = 0;
  while (i < COLS.length - 2 && COLS[i + 1][0] <= t) i++;
  const a = COLS[i], b = COLS[i + 1];
  const f = THREE.MathUtils.smoothstep(t, a[0], b[0]);
  if (typeof a[index] === "number") return a[index] + (b[index] - a[index]) * f;
  return tmp.copy(a[index]).lerp(b[index], f).clone();
}

export function sunDirection(t, out = new THREE.Vector3()) {
  const a = (t - 0.25) * Math.PI * 2;           // 0 at sunrise, pi at sunset
  const c = Math.cos(a);
  // Rises in the north-east behind the mountains, crosses the south at noon, and sets in the
  // north-west at the far end of the bay, where the viewer on the south shore can see it.
  return out.set(-c, Math.sin(a) * 0.92, -2.4 * c * c + 0.4 * Math.sin(a)).normalize();
}

// Everything the scene needs to know about the light at time t.
export function dayState(t) {
  t = ((t % 1) + 1) % 1;
  const sun = sunDirection(t);
  const sunUp = THREE.MathUtils.smoothstep(sun.y, -0.08, 0.10);   // 0 night .. 1 day
  // At night the main light is the moon, opposite the sun and a little higher.
  const light = sunUp > 0.02 ? sun.clone() : sun.clone().negate().setY(Math.abs(sun.y) * 0.6 + 0.35).normalize();
  return {
    t, sun, light, sunUp,
    night: 1 - THREE.MathUtils.smoothstep(sun.y, -0.12, 0.02),    // lanterns and windows
    zenith: lerpKey(t, 1), horizon: lerpKey(t, 2),
    sunColor: lerpKey(t, 3), sunPower: lerpKey(t, 4),
    skyAmbient: lerpKey(t, 5), groundAmbient: lerpKey(t, 6), fog: lerpKey(t, 7),
    stars: 1 - THREE.MathUtils.smoothstep(sun.y, -0.2, 0.0),
  };
}

export const TIMES = { dawn: 0.285, golden: 0.735, night: 0.95, noon: 0.5 };
