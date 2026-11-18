// A worker that builds ground tiles off the main thread, so flying stays smooth while new land is
// worked out. It receives { id, x0, z0, size, res } and posts back the tile's arrays (transferred,
// not copied). Also bakes the island-wide shore map on request.

import { buildTile, shoreBytes } from "./tilework.js";

self.onmessage = e => {
  const m = e.data;
  if (m.kind === "shore") {
    const data = shoreBytes(m.rect, m.nx, m.nz);
    self.postMessage({ kind: "shore", data }, [data.buffer]);
    return;
  }
  const t = buildTile(m.x0, m.z0, m.size, m.res);
  self.postMessage({ kind: "tile", id: m.id, res: m.res, ...t }, [t.pos.buffer, t.nor.buffer, t.col.buffer, t.uv.buffer]);
};
