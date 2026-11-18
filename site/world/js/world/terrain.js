// The land of Corva as a pure function: heightAt(x, z) -> metres above the sea.
//
// Axes: x runs east (-) to west (+), z runs north (-) to south (+), y is up; the sea is y = 0.
// The coast curves round a bay that opens to the west, where the sun sets over the water (as in
// the reference painting). Inland the ground climbs a hillside, the city's hill, and behind it rise
// ranges of mountains.
//
// Everything that sits on the ground (buildings, trees, lanterns) asks heightAt(), so stage 2 (a
// larger land to fly over) only has to widen this function, not touch anything that uses it.

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

// --- the shape of the land --------------------------------------------------------------------
// The shoreline: land is where x < coastX(z). A gentle curve makes the bay; it bends out to sea
// to the north and south so the bay is held between two arms.
export function coastX(z) {
  // The south arm (z > 0) curls round behind the viewer; the north shore bends away more gently,
  // so the bay opens to the sea and the sunset beyond the far end of the city.
  return 10 + (z > 0 ? 0.0028 : 0.0011) * z * z - 6 * Math.sin(z / 37);
}

// How far inland a point is (negative = at sea).
export function inland(x, z) { return coastX(z) - x; }

export function heightAt(x, z) {
  const s = inland(x, z);
  if (s < -2) {
    // the sea floor: shelves down away from the shore
    return Math.max(-14, s * 0.35) + fbm(x * 0.05, z * 0.05, 2) * 1.5;
  }
  // beach and quay: a low flat strip along the water
  const beach = 1.2 * smooth(Math.min(1, Math.max(0, (s + 2) / 10)));
  // the city's hill: rises steadily, flattening to a summit about 120 m inland
  const hill = 52 * (1 - Math.exp(-Math.max(0, s - 8) / 55));
  // a shoulder of rock near the summit, where the summit temple stands
  const summit = 10 * Math.exp(-((x + 105) ** 2 + (z + 14) ** 2) / 900);
  // mountains: start ~170 m inland behind the city, further back along the north shore, so they
  // recede in layers up the coast; rough with noise and ridged peaks
  const start = 250 + Math.max(0, -z - 80) * 0.55;
  const m = Math.max(0, s - start);
  const ridge = Math.pow(fbm(x * 0.006 + 3.1, z * 0.009 - 1.7, 5), 1.6);
  const peaks = Math.pow(1 - Math.abs(fbm(x * 0.004 - 5.3, z * 0.004 + 2.2, 3) * 2 - 1), 3);   // sharp ridgelines
  const far = Math.pow(1 - Math.abs(fbm(x * 0.0022 + 9.1, z * 0.0022 - 4.4, 3) * 2 - 1), 4);      // the distant ranges
  const mountains = m > 0 ? (m * 0.38 + 150 * ridge + 150 * peaks + 260 * far * smooth(Math.min(1, m / 600)))
                           * smooth(Math.min(1, m / 260)) : 0;
  // small roughness everywhere on land, larger further inland
  const rough = (fbm(x * 0.04, z * 0.04, 4) - 0.5) * (2 + Math.min(18, s * 0.05));
  return beach + hill + summit + mountains + rough * smooth(Math.min(1, Math.max(0, s / 20)));
}

// Slope (0 flat .. 1+ steep), for choosing grass / rock and where trees may grow.
export function slopeAt(x, z) {
  const e = 1.5;
  const dx = heightAt(x + e, z) - heightAt(x - e, z), dz = heightAt(x, z + e) - heightAt(x, z - e);
  return Math.hypot(dx, dz) / (2 * e);
}
