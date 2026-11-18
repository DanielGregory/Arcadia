// The island of Corva as a pure function: heightAt(x, z) -> metres above the sea.
//
// Axes: x runs east (-) to west (+), z runs north (-) to south (+), y is up; the sea is y = 0.
// One metre is one unit.
//
// The island is about 8 km across. Its centre lies ~3.8 km east of the city; a mountain of about
// 1,200 m rises near the middle, with ridges running out from it. The city of Corva sits on the
// west coast, on a bay that opens west to the sunset (as in the reference painting).
//
// Two shapes are blended:
//   - near the city (within ~700 m), the hand-tuned bay of stage 1: coastX(z), the city's hill and
//     the summit, so the city layout and the first view are unchanged;
//   - everywhere else, the island: a coastline that wobbles round a circle (noise sampled round the
//     circle, so it closes on itself), and land that climbs toward the central mountain.
// Between 700 m and 1.5 km from the city one fades into the other, which turns the bay's two arms
// into headlands.
//
// Everything that sits on the ground (buildings, trees, the camera) asks heightAt(), so nothing
// that uses it needed to change when the land grew from a bay into an island.

import { riverAt } from "./featuremap.js";

export const SEA_LEVEL = 0;

// --- tiny deterministic noise (value noise + fractal sum) -----------------------------------
function hash(ix, iz) {
  let h = ix * 374761393 + iz * 668265263;
  h = (h ^ (h >>> 13)) * 1274126177;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}
function smooth(t) { return t * t * (3 - 2 * t); }
export function noise(x, z) {
  const ix = Math.floor(x), iz = Math.floor(z), fx = smooth(x - ix), fz = smooth(z - iz);
  const a = hash(ix, iz), b = hash(ix + 1, iz), c = hash(ix, iz + 1), d = hash(ix + 1, iz + 1);
  return a + (b - a) * fx + (c - a) * fz + (a - b - c + d) * fx * fz;  // 0..1
}
export function fbm(x, z, octaves = 5) {
  let sum = 0, amp = 0.5, f = 1;
  for (let i = 0; i < octaves; i++) { sum += amp * noise(x * f, z * f); f *= 2.03; amp *= 0.5; }
  return sum;  // ~0..1
}

// --- the island ---------------------------------------------------------------------------------
export const ISLAND = { cx: -3700, cz: 300, r: 3600 };     // centre and typical radius of the coast
export const PEAK = { x: -4100, z: 600 };                   // the central mountain
export const CITY = { x: -60, z: 0 };                       // the middle of Corva
// The island's extent with its shallows, for anything that needs a box round it (tiles, maps).
export const BOUNDS = { minX: -8800, maxX: 1600, minZ: -6400, maxZ: 7000 };

// Distance from the island's centre to its coast, in direction theta. The island is stretched
// north-south (about 9.5 km long, 6.5 km wide). Noise is read at points on a circle (cos, sin), so
// the coast closes on itself with no seam: big bulges and bays, then capes and coves on top.
function islandRadius(theta) {
  const c = Math.cos(theta), s = Math.sin(theta);
  const ellipse = 1 / Math.hypot(c / 0.85, s / 1.3);
  const big = fbm(c * 1.4 + 4.2, s * 1.4 - 2.7, 3);
  const small = fbm(c * 7.0 + 1.1, s * 7.0 + 7.3, 3);
  let r = ISLAND.r * ellipse * (0.78 + 0.44 * big + 0.22 * (small - 0.5));
  // toward the city, pull the coast out to meet the bay (whose shore is at x ~ 10), a little
  // beyond it so the bay's arms become headlands
  let dt = theta - TO_CITY;
  dt = Math.atan2(Math.sin(dt), Math.cos(dt));
  return r + (AT_CITY + 250 - r) * Math.exp(-((dt / 0.42) ** 2));
}
const TO_CITY = Math.atan2(CITY.z - ISLAND.cz, 10 - ISLAND.cx);
const AT_CITY = Math.hypot(10 - ISLAND.cx, CITY.z - ISLAND.cz);

// How much of the city's hand-made bay applies here: 1 near the city, 0 beyond ~1.5 km.
// The zone is stretched along the coast and its edge is roughened with noise, so the city's
// ranges trail off into the island's hills instead of ending in a neat semicircle.
export function localWeight(x, z) {
  const d = Math.hypot(x - CITY.x, (z - CITY.z) * 0.7) + 700 * (fbm(x * 0.0016 + 5.5, z * 0.0016 - 8.1, 3) - 0.5);
  return 1 - smooth(Math.min(1, Math.max(0, (d - 700) / 800)));
}

// --- the shape of the land --------------------------------------------------------------------
// The shoreline: land is where x < coastX(z). A gentle curve makes the bay; it bends out to sea
// to the north and south so the bay is held between two arms.
export function coastX(z) {
  // The south arm (z > 0) curls round behind the viewer; the north shore bends away more gently,
  // so the bay opens to the sea and the sunset beyond the far end of the city.
  return 10 + (z > 0 ? 0.0028 : 0.0011) * z * z - 6 * Math.sin(z / 37);
}

// How far inland a point is, in metres (negative = out at sea): the city's bay blended into the
// island's coast. (The bay's two arms are capped so they turn into headlands, not long spits.)
export function inland(x, z) {
  const w = localWeight(x, z);
  const bay = Math.min(coastX(z), 420) - x;
  if (w >= 1) return bay;
  const dx = x - ISLAND.cx, dz = z - ISLAND.cz;
  const island = islandRadius(Math.atan2(dz, dx)) - Math.hypot(dx, dz);
  return w <= 0 ? island : w * bay + (1 - w) * island;
}

