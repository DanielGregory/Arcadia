// The buildings, modelled from simple parts: houses of several kinds and sizes, and Doric temples.
//
// Each building is put together from boxes, prisms, cylinders and turned (lathe) shapes, every part
// with its own colour, then merged into one mesh. Houses are made once per kind and size and then
// stamped out many times as instances (one draw call per kind and size, however many houses);
// temples are few, so each is built whole for its own size and number of columns.
//
// Two extra values ride along on every vertex:
//   glow  a window's number (0 for everything that isn't a window). At night about half the windows
//         light up warm; which ones is decided per house from the window's number, so neighbours
//         differ and it never flickers.
//   wall  1 on plastered walls: they get the weathered plaster texture, laid on by world position
//         (so it doesn't stretch with a building's size).
//
// Local frame: a building's front faces +x; z runs along its width; y = 0 is the ground at its
// middle, and walls run 2.5 m below that so they meet the ground on a slope.

import * as THREE from "../../vendor/three.module.min.js";
import { mergeGeometries } from "../../vendor/addons/utils/BufferGeometryUtils.js";

const C = hex => new THREE.Color(hex);
export const PALETTE = {
  white: C("#f2ebdc"), cream: C("#e8dcc3"), ochre: C("#e2c99a"), pink: C("#e8cdb8"),
  terracotta: C("#b0603d"), tileDark: C("#8f4a30"), wood: C("#5a3f2a"), door: C("#4a3426"),
  blue: C("#3f6f8f"), green: C("#4f7254"), window: C("#2f2822"), stone: C("#c9b896"),
  marble: C("#efe7d6"), marbleShade: C("#d8cdb6"), cella: C("#b3a284"), frieze: C("#9c8d74"),
  roofTemple: C("#a7745a"), paint: C("#7a3b2e"),
};

// --- a little builder for coloured, merged geometry -----------------------------------------------
class Parts {
  constructor() { this.list = []; this.windows = 0; }
  // add a geometry (already placed), all one colour; opts: { glow: true, wall: true }
  add(geo, color, { glow = false, wall = false } = {}) {
    const g = geo.index ? geo.toNonIndexed() : geo;
    g.deleteAttribute("uv");
    if (!g.attributes.normal) g.computeVertexNormals();
    const n = g.attributes.position.count;
    const col = new Float32Array(n * 3), gl = new Float32Array(n), wl = new Float32Array(n);
    const id = glow ? ++this.windows : 0;
    for (let i = 0; i < n; i++) { col[i * 3] = color.r; col[i * 3 + 1] = color.g; col[i * 3 + 2] = color.b; gl[i] = id; wl[i] = wall ? 1 : 0; }
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.setAttribute("glow", new THREE.BufferAttribute(gl, 1));
    g.setAttribute("wall", new THREE.BufferAttribute(wl, 1));
    this.list.push(g);
    return this;
  }
  box(x, y, z, sx, sy, sz, color, opts) { return this.add(new THREE.BoxGeometry(sx, sy, sz).translate(x, y + sy / 2, z), color, opts); }
  build() { const g = mergeGeometries(this.list); g.computeBoundingSphere(); return g; }
}

// A gable (two-sloped) roof: a prism along z, eaves overhanging by `over`, pitch rise `rise`.
function gableRoof(d, w, rise, over) {
  const s = new THREE.Shape([new THREE.Vector2(-d / 2 - over, 0), new THREE.Vector2(d / 2 + over, 0), new THREE.Vector2(0, rise)]);
  return new THREE.ExtrudeGeometry(s, { depth: w + over * 2, bevelEnabled: false }).translate(0, 0, -(w + over * 2) / 2);
}
// A hipped roof: four slopes up to a short ridge (a stretched four-sided pyramid frustum).
function hipRoof(d, w, rise, over) {
  const g = new THREE.CylinderGeometry(0.18, Math.SQRT1_2, 1, 4, 1).rotateY(Math.PI / 4);
  return g.scale(d + over * 2, rise, w + over * 2).translate(0, rise / 2, 0);
}

