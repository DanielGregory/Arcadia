// Settings that change between devices, and the URL switches used for screenshots and testing.
//
//   ?q=low|medium|high   quality (default: a guess from the device)
//   ?t=0.74              fix the time of day (0 midnight, 0.27 dawn, 0.74 golden hour, 0.95 night)
//   ?still=1             no camera drift (for screenshots)
//   ?seed=1717           the city's random seed

export const QUALITY = {
  // pixelRatio: how sharp; renderScale: the share of those pixels the painting pass renders;
  // kuwahara: brush size of the oil-paint filter (0 = off); terrain: grid resolution.
  low:    { pixelRatio: 1,   renderScale: 0.7,  kuwahara: 2, terrain: 150, shadows: false, shadowSize: 0,    lights: 0, smoke: 40,  glow: 0.8 },
  medium: { pixelRatio: 1.5, renderScale: 0.85, kuwahara: 3, terrain: 240, shadows: true,  shadowSize: 1024, lights: 2, smoke: 70,  glow: 1.0 },
  high:   { pixelRatio: 2,   renderScale: 1.0,  kuwahara: 4, terrain: 340, shadows: true,  shadowSize: 2048, lights: 4, smoke: 110, glow: 1.0 },
};

export const params = new URLSearchParams(location.search);

export function chooseQuality() {
  const asked = params.get("q") || safeGet("corva-quality");
  if (asked && QUALITY[asked]) return asked;
  // Phones and small screens start on low; everything else on medium. The toggle changes it.
  const small = Math.min(screen.width, screen.height) < 600;
  const touch = matchMedia("(pointer: coarse)").matches;
  return small || touch ? "low" : "medium";
}

export function safeGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
export function safeSet(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }

export const DAY_SECONDS = 360;        // one full day-night cycle in the live view
export const START_TIME = 0.70;        // start just before golden hour