// The sea floor: shelves down away from the shore.
function seaFloor(x, z, s) { return Math.max(-14, s * 0.35) + fbm(x * 0.05, z * 0.05, 2) * 1.5; }

// Stage 1's land round the bay: the quay, the city's hill and summit, and the ranges behind it
// receding up the north shore. (Lowered by a third in step B: built as a backdrop for one fixed
// view, from the air they stood as a 700 m wall behind the city.)
function bayLand(x, z, s) {
  const hill = 52 * (1 - Math.exp(-Math.max(0, s - 8) / 55));
  const summit = 10 * Math.exp(-((x + 105) ** 2 + (z + 14) ** 2) / 900);
  const start = 250 + Math.max(0, -z - 80) * 0.55;
  const m = Math.max(0, s - start);
  const ridge = Math.pow(fbm(x * 0.006 + 3.1, z * 0.009 - 1.7, 5), 1.6);
  const peaks = Math.pow(1 - Math.abs(fbm(x * 0.004 - 5.3, z * 0.004 + 2.2, 3) * 2 - 1), 3);   // sharp ridgelines
  const far = Math.pow(1 - Math.abs(fbm(x * 0.0022 + 9.1, z * 0.0022 - 4.4, 3) * 2 - 1), 4);      // the distant ranges
  const mountains = m > 0 ? (m * 0.3 + 110 * ridge + 120 * peaks + 150 * far * smooth(Math.min(1, m / 600)))
                           * smooth(Math.min(1, m / 260)) : 0;
  return hill + summit + mountains;
}

// The rest of the island: rolling hills and basins (room for villages and olive groves), rising to
// a massif in the middle with a ridged central mountain and spurs running off it.
function islandLand(x, z, s) {
  const coastal = smooth(Math.min(1, Math.max(0, s / 600)));              // the land climbs off the shore
  const hills = (30 + 190 * Math.pow(fbm(x * 0.0008 + 2.3, z * 0.0008 - 5.1, 4), 1.4)) * coastal;
  const dc = Math.hypot(x - PEAK.x, (z - PEAK.z) * 0.8);                  // the massif runs north-south
  const massif = Math.exp(-((dc / 1350) ** 2));                          // the mountain's spread (step B: was 1900)
  const ridged = Math.pow(1 - Math.abs(fbm(x * 0.0011 - 1.7, z * 0.0011 + 3.9, 4) * 2 - 1), 2);
  const mountain = 820 * Math.pow(massif, 1.4) * (0.55 + 0.45 * ridged);
  const spurs = 260 * Math.pow(1 - Math.abs(fbm(x * 0.0026 + 8.2, z * 0.0026 - 0.6, 3) * 2 - 1), 3)
                * smooth(Math.min(1, massif * 2.2));
  return hills + (mountain + spurs) * smooth(Math.min(1, Math.max(0, s / 900)));
}

// step: when the caller only samples every `step` metres (a coarse ground tile), roughness finer
// than that is left out: sampled too sparsely it would only alias into a checkerboard of bumps.
// Everything that stands on the ground uses the full detail (step 0).
export function heightAt(x, z, step = 0) {
  const s = inland(x, z);
  if (s < -2) return seaFloor(x, z, s);
  // beach and quay: a low flat strip along the water
  const beach = 1.2 * smooth(Math.min(1, Math.max(0, (s + 2) / 10)));
  const w = localWeight(x, z);
  const land = w >= 1 ? bayLand(x, z, s) : w <= 0 ? islandLand(x, z, s) : w * bayLand(x, z, s) + (1 - w) * islandLand(x, z, s);
  // small roughness everywhere on land, larger further inland
  const fine = 1 - smooth(Math.min(1, Math.max(0, (step - 6) / 14)));     // 1 up to 6 m spacing, 0 by 20 m
  const rough = fine > 0 ? (fbm(x * 0.04, z * 0.04, 4) - 0.5) * (2 + Math.min(18, s * 0.05)) * fine : 0;
  const h = beach + land + rough * smooth(Math.min(1, Math.max(0, s / 20)));
  return carve(x, z, h);
}

// Rivers cut their valleys: along a river the ground can be no higher than the water (a channel
// 1.6 m deep in the middle), rising from its banks at about 1 in 3, then more steeply. Taking the lower of that and
// the land gives V-shaped valleys that fade out where the land is already low. (The river's water
// height falls steadily from source to sea, worked out when the river is made: features.js.)
function carve(x, z, h) {
  const r = riverAt(x, z);
  if (!r) return h;
  // beyond ~250 m the valley side steepens quickly, so the carving always fades out long before the
  // edge of the area the lookup covers (~500 m): no plateaus with square edges
  const far = Math.max(0, r.d - 250);
  const bank = r.h - 1.6 * (1 - smooth(Math.min(1, r.d / r.w))) + Math.max(0, r.d - r.w) * 0.32 + far * far * 0.02;
  return Math.min(h, bank);
}

// Slope (0 flat .. 1+ steep), for choosing grass / rock and where trees may grow.
export function slopeAt(x, z) {
  const e = 1.5;
  const dx = heightAt(x + e, z) - heightAt(x - e, z), dz = heightAt(x, z + e) - heightAt(x, z - e);
  return Math.hypot(dx, dz) / (2 * e);
}
