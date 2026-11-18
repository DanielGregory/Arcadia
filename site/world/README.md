# /world: Corva, living (three.js)

Stage 1 of the 3D Corva. Plain ES modules, no build step; three.js 0.170 is vendored in `vendor/`.
The earlier Godot "living painting" moved to `/painting`.

```
js/main.js            wires everything and runs the loop
js/config.js          quality presets (low / medium / high) and URL switches
js/camera.js          DriftRig: slow cinematic drift, drag to orbit, eases back when idle
js/world/terrain.js   the land as a function: heightAt(x, z), coastX(z)          (no three.js)
js/world/layout.js    the city as data: houses, temples, stairs, walls, trees,    (no three.js)
                      ships, chimneys, streets; generateLayout(seed)
js/world/daycycle.js  time of day -> sun, sky, light and fog colours
js/scene/*.js         builders that turn that data into meshes (sky, sea, land, city, life)
js/render/painterly.js  Kuwahara oil-paint filter, ACES, warm Lorrain grade, vignette, grain
```

URL switches: `?q=low|medium|high`, `?t=0.735` (fixed time: 0.285 dawn, 0.735 golden hour,
0.95 night), `?still=1` (no drift), `?shot=1` (render 6 frames and stop, for screenshots),
`?seed=1717`.

Next stages, and where they plug in:
- **Stage 2, a larger land to fly over:** widen `heightAt()` (it is the only source of ground
  height), stream the land mesh in tiles from `makeLand(res, bounds)`, and add a fly rig with the
  same `update(dt, time)` interface as `DriftRig`.
- **Stage 3, the world tables:** replace `generateLayout()` with a layout built from Supabase
  (`places`, `objects`, `people`, weather in `vital_signs`) in the same shape; the scene builders
  only read that shape. Lanterns already walk `layout.streets`; people become walkers on routes.