// windows (with shutters) and a door on one face of a box (front = +x face at x = d/2)
function openings(P, d, w, h, floors, shutter, { side = true, door = true } = {}) {
  const fy = [0.9];
  if (floors > 1) fy.push(0.9 + h / floors);
  const perRow = w > 7 ? 3 : w > 4.5 ? 2 : 1;
  fy.forEach((y0, f) => {
    for (let k = 0; k < perRow; k++) {
      const z = (k - (perRow - 1) / 2) * (w / perRow);
      if (f === 0 && door && k === Math.floor(perRow / 2)) {            // the door, with a stone frame
        P.box(d / 2 + 0.02, -0.05, z, 0.12, 2.3, 1.5, PALETTE.stone);
        P.box(d / 2 + 0.06, 0, z, 0.06, 2.1, 1.1, PALETTE.door);
        continue;
      }
      P.box(d / 2 + 0.03, y0, z, 0.06, 1.15, 0.8, PALETTE.window, { glow: true });
      P.box(d / 2 + 0.05, y0, z - 0.72, 0.05, 1.15, 0.55, shutter);    // shutters, open
      P.box(d / 2 + 0.05, y0, z + 0.72, 0.05, 1.15, 0.55, shutter);
    }
  });
  if (side && w > 4) {                                                   // one window on the side
    const y0 = 0.9 + (floors > 1 ? h / floors : 0);
    P.box(0, y0, w / 2 + 0.03, 0.8, 1.1, 0.06, PALETTE.window, { glow: true });
  }
}

// --- houses -----------------------------------------------------------------------------------------
// kinds: cube (flat Cycladic roof with a parapet), gable and hip (terracotta tiles), two-storey
// (with a wooden balcony), courtyard (a walled yard in front), tower (a tall merchant's house)
export const HOUSE_KINDS = ["cube", "gable", "hip", "twostorey", "courtyard", "tower"];
export const HOUSE_SIZES = [{ w: 5, d: 4.5, h: 3.3 }, { w: 7, d: 5.5, h: 3.8 }, { w: 9.5, d: 7, h: 4.4 }];

function house(kind, { w, d, h }, detail) {
  const P = new Parts();
  const wall = { wall: true };
  const shutter = kind === "gable" || kind === "tower" ? PALETTE.green : PALETTE.blue;
  let H = h, floors = 1;
  if (kind === "twostorey") { H = h + 2.9; floors = 2; }
  if (kind === "tower") { H = h + 5.5; floors = 2; w = w * 0.75; d = d * 0.85; }
  P.box(0, -2.5, 0, d, H + 2.5, w, PALETTE.white, wall);                 // the walls (down into the slope)
  P.box(0, -2.5, 0, d + 0.25, 0.75 + 2.5, w + 0.25, PALETTE.stone);    // a stone plinth
  openings(P, d, w, H, floors, shutter);
  if (kind === "cube" || kind === "courtyard") {                        // flat roof, parapet, a chimney
    P.box(0, H, 0, d + 0.15, 0.35, w + 0.15, PALETTE.cream, wall);
    P.box(-d * 0.25, H, w * 0.3, 0.7, 1.2, 0.7, PALETTE.cream, wall);
    if (detail > 0) P.box(d * 0.2, H + 0.35, -w * 0.25, 1.6, 0.9, 1.6, PALETTE.white, wall);   // a little room on the roof
  } else if (kind === "gable" || kind === "twostorey") {
    P.add(gableRoof(d, w, Math.min(2.2, d * 0.32), 0.45).translate(0, H, 0), PALETTE.terracotta);
    P.box(0, H + Math.min(2.2, d * 0.32) - 0.05, 0, 0.35, 0.18, w + 0.95, PALETTE.tileDark);   // ridge tiles
  } else {                                                              // hip and tower
    P.add(hipRoof(d, w, Math.min(2.4, Math.max(d, w) * 0.3), 0.45).translate(0, H, 0), PALETTE.terracotta);
  }
  if (kind === "twostorey") {                                           // a balcony across the front
    P.box(d / 2 + 0.7, H / 2 + 0.25, 0, 1.4, 0.15, w * 0.8, PALETTE.wood);
    if (detail > 0) for (let k = 0; k <= 6; k++) P.box(d / 2 + 1.35, H / 2 + 0.4, -w * 0.4 + (k * w * 0.8) / 6, 0.07, 0.9, 0.07, PALETTE.wood);
    P.box(d / 2 + 1.35, H / 2 + 1.25, 0, 0.08, 0.08, w * 0.8, PALETTE.wood);
  }
  if (kind === "courtyard") {                                           // a walled yard with a gate
    const yd = 4.5;
    P.box(d / 2 + yd / 2, -2.5, w / 2 - 0.15, yd, 2.5 + 1.8, 0.3, PALETTE.white, wall);
    P.box(d / 2 + yd / 2, -2.5, -w / 2 + 0.15, yd, 2.5 + 1.8, 0.3, PALETTE.white, wall);
    P.box(d / 2 + yd - 0.15, -2.5, w * 0.3, 0.3, 2.5 + 1.8, w * 0.4, PALETTE.white, wall);
    P.box(d / 2 + yd - 0.15, -2.5, -w * 0.3, 0.3, 2.5 + 1.8, w * 0.4, PALETTE.white, wall);
  }
  return P.build();
}

