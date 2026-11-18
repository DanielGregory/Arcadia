// Place names over the island: Corva, the villages, the mountain. Plain HTML text pinned to points
// in the world (projected through the camera each frame), so it stays sharp at any quality.
// They show once you're far enough out to need them, fade when far off or close up, and tapping
// one flies you there.

import * as THREE from "../../vendor/three.module.min.js";

const v = new THREE.Vector3();

// places: [{ name, x, y, z, kind: "city" | "village" | "mountain", fly: { x, z, dist, el } }]
export function makeLabels(places, onPick) {
  const layer = document.createElement("div");
  layer.className = "labels";
  document.body.append(layer);
  const items = places.map(p => {
    const el = document.createElement("button");
    el.className = `place ${p.kind}`;
    el.textContent = p.name;
    el.addEventListener("click", e => { e.stopPropagation(); onPick(p); });
    layer.append(el);
    return { p, el };
  });
  return {
    update(camera, viewDist) {
      const w = innerWidth, h = innerHeight;
      for (const { p, el } of items) {
        v.set(p.x, p.y + (p.kind === "mountain" ? 60 : 40), p.z);
        const d = camera.position.distanceTo(v);
        v.project(camera);
        // shown when zoomed out past ~500 m, and not for a place you're already right over
        let a = THREE.MathUtils.smoothstep(viewDist, 450, 900) * THREE.MathUtils.smoothstep(d, 500, 1100)
                * (1 - THREE.MathUtils.smoothstep(d, 14000, 22000));
        if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) a = 0;   // behind the camera or off screen
        el.style.opacity = a.toFixed(2);
        el.style.visibility = a < 0.03 ? "hidden" : "visible";
        if (a >= 0.03) el.style.transform = `translate(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px) translate(-50%, -100%)`;
      }
    },
  };
}
