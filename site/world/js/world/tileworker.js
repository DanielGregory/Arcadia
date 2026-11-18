// A worker that builds ground tiles off the main thread, so flying stays smooth while new land is
// worked out. It receives { id, x0, z0, size, res } and posts back the tile's arrays (transferred,
// not copied), with its trees when it's near enough to show them. Also bakes the island-wide shore
// map on request. It is first sent the island's features (rivers, roads, villages).

import { buildTile, shoreBytes, tileTrees } from "./tilework.js";
import { setFeatures } from "./featuremap.js";

self.onmessage = e => {
  const m = e.data;
  if (m.kind === "features") { setFeatures(m.features); return; }   // the island's rivers, roads, villages
  if (m.kind === "shore") {
    const data = shoreBytes(m.rect, m.nx, m.nz);
    self.postMessage({ kind: "shore", data }, [data.buffer]);
    return;
  }
  const t = buildTile(m.x0, m.z0, m.size, m.res);
  const trees = m.trees ? tileTrees(m.x0, m.z0, m.size, m.size / m.res, m.trees, m.near) : null;
  const transfer = [t.pos.buffer, t.nor.buffer, t.col.buffer, t.uv.buffer];
  if (trees) for (const k in trees) transfer.push(trees[k].buffer);
  self.postMessage({ kind: "tile", id: m.id, res: m.res, trees, ...t }, transfer);
};
