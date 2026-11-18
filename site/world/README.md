# /world: Corva, living (three.js)

Stage 1 of the 3D Corva. Plain ES modules, no build step; three.js 0.170 is vendored in `vendor/`.
The earlier Godot "living painting" moved to `/painting`.

```
js/main.js              wires everything and runs the loop
js/config.js            quality presets (low / medium / high) and URL switches
js/camera.js            FlyRig: fly anywhere (drag, pinch, twist, tap to travel; "Corva" flies home)
js/world/terrain.js     the island as a function: heightAt(x, z), inland(), coastX()   (no three.js)
js/world/ground.js      the colour of the ground at a point; where forests and groves are (no three.js)
js/world/features.js    villages, rivers and roads made from the seed                    (no three.js)
js/world/featuremap.js  fast "how near a river / road / village is this?" lookups         (no three.js)
js/world/tilework.js    one ground tile as plain arrays, plus the shore depth map        (no three.js)
js/world/tileworker.js  a worker that runs tilework.js off the main thread
js/world/layout.js      the city as data: houses, temples, stairs, walls, trees, ships, chimneys,
                        streets; generateLayout(seed)                                   (no three.js)
js/world/daycycle.js    time of day -> sun, sky, light and fog colours
js/scene/terrain.js     the ground in 640 m tiles, finer near the camera, built in workers,
                        with each near tile's trees (forests, olive groves, cypresses)
js/scene/rivers.js      the rivers' flowing water
js/scene/labels.js      place names; tap one to fly there
tools/make_features.mjs makes assets/island/features-<seed>.json (and a map to check by eye)
js/scene/horizon.js     other islands far out at sea (shapes on the horizon)
js/scene/*.js           the rest: sky and sea, the city, life (ships, smoke, lanterns, clouds), AI assets
js/render/painterly.js  Kuwahara oil-paint filter, aerial perspective, ACES, warm Lorrain grade
```

The island: about 7 x 9.5 km, its centre ~3.8 km east of the city, Mount Aetos (~1,100 m) in the
middle, rolling hills and basins round it, four villages (Elaia, Ampelos, Kryoneri, Platanos)
joined to Corva by roads, five rivers from the mountain to the sea, forests on the middle slopes,
olive groves round the villages. Change the terrain or the rules and run
`node site/world/tools/make_features.mjs 1717 map.ppm` to remake the saved features. Near the city (within ~0.7-1.5 km) the hand-tuned bay of
stage 1 is blended in, so the city and the first view are unchanged.

URL switches: `?q=low|medium|high`, `?t=0.735` (fixed time: 0.285 dawn, 0.735 golden hour,
0.95 night), `?still=1` (no drift), `?shot=1` (render 6 frames and stop, for screenshots),
`?seed=1717`, `?view=x,z,dist,az,el` (start looking at a place), `?fps` (frame counter),
`?ai=0` (hand-built only), `?backdrop=sdxl` (stage 1's painted backdrops, for comparison).

Next stages, and where they plug in:
- **Step A (done), the island to fly over:** `heightAt()` widened to the island, the ground in
  tiles with levels of detail, the fly rig, distant islands.
- **Step B (done), villages, roads, rivers, forests:** made from the seed (features.js), rivers
  carved into the land, villages built by the same code as Corva's houses, trees per tile.
- **Later, street level in Corva:** a walking mode inside the city only (not built yet).
- **Step C, the world tables:** replace `generateLayout()` with a layout built from Supabase
  (`places`, `objects`, `people`, weather in `vital_signs`) in the same shape; the scene builders
  only read that shape. Lanterns already walk `layout.streets`; people become walkers on routes.
