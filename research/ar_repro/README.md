# AR page repro (phone-like, headless Edge)

Runs the real AR page (`components/ar/faceTrackerHtml.ts`) like a WebView: fake camera (a still face), CPU throttling,
the makeup state injected through the same `message` path the app uses, then screenshots, frame gaps, the HUD and the
console are collected. Made on 11-06 after "no shading at all" turned out to be a `ReferenceError` in `faceFitStep` that the
render's `catch` swallowed (the unit tests had defined fake globals `W` / `H`, which hid it).

Needs Edge, internet (MediaPipe and the model come from their CDN) and Node 22+. Paths below are examples.

```
node research/ar_repro/build_page.mjs components/ar/faceTrackerHtml.ts components/ar/faceUV.ts page.html
python research/ar_repro/make_y4m.py face.jpg .
node research/ar_repro/drive.mjs <abs>/page.html <abs>/face.y4m <abs>/out 4 run1 shade      # 4 = CPU throttle, "none" = no shading
node research/ar_repro/undef.mjs page.html                                                   # identifiers used but never defined
node research/ar_repro/glsl2.mjs components/ar/faceTrackerHtml.ts glsl.html && node research/ar_repro/glsl_check.mjs <abs>/glsl.html
```

Read it as a relative check (same environment, before / after): headless Edge renders in software, so fps and the absolute ms are
not a phone's. The number that matters is "shading pixels after the colour is chosen" (screenshot diff, HUD hidden) and the HUD
`jaw` / `ERR` lines. Close the processes it starts (`drive.mjs` kills the Edge tree itself).