// All house geometries: houses[kind][size]
export function houseKit(detail = 1) {
  const kit = {};
  for (const k of HOUSE_KINDS) kit[k] = HOUSE_SIZES.map(s => house(k, s, detail));
  return kit;
}

// --- temples ----------------------------------------------------------------------------------------
// A Doric temple: three steps, a ring of columns (slightly swelling shafts that taper toward the top,
// with a cushion-shaped capital and a square slab on each), the beam above them, a frieze of
// alternating triglyphs and painted panels, a projecting cornice, a pediment at each end and a
// tiled roof; inside, the walled hall with its door.
// t: { w, d, cols: [nShort, nLong], scale } as in the layout (d runs front to back, along x).
export function templeGeometry(t, detail = 1) {
  const P = new Parts(), S = t.scale, H = 7 * S, seg = detail > 0 ? 16 : 8;
  const W = t.w, D = t.d;
  // crepidoma: three steps
  const step = 0.42 * S;
  for (let k = 0; k < 3; k++) P.box(0, -3 + k * step, 0, D + 2.4 - k * 0.9 * S, (k === 0 ? 3 : 0) + step, W + 2.4 - k * 0.9 * S, PALETTE.marbleShade);
  const base = -3 + 3 + 3 * step;
  // the hall inside the columns, with its door
  P.box(0, base, 0, D * 0.62, H * 0.95, W * 0.56, PALETTE.cella);
  P.box(D * 0.31 + 0.03, base, 0, 0.06, H * 0.55, W * 0.18, PALETTE.door);
  // columns
  const r0 = 0.62 * S;
  const prof = [];
  for (let i = 0; i <= 8; i++) {
    const f = i / 8;
    prof.push(new THREE.Vector2(r0 * (1 - 0.2 * f + 0.06 * Math.sin(Math.PI * f)), f * H * 0.9));   // entasis: a gentle swell
  }
  prof.push(new THREE.Vector2(r0 * 0.78, H * 0.9), new THREE.Vector2(r0 * 1.15, H * 0.955), new THREE.Vector2(r0 * 1.2, H * 0.965));
  const column = new THREE.LatheGeometry(prof, seg);
  const abacus = new THREE.BoxGeometry(r0 * 2.6, H * 0.035, r0 * 2.6).translate(0, H * 0.9825, 0);
  const [nShort, nLong] = t.cols, hx = D / 2, hz = W / 2;
  const ring = [];
  for (let i = 0; i < nShort; i++) { const z = -hz + (2 * hz * i) / (nShort - 1); ring.push([hx, z], [-hx, z]); }
  for (let i = 1; i < nLong - 1; i++) { const x = -hx + (2 * hx * i) / (nLong - 1); ring.push([x, hz], [x, -hz]); }
  for (const [x, z] of ring) {
    P.add(column.clone().translate(x, base, z), PALETTE.marble);
    P.add(abacus.clone().translate(x, base, z), PALETTE.marble);
  }
  // entablature: architrave, frieze (triglyphs and metopes), cornice
  const top = base + H;
  P.box(0, top, 0, D + r0 * 2.4, 1.0 * S, W + r0 * 2.4, PALETTE.marble);
  const fy = top + 1.0 * S, fh = 0.9 * S;
  if (detail > 0) {
    // the frieze: blocks round all four sides, alternating dark triglyphs and light panels
    const unit = 1.05 * S;
    const sides = [[D + r0 * 2.4, (W + r0 * 2.4) / 2, "x"], [W + r0 * 2.4, (D + r0 * 2.4) / 2, "z"]];
    for (const [len, off, axis] of sides) {
      const n = Math.max(4, Math.round(len / unit));
      for (let k = 0; k < n; k++) {
        const u = -len / 2 + (k + 0.5) * (len / n), c = k % 2 ? PALETTE.marble : PALETTE.frieze;
        for (const sgn of [1, -1]) {
          if (axis === "x") P.box(u, fy, sgn * off, len / n, fh, 0.3, c);
          else P.box(sgn * off, fy, u, 0.3, fh, len / n, c);
        }
      }
    }
  } else P.box(0, fy, 0, D + r0 * 2.4, fh, W + r0 * 2.4, PALETTE.frieze);
  P.box(0, fy + fh, 0, D + r0 * 3.2, 0.4 * S, W + r0 * 3.2, PALETTE.marble);       // cornice
  // pediments (front and back) and the roof: a low gable along x
  const ry = fy + fh + 0.4 * S, rise = (W + r0 * 3.2) * 0.14;
  const tri = new THREE.Shape([new THREE.Vector2(-(W + r0 * 3.2) / 2, 0), new THREE.Vector2((W + r0 * 3.2) / 2, 0), new THREE.Vector2(0, rise)]);
  const roof = new THREE.ExtrudeGeometry(tri, { depth: D + r0 * 3.2, bevelEnabled: false })
    .translate(0, 0, -(D + r0 * 3.2) / 2).rotateY(Math.PI / 2).translate(0, ry, 0);
  P.add(roof, PALETTE.roofTemple);
  // the triangular gable faces in marble, with a recessed, darker tympanum
  for (const sgn of [1, -1]) {
    const face = new THREE.ShapeGeometry(tri).rotateY(sgn * Math.PI / 2).translate(sgn * ((D + r0 * 3.2) / 2 + 0.02), ry, 0);
    P.add(face, PALETTE.marble);
    const inner = new THREE.Shape([new THREE.Vector2(-(W) / 2 + 0.6, 0.25), new THREE.Vector2(W / 2 - 0.6, 0.25), new THREE.Vector2(0, rise - 0.5)]);
    P.add(new THREE.ShapeGeometry(inner).rotateY(sgn * Math.PI / 2).translate(sgn * ((D + r0 * 3.2) / 2 + 0.06), ry, 0), PALETTE.paint);
    if (detail > 0) P.box(sgn * ((D + r0 * 3.2) / 2), ry + rise - 0.1, 0, 0.5, 0.9 * S, 0.5, PALETTE.marble);   // akroterion
  }
  return P.build();
}

