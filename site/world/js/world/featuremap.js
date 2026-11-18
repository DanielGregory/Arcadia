// Fast questions about the island's features: how far is this point from a river or a road, and
// is it in a village? (No three.js, no other imports, so the terrain and the workers can use it.)
//
// The features themselves (villages, rivers, roads) are made once by features.js and handed to
// setFeatures(). Rivers and roads are polylines; to answer "what's near here" without checking
// every segment, segments are filed in a grid of square cells, each listing the segments that
// pass within reach of it. A question then only looks at one cell's short list.

let F = null;
let riverIdx = null, roadIdx = null;

class SegmentIndex {
  constructor(lines, reach, cell = 250) {
    this.cell = cell;
    this.cells = new Map();
    this.segs = [];
    for (const line of lines) {
      for (let i = 0; i + 1 < line.pts.length; i++) {
        const a = line.pts[i], b = line.pts[i + 1], id = this.segs.length;
        this.segs.push({ a, b, line });
        const x0 = Math.floor((Math.min(a.x, b.x) - reach) / cell), x1 = Math.floor((Math.max(a.x, b.x) + reach) / cell);
        const z0 = Math.floor((Math.min(a.z, b.z) - reach) / cell), z1 = Math.floor((Math.max(a.z, b.z) + reach) / cell);
        for (let cz = z0; cz <= z1; cz++) for (let cx = x0; cx <= x1; cx++) {
          const k = cx * 100003 + cz;
          let list = this.cells.get(k);
          if (!list) this.cells.set(k, list = []);
          list.push(id);
        }
      }
    }
  }
  // the nearest segment: { d (distance), t (0..1 along it), seg }, or null if none within reach
  nearest(x, z) {
    const list = this.cells.get(Math.floor(x / this.cell) * 100003 + Math.floor(z / this.cell));
    if (!list) return null;
    let best = null, bd = Infinity, bt = 0;
    for (const id of list) {
      const { a, b } = this.segs[id];
      const dx = b.x - a.x, dz = b.z - a.z, L2 = dx * dx + dz * dz;
      let t = L2 > 0 ? ((x - a.x) * dx + (z - a.z) * dz) / L2 : 0;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
      const px = a.x + dx * t - x, pz = a.z + dz * t - z, d = px * px + pz * pz;
      if (d < bd) { bd = d; best = this.segs[id]; bt = t; }
    }
    return best ? { d: Math.sqrt(bd), t: bt, seg: best } : null;
  }
}

export function setFeatures(f) {
  F = f;
  riverIdx = f && f.rivers.length ? new SegmentIndex(f.rivers, 520) : null;
  roadIdx = f && f.roads.length ? new SegmentIndex(f.roads, 60) : null;
}
export function getFeatures() { return F; }

// The river nearest a point (within ~500 m): { d: distance from its centre line, w: its half-width
// there, h: the water's height there }, or null.
export function riverAt(x, z) {
  if (!riverIdx) return null;
  const n = riverIdx.nearest(x, z);
  if (!n) return null;
  const { a, b } = n.seg;
  return { d: n.d, w: a.w + (b.w - a.w) * n.t, h: a.h + (b.h - a.h) * n.t };
}

// Distance to the nearest road (Infinity beyond ~60 m).
export function roadDist(x, z) {
  if (!roadIdx) return Infinity;
  const n = roadIdx.nearest(x, z);
  return n ? n.d : Infinity;
}

// The village a point is in or near: { v, d } for the closest within 2.5 village radii, or null.
export function villageNear(x, z) {
  if (!F) return null;
  let best = null;
  for (const v of F.villages) {
    const d = Math.hypot(x - v.x, z - v.z);
    if (d < v.r * 2.5 && (!best || d < best.d)) best = { v, d };
  }
  return best;
}