// --- the shared material -----------------------------------------------------------------------------
// Vertex-coloured Lambert, plus: windows that glow at night (half of them, chosen per house and per
// window), and plaster texture on the walls laid on by world position.
export function buildingMaterial(plaster = null) {
  const mat = new THREE.MeshLambertMaterial({ vertexColors: true });
  mat.userData.night = { value: 0 };
  mat.onBeforeCompile = shader => {
    shader.uniforms.night = mat.userData.night;
    shader.uniforms.plaster = { value: plaster };
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>
        attribute float glow; attribute float wall;
        varying float vGlow; varying float vWall; varying float vSeed; varying vec3 vWorldPos; varying vec3 vWorldNormal;`)
      .replace("#include <begin_vertex>", `#include <begin_vertex>
        vGlow = glow; vWall = wall;
        #ifdef USE_INSTANCING
          vSeed = float(gl_InstanceID);
          mat4 placeM = modelMatrix * instanceMatrix;
        #else
          vSeed = 0.0;
          mat4 placeM = modelMatrix;
        #endif
        vWorldPos = (placeM * vec4(transformed, 1.0)).xyz;
        vWorldNormal = normalize(mat3(placeM) * objectNormal);`);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", `#include <common>
        uniform float night; ${plaster ? "uniform sampler2D plaster;" : ""}
        varying float vGlow; varying float vWall; varying float vSeed; varying vec3 vWorldPos; varying vec3 vWorldNormal;
        float hash11(float p) { p = fract(p * 0.1031); p *= p + 33.33; p *= p + p; return fract(p); }`)
      .replace("#include <color_fragment>", `#include <color_fragment>
        ${plaster ? `
        if (vWall > 0.5) {
          // plaster laid on by world position: pick the two axes the wall faces across
          vec3 n = abs(vWorldNormal);
          vec2 uv = n.x > n.z ? vWorldPos.zy : vWorldPos.xy;
          if (n.y > 0.7) uv = vWorldPos.xz;
          float fade = smoothstep(260.0, 90.0, length(vViewPosition));
          diffuseColor.rgb *= mix(vec3(1.0), texture2D(plaster, uv / 5.0).rgb * 1.08, fade * 0.85);
        }` : ""}`)
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        if (vGlow > 0.5 && hash11(vSeed * 17.31 + vGlow * 3.7) < 0.55) {
          totalEmissiveRadiance += vec3(1.0, 0.62, 0.28) * night * 2.4;
        }`);
  };
  return mat;
}
