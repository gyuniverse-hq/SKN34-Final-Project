/**
 * Self-contained page that runs MediaPipe Face Landmarker on the front camera and
 * renders makeup. Runs fully on-device: frames are never stored or sent.
 *
 * Rendering (AR_SPEC 6-4, 6-5, PBR_DEMO_SPEC 6): the 468-point face mesh is drawn with the
 * canonical model's UVs (components/ar/faceUV.ts), so masks painted once in UV space stay on
 * the lips, cheeks and lids when the head turns. Mouth and eyes are holes in the mesh.
 * Lips are layered, not painted over (AR_SPEC 6-5-3): the camera pixel is light × shading × bare-lip
 * color, and lipstick only changes the lip color. The page measures the bare-lip color, builds the
 * lipstick layer on top of it (opaque pigment covers it, sheer/gloss tints it like a dye) and
 * multiplies the camera pixel by layered / bare reflectance. Camera wrinkles, light and noise stay.
 * The product hex is the mid-tone. Sheen is the same colour, brighter; white GGX is only a small lower-
 * centre peak. Coverage = 1 - (1 - a1)^layers (6-7). Pixels outside the masks are discarded.
 * Each new camera frame is uploaded first and the landmarks are detected on that same frame, so
 * the makeup never trails the image. The lip outline is drawn in screen space each frame from the
 * smoothed landmarks (sharp corners, no mesh-triangle kinks), softened by the measured camera blur.
 * Paint darkens toward that outline (lip volume). Coverage fades slightly toward the inner (wet)
 * line and the mouth corners.
 * Light (6-6-1): color from background Gray World (selfie multiclass segmenter), direction
 * and strength from skin brightness vs. mesh normals, both every 0.5 s.
 * Foundation hairline: the same segmenter class 3 (face skin) vs class 1 (hair), ~400 ms while the
 * layer is on (skipped under 20 fps once a mask exists); newly visible skin rises faster than hair
 * appears. brightness foundHair is only the fallback when the segmenter is missing. Capture height
 * is capped (ideal 720, max 960). 1x is that full FOV with cover (no 9:16 sensor crop). Pinch
 * scales the WebGL and overlay canvases together (1–4× digital); below 1× would letterbox empty
 * pixels so it is not offered. Stream and MediaPipe stay running.
 * Requires WebGL; without it the page reports `unavailable` and the host shows swatches.
 * Double-tap the view to toggle a debug HUD (FPS, light estimate). Tune values in TUNING.
 *
 * Protocol
 *   host → page : {"type":"makeup","makeup":MakeupState} | {"type":"compare","value":boolean}
 *   page → host : {"type":"hello"} | {"type":"status","status":ArStatus,"detail"?:string}
 */
import { FACE_MOUTH_TRIANGLES, FACE_TRIANGLES, FACE_UV } from './faceUV';

export const MEDIAPIPE_VERSION = '1.1.1';

export type ArStatus = 'loading' | 'tracking' | 'no-face' | 'denied' | 'unavailable';

export const FACE_TRACKER_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #000; overflow: hidden; touch-action: none; }
  #video { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; transform-origin: 50% 50%; }
  #hud { position: absolute; left: 8px; top: 84px; padding: 6px 8px; border-radius: 6px; display: none;
         background: rgba(0,0,0,0.55); color: #fff; font: 11px/1.4 monospace; white-space: pre; pointer-events: none; }
  #jawdbg { position: absolute; left: 8px; top: 36px; padding: 6px 8px; border-radius: 4px; display: none; z-index: 5;
         background: rgba(0,0,0,0.45); color: #fff; font: 10px/1.3 monospace; pointer-events: auto; }
</style>
</head>
<body>
<video id="video" playsinline muted autoplay></video>
<canvas id="canvas"></canvas>
<canvas id="overlay" style="pointer-events: none"></canvas>
<div id="hud"></div>
<div id="jawdbg"></div>
<script type="module">
  const VERSION = '${MEDIAPIPE_VERSION}';
  const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
  const SEG_MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite';
  const FACE_UV = ${JSON.stringify(FACE_UV)};
  const FACE_TRIANGLES = ${JSON.stringify(FACE_TRIANGLES)};
  const FACE_MOUTH_TRIANGLES = ${JSON.stringify(FACE_MOUTH_TRIANGLES)};
  const NL = String.fromCharCode(10);

  // ── Tuning: adjust these on real devices ─────────────────────────────
  const TUNING = {
    // One Euro on each point's offset from the raw face centre (the centre itself is unfiltered).
    smoothMinCutoff: 1.5,       // lower = steadier when still (more lag in expression changes)
    smoothBeta: 25,             // higher = less lag when the face changes shape or turns
    smoothDCutoff: 2.0,         // speed estimate cutoff: 1.0 made the filter open late when motion began
    // 눈꺼풀·홍채: 깜빡임은 약 100ms에 닫히는데, 얼굴 전체 값이면 아이라인이 실제 눈꺼풀보다 1~2프레임 늦는다.
    // beta와 속도 컷오프를 높이면 깜빡이는 그 프레임 안에서 필터가 열린다.
    eyeSmooth: { minCutoff: 3.0, beta: 200, dCutoff: 6.0 },
    maskSize: 1024,             // UV mask texture size
    lipFeatherPx: 3,            // UV-space blur radii (≈ screen px at a normal distance)
    lipEdgePx: 2,               // outer lip line: crisp like a real lipstick edge
    // Screen-space outline softness = lipEdgeBlurK × measured camera blur (px), within [0.5, lipEdgeSoftMax]. 11-02 (survey: edge
    // 75% "too crisp"): 0.5 → 1.2. Offline, the paint edge was 2.1 px against ~8 px for the photo's own lip edge (0.27×).
    // The cap keeps a blurry video (blur 4) from smearing: 2.5 px is what 10-22 measured as matching the camera there.
    lipEdgeBlurK: 1.2,
    lipEdgeSoftMax: 2.5,
    innerFadeStrength: 0,       // 0 = same coverage to the inner line (no 농도 그라데이션)
    // A real lipstick reaches the mouth corners (10-25 reference photo); 0.12 / 0.35 left the corner
    // tip at 0.22 of the lip's color on 60 real faces, now 0.50 together with lipFill.
    cornerFadeSize: 0.06,       // mouth-corner fade radius as a share of the mouth width
    cornerFadeStrength: 0.1,    // coverage lost right at the corners
    // The UV mask says where the lip is, not how much paint: its soft edge, the thin corner wedge and
    // the inner fade all read as half-painted lip. × this, capped at 1: full color up to a ~1 px
    // edge (outer 2 px of the lip 0.35 → 0.68 of the core color; LaPa miss 19.4% → 16.5%, spill
    // 15.7% → 18.4%).
    lipFill: 1.6,
    layersPerIntensity: 3,      // intensity slider → number of swipes (0.35 ≈ 1, 0.85 ≈ 2.5)
    lipBandPx: 12,              // UV band around the lips where lip fragments are drawn (the outline decides inside it); wide enough for an overlip
    overlipOpenReduce: 0.6,     // overlip / peak overdraw shrink by this share as the mouth opens (never over the teeth)
    lipCenterWidth: 0.18,       // lip-centre highlight: gaussian width, share of the mouth width
    refineMinContrast: 0.02,    // lip-vs-skin redness gap below which the lip/skin tests are off
    // Outline in screen space (10-25 close-ups: the UV spline warped per mesh triangle into kinks and
    // beak corners, and the 256 px UV redness band grew lumps). Drawn each frame from the landmarks.
    lipOutlinePx: 512,          // longest side of the outline crop texture
    lipOutlineSmooth: 0.5,      // Taubin smoothing of the landmark ring (corners and Cupid's bow fixed)
    // Open mouth: keep the hole at least this far into the mouth so the inner landmark (often on the teeth)
    // is not the paint edge. Upper bound still matches the measured wet line.
    innerInset: [0.12, 0.28],
    // Open mouth over the teeth (device 11-04: the inset above and the reflection rule painted the front teeth). Each off
    // = as before. Guard: along the inner line only, pixels that look like teeth or the dark mouth lose the paint.
    lipTeethGuard: true,
    teethBandPx: 2,             // guard band: the inset reach plus this, each side of the landmark inner line
    teethSat: [0.45, 0.7],      // teeth saturation (warm-lit teeth ~0.5; the redness test already keeps the lip)
    teethDark: 0.3,             // mouth darker than this share of the lip mean is not lip
    // Inner line from the camera: per inner point, how far lip-red reaches into the mouth (within innerInset[1]),
    // instead of the fixed inset. Falls back to the fixed inset where a ray found nothing.
    lipInnerMeasure: true,
    lipInnerEveryMs: 100,
    // Outer line pulled in where the camera sees the lip end before the landmarks (lipEdge rays, t < 1), never pushed
    // out (the 10-25 camera outline grew onto warm skin); at most this share of the lip thickness.
    lipEdgePull: true,
    lipEdgePullMax: 0.15,
    // Lip form (10-25 "직접 바른 느낌", user request): each lip is a rounded body built from this
    // person's outline (upper and lower lip apart, split at the inner line). Its normal shades the
    // paint (Lambert under the estimated light) and places each finish's GGX highlight, so a gloss
    // shines on the lower-lip centre and upper-lip ridge and a matte stays dull. The 10-25 edge band
    // darkening read as a drawn liner on thin, open lips.
    lipForm: true,
    formReach: 0.45,            // form blur radius as a share of this lip's thickness
    formFieldPx: 160,           // longest side of the blurred form field
    formTilt: 1.0,              // max tilt of the form normal at the lip line (≈ 45°)
    lipVolume: 0.3,             // share of the form's Lambert falloff applied to the paint (was 0.6; 11-02: the camera already carries the lip's own shading, the added form shade read as a dark band along the lower lip)
    seamPx: 0.12,               // closed mouth: seam split width as a share of the lip thickness
    glossMax: [0.04, 0.45],     // form highlight peak: matte → glossy (by (1 - roughness)³; satin ≈ 0.2). Was 0.85: survey 11-02, glossy lips read as plastic (white streak on the lower lip)
    glossGain: 3.0,             // highlight peak = glossMax × skin luminance × this (light sources ≫ skin)
    frontGloss: 0.6,            // share of the peak from the always-present frontal source (screen, room)
    // Flat selfie: the camera has no specular, so keepHl adds nothing and gloss looked like matte
    // (device 10-25). Boost the *form* highlight (already approved 10-25), not a UV sticker.
    // × smoothness² so matte stays dull. When the camera already has a highlight, this is ~1.
    // 11-02: 1.2 → 0.6. Off (0) made a gloss look matte again on a flat selfie (the 10-25 device case), so half of the boost stays.
    glossFlat: 0.6,
    // Gloss shape (11-02 round 2). A gloss that reads as a layer on top has a flat-topped patch (the lobe saturates), is near white and
    // warm-tinted, is added on top (so it washes the colour), spreads over the whole lip and follows the estimated light and exposure.
    // Measured on the 7 glossy pairs (the gloss layer = render minus the same render with the gloss off): highlight area 20.8% -> 16.8%
    // of the lip, peak +22.6 -> +15.3 L*, flat-topped share 27% -> 17%, colour kept (chroma x0.79 -> x0.94), 70% -> 79% on the lip centre.
    // lipSheen 0.25 -> 0.35 and wideGloss 0.3 -> 0.4 put back a broad, faint wet sheen (no hot spot) that the smaller peak had taken
    // away: lip colour dE median 4.03 -> 3.97 against the real photos.
    // A screen blend (glossTone[2]) was tried and is off: it adds most to the dark channels of a saturated lip, so it whitens more (x0.70).
    glossShape: [0.9, 0.7, 0.5, 0.5],  // [lobe width: how far above its start the highlight reaches full (0.35 = flat top, 0.7+ = a peak),
                                  //  focus on the lip centre 0..1, follow of the skin exposure 0..1, follow of the estimated light direction 0..1]
    glossTone: [0.15, 0.6, 0],    // [whiteness of the soft falloff around the peak 0..1 (1 = white all over), light colour made neutral 0..1,
                                  //  screen blend 0..1 (0 = added, 1 = screen: stops at white, keeps the colour)]
    lightSize: [0.35, 0.6],      // light size (roughness units): the source's sharp reflection, the glow around it
    wideGloss: 0.40,             // glow peak relative to the sharp reflection
    // Lip detail normal (11-03, user decision: the lip's own texture has to show in the shine). This person's wrinkles, read live
    // from the camera with the 4 neighbours that already give the local mean (no extra samples), tilt the form normal: brightness
    // relative to the local mean is taken as height (ridges light, creases dark). Nothing is drawn or stored. Off: on 5 still faces
    // the tilt (±1.5, ±4) did not make the shine follow the lip's lines (correlation inside the shine −0.06…0.13); glossCavity did.
    lipDetail: 0,                // 0 = off (form normal only)
    lipDetailTilt: 4.0,          // tilt per unit of relative brightness step across 3 px (saturates at 45°)
    lipDetailNoise: [1.5, 3.0],  // relative step below camera grain × first is ignored, full above grain × second
    lipDetailGrainMin: 0.01,     // grain floor for those thresholds (a clean still image measures ~0)
    lipDetailMouthPx: [70, 120], // mouth width (px) over which it fades in; on a smaller mouth the wrinkles are under a pixel
    // A narrow crease hides its floor from the light (brightness-as-height left a ridge top and a crease floor both untilted, lit
    // alike): the gloss and sheen are scaled by (camera / 3 px surround)^this, so they brighten on the lip's ridges and dim in its
    // creases. 5 still faces, 2 vs 0: correlation of the shine with the bare lip's lines inside the shine gloss −0.05 → 0.41,
    // satin 0.03 → 0.62; lip-core mean colour ΔE2000 ≤ 0.15. 0 = off.
    glossCavity: 2,
    wideDetail: 0,               // share of the detail normal in the broad glow and sheen (satin's look); 0 = smooth form only (needs lipDetail)
    // Unresolved vertical lip lines spread the reflection across the mouth: the GGX lobes get a larger roughness along the mouth
    // axis than across it (area kept: αx = α(1 + k), αy = α / (1 + k)). 0 = isotropic. Off: 0.6 on top of wideDetail 0.5 lowered
    // the shine-follows-lines correlation (gloss 0.08 → 0.06, satin 0.19 → 0.13) and moved a matte's mean colour most (ΔE 0.56).
    glossAniso: 0,
    grainMax: 0.2,              // cap on the measured relative camera grain
    blurMax: 4,                 // cap on the measured camera blur (px): sets grain size and mask edge softness
    lipGlint: 1.5,              // glints on lip ridges (absolute), scaled by (1 - roughness)²
    glintThreshold: 0.04,       // fine detail below this share of the lip mean (camera noise) never glints
    diffuseCap: 1.3,            // camera brightness above this × lip mean counts as highlight, not color
    specFill: 0.7,              // floor on light-dir mix so PBR sheen never fully turns off
    creaseGain: 1.0,            // scale on material detail (how much of the camera's wrinkle contrast stays)
    paperWhite: 0.85,           // reflectance of the swatch paper: tint transmittance² = product color / this
    ratioMax: 4.0,              // cap on layered/bare reflectance per channel (bright paint on dark lips)
    lumGainMax: 1.15,           // estimated chip hex may not make the lip brighter than bare × this
    creaseCover: 0.15,          // matte pigment collects in creases (+), gloss thins on ridges (−)
    mouthClosedGap: 0.06,       // inner-lip gap / mouth width below which the mouth hole is painted
    // Teeth (11-03): on a slightly open mouth the landmark inner line can lie on the teeth (a still face: upper and lower inner
    // points 0–4 px apart, page gap 0.050 of the width, while ~9 px of teeth show), so the outline painted them red. Within
    // teethReach × the mean lip thickness of the inner line (or inside it), a patch whose 4 neighbours at 1.5 px are together
    // far less red than this person's bare lip, and bright, is left unpainted. A lip sparkle (1–2 px peak) or the seam of closed
    // lips (1–2 px line) has lip around it. Redness, not saturation: under warm light teeth are yellowish and as saturated as a
    // pale lip (0.39–0.47 vs lips 0.73–0.89), but their redness was 0.07–0.26 × the lip median and the lip's 10th percentile 0.46–0.73 ×.
    // 5 still faces, painted teeth off → on: 25% → 1%, 9% → 2%, 100% → 46% (the rest: upper teeth in the upper lip's red-tinted
    // shade); inner lip unpainted ≤ 1%. [0.6, 0.8] took that face to 14–23% but left 2–6% of the inner lip of a pale pink lip bare.
    teeth: 1,                   // 0 = off
    teethRed: [0.45, 0.65],     // neighbours' redness / bare-lip redness: teeth below the first, lip above the second
    // 11-04 (device, slightly open mouth): teeth in the upper lip's shade are darker than the lip, so "brighter than the lip"
    // kept them painted. Brightness now only keeps the dark mouth cavity out; redness decides.
    teethBright: [0.3, 0.5],    // neighbours' brightness / lip mean: below the first the dark mouth (painted as before)
    teethFirm: [0.2, 0.6],      // a half-sure teeth pixel was half painted (pink teeth): rescale so a likely one is left bare
    teethReach: 0.5,
    lipRayOutlier: 0.2,         // a lip-edge ray this far (share of lip) from its neighbours' median is skipped
    hlLocal: 1.15,              // camera highlight must exceed the local 3px mean by this (a peak, not a lit area)
    hlSat: [0.3, 0.55],         // ...and be desaturated: lip color saturation ~0.6, specular ~0.2
    hlBlown: 2.2,               // or be this × lip mean (a wide reflection has no local peak in its middle)
    // 11-03: the lip's small wet sparkles along its lines are reflections too, though few reach diffuseCap × the lip mean or the
    // absolute hlSat test. Left in the color they turned into brighter red, lost in a saturated paint (5 still faces: a gloss kept
    // 24% of them, the most lined lip 1%). With this share, a spot above its surround (hlLocal) and whiter than its neighbours is a
    // reflection whatever its height; hlKeep still decides by finish how much of it stays on top of the paint. 0 = before 11-03.
    hlSparkle: 1,
    opaqueShadeGamma: 0.85,     // large-scale brightness swing kept under fully opaque paint (1 = all, 0 = flat sticker). Was 0.6; 0.85 keeps more of the camera's shading and keeps colour ΔE within 4 after the gloss cut
    lowReach: 0.35,             // radius of the large-scale lip brightness, share of the lip thickness
    lipSpecMax: 0.18,           // cap on the added clear-coat highlight (tinted, lower-centre only)
    lipSheen: 0.35,             // broad clear-coat sheen × (1 - roughness)²; coarse mesh normals miss the narrow peak
    hlKeep: [0.15, 1.0],        // camera highlight kept under the paint: matte → glossy (by 1 - roughness); never amplified
    blushFeatherPx: 28,
    // Highlighter and contour (10-25, user request): product color on fixed UV regions only, like
    // blush. Intensity 0 leaves the image untouched; no shape change (AR_SPEC 1-2, 1-3).
    hlFeatherPx: 18,
    contourFeatherPx: 28,
    faceEdgeFadePx: 36,         // contour / highlighter fade-out width inside the face outline (UV px)
    hlCoverage: 0.5,
    contourCoverage: 0.55,
    // Face-fit placement (11-04, plan step 1). Off: highlighter and shading keep today's fixed UV shape, pixel for pixel.
    // On: the style template named by geometry.hlStyle / contourStyle is drawn, with length and width nudged by this
    // person's measured face ratios. Position only; no shape change of the face (AR_SPEC 1-3).
    faceFit: true,              // identical to off until a style is picked (no hlStyle / contourStyle = default layers)
    faceFitFrames: 24,          // frontal frames averaged before the measurement is frozen
    faceFitYaw: [0.85, 1.18],   // nose-to-left-cheek over nose-to-right-cheek distance accepted as frontal
    // Volume (11-04, plan step 2). Off: flat masks, pixel-identical. On: the shading deepens where the surface turns
    // away and the highlighter strengthens where it faces the camera / light. Light direction counts only as far as
    // the estimate is trusted (uLightConf); it over-reads side light, so it is blended in, never relied on.
    hlContourVolume: false,
    volumeGain: [0.6, 0.5],     // contour deepening, highlighter strengthening (share of the product's own strength)
    volumeLight: 0.7,           // how much of the facing term may come from the light direction at full confidence
    faceFitRefs: { cheekWide: 1.2, faceLong: 1.35 }, // heuristic neutral ratios (not validated on a dataset)
    // Two-tone shadow (10-26 gal look): the second color fades in at the outer corner and along the
    // lower lash line; each eye's masks come from its own lid landmarks.
    shadow2Coverage: 0.8,
    shadow2Feather: 14,
    powderTint: 0.6,            // blush / contour: share that tints the skin (translucent) instead of covering it
    faceSheen: 0.5,             // finish sheen on blush / shadow / highlighter: peak × skin luminance, by smoothness
    // Eyeliner and mascara: drawn in screen space each frame from the lid landmarks (thin lines
    // must follow the lid exactly; a UV line warps per mesh triangle).
    eyeCanvasPx: 512,
    // Lid fit: the liner is placed on the lash line the camera shows, per eye and per frame, as offsets from the
    // MediaPipe lid points in eye widths. No per-person table: every number is a share of that eye's width.
    lidFit: {
      d0: 0.02,                 // upper line: offset used where the camera shows no edge (the lid points sit on the lid margin)
      lo: -0.01, hi: 0.05,      // upper offset range
      lowD0: 0.005, lowLo: -0.01, lowHi: 0.03, lowTrust: 0.6, // lower line: same idea, downward, trusted less
      span: 0.06,               // profile read this far each side of a lid point
      samples: 17, tangent: 0.03, // profile samples and the tangent spread averaged per sample
      minDrop: 0.08, fullDrop: 0.30, // edge step over 4 samples (share of the local brightness) mapped to confidence 0..1
      priorWeight: 0.5,         // weight of d0 against the neighbours' measurements
      minEyePx: 40,             // below this eye width the camera read is off
      blinkGap: 0.12,           // lid gap / eye width below which the read is off (eyes closing)
      faceZ: 0.35,              // eye normal z below which the read is off (turned head)
      minCutoff: 1.0, beta: 5, dCutoff: 1.0, // One Euro on the offsets (eye-width units)
      staleS: 0.5,              // no read for this long: restart from the first new value
      cropPx: 128,              // crop width read per eye
    },
    linerLowerThickness: 0.03,  // lower liner band, share of the eye width (geometry.linerLowerThickness)
    liner: { length: 0.18, angle: 15, thickness: 0.09 }, // defaults: wing length / eye width, degrees, outer thickness / eye width
    linerInnerThin: 0.3,        // inner-corner thickness as a share of the outer thickness
    lashCount: 32,              // mascara strands per upper lid
    lashLength: 0.1,            // longest strand, share of the eye width (front view foreshortens lashes)
    lashWidth: 0.012,           // strand width, share of the eye width
    lowerLash: 0.4,             // lower lashes: length share of the upper
    shadowFeatherPx: 10,
    blushSize: [0.17, 0.11],    // ellipse radii relative to the UV face width
    appleScale: 0.8,            // the face-point blush (placement / size / softness set) is this much smaller than the baked default
    shadowCrease: 0.6,          // how far toward the brow the shadow reaches (0..1)
    blushCoverage: 0.6,         // coverage = intensity × this
    // Foundation (10-29): the zone intensity is the coverage slider (0..1). It sets how strongly the layer is put on and
    // how much of it is opaque pigment (camera shading only, so redness and blotches are covered as far as the product
    // covers) versus a translucent film that lets the skin's own color through. No sheen, finish or brightening;
    // YouCam glowIntensity stays 0.
    foundCoverage: [0.3, 0.85],   // layer strength, sheer → full coverage
    foundOpaque: [0.15, 0.9],     // opaque pigment share, sheer → full coverage
    foundHair: [0.3, 0.55],       // brightness / mean skin brightness: below 0.3 no foundation (hair, brows), full above 0.55 — fallback if the segmenter is off
    foundSegEveryMs: 120,         // face-skin mask while foundation is on (~8/s, so a forehead uncovered by lifted bangs fills in quickly)
    foundSegEveryLowFpsMs: 400,   // under segmentMinFps the mask still refreshes this often (it used to stop, freezing the hairline)
    foundSegMix: 0.15,            // keep this share of the previous mask when hair appears (bangs falling back: drop the paint fast)
    foundSegMixRise: 0.12,        // keep little of the previous mask when skin is newly visible
    foundEdgeFadePx: 90,          // foundation-only outline fade (UV px, box blur ~ this wide); the contour fade stays at faceEdgeFadePx
    foundEdgeLo: 0.5,             // blurred outline value that still gets 0 foundation (0.5 = the mesh outline itself: the product is 0 exactly where the mesh ends)
    foundCapLen: 2.2,             // forehead cap above the mesh (which stops mid-forehead): height × (brow centre 9 → mesh top 10); 1.2 ended below the hairline on a high forehead (horizontal seam)
    jawHingeMax: 0.55,            // jawline strip under the earlobe past 234/454, up to 0.55 of 234–132, skin or sideburn
    foundCapFade: 0.6,            // cap share that is full; it fades to 0 above this (fallback when the skin mask is off: brightness gate only)
    foundCapFadeMasked: 0.9,      // same, while the skin mask is on: the mask cuts hair / background, so only the last tenth of the cap fades
    foundEdgeHi: 0.98,            // ... and the value that gets full foundation (smoothstep between: no visible rim)
    foundSkinProb: [0.35, 0.75],  // selfie-multiclass face-skin probability: below no foundation (hair, bangs), full above
    foundTone: [0.18, 0.35],      // chromaticity distance to this face's skin colour: full foundation below, none above (orange / brown bangs the mask missed). Chromaticity only: brightness gates cut highlights into blotches
    // Lower face (11-02, clip of a moving head): the skin mask is a screen-space texture refreshed every 120 ms (400 ms under 20 fps),
    // so on a moving head its edge lagged the face and left a bare strip along the cheek (up to 19% of the lower face at 400 ms). Below
    // the eyes hair and background are rare, so there the paint follows the landmark outline at once and the mask only clips it while a
    // hand or hair covers the lower face (cover below). Above the eyes (bangs) the mask keeps gating as before.
    foundLowerFloor: 0.9,         // lower-face paint kept whatever the (possibly stale) mask says, while nothing covers the lower face
    foundLowerV: [0.50, 0.58],    // atlas v (up = forehead; eyes 0.62, nose tip 0.45): fully lower face below the first, not at all above the second
    foundOccCover: [0.6, 0.85],   // share of cheek / chin landmarks the mask calls skin: floor off below the first, fully on above the second
    // Color makeup over a hand / cup / hair on the eyes (11-04). Off = the paint sits on the mesh even when those
    // cover the region (previous behaviour). The forehead / bangs path for foundation is unchanged.
    makeupOcclusion: true,
    occCover: [0.6, 0.85],        // share of region landmarks that are still face skin: gate 0 below the first, 1 (no clip) above the second
    occGlide: 0.35,               // EMA of the gate; 1 would snap the paint off in one mask frame
    zoomMin: 1,                   // 1x = captured FOV; smaller would letterbox empty sensor
    zoomMax: 4,                   // digital crop of the 720-cap frame; tracking softens past this
    foundShadeMax: 1.2,           // camera highlights may brighten the pigment this much at most (was 1.6 via powder: a glow)
    lightDisplaySec: 0.6,         // light color / exposure / skin brightness glide to each new estimate (no 0.5 s steps)
    // Light direction / strength / confidence glide every frame too (off: the shader gets the 0.5 s estimate as it is).
    // A new fit more than lightDirSnapDeg away from the estimate replaces it at once instead of the 0.35 EMA.
    lightDirGlide: false,
    lightDirSec: 0.4,
    lightDirSnapDeg: 25,
    // Huber IRLS for the normal→brightness fit instead of dropping the worst 20% once (off: the old fit).
    lightRobust: false,
    lightHuberC: 1.345,
    lightIrlsIters: 4,
    // With lightRobust, confidence is the larger of the R² map and |b|/a mapped over lightConfRel: |b|/a does not fall
    // on dark skin, R² does.
    lightConfRel: [0.3, 0.6],
    // 'sh9': skin brightness ≈ ambient + max(b·n, 0) with shadowed samples on the ambient only, and its 9-term spherical
    // harmonics irradiance (Ramamoorthi & Hanrahan 2001) for the lip volume; the gloss size follows how directional the
    // light is. 'linear': brightness ≈ a + b·n as before.
    lightModel: 'linear',
    lightShIters: 6,            // lit-set refits
    lightShMinSamples: 60,      // fewer samples, or a condition number above lightShMaxCond: the linear fit this time
    lightShMaxCond: 1e5,
    // With 'sh9': the lip volume from the SH9 irradiance instead of the Lambert ratio, and the gloss light size × (1 ± spread)
    // by how directional the light is. Both off: on the 20 Kaggle pairs the SH volume cut L* spread wins 11 → 7 and the size
    // changed nothing measurable (research/light_eval/results/stage4_kaggle.json).
    lightShVolume: false,
    lightShSizeSpread: 0,
    skinToneEveryMs: 1500,        // skin tone numbers sent to the app for the shade suggestion
    browCoverage: 1.0,           // EYEBROW_PRESET.baseOpacity. Landmark ring only; no parsing/GAN.
    shadowCoverage: 1.0,        // unused for lid paint; opacity comes from SHADOW_FINISHES
    skinRefLum: 0.34,           // assumed skin reflectance (linear Y) for exposure scaling
    exposureRange: [0.2, 1.6],
    specMax: 0.85,
    flakeDensity: 0.985,        // share of UV cells without a shimmer flake
    flakeScale: 700,            // UV cells per unit for flakes (matte has none)
    flakeScaleShimmer: 480,     // highlighter / lip shimmer cells
    shimmerScale: 520,          // YouCam shimmer: high-frequency sand, not clumps
    glitterScale: 600,          // same fine sand as shimmer, slightly finer cells
    // Lid shimmer / glitter (11-04). The old cells (shimmerScale / glitterScale) are under a pixel on a phone selfie (eye
    // ~0.1 UV wide, ~100 px), so grains came and went with every small move. On: fewer, larger cells still fixed to the
    // face; grain radius from the eye's size on screen (never under lidMinGrainPx); glitter is its own sharp flash
    // toward a fixed virtual light (not the 0.5 s light estimate, which made all of it blink at once); both fade out
    // while the eye closes. Off: the old grains.
    lidSparkle: true,
    lidShimmerScale: 260,       // UV cells per unit
    lidGlitterScale: 130,
    lidGlitterDensity: 0.45,    // share of glitter cells holding a particle (SHADOW_FINISHES.glitter.sparkleDensity is the old one)
    lidGrainRad: [0.2, 0.2],    // grain radius, share of the cell: shimmer, glitter
    lidMinGrainPx: 0.9,         // grain radius never under this on screen
    lidShimmerBase: 0.45,       // shimmer grain level (the old grains used 1)
    lidSheen: 0.6,              // broad pearl sheen under the grains, both finishes
    lidGlitterPower: 48,        // flash sharpness (shimmer stays at 6)
    lidGlitterGain: 2.5,
    lidGlitterBase: 0.35,       // particle visible without a flash, share of the shimmer grain level
    lidOpenGap: [0.08, 0.18],   // lid gap / eye width: sparkle off below, full above
    shimmerFlake: 0.9,
    lightEveryMs: 500,
    segmentEveryMs: 2000,       // background segmentation (light color) is heavier: run less often
    segmentMinFps: 20,          // and skip it while the frame rate is low
    lightSmoothing: 0.35,
    // White balance unlocked (iPhone WebView refuses the lock): the camera keeps re-balancing, so the light color
    // estimate runs more often and follows faster, keeping the painted lip in step with the bare lip.
    segmentEveryMsAuto: 1000,
    lightSmoothingAuto: 0.6,
    // Lock white balance once a face is tracked and the background color has settled (two estimates that agree),
    // not before this many ms; past the deadline it locks anyway.
    wbLockMinMs: 2000,
    wbLockMaxMs: 6000,
    wbStableDelta: 0.03,
    lightColorClamp: [0.75, 1.3],
    bgMinFraction: 0.15,        // Gray World needs this share of background pixels
    bgMaxChroma: 1.6,           // max/min channel ratio above which the background is "one color"
    // Gray-Edge mixed into the Gray World light color (off: Gray World only). Weight [normal background, one-color or
    // small background]; with it on, the one-color check runs on the mixed color. Not measured offline (no segmenter
    // there): check the HUD on a device before shipping it on.
    lightColorEdge: false,
    lightColorEdgeMix: [0.25, 0.75],
    clipLin: 0.92,              // linear value treated as blown out
    darkLum: 0.02,
    lightConfR2: [0.1, 0.4],    // R² of the normal→brightness fit mapped to confidence 0..1
    // Light by matching candidate lights with cast shadows (matchLight) instead of the straight-line fit. Off = old fit.
    // On since 11-04 (user decision after the phone check). Research use; a commercial release needs a patent review (US 11,030,798).
    lightMatch: true,
    lightMatchGrid: 48,         // face height grid cells along the longer side (cast-shadow test)
    lightMatchMaxVerts: 160,    // skin vertices used (evenly spaced); cost grows with this
    lightMatchSpread: 0.02,     // R² gap over which a runner-up candidate's weight in the blend falls by e
    lightChangeDelta: 6,        // CIE76 on mean skin Lab: above this, Gray World snaps (no smoothing)
    blownFaceFraction: 0.15,    // share of in-frame skin verts blown out → "light too strong"
  };
  // roughness/specular/flake: PBR_DEMO_SPEC 5 starting values, then detail/specular nudged
  // toward finish medians in research/data/reference/lip_texture/lip_texture.sqlite (Pexels/Unsplash
  // direction of change vs. bare lips — not a1 or colour ground truth; 6-15 still owns measured a1).
  // a1: share of the lip covered by one swipe; translucent: 0 = paint over, 1 = tint like a filter;
  // detail: how much of the camera's wrinkle contrast stays under the paint (1 = all of it).
  // Lip shading itself is never a material value: it is the real camera shading (layering, 6-5-3).
  const MATERIALS = {
    matte:   { roughness: 0.90, specular: 0.35, flake: 0, a1: 0.72, translucent: 0.0, detail: 1.15 },
    velvet:  { roughness: 0.75, specular: 0.45, flake: 0, a1: 0.66, translucent: 0.0, detail: 1.10 },
    cream:   { roughness: 0.55, specular: 0.60, flake: 0, a1: 0.58, translucent: 0.12, detail: 1.05 },
    satin:   { roughness: 0.42, specular: 0.85, flake: 0, a1: 0.50, translucent: 0.12, detail: 1.15 },
    sheer:   { roughness: 0.32, specular: 0.90, flake: 0, a1: 0.38, translucent: 0.8, detail: 1.05 },
    glossy:  { roughness: 0.16, specular: 1.15, flake: 0, a1: 0.46, translucent: 0.28, detail: 0.95 },
    shimmer: { roughness: 0.38, specular: 0.90, flake: 1, a1: 0.55, translucent: 0.12, detail: 1.10 },
  };
  const SHADOW_FINISHES = {
    matte:   { opacity: 0.7,  roughness: 1.0, sparkleDensity: 0.0, specular: 0.0 },
    shimmer: { opacity: 0.3,  roughness: 0.4, sparkleDensity: 0.35, specular: 0.4 },
    glitter: { opacity: 0.3,  roughness: 0.2, sparkleDensity: 0.75, specular: 0.95 },
    glossy:  { opacity: 0.25, roughness: 0.05, sparkleDensity: 0.0, specular: 0.9 },
  };
  // Brow: product hex on the person's landmark ring. Hair alpha is the camera, not a stock map.
  // Liner: every style is the same band + wing from the geometry numbers (lib/linerLooks.ts). The line is one
  // flat, fully opaque ink (10-29): no matte smudge ring, no gloss sheen, no camera shading, and nothing under it
  // (eyeshadow) shows through its core. Only the edge keeps a half-texel anti-alias.
  const EYELINER_DARK = {
    opacity: 1.0,       // core coverage at every intensity (intensity no longer fades the liner)
    minPx: 1.5,         // band never thinner than this many eye-canvas pixels, so it cannot fade below one texel
  };
  function smooth01(a, b, x) { const r = clamp01((x - a) / (b - a)); return r * r * (3 - 2 * r); }
  const EYEBROW_PRESET = {
    baseOpacity: 1.0,
    colorMixRatio: 1.0,
    roughness: 1.0,
    headDensity: 0.4,
    archDensity: 0.85,
    tailDensity: 0.9,
    hairOverlay: 0.0,
    hairFloor: 0.0,
    hardLight: 0.0,
    feather: 1.0,
    hairMix: 1.0,
    dropTowardEye: 0.55,
    extraDrop: 0.0,
    powder: 0.45,                // pencil/powder layer: translucent tint over skin and hair (never brightens)
    lift: 0.35,                  // brow-mascara layer: how far a dark hair moves toward a lighter product tone
    softness: 0.25,              // feather radius of the brow edge, share of the brow height
  };
  function lipCoverage(zone, mat) {
    const layers = Math.max(0.3, clamp01(zone.intensity) * TUNING.layersPerIntensity);
    return 1 - Math.pow(1 - mat.a1, layers);
  }
  // Keep the selected lip product, but bypass all lip shading at exactly zero intensity.
  function lipEffectEnabled(zone) { return !!zone && zone.intensity > 0; }

  const LIPS_OUTER = [61,185,40,39,37,0,267,269,270,409,291,375,321,405,314,17,84,181,91,146];
  const LIPS_INNER = [78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95];
  const EYES = [
    { lid: [33,246,161,160,159,158,157,173,133], brow: [46,53,52,65,55],
      contour: [33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246] },
    { lid: [263,466,388,387,386,385,384,398,362], brow: [276,283,282,295,285],
      contour: [263,249,390,373,374,380,381,382,362,398,384,385,386,387,388,466] },
  ];
  const BROWS = [70,63,105,66,107,55,65,52,53,46,300,293,334,296,336,285,295,282,283,276];
  const CHEEKS = [
    { inner: 50, outer: 116, low: 205 },
    { inner: 280, outer: 345, low: 425 },
  ];
  const FACE_EDGES = [234, 454];
  const N_MESH = 468;
  const N_LANDMARKS = 478;

  const video = document.getElementById('video');
  const glCanvas = document.getElementById('canvas');
  const hud = document.getElementById('hud');
  const jawdbg = document.getElementById('jawdbg');
  let jawAb = 0;
  let jawAbTap = 0;
  if (jawdbg) {
    const cycleJawAb = (ev) => {
      const t = Date.now();
      if (t - jawAbTap < 400) { ev.stopPropagation(); return; }
      jawAbTap = t;
      jawAb = (jawAb + 1) % 3;
      ev.stopPropagation();
    };
    jawdbg.addEventListener('click', cycleJawAb);
    jawdbg.addEventListener('touchend', cycleJawAb);
  }
  const overlay = document.getElementById('overlay');
  const overlayCtx = overlay.getContext('2d');

  let makeup = { lip: null, blush: null, eyeshadow: null, eyeliner: null, mascara: null, highlighter: null, contour: null, brow: null, foundation: null };
  let pendingRender = null;
  let pendingRestore = null;
  let commandRendererId = null;
  let lastRenderSeq = -1;
  let lastStateSeq = -1;
  let compare = false;
  // Drawing guide (AR_SPEC 6-5-11): null, or { step, angle, length, style } from the app.
  let guide = null;
  let landmarker = null;
  let landmarkerDelegate = '-';
  let segmenter = null;
  let lastVideoTime = -1;
  let lastFaceAt = 0;
  let hasFace = false;
  let status = null;
  let renderer = null;

  // ── Messaging ────────────────────────────────────────────────────────
  function post(message) {
    const text = JSON.stringify(message);
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(text);
    else if (window.parent !== window) window.parent.postMessage(text, '*');
  }
  function setStatus(next, detail) {
    if (status === next) return;
    status = next;
    post({ type: 'status', status: next, detail });
  }
  function handleMessage(raw) {
    let msg;
    try { msg = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { return; }
    if (!msg || typeof msg !== 'object') return;
    const sequenced = (msg.type === 'makeup' || msg.type === 'render_command' || msg.type === 'restore_command') && Number.isSafeInteger(msg.stateSeq);
    if (sequenced && msg.stateSeq <= lastStateSeq) return;
    if (msg.type === 'makeup' && msg.makeup) {
      if (sequenced) lastStateSeq = msg.stateSeq;
      makeup = msg.makeup; pendingRender = null; pendingRestore = null;
    }
    if ((msg.type === 'render_command' || msg.type === 'restore_command') && typeof msg.commandId === 'string' && msg.commandId &&
        Number.isSafeInteger(msg.renderSeq) && msg.renderSeq >= 0 && typeof msg.rendererId === 'string' && msg.rendererId) {
      const restoring = msg.type === 'restore_command';
      if (restoring && (typeof msg.restoreId !== 'string' || !msg.restoreId)) return;
      if ((commandRendererId !== null && commandRendererId !== msg.rendererId) || msg.renderSeq <= lastRenderSeq) return;
      if (sequenced) lastStateSeq = msg.stateSeq;
      commandRendererId = msg.rendererId;
      lastRenderSeq = msg.renderSeq;
      pendingRender = null;
      pendingRestore = null;
      const lip = msg.makeup && msg.makeup.lip;
      const validMakeup = msg.makeup && typeof msg.makeup === 'object';
      const validLip = lip && typeof lip.intensity === 'number' && Number.isFinite(lip.intensity) && lip.intensity >= 0 && lip.intensity <= 1;
      const result = { commandId: msg.commandId, renderSeq: msg.renderSeq, rendererId: msg.rendererId };
      if (restoring) result.restoreId = msg.restoreId;
      if (!validMakeup || (!restoring && !validLip) || (restoring && lip && !validLip)) {
        post(Object.assign({ type: restoring ? 'restore_result' : 'render_result', status: 'failed' }, result));
      } else {
        makeup = msg.makeup;
        pendingRender = restoring ? null : result;
        pendingRestore = restoring ? result : null;
      }
    }
    if (msg.type === 'compare') compare = !!msg.value;
    if (msg.type === 'preview') { /* capture already matches the phone screen; cover stays edge-to-edge */ }
    if (msg.type === 'guide') {
      guide = msg.guide && typeof msg.guide === 'object' ? msg.guide : null;
      if (!guide) overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
    }
  }
  window.__kb = { receive: handleMessage };
  window.addEventListener('message', (e) => handleMessage(e.data));
  document.addEventListener('message', (e) => handleMessage(e.data));

  // ── Color helpers (sRGB EOTF, AR_SPEC 6-5) ───────────────────────────
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function clamp01(v) { return clamp(Number(v) || 0, 0, 1); }
  function toLin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function hexToLinear(hex) {
    const h = String(hex || '').replace('#', '');
    const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16) || 0;
    return [toLin(((n >> 16) & 255) / 255), toLin(((n >> 8) & 255) / 255), toLin((n & 255) / 255)];
  }
  function lumOf(r, g, b) { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
  // Linear sRGB → CIE Lab (D65). CIE76 is enough here: the page has no ΔE2000, and the threshold is 6.
  function linToLab(rgb) {
    const x = (0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]) / 0.95047;
    const y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    const z = (0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    const fx = f(x), fy = f(y), fz = f(z);
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  }
  function cie76(a, b) {
    return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  }

  // ── One Euro filter over all landmarks (no per-frame allocation) ─────
  const sx = new Float32Array(N_LANDMARKS);
  const sy = new Float32Array(N_LANDMARKS);
  const sz = new Float32Array(N_LANDMARKS);
  const dvx = new Float32Array(N_LANDMARKS);
  const dvy = new Float32Array(N_LANDMARKS);
  let filterReady = false;
  let filterT = 0;
  function euroAlpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  // Anchors follow the raw landmarks with no filter, and One Euro smooths only each point's offset from
  // its anchor: a head shake or turn moves the makeup in the same frame (device 10-25: it trailed
  // behind), while a still face keeps its steadiness. The anchor is the mouth centre near the mouth
  // and the face centre elsewhere, blended by canonical distance (no seam). Simulated at 30 fps, ±60 px:
  // 2 Hz shake max error 20.8 → 2.2 px, turn (mouth moving more than the face) 27.3 → 2.2 px.
  const ox = new Float32Array(N_LANDMARKS);
  const oy = new Float32Array(N_LANDMARKS);
  let mouthW = null;
  let eyePt = null;
  function eyePoints() {
    const m = new Uint8Array(N_LANDMARKS);
    for (const e of EYES) for (const i of e.contour) m[i] = 1;
    for (const e of EYE_LINES) for (const i of e.upper.concat(e.lower)) m[i] = 1;
    for (let i = N_MESH; i < N_LANDMARKS; i++) m[i] = 1;
    return m;
  }
  function mouthWeights() {
    const w = new Float32Array(N_LANDMARKS);
    let mx = 0, my = 0;
    for (const i of LIPS_OUTER) { mx += FACE_UV[2 * i]; my += FACE_UV[2 * i + 1]; }
    mx /= LIPS_OUTER.length; my /= LIPS_OUTER.length;
    const mw = Math.hypot(FACE_UV[2 * 61] - FACE_UV[2 * 291], FACE_UV[2 * 61 + 1] - FACE_UV[2 * 291 + 1]);
    for (let i = 0; i < N_MESH; i++) {
      const d = Math.hypot(FACE_UV[2 * i] - mx, FACE_UV[2 * i + 1] - my) / mw;
      const s = clamp((d - 0.6) / 0.9, 0, 1);
      w[i] = 1 - s * s * (3 - 2 * s);
    }
    return w;
  }
  function filterLandmarks(face, t) {
    const n = Math.min(N_LANDMARKS, face.length);
    if (!mouthW) mouthW = mouthWeights();
    if (!eyePt) eyePt = eyePoints();
    let cx = 0, cy = 0, mx = 0, my = 0;
    for (let i = 0; i < n; i++) { cx += face[i].x; cy += face[i].y; }
    cx /= n; cy /= n;
    for (const i of LIPS_OUTER.concat(LIPS_INNER)) { mx += face[i].x; my += face[i].y; }
    mx /= LIPS_OUTER.length + LIPS_INNER.length; my /= LIPS_OUTER.length + LIPS_INNER.length;
    const ax = (i) => cx + mouthW[i] * (mx - cx), ay = (i) => cy + mouthW[i] * (my - cy);
    if (!filterReady || t - filterT > 0.5) {
      for (let i = 0; i < n; i++) { ox[i] = face[i].x - ax(i); oy[i] = face[i].y - ay(i); sz[i] = face[i].z || 0; dvx[i] = 0; dvy[i] = 0; }
      filterReady = true; filterT = t;
    } else {
      const dt = Math.max(0.001, t - filterT);
      filterT = t;
      const ad = euroAlpha(TUNING.smoothDCutoff, dt);
      const ES = TUNING.eyeSmooth;
      const adEye = euroAlpha(ES.dCutoff, dt);
      for (let i = 0; i < n; i++) {
        const x = face[i].x - ax(i), y = face[i].y - ay(i);
        const eyeI = eyePt[i] === 1;
        const adI = eyeI ? adEye : ad;
        dvx[i] += adI * ((x - ox[i]) / dt - dvx[i]);
        dvy[i] += adI * ((y - oy[i]) / dt - dvy[i]);
        const speed = Math.sqrt(dvx[i] * dvx[i] + dvy[i] * dvy[i]);
        const a = eyeI ? euroAlpha(ES.minCutoff + ES.beta * speed, dt) : euroAlpha(TUNING.smoothMinCutoff + TUNING.smoothBeta * speed, dt);
        ox[i] += a * (x - ox[i]);
        oy[i] += a * (y - oy[i]);
        sz[i] += a * ((face[i].z || 0) - sz[i]);
      }
    }
    for (let i = 0; i < n; i++) { sx[i] = ax(i) + ox[i]; sy[i] = ay(i) + oy[i]; }
  }

  // ── UV masks: painted once (R = lips, G = blush, B = eyeshadow) ──────
  function lerp(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }
  function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }
  function centroid(list) {
    let x = 0, y = 0;
    for (const p of list) { x += p[0]; y += p[1]; }
    return [x / list.length, y / list.length];
  }
  function splinePath(c, p) {
    const n = p.length;
    c.moveTo(p[0][0], p[0][1]);
    for (let i = 0; i < n; i++) {
      const p0 = p[(i - 1 + n) % n], p1 = p[i], p2 = p[(i + 1) % n], p3 = p[(i + 2) % n];
      c.bezierCurveTo(
        p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
        p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6,
        p2[0], p2[1]
      );
    }
    c.closePath();
  }
  // Open Catmull–Rom: lid corners stay put; the stroke does not close into a ring.
  function openSpline(p, samples) {
    const n = p.length;
    if (n < 2) return p.slice();
    const s = samples || 6;
    const out = [];
    for (let i = 0; i < n - 1; i++) {
      const p0 = p[Math.max(0, i - 1)], p1 = p[i], p2 = p[i + 1], p3 = p[Math.min(n - 1, i + 2)];
      for (let h = 0; h < s; h++) {
        const t = h / s, t2 = t * t, t3 = t2 * t;
        out.push([
          0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
          0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
        ]);
      }
    }
    out.push(p[n - 1]);
    return out;
  }
  function boxBlur(src, S, r) { return boxBlurRect(src, S, S, r); }
  // Two box passes (≈ a smooth bell) over a W × H field.
  function boxBlurRect(src, W, H, r) {
    if (r < 1) return src;
    let a = src;
    const b = new Float32Array(W * H);
    const w = 2 * r + 1;
    for (let pass = 0; pass < 2; pass++) {
      for (let y = 0; y < H; y++) {
        const row = y * W;
        let acc = 0;
        for (let x = -r; x <= r; x++) acc += a[row + clamp(x, 0, W - 1)];
        for (let x = 0; x < W; x++) {
          b[row + x] = acc / w;
          acc += a[row + Math.min(W - 1, x + r + 1)] - a[row + Math.max(0, x - r)];
        }
      }
      const c = pass === 0 ? new Float32Array(W * H) : a;
      for (let x = 0; x < W; x++) {
        let acc = 0;
        for (let y = -r; y <= r; y++) acc += b[clamp(y, 0, H - 1) * W + x];
        for (let y = 0; y < H; y++) {
          c[y * W + x] = acc / w;
          acc += b[Math.min(H - 1, y + r + 1) * W + x] - b[Math.max(0, y - r) * W + x];
        }
      }
      a = c;
    }
    return a;
  }
  // ── Face-fit style templates (data, like LINER_LOOKS). Right side in UV; side:true mirrors it. ──
  // ell: center = lerp of two landmarks (c: [a, b, mix]), toward = landmark, a / b = radii, in units of a reference length.
  // stroke: landmark chain, w = width. fit names a measured multiplier. ref: cheek | eye | nose | mouth | jaw.
  const HL_TEMPLATES = {
    natural_cheek: [{ t: 'ell', side: true, c: [111, 143, 0.3], to: 34, a: 0.45, b: 0.14, ref: 'cheek', alpha: 0.85, fit: 'cheekLen' }],
    glass_c_zone: [{ t: 'stroke', side: true, ids: [34, 143, 111, 117], w: 0.2, ref: 'cheek', alpha: 0.7, fit: 'cheekLen' }],
    nose_tip: [
      { t: 'stroke', ids: [168, 6, 197, 195, 5], w: 0.9, ref: 'nose', alpha: 1 },
      { t: 'ell', c: [4, 4, 0], to: 5, a: 0.6, b: 0.5, ref: 'nose', alpha: 1 },
    ],
    under_eye_smile: [{ t: 'ell', side: true, c: [145, 205, 0.35], to: 33, a: 0.5, b: 0.22, ref: 'eye', alpha: 0.65 }],
    cupid_bow: [{ t: 'ell', c: [0, 164, 0.55], to: 0, a: 0.45, b: 0.18, ref: 'eye', alpha: 1 }],
    forehead_center: [{ t: 'ell', c: [151, 9, 0.3], to: 8, a: 0.9, b: 0.5, ref: 'eye', alpha: 0.6 }],
  };
  // Shading styles (11-04, user list): where the product goes only. The face itself is never reshaped (AR_SPEC 1-3).
  const CONTOUR_TEMPLATES = {
    // Filled band from the jaw outline inward on the skin (not a single stroke). Extra chin / angle / side
    // patches follow measured ratios only.
    jawline: [
      { t: 'band', side: true, ids: [132, 58, 172, 136, 150, 149, 176, 148, 152], toward: 50,
        insets: [0.42, 0.40, 0.34, 0.28, 0.22, 0.18, 0.15, 0.13, 0.12],
        insetFit: ['jawAngle', 'jawAngle', 'jawAngle', 'jawW', 'jawW', 'jawChin', 'jawChin', 'jawChin', 'jawChin'],
        ref: 'jaw', alpha: 0.9 },
      { t: 'ell', side: true, c: [172, 58, 0.4], to: 132, a: 0.4, b: 0.22, ref: 'jaw', alpha: 0.7, fit: 'jawAngle' },
      { t: 'ell', c: [152, 199, 0.4], to: 18, a: 0.5, b: 0.22, ref: 'jaw', alpha: 0.35, fit: 'jawChin' },
    ],
    // From the triangle under the brow head down both sides of the bridge, with a light touch around the tip.
    nose: [
      { t: 'stroke', side: true, ids: [55, 193, 122, 196, 3, 51, 45], w: 0.9, ref: 'nose', alpha: 1 },
      { t: 'ell', side: true, c: [45, 4, 0.5], to: 4, a: 0.45, b: 0.3, ref: 'nose', alpha: 0.6 },
    ],
  };
  // Measured ratios of this face -> multipliers for the templates, and placement-text keys (no face-shape names).
  function faceFitFrom(r) {
    const R = TUNING.faceFitRefs;
    const wide = r.cheekWide - R.cheekWide, long = r.faceLong - R.faceLong;
    const rec = [];
    if (wide > 0.08) rec.push('cheek_wide'); else if (wide < -0.08) rec.push('cheek_narrow');
    if (long > 0.1) rec.push('face_long'); else if (long < -0.1) rec.push('face_short');
    if (!rec.length) rec.push('balanced');
    const fit = {
      cheekLen: clamp(1 - 0.8 * wide, 0.75, 1.2),
      jawW: clamp(1 - 0.5 * wide, 0.8, 1.15),
      // Placement weights for the jawline fill (no face-shape names).
      jawChin: clamp(1 - 0.9 * long, 0.45, 1.45),
      jawAngle: clamp(1 + 0.7 * wide, 0.55, 1.4),
      jawSide: clamp(1 + 0.45 * wide, 0.65, 1.35),
    };
    return { fit, rec };
  }
  function paintMasks() {
    const S = TUNING.maskSize;
    const canvas = document.createElement('canvas');
    canvas.width = S; canvas.height = S;
    const c = canvas.getContext('2d', { willReadFrequently: true });
    const U = (i) => [FACE_UV[2 * i] * S, FACE_UV[2 * i + 1] * S];
    const pts = (list) => list.map(U);
    function layer(draw, feather) {
      c.globalCompositeOperation = 'source-over';
      c.clearRect(0, 0, S, S);
      draw();
      const d = c.getImageData(0, 0, S, S).data;
      const out = new Float32Array(S * S);
      for (let i = 0; i < S * S; i++) out[i] = d[i * 4 + 3] / 255;
      return boxBlur(out, S, Math.round(feather / 2));
    }
    const lipShape = layer(() => {
      c.fillStyle = '#fff';
      c.beginPath();
      splinePath(c, pts(LIPS_OUTER));
      c.fill();
    }, TUNING.lipEdgePx);
    const cornerR = dist(U(61), U(291)) * TUNING.cornerFadeSize;
    const cornerGlow = layer(() => {
      for (const p of [U(61), U(291)]) {
        const g = c.createRadialGradient(p[0], p[1], 0, p[0], p[1], cornerR);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        c.fillStyle = g;
        c.beginPath(); c.arc(p[0], p[1], cornerR, 0, Math.PI * 2); c.fill();
      }
    }, 0);
    const lip = new Float32Array(S * S);
    const lipFade = new Float32Array(S * S);
    const corner = new Float32Array(S * S);
    for (let i = 0; i < S * S; i++) {
      corner[i] = 1 - TUNING.cornerFadeStrength * cornerGlow[i];
      lipFade[i] = corner[i];
      lip[i] = lipShape[i] * lipFade[i];
    }
    const band = layer(() => {
      c.fillStyle = '#fff';
      c.strokeStyle = '#fff';
      c.lineWidth = TUNING.lipBandPx * 2;
      c.lineJoin = 'round';
      c.beginPath();
      splinePath(c, pts(LIPS_OUTER));
      c.fill();
      c.stroke();
    }, TUNING.lipFeatherPx);
    const faceW = dist(U(FACE_EDGES[0]), U(FACE_EDGES[1]));
    const blush = layer(() => {
      for (const cheek of CHEEKS) {
        const inner = U(cheek.inner), outer = U(cheek.outer);
        const center = lerp(lerp(inner, outer, 0.4), U(cheek.low), 0.25);
        c.save();
        c.translate(center[0], center[1]);
        c.rotate(Math.atan2(outer[1] - inner[1], outer[0] - inner[0]));
        c.scale(faceW * TUNING.blushSize[0], faceW * TUNING.blushSize[1]);
        const g = c.createRadialGradient(0, 0, 0, 0, 0, 1);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(0.4, 'rgba(255,255,255,0.75)');
        g.addColorStop(0.75, 'rgba(255,255,255,0.3)');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        c.fillStyle = g;
        c.beginPath(); c.arc(0, 0, 1, 0, Math.PI * 2); c.fill();
        c.restore();
      }
    }, TUNING.blushFeatherPx);
    const shadow = layer(() => {
      for (const eye of EYES) {
        const lid = pts(eye.lid);
        const crease = eye.brow.map((bi, j) => {
          const li = Math.round((j * (lid.length - 1)) / (eye.brow.length - 1));
          return lerp(lid[li], U(bi), TUNING.shadowCrease);
        });
        const lidC = centroid(lid), creaseC = centroid(crease);
        const g = c.createLinearGradient(lidC[0], lidC[1], creaseC[0], creaseC[1]);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(0.55, 'rgba(255,255,255,0.85)');
        g.addColorStop(1, 'rgba(255,255,255,0.45)');
        c.fillStyle = g;
        c.beginPath(); splinePath(c, lid.concat(crease.slice().reverse())); c.fill();
        // Same product color under the outer lower lash (not the inner corner).
        const low = pts(eye.contour.slice(0, 9));
        const tail = low.slice(0, 6);
        const t0 = tail[0], t1 = tail[tail.length - 1], eyeW = dist(lid[0], lid[lid.length - 1]);
        const lg = c.createLinearGradient(t0[0], t0[1], t1[0], t1[1]);
        lg.addColorStop(0, 'rgba(255,255,255,1)');
        lg.addColorStop(1, 'rgba(255,255,255,0)');
        c.strokeStyle = lg; c.lineWidth = 0.28 * eyeW; c.lineCap = 'round'; c.lineJoin = 'round';
        c.beginPath(); tail.forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.stroke();
      }
    }, TUNING.shadowFeatherPx);
    // Highlighter and contour, drawn on one side and mirrored about the face midline.
    const midU = [1, 4, 5, 6, 168, 152, 10, 0, 17].reduce((a, i) => a + U(i)[0], 0) / 9;
    function bothSides(drawSide) {
      drawSide();
      c.save(); c.translate(2 * midU, 0); c.scale(-1, 1); drawSide(); c.restore();
    }
    function polyStroke(ids, width, alpha) {
      c.globalAlpha = alpha; c.lineWidth = width; c.lineCap = 'round'; c.lineJoin = 'round';
      c.beginPath(); ids.map(U).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.stroke();
    }
    function ellipse(center, toward, rMajor, rMinor, alpha) {
      c.save(); c.globalAlpha = alpha; c.translate(center[0], center[1]);
      c.rotate(Math.atan2(toward[1] - center[1], toward[0] - center[0]));
      c.beginPath(); c.ellipse(0, 0, rMajor, rMinor, 0, 0, Math.PI * 2); c.fill(); c.restore();
    }
    const noseW = dist(U(6), U(122));
    const refLen = { cheek: dist(U(117), U(34)), eye: dist(U(33), U(133)), nose: noseW, mouth: dist(U(0), U(164)), jaw: dist(U(123), U(147)) };
    function drawTemplate(list, fit) {
      c.fillStyle = '#fff'; c.strokeStyle = '#fff';
      for (const e of list) {
        const k = refLen[e.ref] * (e.fit && fit ? fit[e.fit] : 1);
        const once = () => {
          if (e.t === 'band' && e.ids) {
            const o = U(e.toward || 4);
            const outer = e.ids.map(U);
            const inner = e.ids.map((id, j) => {
              const base = e.insets ? e.insets[j] : e.inset;
              const fk = e.insetFit && e.insetFit[j];
              const w = fk && fit && fit[fk] != null ? fit[fk] : (e.fit && fit && fit[e.fit] ? fit[e.fit] : 1);
              return lerp(U(id), o, base * w);
            });
            c.globalAlpha = e.alpha;
            c.beginPath();
            outer.forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])));
            inner.slice().reverse().forEach((q) => c.lineTo(q[0], q[1]));
            c.closePath();
            c.fill();
          } else if (e.t === 'stroke' && e.inset) {
            // Points pulled toward a landmark inside the face: a stroke on the outline itself falls in the edge fade.
            const o = U(e.toward || 4);
            c.globalAlpha = e.alpha; c.lineWidth = e.w * k; c.lineCap = 'round'; c.lineJoin = 'round';
            c.beginPath(); e.ids.map((i) => lerp(U(i), o, e.inset)).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.stroke();
          } else if (e.t === 'stroke') polyStroke(e.ids, e.w * k, e.alpha);
          else {
            const a = U(e.c[0]), b = U(e.c[1]), ctr = lerp(a, b, e.c[2]), to = U(e.to);
            ellipse(ctr, to, e.a * k, e.b * refLen[e.ref], e.alpha);
          }
        };
        if (e.side) bothSides(once); else once();
      }
      c.globalAlpha = 1;
    }
    const highlight = layer(() => {
      c.fillStyle = '#fff'; c.strokeStyle = '#fff';
      bothSides(() => {
        // Cheekbone apex, long toward the temple; inner eye corner.
        const apex = lerp(U(111), U(143), 0.3);
        ellipse(apex, U(34), 0.55 * dist(U(117), U(34)), 0.16 * dist(U(117), U(34)), 1);
        const eyeW = dist(U(33), U(133));
        c.globalAlpha = 0.5; c.beginPath(); const ic = lerp(U(133), U(168), 0.25); c.arc(ic[0], ic[1], 0.12 * eyeW, 0, Math.PI * 2); c.fill();
      });
      // Nose bridge and above the Cupid's bow (on the midline).
      polyStroke([168, 6, 197, 195, 5], 0.9 * noseW, 0.7);
      // Forehead centre, and under the eyes (soft ellipse below the lower lid, along the eye axis).
      const fc = lerp(U(151), U(9), 0.3), fw = dist(U(33), U(133));
      ellipse(fc, [fc[0] + 1, fc[1]], 0.9 * fw, 0.5 * fw, 0.55);
      bothSides(() => {
        const o = U(33), inn = U(133), c0 = lerp(U(145), U(205), 0.35);
        ellipse(c0, [c0[0] + (o[0] - inn[0]), c0[1] + (o[1] - inn[1])], 0.5 * fw, 0.22 * fw, 0.65);
      });
      c.globalAlpha = 0.6; c.beginPath(); const cb = lerp(U(0), U(164), 0.55); c.arc(cb[0], cb[1], 0.35 * dist(U(0), U(164)), 0, Math.PI * 2); c.fill();
      c.globalAlpha = 1;
    }, TUNING.hlFeatherPx);
    const contour = layer(() => {
      c.strokeStyle = '#fff';
      bothSides(() => {
        const base = dist(U(123), U(147));
        // Hollow under the cheekbone, ear → toward the mouth, thinning out.
        polyStroke([93, 177], 1.0 * base, 0.9); polyStroke([177, 147], 0.8 * base, 0.8); polyStroke([147, 187], 0.5 * base, 0.55);
        // Jawline and forehead / temple edge (half of each stroke falls off the face, leaving an inner band).
        polyStroke([132, 58, 172, 136, 150, 149, 176], 0.7 * base, 0.8);
        polyStroke([127, 162, 21, 54, 103, 67, 109], 0.8 * base, 0.6);
        // Sides of the nose.
        polyStroke([193, 122, 196, 3], 0.5 * noseW, 0.5);
      });
      c.globalAlpha = 1;
    }, TUNING.contourFeatherPx);
    // 0 at the face outline, 1 a little inside: the mesh edge often sits on background or hair, and a
    // contour band painted there drew a pale outline around the face (LaPa 10-25).
    const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
      148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
    const faceFill = layer(() => { c.fillStyle = '#fff'; c.beginPath(); pts(FACE_OVAL).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.closePath(); c.fill(); }, TUNING.faceEdgeFadePx);
    // Foundation gets its own wider outline fade and an S-curve, so the product thins out instead of ending at a rim.
    // The top of the oval is not an edge for foundation: the forehead cap continues it, so those points are pushed up
    // (out of the atlas) and only the sides and jaw fade.
    const foundFill = layer(() => {
      c.fillStyle = '#fff'; c.beginPath();
      FACE_OVAL.forEach((idx, i) => {
        const q = U(idx), k = FOREHEAD_CAP.indexOf(idx), lift = k < 0 ? 0 : (CAP_W[k] > 0 ? 0.2 * S : 0);
        const y = q[1] + lift;
        i ? c.lineTo(q[0], y) : c.moveTo(q[0], y);
      });
      c.closePath(); c.fill();
    }, TUNING.foundEdgeFadePx);
    const eyesCut = layer(() => {
      c.fillStyle = '#fff';
      for (const eye of EYES) {
        c.beginPath();
        pts(eye.contour).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])));
        c.closePath(); c.fill();
      }
    }, 8);
    const browCut = layer(() => {
      c.fillStyle = '#fff';
      for (const ids of [BROWS.slice(0, 10), BROWS.slice(10)]) {
        c.beginPath();
        ids.map(U).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1])));
        c.closePath(); c.fill();
      }
    }, 8);
    // Second shadow color: a wedge at each eye's outer corner and a stroke along the lower lash line
    // (outer → inner, fading), both anchored on the eye's own landmarks.
    const shadowDark = layer(() => {
      for (const e of EYE_LINES) {
        const up = e.upper.map(U), low = e.lower.map(U);
        const outer = up[0], inner = up[up.length - 1], eyeW = dist(outer, inner);
        const c0 = lerp(outer, centroid(e.brow.map(U)), 0.12);
        const g = c.createRadialGradient(c0[0], c0[1], 0, c0[0], c0[1], 0.55 * eyeW);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(0.55, 'rgba(255,255,255,0.7)');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        c.fillStyle = g;
        c.beginPath(); c.arc(c0[0], c0[1], 0.55 * eyeW, 0, Math.PI * 2); c.fill();
        const tail = low.slice(0, 6), t0 = tail[0], t1 = tail[tail.length - 1];
        const lg = c.createLinearGradient(t0[0], t0[1], t1[0], t1[1]);
        lg.addColorStop(0, 'rgba(255,255,255,1)');
        lg.addColorStop(1, 'rgba(255,255,255,0)');
        c.strokeStyle = lg; c.lineWidth = 0.34 * eyeW; c.lineCap = 'round'; c.lineJoin = 'round';
        c.beginPath(); tail.forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.stroke();
      }
    }, TUNING.shadow2Feather);
    // Selectable highlighter areas (a look names the ones it wants): R forehead, G nose bridge, B under
    // the eyes, A chin. Mask 2's R keeps the default set for products that name none.
    const eyeWuv = dist(U(33), U(133));
    const areaForehead = layer(() => {
      c.fillStyle = '#fff';
      const fc = lerp(U(151), U(9), 0.3);
      ellipse(fc, [fc[0] + 1, fc[1]], 0.9 * eyeWuv, 0.5 * eyeWuv, 0.7);
    }, TUNING.hlFeatherPx);
    const areaNose = layer(() => { c.strokeStyle = '#fff'; polyStroke([168, 6, 197, 195, 5], 0.9 * noseW, 0.8); c.globalAlpha = 1; }, TUNING.hlFeatherPx);
    const areaUnder = layer(() => {
      c.fillStyle = '#fff';
      bothSides(() => {
        const o = U(33), inn = U(133), c0 = lerp(U(145), U(205), 0.35);
        ellipse(c0, [c0[0] + (o[0] - inn[0]), c0[1] + (o[1] - inn[1])], 0.5 * eyeWuv, 0.22 * eyeWuv, 0.8);
      });
    }, TUNING.hlFeatherPx);
    const areaChin = layer(() => {
      c.fillStyle = '#fff';
      const cc = lerp(U(152), U(17), 0.35);
      ellipse(cc, [cc[0] + 1, cc[1]], 0.5 * eyeWuv, 0.25 * eyeWuv, 0.7);
    }, TUNING.hlFeatherPx);
    const rgba3 = new Uint8Array(S * S * 4);
    const rgba2 = new Uint8Array(S * S * 4);
    for (let i = 0; i < S * S; i++) {
      const inside = clamp01((faceFill[i] - 0.5) * 2);
      rgba3[i * 4] = Math.round(clamp01(areaForehead[i] * inside) * 255);
      rgba3[i * 4 + 1] = Math.round(clamp01(areaNose[i] * inside) * 255);
      rgba3[i * 4 + 2] = Math.round(clamp01(areaUnder[i] * inside) * 255);
      rgba3[i * 4 + 3] = Math.round(clamp01(areaChin[i] * inside) * 255);
      rgba2[i * 4] = Math.round(clamp01(highlight[i] * inside) * 255);
      rgba2[i * 4 + 1] = Math.round(clamp01(contour[i] * inside) * 255);
      rgba2[i * 4 + 2] = Math.round(clamp01(shadowDark[i] * inside) * 255);
      const fe = clamp01((foundFill[i] - TUNING.foundEdgeLo) / (TUNING.foundEdgeHi - TUNING.foundEdgeLo));
      const foundInside = fe * fe * (3 - 2 * fe);
      rgba2[i * 4 + 3] = Math.round(clamp01(foundInside * (1 - lipShape[i]) * (1 - eyesCut[i]) * (1 - browCut[i])) * 255);
    }
    const rgba = new Uint8Array(S * S * 4);
    for (let i = 0; i < S * S; i++) {
      // R: only the inner and corner fades (over the whole band); the screen-space outline cuts the
      // outer edge, so the UV spline's per-triangle warp never shows (10-25).
      rgba[i * 4] = Math.round(clamp01(band[i] > 0.01 ? lipFade[i] : 0) * 255);
      rgba[i * 4 + 1] = Math.round(clamp01(blush[i]) * 255);
      rgba[i * 4 + 2] = Math.round(clamp01(shadow[i]) * 255);
      rgba[i * 4 + 3] = Math.round(clamp01(band[i] * corner[i]) * 255);
    }
    const at = (arr, i) => arr[clamp(Math.round(FACE_UV[2 * i + 1] * S), 0, S - 1) * S + clamp(Math.round(FACE_UV[2 * i] * S), 0, S - 1)];
    const lipVerts = [], skinVerts = [];
    const excluded = new Set(BROWS.concat(EYES[0].contour, EYES[1].contour));
    for (let i = 0; i < N_MESH; i++) {
      if (at(lip, i) > 0.6) lipVerts.push(i);
      else if (at(lip, i) < 0.01 && at(shadow, i) < 0.01 && !excluded.has(i)) skinVerts.push(i);
    }
    // Face-fit: redraw only the highlighter (R) and shading (G) channels of mask 2 for a style and measured fit.
    // A style that is absent keeps the default layer; the caller re-uploads rgba2.
    function repaintHlContour(hlStyle, contourStyle, fit) {
      const hlT = hlStyle && HL_TEMPLATES[hlStyle], coT = contourStyle && CONTOUR_TEMPLATES[contourStyle];
      const h = hlT ? layer(() => drawTemplate(hlT, fit), TUNING.hlFeatherPx) : highlight;
      const k = coT ? layer(() => drawTemplate(coT, fit), contourStyle === 'jawline' ? 10 : TUNING.contourFeatherPx) : contour;
      const jawEdge = contourStyle === 'jawline';
      for (let i = 0; i < S * S; i++) {
        const inside = clamp01((faceFill[i] - 0.5) * 2);
        rgba2[i * 4] = Math.round(clamp01(h[i] * inside) * 255);
        rgba2[i * 4 + 1] = Math.round(clamp01(k[i] * (jawEdge ? 1 : inside)) * 255);
      }
    }
    return { size: S, rgba, rgba2, rgba3, lipVerts, skinVerts, repaintHlContour };
  }

  // ── Mesh (positions, normals) ────────────────────────────────────────
  // Forehead cap: the face mesh ends at landmark 10, well below the hairline. A strip above the upper oval carries
  // foundation only (aUv = (t: 0 at the oval, 1 at the top; w: weight along the chain)); the skin mask stops it at the hair.
  const FOREHEAD_CAP = [127, 162, 21, 54, 103, 67, 109, 10, 338, 297, 332, 284, 251, 389, 356];
  const CAP_W = FOREHEAD_CAP.map((_, i, a) => (i === 0 || i === a.length - 1 ? 0 : i === 1 || i === a.length - 2 ? 0.6 : 1));
  const NC = FOREHEAD_CAP.length;
  const capPos = new Float32Array(NC * 2 * 3);
  const capNrm = new Float32Array(NC * 2 * 3);
  const capUv = new Float32Array(NC * 2 * 2);
  const capIdx = [];
  for (let i = 0; i < NC; i++) {
    capUv[i * 4] = 0; capUv[i * 4 + 1] = Math.min(1, CAP_W[i] / 0.5);
    capUv[i * 4 + 2] = 1; capUv[i * 4 + 3] = Math.min(1, CAP_W[i] / 0.5);
    if (i < NC - 1) { const a = 2 * i, b = a + 1, c = a + 2, d = a + 3; capIdx.push(a, c, b, b, c, d); }
  }
  // Jawline strip under the earlobe from 234/132 and 454/361, away from the cheek. Not toward 152 (neck).
  const JAW_HINGE = [{ v: 234, cheek: 50 }, { v: 132, cheek: 50 }, { v: 454, cheek: 280 }, { v: 361, cheek: 280 }];
  const NJ = JAW_HINGE.length;
  const jawPos = new Float32Array(NJ * 2 * 3);
  const jawNrm = new Float32Array(NJ * 2 * 3);
  const jawHingeOn = [0, 0];
  const jawReach = [0, 0];
  const jawCat = [-1, -1];
  const jawDir = [0, 0];
  const jawDy = [0, 0];
  const jawRise = [0, 0];
  const jawEndCat = [-1, -1];
  const jawUv = new Float32Array(NJ * 2 * 2);
  const jawIdx = [];
  for (let i = 0; i < NJ; i++) {
    jawUv[i * 4] = 0; jawUv[i * 4 + 1] = 1;
    jawUv[i * 4 + 2] = 0.9; jawUv[i * 4 + 3] = 1;
    if (i % 2 === 0) { const a = 2 * i, b = a + 1, c = a + 2, d = a + 3; jawIdx.push(a, c, b, b, c, d); }
  }
  const meshPos = new Float32Array(N_MESH * 3);
  const meshNrm = new Float32Array(N_MESH * 3);
  const scr = new Float32Array(N_MESH * 3);
  // Inner-lip gap (13–14) relative to mouth width (61–291), in landmark space.
  function mouthClosed() {
    const gap = Math.hypot(sx[13] - sx[14], sy[13] - sy[14]);
    const width = Math.hypot(sx[61] - sx[291], sy[61] - sy[291]);
    return width > 1e-4 && gap / width < TUNING.mouthClosedGap;
  }
  // ── Lip thickness: edge widths will follow this person's lips, never an average (6-5-3) ──
  // Outer/inner lip point pairs at the left, centre and right of each lip.
  const LIP_THICK_PAIRS = {
    up: [[37, 82], [0, 13], [267, 312]],
    low: [[84, 87], [17, 14], [314, 317]],
  };
  const lipThick = { up: 0, low: 0, upRatio: 0, lowRatio: 0, upBase: 0, lowBase: 0, uvScale: 0 };
  function meanPairLen(pairs, fx, fy, fz) {
    let s = 0;
    for (const [a, b] of pairs) s += Math.hypot((sx[a] - sx[b]) * fx, (sy[a] - sy[b]) * fy, (sz[a] - sz[b]) * fz);
    return s / pairs.length;
  }
  function uvPairLen(pairs) {
    let s = 0;
    for (const [a, b] of pairs) {
      s += Math.hypot(FACE_UV[2 * a] - FACE_UV[2 * b], FACE_UV[2 * a + 1] - FACE_UV[2 * b + 1]) * TUNING.maskSize;
    }
    return s / pairs.length;
  }
  const UV_LIP_THICK = uvPairLen(LIP_THICK_PAIRS.up) + uvPairLen(LIP_THICK_PAIRS.low);
  function measureLipThickness(W, H) {
    // Screen px (what the edge width is compared with), and that over the 3D mouth width: distance-free,
    // and head yaw does not change it (MediaPipe z is in the same scale as x). Thickness itself stays 2D:
    // the inner lip points sit deeper than the outer ones, so a 3D length hides how thin the lips are.
    lipThick.up = meanPairLen(LIP_THICK_PAIRS.up, W, H, 0);
    lipThick.low = meanPairLen(LIP_THICK_PAIRS.low, W, H, 0);
    const width3d = Math.max(1e-4, Math.hypot((sx[61] - sx[291]) * W, (sy[61] - sy[291]) * H, (sz[61] - sz[291]) * W));
    lipThick.upRatio = lipThick.up / width3d;
    lipThick.lowRatio = lipThick.low / width3d;
    // Screen px per UV-mask px at the lips: how wide the baked edge feather and band really are.
    lipThick.uvScale = (lipThick.up + lipThick.low) / Math.max(1e-4, UV_LIP_THICK);
    // Baseline: closed mouth, roughly frontal (both corners at a similar depth). Smiling or opening
    // stretches the lips thinner, so only this pose defines the person's own thickness. Memory only.
    const frontal = Math.abs(sz[61] - sz[291]) * W < 0.15 * width3d;
    if (mouthClosed() && frontal) {
      const k = lipThick.upBase ? 0.1 : 1;
      lipThick.upBase += k * (lipThick.upRatio - lipThick.upBase);
      lipThick.lowBase += k * (lipThick.lowRatio - lipThick.lowBase);
    }
  }
  // Where the real lip ends, from the camera: walk from each inner lip point out past its outer
  // partner and find the last red-enough sample. 1.0 = the landmark outer line is on the real edge,
  // < 1 = the landmarks sit outside the lip (paint spills onto skin). Corners skipped. Memory only.
  // 60 rays: each outer/inner landmark segment j → j+1 (wrapping) split at 0, 1/3, 2/3, so the edge
  // between the 20 model points comes from the camera, not from the average face's curve.
  const LIP_RAYS = LIPS_OUTER.length * 3;
  const lipEdge = { up: 1, low: 1, samples: 0, t: new Float32Array(LIP_RAYS).fill(1), conf: new Float32Array(LIP_RAYS) };
  function rayEnds(r) {
    const j = Math.floor(r / 3), f = (r % 3) / 3, j2 = (j + 1) % LIPS_OUTER.length;
    const o1 = LIPS_OUTER[j], o2 = LIPS_OUTER[j2], n1 = LIPS_INNER[j], n2 = LIPS_INNER[j2];
    return [sx[n1] + f * (sx[n2] - sx[n1]), sy[n1] + f * (sy[n2] - sy[n1]),
            sx[o1] + f * (sx[o2] - sx[o1]), sy[o1] + f * (sy[o2] - sy[o1])];
  }
  const edgeCrop = document.createElement('canvas');
  const edgeCropCtx = edgeCrop.getContext('2d', { willReadFrequently: true });
  function measureLipEdge(W, H) {
    if (light.lipRed - light.skinRed < TUNING.refineMinContrast) return;
    let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    for (const i of LIPS_OUTER) { x0 = Math.min(x0, sx[i]); x1 = Math.max(x1, sx[i]); y0 = Math.min(y0, sy[i]); y1 = Math.max(y1, sy[i]); }
    const padY = 0.6 * (y1 - y0), padX = (padY * H) / W;
    x0 = clamp(x0 - padX, 0, 1); x1 = clamp(x1 + padX, 0, 1); y0 = clamp(y0 - padY, 0, 1); y1 = clamp(y1 + padY, 0, 1);
    const srcW = (x1 - x0) * W, srcH = (y1 - y0) * H;
    if (srcW < 8 || srcH < 8) return;
    const cw = Math.min(256, Math.round(srcW)), ch = Math.max(1, Math.round((cw * srcH) / srcW));
    if (edgeCrop.width !== cw || edgeCrop.height !== ch) { edgeCrop.width = cw; edgeCrop.height = ch; }
    edgeCropCtx.drawImage(video, x0 * W, y0 * H, srcW, srcH, 0, 0, cw, ch);
    const d = edgeCropCtx.getImageData(0, 0, cw, ch).data;
    // Redness and, for reflections, brightness and saturation of a 3×3 neighbourhood (linear RGB).
    const sampleAt = (nx, ny) => {
      const cx = Math.floor(((nx - x0) / (x1 - x0)) * cw), cy = Math.floor(((ny - y0) / (y1 - y0)) * ch);
      let r = 0, g = 0, b = 0;
      for (let oy = -1; oy <= 1; oy++) for (let ox = -1; ox <= 1; ox++) {
        const k = (clamp(cy + oy, 0, ch - 1) * cw + clamp(cx + ox, 0, cw - 1)) * 4;
        r += toLin(d[k] / 255); g += toLin(d[k + 1] / 255); b += toLin(d[k + 2] / 255);
      }
      const hi = Math.max(r, g, b);
      return { red: (r - g) / (r + g + b + 1e-4), lum: lumOf(r, g, b) / 9, sat: (hi - Math.min(r, g, b)) / Math.max(hi, 1e-4) };
    };
    const mid = light.skinRed + 0.5 * (light.lipRed - light.skinRed);
    // A reflection on the lip is white, not red: inside the landmark lip, a bright desaturated sample
    // continues the lip instead of ending it (skin, even pale skin, stays more saturated than this).
    const isReflection = (s) => s.sat < TUNING.hlSat[0] && s.lum > TUNING.diffuseCap * light.lipMeanLum;
    // One ray per LIP_RAYS entry: t = 0 inner line, 1 landmark outer line. Start past the wet inner
    // lip, stop on a sustained drop below the lip/skin midpoint.
    const found = new Float32Array(LIP_RAYS);
    for (let r = 0; r < LIP_RAYS; r++) {
      const ray = rayEnds(r);
      const step = 1.45 / 40;
      let last = -1, lastV = 0, edge = -1;
      for (let s = 0; s <= 40; s++) {
        const t = 0.15 + s * step;
        const smp = sampleAt(ray[0] + t * (ray[2] - ray[0]), ray[1] + t * (ray[3] - ray[1]));
        const v = t <= 1 && isReflection(smp) ? Math.max(smp.red, mid) : smp.red;
        if (v >= mid) { last = t; lastV = v; edge = -1; }
        else if (last >= 0) {
          // Sub-step: where the redness crosses the midpoint between the last lip and first skin sample.
          if (edge < 0 && t - last < step * 1.5) edge = last + step * clamp((lastV - mid) / Math.max(1e-4, lastV - v), 0, 1);
          if (t - last > 0.12) break;
        }
      }
      found[r] = last > 0 ? (edge > 0 ? edge : last) : -1;
    }
    // Outliers: a ray far from the median of its 4 neighbours (glare, teeth, beard) is skipped this time.
    const first = lipEdge.samples++ === 0;
    const k = first ? 1 : TUNING.lightSmoothing;
    for (let r = 0; r < LIP_RAYS; r++) {
      const near = [-2, -1, 1, 2].map((d) => found[(r + d + LIP_RAYS) % LIP_RAYS]).filter((v) => v > 0).sort((p, q) => p - q);
      const med = near.length ? near[near.length >> 1] : -1;
      const ok = found[r] > 0 && (med < 0 || Math.abs(found[r] - med) < TUNING.lipRayOutlier);
      if (ok) lipEdge.t[r] = first || lipEdge.conf[r] === 0 ? found[r] : lipEdge.t[r] + k * (found[r] - lipEdge.t[r]);
      lipEdge.conf[r] += k * ((ok ? 1 : 0) - lipEdge.conf[r]);
    }
    // Summary per lip, corners excluded: upper = segments 1..8, lower = 11..18.
    const pick = (a, b) => trimmedMean(Array.from({ length: (b - a + 1) * 3 }, (_, i) => a * 3 + i)
      .filter((r) => lipEdge.conf[r] > 0.5).map((r) => lipEdge.t[r]));
    const up = pick(1, 8), low = pick(11, 18);
    if (up !== null) lipEdge.up = up;
    if (low !== null) lipEdge.low = low;
  }
  // Open mouth: where the lip really ends toward the mouth, per inner point. Walk from inside the lip (t < 0, toward its
  // outer partner) past the inner landmark into the mouth (t > 0) and keep the last lip-red, not-dark sample before two
  // non-lip ones in a row (teeth, the dark mouth; a lip reflection is shorter). t is a share of the lip thickness there:
  // negative = the landmark already lies on the teeth. Memory only.
  const lipInner = { t: new Float32Array(LIPS_INNER.length), conf: new Float32Array(LIPS_INNER.length), at: 0 };
  function measureLipInner(W, H, now) {
    if (mouthClosed()) { lipInner.conf.fill(0); return; }
    if (now - lipInner.at < TUNING.lipInnerEveryMs) return;
    lipInner.at = now;
    if (light.lipRed - light.skinRed < TUNING.refineMinContrast) return;
    let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    for (const i of LIPS_OUTER) { x0 = Math.min(x0, sx[i]); x1 = Math.max(x1, sx[i]); y0 = Math.min(y0, sy[i]); y1 = Math.max(y1, sy[i]); }
    x0 = clamp(x0, 0, 1); x1 = clamp(x1, 0, 1); y0 = clamp(y0, 0, 1); y1 = clamp(y1, 0, 1);
    const srcW = (x1 - x0) * W, srcH = (y1 - y0) * H;
    if (srcW < 8 || srcH < 8) return;
    const cw = Math.min(192, Math.round(srcW)), ch = Math.max(1, Math.round((cw * srcH) / srcW));
    if (edgeCrop.width !== cw || edgeCrop.height !== ch) { edgeCrop.width = cw; edgeCrop.height = ch; }
    edgeCropCtx.drawImage(video, x0 * W, y0 * H, srcW, srcH, 0, 0, cw, ch);
    const d = edgeCropCtx.getImageData(0, 0, cw, ch).data;
    const sampleAt = (nx, ny) => {
      const cx = clamp(Math.floor(((nx - x0) / (x1 - x0)) * cw), 0, cw - 1), cy = clamp(Math.floor(((ny - y0) / (y1 - y0)) * ch), 0, ch - 1);
      const k = (cy * cw + cx) * 4;
      const r = toLin(d[k] / 255), g = toLin(d[k + 1] / 255), b = toLin(d[k + 2] / 255);
      return { red: (r - g) / (r + g + b + 1e-4), lum: lumOf(r, g, b) };
    };
    const mid = light.skinRed + 0.5 * (light.lipRed - light.skinRed);
    const dark = TUNING.teethDark * light.lipMeanLum;
    const maxT = TUNING.innerInset[1], step = 0.025;
    for (let j = 0; j < LIPS_INNER.length; j++) {
      if (j % 10 === 0) continue;
      const n = LIPS_INNER[j], o = LIPS_OUTER[j];
      const dx = sx[n] - sx[o], dy = sy[n] - sy[o];
      let last = null, miss = 0;
      for (let t = -0.3; t <= maxT + 1e-6; t += step) {
        const s = sampleAt(sx[n] + t * dx, sy[n] + t * dy);
        if (s.red >= mid && s.lum > dark) { last = t; miss = 0; }
        else if (last !== null && ++miss >= 2) break;
      }
      const ok = last !== null;
      // Never a negative inset: that would pull the hole onto the teeth. Miss → the openness floor.
      const found = ok ? clamp(last, TUNING.innerInset[0], maxT) : TUNING.innerInset[0];
      const k = lipInner.conf[j] > 0 ? 0.5 : 1;
      if (ok) lipInner.t[j] = k === 1 ? found : lipInner.t[j] + k * (found - lipInner.t[j]);
      lipInner.conf[j] += 0.5 * ((ok ? 1 : 0) - lipInner.conf[j]);
    }
  }
  // Lip outline in screen space, redrawn every frame from the smoothed landmarks: a curve through the
  // outer points with sharp mouth corners, minus the inner curve when the mouth is open. Drawn on the
  // screen it never bends at mesh triangle edges (10-25 close-ups: kinks, beak corners). White on an
  // opaque black crop; the shader reads it in video coordinates (suv). Memory only.
  // (A2, the camera-measured outline, was removed: on 200 LaPa faces it matched the lip worse than the
  // landmarks, IoU 0.703 vs 0.736, and on device it grew onto warm, reddish skin.)
  const outlineCanvas = document.createElement('canvas');
  const outlineCtx = outlineCanvas.getContext('2d');
  // Lip form field: the form channel drawn small and blurred by a share of the lip thickness, so the
  // shader reads a smooth round (a few-tap ring left contour stripes inside the lips).
  const formCanvas = document.createElement('canvas');
  const formCtx = formCanvas.getContext('2d', { willReadFrequently: true });
  let formImg = null;
  const formStep = [0, 0];
  function drawLipForm(srcW, srcH) {
    const fw = Math.max(8, Math.min(TUNING.formFieldPx, Math.ceil(outlineCanvas.width / 3)));
    const fh = Math.max(4, Math.round((fw * outlineCanvas.height) / outlineCanvas.width));
    if (formCanvas.width !== fw || formCanvas.height !== fh) { formCanvas.width = fw; formCanvas.height = fh; formImg = null; }
    formCtx.drawImage(outlineCanvas, 0, 0, fw, fh);
    const d = formCtx.getImageData(0, 0, fw, fh).data;
    const g = new Float32Array(fw * fh);
    for (let i = 0; i < fw * fh; i++) g[i] = d[i * 4 + 1] / 255;
    const thickPx = 0.5 * (lipThick.up + lipThick.low) * (fw / srcW);
    const r = Math.max(1, Math.round((TUNING.formReach * thickPx) / 2));
    const h = boxBlurRect(g, fw, fh, r);
    if (!formImg) formImg = formCtx.createImageData(fw, fh);
    const o = formImg.data;
    for (let i = 0; i < fw * fh; i++) { const v = Math.round(clamp01(h[i]) * 255); o[i * 4] = v; o[i * 4 + 1] = v; o[i * 4 + 2] = v; o[i * 4 + 3] = 255; }
    formCtx.putImageData(formImg, 0, 0);
    // One field texel in video coordinates, and how far (texels) the field rises from 0 to 1.
    formStep[0] = srcW / fw; formStep[1] = 2 * r + 1;
  }
  const outlineRect = [0, 0, 1, 1];
  const innerRingPx = new Float32Array(40); // the drawn inner lip ring, video px (teeth test)
  // Ring positions that stay put while smoothing: mouth corners (both rings) and the Cupid's bow (outer).
  const OUTER_FIXED = [0, 4, 5, 6, 10];
  const INNER_FIXED = [0, 10];
  // inset: move each point this share of the way from its partner ring, away from it (inner ring →
  // into the mouth).
  function lipRing(ids, fixed, W, H, partner, inset) {
    let p = ids.map((i, j) => {
      const k = partner ? (Array.isArray(inset) ? inset[j] : inset) : 0, q = partner ? partner[j] : i;
      return [(sx[i] + k * (sx[i] - sx[q])) * W, (sy[i] + k * (sy[i] - sy[q])) * H];
    });
    const n = p.length, k = TUNING.lipOutlineSmooth;
    // Taubin λ|μ: removes landmark zigzag without shrinking the lip.
    for (const w of [k, -1.06 * k]) {
      p = p.map((q, i) => {
        if (fixed.includes(i)) return q;
        const a = p[(i - 1 + n) % n], b = p[(i + 1) % n];
        return [q[0] + w * ((a[0] + b[0]) / 2 - q[0]), q[1] + w * ((a[1] + b[1]) / 2 - q[1])];
      });
    }
    return p;
  }
  // Cubic curve through the ring; at corner points (index 0 and 10) the tangent is 0, so they stay sharp.
  function ringPath(c, p, map) {
    const n = p.length;
    const tan = (i) => {
      if (i % 10 === 0) return [0, 0];
      const a = p[(i - 1 + n) % n], b = p[(i + 1) % n];
      return [(b[0] - a[0]) / 6, (b[1] - a[1]) / 6];
    };
    const q0 = map(p[0]);
    c.moveTo(q0[0], q0[1]);
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n, ti = tan(i), tj = tan(j);
      const c1 = map([p[i][0] + ti[0], p[i][1] + ti[1]]), c2 = map([p[j][0] - tj[0], p[j][1] - tj[1]]), e = map(p[j]);
      c.bezierCurveTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1]);
    }
    c.closePath();
  }
  // Overlip (retro / semi gal look): the outer ring pushed outward from the lip centre by the overlip share of the
  // mouth width, smoothly to zero at the corners, with the Cupid's-bow peaks (landmarks 37, 267 and their
  // neighbours) drawn further up by the peak-overdraw share. Shrinks as the mouth opens so it never reaches the
  // teeth. The base ring stays in the outline's B channel: the band between the two is skin.
  function overlipRing(base, shape) {
    const over = shape && shape.overlip > 0 ? shape.overlip : 0;
    const peak = shape && shape.peakOverdraw > 0 ? shape.peakOverdraw : 0;
    if (!over && !peak) return base;
    const mouthW = dist(base[0], base[10]);
    const open = Math.hypot(sx[13] - sx[14], sy[13] - sy[14]) / Math.max(1e-4, Math.hypot(sx[61] - sx[291], sy[61] - sy[291]));
    const f = 1 - TUNING.overlipOpenReduce * clamp((open - 0.12) / 0.35, 0, 1);
    const ctr = centroid(base);
    const ul = dist(base[5], base[15]) || 1;
    const up = [(base[5][0] - base[15][0]) / ul, (base[5][1] - base[15][1]) / ul];
    return base.map((q, i) => {
      if (i === 0 || i === 10) return q;
      const dx = q[0] - ctr[0], dy = q[1] - ctr[1], len = Math.hypot(dx, dy) || 1;
      const off = over * mouthW * Math.sin((Math.PI * (i % 10)) / 10) * f;
      const pk = i === 4 || i === 6 ? 1 : i === 3 || i === 7 ? 0.5 : 0;
      return [q[0] + (dx / len) * off + up[0] * peak * mouthW * pk * f, q[1] + (dy / len) * off + up[1] * peak * mouthW * pk * f];
    });
  }
  function drawLipOutline(W, H, shape) {
    let base;
    if (TUNING.lipEdgePull) {
      const pull = LIPS_OUTER.map((_, j) => {
        const r = 3 * j, t = lipEdge.t[r];
        return j % 10 === 0 || lipEdge.conf[r] <= 0.5 || t >= 1 ? 0 : -Math.min(1 - t, TUNING.lipEdgePullMax);
      });
      base = lipRing(LIPS_OUTER, OUTER_FIXED, W, H, LIPS_INNER, pull);
    } else {
      base = lipRing(LIPS_OUTER, OUTER_FIXED, W, H);
    }
    const outer = overlipRing(base, shape);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const q of outer) { x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); }
    const pad = 0.08 * (x1 - x0) + 4;
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad;
    const srcW = x1 - x0, srcH = y1 - y0;
    if (srcW < 8 || srcH < 4) return false;
    const cw = Math.min(TUNING.lipOutlinePx, Math.ceil(srcW)), ch = Math.max(4, Math.ceil((cw * srcH) / srcW));
    if (outlineCanvas.width !== cw || outlineCanvas.height !== ch) { outlineCanvas.width = cw; outlineCanvas.height = ch; }
    const map = (q) => [((q[0] - x0) / srcW) * cw, ((q[1] - y0) / srcH) * ch];
    // R = where to paint, G = lip form (upper and lower lip as separate bodies).
    const c = outlineCtx;
    c.fillStyle = '#000';
    c.fillRect(0, 0, cw, ch);
    c.fillStyle = '#ff0';
    c.beginPath(); ringPath(c, outer, map); c.fill();
    c.globalCompositeOperation = 'lighter';
    c.fillStyle = '#00f';
    c.beginPath(); ringPath(c, base, map); c.fill();
    c.globalCompositeOperation = 'source-over';
    // The landmark inner line sits short of the wet inner lip on open mouths: 13% of the real lip
    // (LaPa, 1,132 open mouths) lay inside it, unpainted. Best shift by openness (gap / width):
    // < 0.2 → 0.15 (IoU 0.698 → 0.717), 0.2–0.5 → 0.15–0.2 (0.647 → 0.683), wider → 0.2 (n = 25).
    // Rendered on 200 phone-size faces, 0.15 on slightly open mouths painted teeth (IoU 0.624 → 0.615):
    // start small and grow with the opening.
    const open = Math.hypot(sx[13] - sx[14], sy[13] - sy[14]) / Math.max(1e-4, Math.hypot(sx[61] - sx[291], sy[61] - sy[291]));
    const s = clamp((open - 0.1) / 0.4, 0, 1);
    const inset = TUNING.innerInset[0] + (TUNING.innerInset[1] - TUNING.innerInset[0]) * s * s * (3 - 2 * s);
    const fixedInset = mouthClosed() ? 0 : inset;
    const inner = lipRing(LIPS_INNER, INNER_FIXED, W, H, LIPS_OUTER, TUNING.lipInnerMeasure && !mouthClosed()
      ? LIPS_INNER.map((_, j) => Math.max(fixedInset, lipInner.conf[j] >= 0.5 ? lipInner.t[j] : fixedInset)) : fixedInset);
    for (let i = 0; i < 20; i++) { innerRingPx[2 * i] = inner[i][0]; innerRingPx[2 * i + 1] = inner[i][1]; }
    if (!mouthClosed()) {
      // Open mouth: the inner curve is a hole (teeth, tongue) in both.
      c.fillStyle = '#000';
      c.beginPath(); ringPath(c, inner, map); c.fill();
    } else {
      // Closed: the thin gap is painted, but the form splits there so each lip keeps its own round.
      c.strokeStyle = '#f0f'; // B stays 1: the gap is lip, not the skin band of an overlip
      c.lineWidth = Math.max(1, TUNING.seamPx * 0.5 * (lipThick.up + lipThick.low) * (cw / srcW));
      c.lineJoin = 'round';
      c.beginPath(); ringPath(c, inner, map); c.stroke();
    }
    outlineRect[0] = x0 / W; outlineRect[1] = y0 / H; outlineRect[2] = srcW / W; outlineRect[3] = srcH / H;
    if (TUNING.lipForm) drawLipForm(srcW, srcH);
    // G is read only by drawLipForm above; after it, G becomes the band along the inner line where the shader may
    // take teeth and the dark mouth out of the paint (tested nowhere else: a lip reflection looks the same).
    if (TUNING.lipTeethGuard) {
      c.globalCompositeOperation = 'multiply';
      c.fillStyle = '#f0f';
      c.fillRect(0, 0, cw, ch);
      c.globalCompositeOperation = 'source-over';
    }
    if (TUNING.lipTeethGuard && !mouthClosed()) {
      const thick = 0.5 * (lipThick.up + lipThick.low);
      const land = lipRing(LIPS_INNER, INNER_FIXED, W, H);
      c.globalCompositeOperation = 'lighter';
      c.strokeStyle = '#0f0';
      c.lineJoin = 'round';
      c.lineWidth = Math.max(1, 2 * (TUNING.innerInset[1] * thick + TUNING.teethBandPx) * (cw / srcW));
      c.beginPath(); ringPath(c, land, map); c.stroke();
      c.globalCompositeOperation = 'source-over';
    }
    return true;
  }
  // ── Eyeliner and mascara: screen-space eye canvas (R = liner, G = mascara), redrawn each frame ──
  // Upper lid outer → inner corner, lower lid outer → inner, and the brow (which side is "up").
  const EYE_LINES = [
    { upper: [33, 246, 161, 160, 159, 158, 157, 173, 133], lower: [33, 7, 163, 144, 145, 153, 154, 155, 133], brow: [70, 63, 105, 66, 107], center: 159 },
    { upper: [263, 466, 388, 387, 386, 385, 384, 398, 362], lower: [263, 249, 390, 373, 374, 380, 381, 382, 362], brow: [300, 293, 334, 296, 336], center: 386 },
  ];
  // The mesh has holes for the eyes; these fans cover them so lashes can overhang the eye opening.
  const EYE_HOLE_TRIANGLES = [];
  for (const e of EYES) for (let j = 1; j < e.contour.length - 1; j++) EYE_HOLE_TRIANGLES.push(e.contour[0], e.contour[j], e.contour[j + 1]);
  const eyeCanvas = document.createElement('canvas');
  const eyeCtx = eyeCanvas.getContext('2d');
  const browCanvas = document.createElement('canvas');
  const browCtx = browCanvas.getContext('2d');
  const eyeRect = [0, 0, 1, 1];
  // Deterministic per-strand jitter: the same lash keeps its length and angle every frame.
  function seeded(i) { const x = Math.sin(i * 12.9898 + 4.1) * 43758.5453; return x - Math.floor(x); }
  // Brow reference points for the shader (normalized video coordinates): six bare-skin samples per brow
  // (three just below the lower line toward the lid, three above the upper line on the forehead), the head
  // and tail, and the mean brow height in pixels. Landmarks only; no camera read here.
  const browSkin = new Float32Array(24), browHead = new Float32Array(4), browTail = new Float32Array(4);
  function browGuides(W, H) {
    let height = 0;
    const P = (i) => [sx[i] * W, sy[i] * H];
    for (let k = 0; k < 2; k++) {
      const lower = EYES[k].brow.map(P), upper = EYE_LINES[k].brow.map(P);
      const head = lower[lower.length - 1], tail = lower[0];
      const ax = [tail[0] - head[0], tail[1] - head[1]];
      const al = Math.hypot(ax[0], ax[1]) || 1;
      let nU = [-ax[1] / al, ax[0] / al];
      const lowC = centroid(lower), upC = centroid(upper);
      if (nU[0] * (upC[0] - lowC[0]) + nU[1] * (upC[1] - lowC[1]) < 0) nU = [-nU[0], -nU[1]];
      const bH = Math.abs((upC[0] - lowC[0]) * nU[0] + (upC[1] - lowC[1]) * nU[1]) || al * 0.12;
      for (let j = 0; j < 3; j++) {
        const lo = lower[j + 1], up = upper[j + 1];
        const b = k * 12 + j * 2, a = k * 12 + 6 + j * 2;
        browSkin[b] = (lo[0] - nU[0] * 0.7 * bH) / W; browSkin[b + 1] = (lo[1] - nU[1] * 0.7 * bH) / H;
        browSkin[a] = (up[0] + nU[0] * 0.6 * bH) / W; browSkin[a + 1] = (up[1] + nU[1] * 0.6 * bH) / H;
      }
      browHead[k * 2] = head[0] / W; browHead[k * 2 + 1] = head[1] / H;
      browTail[k * 2] = tail[0] / W; browTail[k * 2 + 1] = tail[1] / H;
      height += bH / 2;
    }
    return { skin: browSkin, head: browHead, tail: browTail, height };
  }
  // ── Lid fit: find the lash line in the camera pixels of each eye (offsets from the lid points, eye widths) ──
  const lidCanvas = document.createElement('canvas');
  const lidCtx = lidCanvas.getContext('2d', { willReadFrequently: true });
  let lidLum = new Float32Array(128 * 128);
  function newLidSide() {
    return { x: new Float32Array(9), dx: new Float32Array(9), conf: new Float32Array(9), ready: false, active: false };
  }
  const lidFit = [{ up: newLidSide(), low: newLidSide(), t: 0 }, { up: newLidSide(), low: newLidSide(), t: 0 }];
  const lidHud = ['-', '-'];
  let lidFitMs = 0;
  function resetLidFit() { for (const f of lidFit) { f.up.ready = false; f.low.ready = false; f.t = 0; } }
  // Luminance (0..255) of the crop around one eye; the crop is read from the video frame once per eye per frame.
  function readEyeCrop(pts, eyeW, W, H) {
    const L = TUNING.lidFit;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const q of pts) { x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); }
    const pad = (L.span + L.tangent + 0.04) * eyeW;
    x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(W, x1 + pad); y1 = Math.min(H, y1 + pad);
    const sw = x1 - x0, sh = y1 - y0;
    if (sw < 8 || sh < 4) return null;
    const cw = Math.min(L.cropPx, Math.ceil(sw)), ch = Math.max(4, Math.ceil((cw * sh) / sw));
    if (lidCanvas.width !== cw || lidCanvas.height !== ch) { lidCanvas.width = cw; lidCanvas.height = ch; }
    lidCtx.drawImage(video, x0, y0, sw, sh, 0, 0, cw, ch);
    const data = lidCtx.getImageData(0, 0, cw, ch).data;
    if (lidLum.length < cw * ch) lidLum = new Float32Array(cw * ch);
    for (let i = 0, n = cw * ch; i < n; i++) lidLum[i] = 0.2126 * data[i * 4] + 0.7152 * data[i * 4 + 1] + 0.0722 * data[i * 4 + 2];
    return { cw, ch, x0, y0, k: cw / sw };
  }
  function cropLum(c, x, y) {
    const u = (x - c.x0) * c.k - 0.5, v = (y - c.y0) * c.k - 0.5;
    const i = Math.floor(u), j = Math.floor(v), fu = u - i, fv = v - j;
    const at = (a, b) => lidLum[clamp(b, 0, c.ch - 1) * c.cw + clamp(a, 0, c.cw - 1)];
    return (at(i, j) * (1 - fu) + at(i + 1, j) * fu) * (1 - fv) + (at(i, j + 1) * (1 - fu) + at(i + 1, j + 1) * fu) * fv;
  }
  // One side of one eye. For every lid point: read the brightness along the outward normal and take the strongest
  // edge inside [lo, hi]. Upper line (rise = true): dark to bright going up, the top of the dark iris / lash band where
  // the lid skin starts (measured on LaPa: at the eye centre the iris is dark right below the lid point). Lower line:
  // bright to dark going down, where the sclera ends. Weak edges get a low confidence. Offsets are blended with the
  // neighbours and a prior, then One Euro filtered. enabled = false eases back to the prior.
  function fitLidSide(side, pts, outDir, eyeW, crop, enabled, prior, lo, hi, trust, dt, rise) {
    const L = TUNING.lidFit, n = pts.length, M = L.samples;
    const raw = new Float32Array(n), conf = new Float32Array(n), prof = new Float32Array(M);
    if (enabled && crop) {
      for (let i = 1; i < n - 1; i++) {
        const a = pts[i - 1], b = pts[i + 1];
        let tx = b[0] - a[0], ty = b[1] - a[1];
        const tl = Math.hypot(tx, ty) || 1;
        tx /= tl; ty /= tl;
        let nx = -ty, ny = tx;
        if (nx * outDir[0] + ny * outDir[1] < 0) { nx = -nx; ny = -ny; }
        let mean = 0;
        for (let j = 0; j < M; j++) {
          const t = (j / (M - 1) * 2 - 1) * L.span * eyeW;
          let acc = 0;
          for (let q = -1; q <= 1; q++) {
            acc += cropLum(crop, pts[i][0] + nx * t + tx * q * L.tangent * eyeW, pts[i][1] + ny * t + ty * q * L.tangent * eyeW);
          }
          prof[j] = acc / 3;
          mean += prof[j] / M;
        }
        const half = 0.5 * L.span / (M - 1);
        let best = -1, bestDrop = 0;
        for (let j = 2; j < M - 2; j++) {
          const t = (j / (M - 1) * 2 - 1) * L.span;
          if (t < lo - half || t > hi + half) continue;
          const step = ((prof[j + 2] - prof[j - 2]) / 2) * (rise ? 1 : -1); // positive along the wanted edge
          if (step > bestDrop) { bestDrop = step; best = j; }
        }
        if (best >= 0) {
          raw[i] = clamp((best / (M - 1) * 2 - 1) * L.span, lo, hi);
          conf[i] = trust * clamp((bestDrop / Math.max(mean, 20) - L.minDrop) / (L.fullDrop - L.minDrop), 0, 1);
        }
      }
    }
    // Blend with the neighbours (1, 2, 1) and the prior; the corners (conf 0) lean on the neighbour and the prior.
    const target = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      let num = L.priorWeight * prior, den = L.priorWeight;
      for (let o = -1; o <= 1; o++) {
        const j = i + o;
        if (j < 0 || j >= n) continue;
        const w = (o === 0 ? 2 : 1) * conf[j];
        num += w * raw[j]; den += w;
      }
      target[i] = clamp(num / den, lo, hi);
    }
    const stale = !side.ready || dt > L.staleS;
    const dts = clamp(dt, 1 / 120, 0.25);
    for (let i = 0; i < n; i++) {
      side.conf[i] = conf[i];
      if (stale) { side.x[i] = target[i]; side.dx[i] = 0; continue; }
      const dxr = (target[i] - side.x[i]) / dts;
      side.dx[i] += euroAlpha(L.dCutoff, dts) * (dxr - side.dx[i]);
      side.x[i] += euroAlpha(L.minCutoff + L.beta * Math.abs(side.dx[i]), dts) * (target[i] - side.x[i]);
    }
    side.ready = true;
    side.active = enabled && !!crop;
    return side.x;
  }
  // Moves the 9 upper and 9 lower lid points to the camera's lash line. Returns new arrays; the landmarks stay put.
  function fitLidLine(ek, e, upRaw, lowRaw, eyeW, nUp, fade, W, H, now) {
    const L = TUNING.lidFit, f = lidFit[ek], t0 = performance.now();
    const gap = dist(lerp(upRaw[3], upRaw[5], 0.5), lerp(lowRaw[3], lowRaw[5], 0.5)) / eyeW;
    const facing = meshNrm[e.center * 3 + 2];
    const enabled = eyeW >= L.minEyePx && gap >= L.blinkGap && facing >= L.faceZ && fade > 0;
    const dt = f.t ? (now - f.t) / 1000 : 1;
    f.t = now;
    const crop = enabled ? readEyeCrop(upRaw.concat(lowRaw), eyeW, W, H) : null;
    const dUp = fitLidSide(f.up, upRaw, nUp, eyeW, crop, enabled, L.d0, L.lo, L.hi, 1, dt, true);
    const dLow = fitLidSide(f.low, lowRaw, [-nUp[0], -nUp[1]], eyeW, crop, enabled, L.lowD0, L.lowLo, L.lowHi, L.lowTrust, dt, false);
    const move = (pts, d, sign) => pts.map((q, i) => {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
      const tx = b[0] - a[0], ty = b[1] - a[1];
      const tl = Math.hypot(tx, ty) || 1;
      let nx = -ty / tl, ny = tx / tl;
      if (nx * nUp[0] + ny * nUp[1] < 0) { nx = -nx; ny = -ny; }
      return [q[0] + sign * nx * d[i] * eyeW, q[1] + sign * ny * d[i] * eyeW];
    });
    let mu = 0, mc = 0;
    for (let i = 0; i < 9; i++) { mu += dUp[i] / 9; mc += f.up.conf[i] / 9; }
    lidHud[ek] = (f.up.active ? 'read' : 'prior') + ' d ' + mu.toFixed(3) + ' conf ' + mc.toFixed(2);
    lidFitMs = 0.9 * lidFitMs + 0.1 * (performance.now() - t0);
    return { up: move(upRaw, dUp, 1), low: move(lowRaw, dLow, -1) };
  }
  // Lid sparkle, per frame: screen pixels per UV unit across the eyes (cells stay fixed to the face; only the grain
  // radius follows this) and how open the lids are (0 = closed). Both eyes share one value; they blink together.
  const lidSparkle = { pxPerUv: 0, open: 1 };
  function lidSparkleState(W, H) {
    const [g0, g1] = TUNING.lidOpenGap;
    const P = (i) => [sx[i] * W, sy[i] * H];
    const U = (i) => [FACE_UV[2 * i], FACE_UV[2 * i + 1]];
    let px = 0, n = 0, open = 1;
    for (const e of EYE_LINES) {
      const a = e.upper[0], b = e.upper[e.upper.length - 1];
      const w = dist(P(a), P(b)), wuv = dist(U(a), U(b));
      if (w < 4 || wuv < 1e-4) continue;
      px += w / wuv; n++;
      const gap = dist(lerp(P(e.upper[3]), P(e.upper[5]), 0.5), lerp(P(e.lower[3]), P(e.lower[5]), 0.5)) / w;
      open = Math.min(open, clamp01((gap - g0) / (g1 - g0)));
    }
    if (n) lidSparkle.pxPerUv = lidSparkle.pxPerUv ? 0.8 * lidSparkle.pxPerUv + 0.2 * px / n : px / n;
    lidSparkle.open = open;
    return lidSparkle;
  }
  // The UV is stretched on screen 2-5x near the lash line, in a different direction per triangle, so each vertex gets
  // the screen metric J^T J (px^2 per UV^2) of its UV -> pixel map, area-weighted over its triangles. A grain round in
  // it is round on screen, and its size sets the grain's pixel floor. Stored per grain cell (px^2 per cell^2, about
  // 1-100) so it fits a mediump varying.
  const lidMetric = new Float32Array(N_MESH * 3);
  const lidMetricW = new Float32Array(N_MESH);
  function fillLidMetric(W, H, cellsPerUv) {
    lidMetric.fill(0); lidMetricW.fill(0);
    for (let t = 0; t < FACE_TRIANGLES.length; t += 3) {
      const a = FACE_TRIANGLES[t], b = FACE_TRIANGLES[t + 1], c = FACE_TRIANGLES[t + 2];
      if (a >= N_MESH || b >= N_MESH || c >= N_MESH) continue;
      const u1x = FACE_UV[2 * b] - FACE_UV[2 * a], u1y = FACE_UV[2 * b + 1] - FACE_UV[2 * a + 1];
      const u2x = FACE_UV[2 * c] - FACE_UV[2 * a], u2y = FACE_UV[2 * c + 1] - FACE_UV[2 * a + 1];
      const det = u1x * u2y - u2x * u1y;
      if (Math.abs(det) < 1e-9) continue;
      const s1x = (sx[b] - sx[a]) * W, s1y = (sy[b] - sy[a]) * H, s2x = (sx[c] - sx[a]) * W, s2y = (sy[c] - sy[a]) * H;
      // J = [s1 s2] [u1 u2]^-1
      const i00 = u2y / det, i01 = -u2x / det, i10 = -u1y / det, i11 = u1x / det;
      const j00 = s1x * i00 + s2x * i10, j01 = s1x * i01 + s2x * i11;
      const j10 = s1y * i00 + s2y * i10, j11 = s1y * i01 + s2y * i11;
      const m0 = j00 * j00 + j10 * j10, m1 = j00 * j01 + j10 * j11, m2 = j01 * j01 + j11 * j11;
      const wt = Math.abs(det);
      for (const v of [a, b, c]) {
        lidMetric[3 * v] += wt * m0; lidMetric[3 * v + 1] += wt * m1; lidMetric[3 * v + 2] += wt * m2; lidMetricW[v] += wt;
      }
    }
    for (let v = 0; v < N_MESH; v++) {
      const wt = (lidMetricW[v] || 1) * cellsPerUv * cellsPerUv;
      lidMetric[3 * v] /= wt; lidMetric[3 * v + 1] /= wt; lidMetric[3 * v + 2] /= wt;
    }
    return lidMetric;
  }
  function drawEyes(W, H, liner, mascara, shadow, browPaint) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const e of EYE_LINES) for (const i of e.upper.concat(e.lower, e.brow)) {
      x0 = Math.min(x0, sx[i] * W); x1 = Math.max(x1, sx[i] * W); y0 = Math.min(y0, sy[i] * H); y1 = Math.max(y1, sy[i] * H);
    }
    for (const i of BROWS) {
      x0 = Math.min(x0, sx[i] * W); x1 = Math.max(x1, sx[i] * W); y0 = Math.min(y0, sy[i] * H); y1 = Math.max(y1, sy[i] * H);
    }
    const pad = 0.12 * (x1 - x0);
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad;
    const srcW = x1 - x0, srcH = y1 - y0;
    if (srcW < 16 || srcH < 8) return false;
    const cw = Math.min(TUNING.eyeCanvasPx, Math.ceil(srcW)), ch = Math.max(4, Math.ceil((cw * srcH) / srcW));
    if (eyeCanvas.width !== cw || eyeCanvas.height !== ch) { eyeCanvas.width = cw; eyeCanvas.height = ch; }
    if (browPaint && (browCanvas.width !== cw || browCanvas.height !== ch)) { browCanvas.width = cw; browCanvas.height = ch; }
    const k = cw / srcW;
    const map = (q) => [(q[0] - x0) * k, (q[1] - y0) * k];
    const pathOn = (ctx, pts) => { ctx.beginPath(); pts.map(map).forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]))); };
    const path = (pts) => pathOn(eyeCtx, pts);
    if (browPaint) {
      browCtx.globalCompositeOperation = 'source-over'; browCtx.globalAlpha = 1;
      browCtx.fillStyle = '#000'; browCtx.fillRect(0, 0, cw, ch);
      browCtx.globalCompositeOperation = 'lighter';
    }
    const c = eyeCtx;
    c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1;
    c.fillStyle = '#000'; c.fillRect(0, 0, cw, ch);
    c.globalCompositeOperation = 'lighter';
    const P = (i) => [sx[i] * W, sy[i] * H];
    const nowMs = performance.now();
    for (const e of EYE_LINES) {
      let up = e.upper.map(P);
      let low = e.lower.map(P);
      let outer = up[0], inner = up[up.length - 1];
      const eyeW = dist(outer, inner); // from the landmarks: the lash-line fit below never changes the eye's size
      if (eyeW < 4) continue;
      const axis = [(outer[0] - inner[0]) / eyeW, (outer[1] - inner[1]) / eyeW];
      // "Up" = perpendicular to the corner-to-corner axis, on the brow side (stable through a blink).
      const browCtr = centroid(e.brow.map(P)), mid = lerp(outer, inner, 0.5);
      let nUp = [-axis[1], axis[0]];
      if (nUp[0] * (browCtr[0] - mid[0]) + nUp[1] * (browCtr[1] - mid[1]) < 0) nUp = [-nUp[0], -nUp[1]];
      // The far eye of a turned head is foreshortened; fade both with the eye's facing.
      const fade = clamp((meshNrm[e.center * 3 + 2] - 0.15) / 0.35, 0, 1);
      if (fade <= 0) continue;
      if (liner) {
        const fit = fitLidLine(EYE_LINES.indexOf(e), e, up, low, eyeW, nUp, fade, W, H, nowMs);
        up = fit.up; low = fit.low;
        outer = up[0]; inner = up[up.length - 1];
      }
      c.globalAlpha = fade;
      if (liner) {
        const g = Object.assign({}, TUNING.liner, liner.geometry || {});
        if (g.linerStyle === 'puppy' && !(g.angle < 0)) g.angle = -8;
        if (g.linerStyle === 'tightline' && !(g.length < 0.12)) g.length = Math.min(g.length, 0.1);
        const thickOuter = g.thickness * eyeW;
        const innerShare = TUNING.linerInnerThin;
        const taper = 2;
        const floorPx = EYELINER_DARK.minPx / k; // video pixels that are one eye-canvas texel and a half
        const curve = openSpline(up, 6);
        const nC = curve.length;
        const top = [], bottom = [];
        for (let j = 0; j < nC; j++) {
          const t = 1 - j / (nC - 1); // 1 at the outer corner
          const th = Math.max(thickOuter * (innerShare + (1 - innerShare) * Math.pow(t, taper)), floorPx);
          const q = curve[j];
          bottom.push(q);
          top.push([q[0] + nUp[0] * th, q[1] + nUp[1] * th]);
        }
        const ang = (g.angle * Math.PI) / 180;
        const edgeP = [P(234), P(454)].reduce((a, b) => (dist(outer, a) < dist(outer, b) ? a : b));
        const len = Math.min(g.length * eyeW, 0.8 * dist(outer, edgeP));
        const wdir = [axis[0] * Math.cos(ang) + nUp[0] * Math.sin(ang), axis[1] * Math.cos(ang) + nUp[1] * Math.sin(ang)];
        const tip = len > 0.5 ? [outer[0] + wdir[0] * len, outer[1] + wdir[1] * len] : null;
        const ring = bottom.slice().reverse();
        if (tip) ring.push(tip);
        for (let j = 0; j < top.length; j++) ring.push(top[j]);
        c.fillStyle = '#f00';
        path(ring);
        c.closePath();
        c.fill();
        // Optional lower liner (linerLower): a band along the lower lid that grows from nothing at the inner
        // corner and pinches onto the shared outer corner; it fades out as the lids meet so it never stacks
        // on the upper line.
        if (g.linerLower) {
          const lidGap = dist(lerp(up[3], up[5], 0.5), lerp(low[3], low[5], 0.5)) / eyeW;
          const open = smooth01(0.06, 0.14, lidGap);
          if (open > 0.01) {
            const lcurve = openSpline(low, 6);
            const nL = lcurve.length;
            const base = clamp(g.linerLowerThickness == null ? TUNING.linerLowerThickness : g.linerLowerThickness, 0.002, 0.08) * eyeW;
            const ltop = [], lbot = [];
            for (let j = nL - 1; j >= 0; j--) { // inner → outer
              const t = 1 - j / (nL - 1);
              const th = Math.max(base * smooth01(0, 0.35, t) * (1 - smooth01(0.9, 1, t)), 0);
              const q = lcurve[j];
              ltop.push(q);
              lbot.push([q[0] - nUp[0] * th, q[1] - nUp[1] * th]);
            }
            ltop.push(outer); lbot.push(outer);
            c.globalAlpha = fade * open;
            path(ltop.concat(lbot.reverse()));
            c.closePath();
            c.fill();
            c.globalAlpha = fade;
          }
        }
      }
      if (browPaint) {
        // Landmarks stay put. Fill slides a fixed distance toward the lid. No per-frame camera read.
        // Drawn on a side canvas so G stays mascara and A carries the brow (looks can wear both).
        const lower0 = e.brow.map(P);
        const upper0 = EYES[EYE_LINES.indexOf(e)].brow.slice().reverse().map(P);
        const lowC = centroid(lower0), upC = centroid(upper0);
        const browH = Math.abs((upC[0] - lowC[0]) * nUp[0] + (upC[1] - lowC[1]) * nUp[1]) || eyeW * 0.08;
        const towardEye = (q, dist) => [q[0] - nUp[0] * dist, q[1] - nUp[1] * dist];
        const drop = EYEBROW_PRESET.dropTowardEye * browH;
        const upper = upper0.map((q) => towardEye(q, drop));
        const lower = lower0.map((q) => {
          const nq = towardEye(q, drop);
          const past = (nq[0] - q[0]) * (-nUp[0]) + (nq[1] - q[1]) * (-nUp[1]);
          return past > 0 ? q : nq;
        });
        const head = lower[lower.length - 1], tail = lower[0], arch = lower[Math.floor(lower.length / 2)];
        const h = map(head), t = map(tail);
        const vx = tail[0] - head[0], vy = tail[1] - head[1];
        const d2 = vx * vx + vy * vy || 1;
        const archT = clamp01(((arch[0] - head[0]) * vx + (arch[1] - head[1]) * vy) / d2);
        const gB = browCtx.createLinearGradient(h[0], h[1], t[0], t[1]);
        const gStop = (d) => 'rgb(0,' + Math.round(clamp01(d) * 255) + ',0)';
        gB.addColorStop(0, gStop(EYEBROW_PRESET.headDensity));
        gB.addColorStop(archT, gStop(EYEBROW_PRESET.archDensity));
        gB.addColorStop(1, gStop(EYEBROW_PRESET.tailDensity));
        browCtx.globalAlpha = fade;
        browCtx.fillStyle = gB;
        pathOn(browCtx, lower.concat(upper));
        browCtx.closePath();
        browCtx.fill();
      }
      const ip = shadow && shadow.geometry && shadow.geometry.innerPoint;
      if (ip) {
        // White pearl at the inner corner: nose side and a little below it, as round as the eye is wide.
        const ctr = map([inner[0] - axis[0] * 0.05 * eyeW - nUp[0] * 0.12 * eyeW, inner[1] - axis[1] * 0.05 * eyeW - nUp[1] * 0.12 * eyeW]);
        const rr = clamp(ip.radius, 0.05, 0.4) * eyeW * k;
        const g2 = c.createRadialGradient(ctr[0], ctr[1], 0, ctr[0], ctr[1], rr);
        g2.addColorStop(0, 'rgba(0,0,255,1)');
        g2.addColorStop(0.5, 'rgba(0,0,255,0.7)');
        g2.addColorStop(1, 'rgba(0,0,255,0)');
        c.fillStyle = g2;
        c.beginPath(); c.arc(ctr[0], ctr[1], rr, 0, Math.PI * 2); c.fill();
      }
      if (mascara) {
        const mg = Object.assign({ length: 1, thickness: 1 }, mascara.geometry || {});
        const lengthen = (0.75 + 0.5 * clamp01(mascara.intensity)) * clamp(mg.length, 0.5, 2.5);
        const nLash = clamp(Math.round(TUNING.lashCount * mg.thickness), 12, 72);
        c.strokeStyle = '#0f0'; c.lineCap = 'round'; c.lineJoin = 'round';
        // Open eye: lashes rise from the margin and curl up. Closed: they hang down over the lid.
        const gap = dist(lerp(up[3], up[5], 0.5), lerp(low[3], low[5], 0.5)) / eyeW;
        const openness = clamp((gap - 0.06) / 0.18, 0, 1);
        const lashUp = [nUp[0] * (2 * openness - 1), nUp[1] * (2 * openness - 1)];
        const lashUpLen = Math.hypot(lashUp[0], lashUp[1]) || 1;
        const lu = Math.abs(2 * openness - 1) < 0.2 ? [-nUp[0], -nUp[1]] : [lashUp[0] / lashUpLen, lashUp[1] / lashUpLen];
        // A strand: thick root half, thin tip (mascara coats the base). The mid control lifts in the
        // curl direction so the lash bends up when open (and down when closed). Tips stay mostly separate.
        const strand = (root, dir, curl, L, w, pull) => {
          const mid = [root[0] + dir[0] * 0.45 * L + curl[0] * 0.22 * L, root[1] + dir[1] * 0.45 * L + curl[1] * 0.22 * L];
          const end = [root[0] + dir[0] * L + curl[0] * 0.55 * L + pull[0], root[1] + dir[1] * L + curl[1] * 0.55 * L + pull[1]];
          const r = map(root), m = map(mid), e2 = map(end);
          const cc = map([mid[0] + curl[0] * 0.28 * L, mid[1] + curl[1] * 0.28 * L]);
          c.lineWidth = Math.max(0.8, w * k);
          c.beginPath(); c.moveTo(r[0], r[1]); c.lineTo(m[0], m[1]); c.stroke();
          c.lineWidth = Math.max(0.5, 0.45 * w * k);
          c.beginPath(); c.moveTo(m[0], m[1]); c.quadraticCurveTo(cc[0], cc[1], e2[0], e2[1]); c.stroke();
        };
        const along = (pts, u) => {
          const f = u * (pts.length - 1), j = Math.min(pts.length - 2, Math.floor(f));
          return lerp(pts[j], pts[j + 1], f - j);
        };
        // Upper lashes inner (u = 0) → outer corner (u = 1): uneven spacing, fanning outward,
        // longer toward the outer corner, tips only lightly gathered.
        const upIn = up.slice().reverse(), lowIn = low.slice().reverse();
        const nUpper = nLash;
        const tips = [];
        for (let i = 0; i < nUpper; i++) {
          const u = clamp(0.06 + (0.94 * (i + 0.6 * (seeded(i + 300) - 0.5))) / (nUpper - 1), 0.04, 1);
          const th = ((u - 0.35) * 50 * Math.PI) / 180 + (seeded(i) - 0.5) * 0.3;
          const dir = [lu[0] * Math.cos(th) + axis[0] * Math.sin(th), lu[1] * Math.cos(th) + axis[1] * Math.sin(th)];
          const L = eyeW * TUNING.lashLength * lengthen * (0.42 + 0.58 * Math.min(1, u)) * (0.85 + 0.3 * seeded(i + 100));
          tips.push({ root: along(upIn, u), dir, L });
        }
        for (let i = 0; i < nUpper; i++) {
          const g = Math.floor(i / 3) * 3, gEnd = Math.min(nUpper, g + 3);
          let cx = 0, cy = 0;
          for (let j = g; j < gEnd; j++) { cx += tips[j].root[0] + tips[j].dir[0] * tips[j].L; cy += tips[j].root[1] + tips[j].dir[1] * tips[j].L; }
          cx /= gEnd - g; cy /= gEnd - g;
          const t0 = tips[i], own = [t0.root[0] + t0.dir[0] * t0.L, t0.root[1] + t0.dir[1] * t0.L];
          const pull = [(cx - own[0]) * 0.18 * clamp01(mascara.intensity), (cy - own[1]) * 0.18 * clamp01(mascara.intensity)];
          strand(t0.root, t0.dir, lu, t0.L, eyeW * TUNING.lashWidth, pull);
        }
        // Lower lashes: few, short, faint, pointing down (only when the eye is open).
        c.globalAlpha = fade * 0.5 * openness;
        const nLow = mg.lower === false ? 0 : Math.round(nLash / 3);
        for (let i = 0; i < nLow && openness > 0; i++) {
          const u = 0.3 + (0.65 * (i + 0.5 * (seeded(i + 400) - 0.5))) / (nLow - 1);
          const th = ((u - 0.4) * 40 * Math.PI) / 180;
          const dir = [-nUp[0] * Math.cos(th) + axis[0] * Math.sin(th), -nUp[1] * Math.cos(th) + axis[1] * Math.sin(th)];
          const L = eyeW * TUNING.lashLength * TUNING.lowerLash * lengthen * (0.7 + 0.3 * seeded(i + 200));
          strand(along(lowIn, u), dir, [-nUp[0], -nUp[1]], L, 0.7 * eyeW * TUNING.lashWidth, [0, 0]);
        }
        // Lash line: the coated roots darken and thicken the upper lid margin (the most visible
        // mascara change at selfie distance).
        c.globalAlpha = fade;
        c.lineWidth = Math.max(1, 0.035 * eyeW * k);
        path(up.slice(0, -1)); c.stroke();
      }
    }
    c.globalAlpha = 1; c.globalCompositeOperation = 'source-over';
    if (browPaint) {
      const packed = c.getImageData(0, 0, cw, ch);
      const browPx = browCtx.getImageData(0, 0, cw, ch);
      for (let i = 3; i < packed.data.length; i += 4) packed.data[i] = browPx.data[i - 2];
      c.putImageData(packed, 0, 0);
    }
    eyeRect[0] = x0 / W; eyeRect[1] = y0 / H; eyeRect[2] = srcW / W; eyeRect[3] = srcH / H;
    return true;
  }
  // ── Blush from the face points: the cheek ellipse in the face's UV space (soft peach coral look) ──
  // Same cheek landmarks as the baked mask; placement moves the centre (apple = cheekbone, under_eye = toward the
  // lower lid, side = toward the ear), size scales the radii, the rotation follows the line from the inner to the
  // outer cheek point. Clipped to below the lower lid. The mesh carries it with the face, so it turns with the head.
  const UVP = (i) => [FACE_UV[2 * i], FACE_UV[2 * i + 1]];
  const LOWER_LID_MID = [145, 374];
  function blushShape(placement, size) {
    const faceW = dist(UVP(FACE_EDGES[0]), UVP(FACE_EDGES[1]));
    return CHEEKS.map((cheek, k) => {
      const inner = UVP(cheek.inner), outer = UVP(cheek.outer), lid = UVP(LOWER_LID_MID[k]);
      // Apple: under the pupil, half way from the lower lid to the lower cheek point and a little outward (the
      // baked default sits lower and outside the eye's column, on the side of the cheek).
      const low = UVP(cheek.low);
      let ctr = [lid[0] + (low[0] - lid[0]) * 0.5 + (outer[0] - inner[0]) * 0.15, lid[1] + (low[1] - lid[1]) * 0.5 + (outer[1] - inner[1]) * 0.15];
      if (placement === 'under_eye') ctr = lerp(ctr, lid, 0.5);
      else if (placement === 'side') ctr = lerp(ctr, outer, 0.45);
      const ang = Math.atan2(outer[1] - inner[1], outer[0] - inner[0]);
      return {
        e: [ctr[0], ctr[1], faceW * TUNING.blushSize[0] * TUNING.appleScale * size, faceW * TUNING.blushSize[1] * TUNING.appleScale * size],
        r: [Math.cos(ang), Math.sin(ang), lid[1]],
      };
    });
  }
  const mouthN = [0, 0, 1];
  function updateMesh(W, H) {
    for (let i = 0; i < N_MESH; i++) {
      // Clip space of the mirrored display; MediaPipe z: smaller = closer, so depth LESS keeps the near surface.
      meshPos[i * 3] = 1 - 2 * sx[i];
      meshPos[i * 3 + 1] = 1 - 2 * sy[i];
      meshPos[i * 3 + 2] = clamp(sz[i], -0.99, 0.99);
      // Shading frame: x right on the (mirrored) screen, y up, z toward the viewer, in pixels.
      scr[i * 3] = -sx[i] * W;
      scr[i * 3 + 1] = -sy[i] * H;
      scr[i * 3 + 2] = -sz[i] * W;
    }
    meshNrm.fill(0);
    for (let t = 0; t < FACE_TRIANGLES.length; t += 3) {
      const a = FACE_TRIANGLES[t] * 3, b = FACE_TRIANGLES[t + 1] * 3, c = FACE_TRIANGLES[t + 2] * 3;
      const ux = scr[b] - scr[a], uy = scr[b + 1] - scr[a + 1], uz = scr[b + 2] - scr[a + 2];
      const vx = scr[c] - scr[a], vy = scr[c + 1] - scr[a + 1], vz = scr[c + 2] - scr[a + 2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      for (const k of [a, b, c]) { meshNrm[k] += nx; meshNrm[k + 1] += ny; meshNrm[k + 2] += nz; }
    }
    let zSum = 0;
    for (let i = 0; i < N_MESH; i++) zSum += meshNrm[i * 3 + 2];
    const sign = zSum < 0 ? -1 : 1;
    for (let i = 0; i < N_MESH; i++) {
      const k = i * 3;
      const len = Math.hypot(meshNrm[k], meshNrm[k + 1], meshNrm[k + 2]) || 1;
      meshNrm[k] = (sign * meshNrm[k]) / len;
      meshNrm[k + 1] = (sign * meshNrm[k + 1]) / len;
      meshNrm[k + 2] = (sign * meshNrm[k + 2]) / len;
    }
    // Mouth orientation: mean normal of the lip rings (upper lip faces down, lower up; the mean is the mouth).
    let mx = 0, my = 0, mz = 0;
    for (const i of LIPS_OUTER.concat(LIPS_INNER)) { mx += meshNrm[i * 3]; my += meshNrm[i * 3 + 1]; mz += meshNrm[i * 3 + 2]; }
    const ml = Math.hypot(mx, my, mz) || 1;
    mouthN[0] = mx / ml; mouthN[1] = my / ml; mouthN[2] = mz / ml;
    // Forehead cap: each upper-oval point and one pushed up along the face's chin → forehead axis (pixels, so aspect is kept).
    let ux = (sx[10] - sx[152]) * W, uy = (sy[10] - sy[152]) * H;
    const ul = Math.hypot(ux, uy) || 1; ux /= ul; uy /= ul;
    const fh = Math.hypot((sx[10] - sx[9]) * W, (sy[10] - sy[9]) * H) * TUNING.foundCapLen;
    for (let i = 0; i < NC; i++) {
      const v = FOREHEAD_CAP[i], e = fh * CAP_W[i];
      const qx = sx[v] + (ux * e) / W, qy = sy[v] + (uy * e) / H;
      for (let r = 0; r < 2; r++) {
        const k = (2 * i + r) * 3;
        capPos[k] = 1 - 2 * (r ? qx : sx[v]);
        capPos[k + 1] = 1 - 2 * (r ? qy : sy[v]);
        capPos[k + 2] = clamp(sz[v], -0.99, 0.99);
        capNrm[k] = meshNrm[v * 3]; capNrm[k + 1] = meshNrm[v * 3 + 1]; capNrm[k + 2] = meshNrm[v * 3 + 2];
      }
    }
    jawHingeOn[0] = 0; jawHingeOn[1] = 0;
    jawReach[0] = 0; jawReach[1] = 0; jawCat[0] = -1; jawCat[1] = -1;
    jawDir[0] = 0; jawDir[1] = 0; jawDy[0] = 0; jawDy[1] = 0; jawRise[0] = 0; jawRise[1] = 0; jawEndCat[0] = -1; jawEndCat[1] = -1;
    for (let side = 0; side < 2; side++) {
      const ear = side ? 454 : 234, jaw = side ? 361 : 132, cheek = side ? 280 : 50;
      const span = Math.hypot(sx[ear] - sx[jaw], sy[ear] - sy[jaw]) || 1e-4;
      const dirs = [
        [sx[ear] - sx[jaw], 0],
        [sx[ear] - sx[jaw], Math.abs(sx[ear] - sx[jaw]) * 0.35],
      ];
      let bestT = 0, bestDir = 0, firstCat = -1;
      if (foundSkinReady && foundSkinCat && foundSkinW && foundSkinH) {
        for (let d = 0; d < dirs.length; d++) {
          const len = Math.hypot(dirs[d][0], dirs[d][1]) || 1;
          const ux = dirs[d][0] / len, uy = dirs[d][1] / len;
          let tHit = 0;
          for (let s = 1; s <= 8; s++) {
            const dist = span * 0.9 * (s / 8);
            const qx = sx[jaw] + ux * dist, qy = sy[jaw] + uy * dist;
            if (qy < sy[ear]) break;
            const px = clamp(Math.floor(qx * foundSkinW), 0, foundSkinW - 1);
            const py = clamp(Math.floor(qy * foundSkinH), 0, foundSkinH - 1);
            const cat = foundSkinCat[py * foundSkinW + px];
            if (s === 1 && d === 0) firstCat = cat;
            if (cat !== 3) break;
            tHit = dist / span;
          }
          if (tHit > bestT) { bestT = tHit; bestDir = d; }
        }
      }
      jawReach[side] = Math.round(bestT * 100) / 100;
      jawCat[side] = firstCat;
      jawDir[side] = bestDir;
      jawHingeOn[side] = bestT > 0.08 ? 1 : 0;
      const len = Math.hypot(dirs[bestDir][0], dirs[bestDir][1]) || 1;
      const ux = dirs[bestDir][0] / len, uy = dirs[bestDir][1] / len;
      const reach = bestT * span;
      const farX = sx[jaw] + ux * reach, farY = sy[jaw] + uy * reach;
      const inY = farY + (sy[cheek] - farY) * 0.42;
      jawDy[side] = Math.round((farY - sy[jaw]) * 1000) / 1000;
      jawRise[side] = Math.round((inY - farY) * 1000) / 1000;
      if (foundSkinReady && foundSkinCat && foundSkinW) {
        const px = clamp(Math.floor(farX * foundSkinW), 0, foundSkinW - 1);
        const py = clamp(Math.floor(farY * foundSkinH), 0, foundSkinH - 1);
        jawEndCat[side] = foundSkinCat[py * foundSkinW + px];
      }
      for (let i = side * 2; i < side * 2 + 2; i++) {
        const along = i === side * 2 ? reach : 0;
        const bx = sx[jaw] + ux * along, by = sy[jaw] + uy * along;
        const ix = bx + (sx[cheek] - bx) * 0.42, iy = by + (sy[cheek] - by) * 0.42;
        for (let r = 0; r < 2; r++) {
          const k = (2 * i + r) * 3;
          jawPos[k] = 1 - 2 * (r ? ix : bx);
          jawPos[k + 1] = 1 - 2 * (r ? iy : by);
          jawPos[k + 2] = clamp(sz[jaw], -0.99, 0.99);
          jawNrm[k] = meshNrm[jaw * 3]; jawNrm[k + 1] = meshNrm[jaw * 3 + 1]; jawNrm[k + 2] = meshNrm[jaw * 3 + 2];
        }
      }
    }
  }

  // ── Scene / light estimation every 0.5 s (AR_SPEC 6-6-1) ─────────────
  const grainCanvas = document.createElement('canvas');
  grainCanvas.width = 24; grainCanvas.height = 24;
  const grainCtx = grainCanvas.getContext('2d', { willReadFrequently: true });
  // Camera grain: std of the 3×3 high-pass of linear luminance on a cheek patch, relative to its mean.
  // Camera blur: how far that noise spreads, from the lag-1 correlation of the residual from a 5×5 mean
  // (≈ 0 for sharp per-pixel noise, about (w - 1) / w for noise smeared over w px by focus or compression).
  function measureCamera(W, H) {
    const cheek = meshNrm[50 * 3 + 2] >= meshNrm[280 * 3 + 2] ? 50 : 280;
    const N = 24;
    const x0 = clamp(Math.round(sx[cheek] * W) - N / 2, 0, W - N), y0 = clamp(Math.round(sy[cheek] * H) - N / 2, 0, H - N);
    grainCtx.drawImage(video, x0, y0, N, N, 0, 0, N, N);
    const d = grainCtx.getImageData(0, 0, N, N).data;
    const L = new Float32Array(N * N);
    for (let i = 0; i < N * N; i++) L[i] = lumOf(toLin(d[i * 4] / 255), toLin(d[i * 4 + 1] / 255), toLin(d[i * 4 + 2] / 255));
    let sum = 0, sq = 0, mean = 0, n = 0;
    for (let y = 1; y < N - 1; y++) {
      for (let x = 1; x < N - 1; x++) {
        let m = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) m += L[(y + dy) * N + x + dx];
        const hp = L[y * N + x] - m / 9;
        sum += hp; sq += hp * hp; mean += L[y * N + x]; n++;
      }
    }
    const sd = Math.sqrt(Math.max(0, sq / n - (sum / n) * (sum / n)));
    const R = new Float32Array(N * N);
    for (let y = 2; y < N - 2; y++) {
      for (let x = 2; x < N - 2; x++) {
        let m = 0;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) m += L[(y + dy) * N + x + dx];
        R[y * N + x] = L[y * N + x] - m / 25;
      }
    }
    let rr = 0, rl = 0;
    for (let y = 2; y < N - 3; y++) {
      for (let x = 2; x < N - 3; x++) {
        const r = R[y * N + x];
        rr += r * r;
        rl += r * (R[y * N + x + 1] + R[(y + 1) * N + x]) / 2;
      }
    }
    const rho = rr > 1e-12 ? clamp(rl / rr, 0, 0.95) : 0;
    return {
      grain: clamp(sd / Math.max(1e-3, mean / n), 0, TUNING.grainMax),
      blur: clamp(1 / (1 - rho), 1, TUNING.blurMax),
    };
  }
  const stats = document.createElement('canvas');
  const statsCtx = stats.getContext('2d', { willReadFrequently: true });
  const light = {
    color: [1, 1, 1], colorConf: 0, dir: [0, 0.3, 0.95], strength: 1, dirConf: 0, matchR2: -1,
    lipMeanLum: 0.12, skinMeanLum: TUNING.skinRefLum, bgFraction: 0, samples: 0,
    lipRed: 0.2, skinRed: 0.2, grain: 0, blur: 1, lipColor: [0.12, 0.06, 0.06], lipUpLow: 1,
    skinColor: [0.42, 0.28, 0.22], colorSamples: 0, colorDelta: 1,
    snapColor: false, refSkinLab: null, blownFrac: 0, fitR2: 0, fitRel: 0,
    sh: [1, 0, 0, 0, 0, 0, 0, 0, 0], shDirectional: 0.5, shCond: 0, shUsed: false, colorEdgeW: 0,
  };
  // What the shader is given. The estimates above change every 0.5 s (and snap on a big light change); applied as they are,
  // every layer covering the face (foundation most of all) stepped brighter or darker. The shown values glide instead.
  const shownLight = { color: [1, 1, 1], exposure: 1, skinMeanLum: TUNING.skinRefLum, dir: [0, 0.3, 0.95], strength: 1, conf: 0, sh: [1, 0, 0, 0, 0, 0, 0, 0, 0], t: 0 };
  function glideLight(now) {
    const w = clamp(light.colorConf, 0, 1);
    const target = [1 + w * (light.color[0] - 1), 1 + w * (light.color[1] - 1), 1 + w * (light.color[2] - 1)];
    const exposure = clamp(light.skinMeanLum / TUNING.skinRefLum, TUNING.exposureRange[0], TUNING.exposureRange[1]);
    const dt = shownLight.t ? (now - shownLight.t) / 1000 : Infinity;
    shownLight.t = now;
    const k = dt === Infinity ? 1 : 1 - Math.exp(-Math.max(0, dt) / TUNING.lightDisplaySec);
    for (let j = 0; j < 3; j++) shownLight.color[j] += k * (target[j] - shownLight.color[j]);
    shownLight.exposure += k * (exposure - shownLight.exposure);
    shownLight.skinMeanLum += k * (light.skinMeanLum - shownLight.skinMeanLum);
    if (TUNING.lightDirGlide) {
      const kd = dt === Infinity ? 1 : 1 - Math.exp(-Math.max(0, dt) / TUNING.lightDirSec);
      const d = [0, 1, 2].map((j) => shownLight.dir[j] + kd * (light.dir[j] - shownLight.dir[j]));
      const dl = Math.hypot(d[0], d[1], d[2]) || 1;
      shownLight.dir = d.map((v) => v / dl);
      shownLight.strength += kd * (light.strength - shownLight.strength);
      shownLight.conf += kd * (light.dirConf - shownLight.conf);
      shownLight.sh = shownLight.sh.map((v, i) => v + kd * (light.sh[i] - v));
    }
    return shownLight;
  }
  // Skin tone for the shade suggestion: numbers only (AR_SPEC 1-4). The mean bare-skin color with the estimated light
  // color divided out, in Lab. Camera exposure is not undone (it cannot be without a reference), so L is approximate.
  let lastSkinToneAt = 0;
  function postSkinTone(now, nSkin) {
    if (now - lastSkinToneAt < TUNING.skinToneEveryMs || light.samples < 3 || nSkin < 30) return;
    lastSkinToneAt = now;
    const w = clamp(light.colorConf, 0, 1);
    const lc = [0, 1, 2].map((j) => 1 + w * (light.color[j] - 1));
    const lab = linToLab([0, 1, 2].map((j) => clamp(light.skinColor[j] / lc[j], 0, 1)));
    post({ type: 'skin_tone', lab: lab.map((v) => Math.round(v * 10) / 10), conf: Math.round(w * 100) / 100 });
  }
  let lastLightHint = undefined;
  function postLightHint() {
    let hint = null;
    if (light.blownFrac >= TUNING.blownFaceFraction) hint = 'blown';
    else if (light.colorSamples >= 1 && light.colorConf < 0.5) hint = 'low';
    if (hint === lastLightHint) return;
    lastLightHint = hint;
    post({ type: 'light_hint', value: hint });
  }
  // ── Face-fit measurement (11-04): this person's ratios from the landmarks, frontal frames only, then frozen ──
  let faceFitAcc = null, faceFitState = null, faceFitSeenAt = 0, faceFitKey = 'default';
  function d3(a, b) { return Math.hypot(sx[a] - sx[b], sy[a] - sy[b], sz[a] - sz[b]); }
  function faceFitStep(now) {
    if (faceFitState && now - faceFitSeenAt > 2500) { faceFitState = null; faceFitAcc = null; } // someone else may be in front
    faceFitSeenAt = now;
    if (faceFitState) return;
    const side = d3(1, 234) / Math.max(1e-6, d3(1, 454));
    if (side < TUNING.faceFitYaw[0] || side > TUNING.faceFitYaw[1]) return;
    const width = d3(234, 454), jaw = d3(172, 397);
    if (width < 1e-4 || jaw < 1e-4) return;
    if (!faceFitAcc) faceFitAcc = { n: 0, cheekWide: 0, faceLong: 0 };
    faceFitAcc.n++;
    faceFitAcc.cheekWide += width / jaw;
    faceFitAcc.faceLong += d3(10, 152) / width;
    if (faceFitAcc.n < TUNING.faceFitFrames) return;
    const ratios = { cheekWide: faceFitAcc.cheekWide / faceFitAcc.n, faceLong: faceFitAcc.faceLong / faceFitAcc.n };
    const out = faceFitFrom(ratios);
    faceFitState = { ratios, fit: out.fit, rec: out.rec };
    post({ type: 'face_fit', ratios: { cheekWide: Math.round(ratios.cheekWide * 100) / 100, faceLong: Math.round(ratios.faceLong * 100) / 100 }, rec: out.rec });
  }
  let masks = null;
  let lastLightAt = 0;
  let lastJawBandAt = 0;
  let lightMs = 0;
  let lastSegmentAt = -1e9;
  let lastFoundSegAt = -1e9;
  let segmentBusy = false;
  let foundSkinReady = false;
  let foundSkinW = 0;
  let foundSkinH = 0;
  let foundSkinBin = null;
  let foundSkinCat = null;
  let foundSkinPrev = null;
  let foundSkinRgba = null;
  const foundSkinStat = { cat: 0, prob: -1 }; // HUD: face-skin share of the frame (category / probability mask, -1 = not used)

  function trimmedMean(values) {
    if (!values.length) return null;
    values.sort((p, q) => p - q);
    const lo = Math.floor(values.length * 0.25), hi = Math.max(lo + 1, Math.ceil(values.length * 0.75));
    let s = 0;
    for (let i = lo; i < hi; i++) s += values[i];
    return s / (hi - lo);
  }
  function solve4(A, b) {
    const M = A.map((row, i) => row.concat([b[i]]));
    for (let col = 0; col < 4; col++) {
      let piv = col;
      for (let r = col + 1; r < 4; r++) if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
      if (Math.abs(M[piv][col]) < 1e-9) return null;
      const tmp = M[col]; M[col] = M[piv]; M[piv] = tmp;
      for (let r = 0; r < 4; r++) {
        if (r === col) continue;
        const f = M[r][col] / M[col][col];
        for (let k = col; k < 5; k++) M[r][k] -= f * M[col][k];
      }
    }
    return M.map((row, i) => row[4] / row[i]);
  }
  function fitLight(samples, weights) {
    const A = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]], b = [0,0,0,0];
    for (let n = 0; n < samples.length; n++) {
      const s = samples[n];
      const f = weights ? [weights[n], weights[n] * s[0], weights[n] * s[1], weights[n] * s[2]] : [1, s[0], s[1], s[2]];
      const g = [1, s[0], s[1], s[2]];
      for (let i = 0; i < 4; i++) { b[i] += f[i] * s[3]; for (let j = 0; j < 4; j++) A[i][j] += f[i] * g[j]; }
    }
    return solve4(A, b);
  }
  // Huber IRLS (TUNING.lightRobust): residual scale 1.4826 · median |r|, weight 1 inside c · scale, c · scale / |r| outside.
  function fitLightRobust(samples) {
    let fit = fitLight(samples);
    if (!fit) return null;
    let weights = samples.map(() => 1);
    for (let it = 0; it < TUNING.lightIrlsIters; it++) {
      const abs = samples.map((s) => Math.abs(s[3] - (fit[0] + fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2])));
      const scale = 1.4826 * abs.slice().sort((p, q) => p - q)[Math.floor(abs.length / 2)];
      if (!(scale > 1e-9)) break;
      const c = TUNING.lightHuberC * scale;
      weights = abs.map((v) => (v <= c ? 1 : c / v));
      fit = fitLight(samples, weights) || fit;
    }
    return { fit, weights };
  }
  // Real SH basis up to l = 2 at a unit normal (x, y, z). The shader's shE() uses the same constants.
  const shBasis = (x, y, z) => [0.282095, 0.488603 * y, 0.488603 * z, 0.488603 * x, 1.092548 * x * y, 1.092548 * y * z,
    0.315392 * (3 * z * z - 1), 1.092548 * x * z, 0.546274 * (x * x - y * y)];
  // Eigenvalues of a symmetric matrix (cyclic Jacobi), for the condition number of the normal equations.
  function symEigen(A) {
    const n = A.length, M = A.map((r) => r.slice());
    for (let sweep = 0; sweep < 12; sweep++) {
      let off = 0;
      for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) off += M[p][q] * M[p][q];
      if (off < 1e-20) break;
      for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) {
        if (Math.abs(M[p][q]) < 1e-15) continue;
        const th = (M[q][q] - M[p][p]) / (2 * M[p][q]);
        const t = (th >= 0 ? 1 : -1) / (Math.abs(th) + Math.sqrt(th * th + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < n; k++) { const kp = M[k][p], kq = M[k][q]; M[k][p] = c * kp - s * kq; M[k][q] = s * kp + c * kq; }
        for (let k = 0; k < n; k++) { const pk = M[p][k], qk = M[q][k]; M[p][k] = c * pk - s * qk; M[q][k] = s * pk + c * qk; }
      }
    }
    return M.map((r, i) => r[i]);
  }
  // 'sh9' fit: brightness ≈ a + max(b·n, 0), Lambert under one light plus ambient. Samples facing away from the light take
  // the ambient only; the lit set is refound from the new b each round, with the Huber weights of fitLightRobust. A free
  // 9-term SH fit is ill-posed here: a selfie shows only the front of the face, so the l = 2 terms trade off against l = 0/1
  // (the direction drifts under frontal light and the lip volume gets too dark). The SH9 the shader uses is this model's
  // projection. Null when there are too few samples or the lit-set normal equations are ill-conditioned: keep the linear fit.
  function fitLightLambert(samples) {
    if (samples.length < TUNING.lightShMinSamples) return null;
    const rob = fitLightRobust(samples);
    if (!rob) return null;
    let fit = rob.fit, weights = rob.weights, cond = 0;
    const predict = (f) => samples.map((s) => f[0] + Math.max(f[1] * s[0] + f[2] * s[1] + f[3] * s[2], 0));
    for (let it = 0; it < TUNING.lightShIters; it++) {
      const A = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]], b = [0,0,0,0];
      for (let n = 0; n < samples.length; n++) {
        const s = samples[n];
        const lit = fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2] > 0 ? 1 : 0;
        const g = [1, lit * s[0], lit * s[1], lit * s[2]];
        for (let i = 0; i < 4; i++) { b[i] += weights[n] * g[i] * s[3]; for (let j = 0; j < 4; j++) A[i][j] += weights[n] * g[i] * g[j]; }
      }
      const ev = symEigen(A).map(Math.abs);
      cond = Math.max(...ev) / Math.max(Math.min(...ev), 1e-12);
      if (!(cond <= TUNING.lightShMaxCond)) return null;
      const next = solve4(A, b);
      if (!next) return null;
      fit = next;
      const abs = predict(fit).map((p, n) => Math.abs(samples[n][3] - p));
      const scale = 1.4826 * abs.slice().sort((p, q) => p - q)[Math.floor(abs.length / 2)];
      if (scale > 1e-9) {
        const lim = TUNING.lightHuberC * scale;
        weights = abs.map((v) => (v <= lim ? 1 : lim / v));
      }
    }
    return { fit, weights, cond, pred: predict(fit) };
  }
  const SH_LAMBERT = [Math.PI, 2 * Math.PI / 3, 2 * Math.PI / 3, 2 * Math.PI / 3, Math.PI / 4, Math.PI / 4, Math.PI / 4, Math.PI / 4, Math.PI / 4];
  // SH9 irradiance coefficients of a + max(b·n, 0): a on Y0, the clamped cosine toward b as Â_l·Yᵢ(b̂)·|b| (Ramamoorthi &
  // Hanrahan 2001; Â_l = π, 2π/3, π/4).
  function lambertToSH(fit) {
    const bm = Math.hypot(fit[1], fit[2], fit[3]);
    const y = bm > 1e-9 ? shBasis(fit[1] / bm, fit[2] / bm, fit[3] / bm) : shBasis(0, 0, 1);
    const c = y.map((v, i) => bm * SH_LAMBERT[i] * v);
    c[0] += fit[0] / 0.282095;
    return c;
  }
  // Light by matching (after Perfect Corp US 11,030,798, studied for research): shade this face under a fixed set of
  // candidate lights, cast shadows of the nose, brows and lips included, and keep the candidates whose shading best
  // matches the camera. The straight-line fit above cannot see cast or attached shadows and pulls side light frontal.
  function lightGrid(azs, els) {
    const out = [];
    for (const el of els) {
      for (const az of azs) {
        const e = (el * Math.PI) / 180, a = (az * Math.PI) / 180;
        const d = [Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e)];
        if (d[2] >= 0.2) out.push(d);
      }
    }
    return out;
  }
  const LIGHT_CANDIDATES = lightGrid([-70, -45, -20, 0, 20, 45, 70], [-45, -20, 0, 20, 45, 65]);
  const LIGHT_REFINE = [-12, -8, -4, 0, 4, 8, 12]; // degrees around the coarse winner
  // Highest surface z (toward the viewer) per cell of an x/y grid over the face, from the triangles.
  function faceHeightGrid(pos, tris, res) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, zMax = -Infinity;
    for (let t = 0; t < tris.length; t++) {
      const v = tris[t] * 3;
      x0 = Math.min(x0, pos[v]); x1 = Math.max(x1, pos[v]);
      y0 = Math.min(y0, pos[v + 1]); y1 = Math.max(y1, pos[v + 1]);
      zMax = Math.max(zMax, pos[v + 2]);
    }
    const cell = Math.max(x1 - x0, y1 - y0, 1e-6) / res;
    const nx = Math.floor((x1 - x0) / cell) + 1, ny = Math.floor((y1 - y0) / cell) + 1;
    const h = new Float32Array(nx * ny).fill(-Infinity);
    for (let t = 0; t < tris.length; t += 3) {
      const a = tris[t] * 3, b = tris[t + 1] * 3, c = tris[t + 2] * 3;
      const ax = (pos[a] - x0) / cell, ay = (pos[a + 1] - y0) / cell;
      const bx = (pos[b] - x0) / cell, by = (pos[b + 1] - y0) / cell;
      const cx = (pos[c] - x0) / cell, cy = (pos[c + 1] - y0) / cell;
      const den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
      if (Math.abs(den) < 1e-9) continue;
      const i0 = Math.max(0, Math.ceil(Math.min(ax, bx, cx))), i1 = Math.min(nx - 1, Math.floor(Math.max(ax, bx, cx)));
      const j0 = Math.max(0, Math.ceil(Math.min(ay, by, cy))), j1 = Math.min(ny - 1, Math.floor(Math.max(ay, by, cy)));
      for (let j = j0; j <= j1; j++) {
        for (let i = i0; i <= i1; i++) {
          const w0 = ((by - cy) * (i - cx) + (cx - bx) * (j - cy)) / den;
          const w1 = ((cy - ay) * (i - cx) + (ax - cx) * (j - cy)) / den;
          const w2 = 1 - w0 - w1;
          if (w0 < -1e-4 || w1 < -1e-4 || w2 < -1e-4) continue;
          const z = w0 * pos[a + 2] + w1 * pos[b + 2] + w2 * pos[c + 2];
          if (z > h[j * nx + i]) h[j * nx + i] = z;
        }
      }
    }
    return { h, x0, y0, cell, nx, ny, zMax };
  }
  const HORIZON_BINS = 24;
  // Per vertex and side (azimuth bin), the steepest rise (Δz / x-y distance) of the face toward that side. Light d
  // reaches the vertex when its own rise d.z / |d.xy| is above it, so one march per side serves every candidate.
  function horizonSlopes(grid, pos, verts) {
    const out = new Float32Array(verts.length * HORIZON_BINS);
    const reach = Math.hypot(grid.nx, grid.ny) * grid.cell;
    for (let k = 0; k < verts.length; k++) {
      const v = verts[k] * 3, px = pos[v], py = pos[v + 1], pz = pos[v + 2] + grid.cell;
      for (let b = 0; b < HORIZON_BINS; b++) {
        const ang = (2 * Math.PI * b) / HORIZON_BINS, ux = Math.cos(ang), uy = Math.sin(ang);
        let top = -Infinity;
        for (let s = 2 * grid.cell; s < reach; s += grid.cell) {
          if ((grid.zMax - pz) / s <= top) break;
          const i = Math.round((px + ux * s - grid.x0) / grid.cell), j = Math.round((py + uy * s - grid.y0) / grid.cell);
          if (i < 0 || j < 0 || i >= grid.nx || j >= grid.ny) break;
          const slope = (grid.h[j * grid.nx + i] - pz) / s;
          if (slope > top) top = slope;
        }
        out[k * HORIZON_BINS + b] = top;
      }
    }
    return out;
  }
  // Coarse candidates, then a finer grid around the winner (the coarse step alone leaves ~8° error).
  // At most maxVerts evenly spaced vertices: the cost is per vertex and 0.5 s light updates must stay a few ms.
  function matchLight(grid, pos, nrm, verts, lums, spread, maxVerts) {
    const stride = Math.max(1, Math.ceil(verts.length / (maxVerts || verts.length)));
    const vs = verts.filter((_, k) => k % stride === 0), ls = lums.filter((_, k) => k % stride === 0);
    const hor = horizonSlopes(grid, pos, vs);
    const coarse = scoreLights(pos, nrm, vs, ls, hor, spread, LIGHT_CANDIDATES);
    if (!coarse) return null;
    const az = (Math.atan2(coarse.dir[0], coarse.dir[2]) * 180) / Math.PI;
    const el = (Math.asin(Math.max(-1, Math.min(1, coarse.dir[1]))) * 180) / Math.PI;
    const fine = lightGrid(LIGHT_REFINE.map((v) => az + v), LIGHT_REFINE.map((v) => el + v));
    return scoreLights(pos, nrm, vs, ls, hor, spread, fine) || coarse;
  }
  // brightness ≈ a + b · shading(candidate) per vertex; returns the blended best direction, its R² and peak a + b.
  function scoreLights(pos, nrm, verts, lums, hor, spread, candidates) {
    const n = verts.length;
    const shades = candidates.map((d) => {
      const s = new Float32Array(n);
      const r = Math.hypot(d[0], d[1]), rise = r < 1e-3 ? Infinity : d[2] / r;
      const bin = ((Math.round((Math.atan2(d[1], d[0]) / (2 * Math.PI)) * HORIZON_BINS) % HORIZON_BINS) + HORIZON_BINS) % HORIZON_BINS;
      for (let k = 0; k < n; k++) {
        const v = verts[k] * 3;
        const ndl = nrm[v] * d[0] + nrm[v + 1] * d[1] + nrm[v + 2] * d[2];
        s[k] = ndl > 0 && rise > hor[k * HORIZON_BINS + bin] ? ndl : 0;
      }
      return s;
    });
    const fitOn = (s, keep) => {
      let m = 0, sumX = 0, sumY = 0, sumXX = 0, sumXY = 0, sumYY = 0;
      for (const k of keep) { const x = s[k], y = lums[k]; m++; sumX += x; sumY += y; sumXX += x * x; sumXY += x * y; sumYY += y * y; }
      const vx = sumXX - (sumX * sumX) / m, vy = sumYY - (sumY * sumY) / m, cxy = sumXY - (sumX * sumY) / m;
      if (m < 3 || vx < 1e-9 || vy < 1e-12 || cxy <= 0) return null;
      const b = cxy / vx;
      return { a: (sumY - b * sumX) / m, b, r2: (cxy * cxy) / (vx * vy) };
    };
    const rank = (keep) => {
      let best = -1, fits = shades.map((s) => fitOn(s, keep));
      fits.forEach((f, c) => { if (f && (best < 0 || f.r2 > fits[best].r2)) best = c; });
      return { fits, best };
    };
    const all = [];
    for (let k = 0; k < n; k++) all.push(k);
    let { fits, best } = rank(all);
    if (best < 0) return null;
    // Drop the worst 20% (specular spots, hair, glasses) under the first winner, then rank again.
    const f0 = fits[best], s0 = shades[best];
    const resid = all.map((k) => Math.abs(lums[k] - (f0.a + f0.b * s0[k])));
    const cut = resid.slice().sort((p, q) => p - q)[Math.floor(n * 0.8)];
    ({ fits, best } = rank(all.filter((k) => resid[k] <= cut)));
    if (best < 0) return null;
    const top = fits[best];
    const dir = [0, 0, 0];
    fits.forEach((f, c) => {
      if (!f || f.r2 < top.r2 - 3 * spread) return;
      const w = Math.exp((f.r2 - top.r2) / spread);
      for (let j = 0; j < 3; j++) dir[j] += w * candidates[c][j];
    });
    const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
    return { dir: dir.map((v) => v / len), r2: top.r2, peak: top.a + top.b };
  }
  function ensureFoundSkinBuffers(w, h) {
    if (foundSkinW === w && foundSkinH === h && foundSkinBin && foundSkinCat) return;
    foundSkinW = w;
    foundSkinH = h;
    const n = w * h;
    foundSkinBin = new Uint8Array(n);
    foundSkinCat = new Uint8Array(n);
    foundSkinPrev = new Float32Array(n);
    foundSkinRgba = new Uint8Array(n * 4);
    foundSkinReady = false;
  }
  // Cheek and chin landmarks inside the lower face (none on the lips or eyes): the mask is checked there for a hand or hair
  // covering the face, which turns the lower-face floor (TUNING.foundLowerFloor) off.
  const FOUND_COVER_PTS = [1, 2, 98, 327, 129, 358, 203, 423, 205, 425, 50, 280, 101, 330, 118, 347, 117, 346, 187, 411, 207, 427, 147, 376, 213, 433, 200, 199, 175, 396];
  const OCC_LIP_PTS = LIPS_OUTER;
  const OCC_EYE_PTS = EYES[0].contour.concat(EYES[1].contour);
  const OCC_CHEEK_PTS = [50, 280, 116, 345, 205, 425, 123, 352, 147, 376, 187, 411];
  let foundOcc = 0;
  const occGate = { lip: 1, eye: 1, cheek: 1 };
  let foundSegMs = 0;   // moving mean of one segmentation call, ms (HUD)
  // Selfie multiclass: 0 bg, 1 hair, 2 body, 3 face skin, 4 clothes, 5 accessory.
  function applyFoundSkinMask(mask, conf) {
    if (!mask || !renderer) return;
    const mw = mask.width, mh = mask.height, cat = mask.getAsUint8Array();
    ensureFoundSkinBuffers(mw, mh);
    const n = mw * mh;
    let prob = null;
    try { prob = conf && conf[3] && conf[3].width === mw ? conf[3].getAsFloat32Array() : null; } catch (e) { prob = null; }
    // Some Android WebViews read the GPU confidence texture back as zeros: the whole face then reads as "no skin" and the
    // foundation vanishes. Use the probabilities only while they agree with the category mask's face-skin area.
    let catSkin = 0, probSkin = 0;
    for (let i = 0; i < n; i++) { if (cat[i] === 3) catSkin++; if (prob && prob[i] > 0.5) probSkin++; }
    if (prob && probSkin < 0.5 * catSkin) prob = null;
    foundSkinStat.cat = catSkin / n; foundSkinStat.prob = prob ? probSkin / n : -1;
    foundSkinCat.set(cat);
    if (prob) {
      // Soft skin share: smoothstep over the face-skin probability, then also zero where hair (1) clearly wins.
      const lo = TUNING.foundSkinProb[0], hi = TUNING.foundSkinProb[1];
      for (let i = 0; i < n; i++) {
        const t = Math.min(1, Math.max(0, (prob[i] - lo) / (hi - lo)));
        foundSkinBin[i] = Math.round(t * t * (3 - 2 * t) * (cat[i] === 1 ? 0 : 1) * 255);
      }
    } else {
      for (let i = 0; i < n; i++) foundSkinBin[i] = cat[i] === 3 ? 255 : 0;
    }
    // Is the lower face uncovered? The share of cheek / chin landmarks (current frame) that this fresh mask calls skin.
    let hit = 0;
    for (const i of FOUND_COVER_PTS) {
      const px = clamp(Math.floor(sx[i] * mw), 0, mw - 1), py = clamp(Math.floor(sy[i] * mh), 0, mh - 1);
      if (foundSkinBin[py * mw + px] > 127) hit++;
    }
    foundOcc = smooth01(TUNING.foundOccCover[0], TUNING.foundOccCover[1], hit / FOUND_COVER_PTS.length);
    const first = !foundSkinReady;
    for (let i = 0; i < n; i++) {
      const next = foundSkinBin[i];
      const keep = first ? 0 : (next >= foundSkinPrev[i] ? TUNING.foundSegMixRise : TUNING.foundSegMix);
      const mixed = foundSkinPrev[i] * keep + next * (1 - keep);
      foundSkinPrev[i] = mixed;
      const v = mixed < 0 ? 0 : mixed > 255 ? 255 : mixed;
      foundSkinRgba[i * 4] = v;
      foundSkinRgba[i * 4 + 1] = v;
      foundSkinRgba[i * 4 + 2] = v;
      foundSkinRgba[i * 4 + 3] = 255;
    }
    foundSkinReady = true;
    updateOccGates(mw, mh, cat);
    renderer.uploadFoundSkin(foundSkinRgba, mw, mh);
  }
  // Jaw hinge sample: face skin (bin >= 80) and not above the ear. The walker may cross a short hair gap; this still rejects the hair sample itself.
  function jawHingeAllow(qx, qy, side) {
    const px = clamp(Math.floor(qx * foundSkinW), 0, foundSkinW - 1);
    const py = clamp(Math.floor(qy * foundSkinH), 0, foundSkinH - 1);
    if (foundSkinBin[py * foundSkinW + px] < 80) return false;
    const ear = side ? 454 : 234;
    return qy >= sy[ear];
  }
  function occMakeupOn() {
    return !!(makeup.lip || makeup.blush || makeup.eyeshadow || makeup.eyeliner || makeup.mascara || makeup.highlighter || makeup.contour);
  }
  function wantSkinMask() {
    const jawline = makeup.contour && makeup.contour.geometry && makeup.contour.geometry.contourStyle === 'jawline';
    return !!(makeup.foundation || jawline || (TUNING.makeupOcclusion && occMakeupOn()));
  }
  function occPointOk(cat, allowAccessory) {
    return cat === 3 || (allowAccessory && cat === 5);
  }
  function occVisShare(pts, cat, mw, mh, allowAccessory) {
    let hit = 0;
    for (const i of pts) {
      const px = clamp(Math.floor(sx[i] * mw), 0, mw - 1), py = clamp(Math.floor(sy[i] * mh), 0, mh - 1);
      if (occPointOk(cat[py * mw + px], allowAccessory)) hit++;
    }
    return hit / Math.max(1, pts.length);
  }
  function glideOcc(key, vis) {
    const g = smooth01(TUNING.occCover[0], TUNING.occCover[1], vis);
    occGate[key] += TUNING.occGlide * (g - occGate[key]);
  }
  function updateOccGates(mw, mh, cat) {
    if (!TUNING.makeupOcclusion) { occGate.lip = occGate.eye = occGate.cheek = 1; return; }
    glideOcc('lip', occVisShare(OCC_LIP_PTS, cat, mw, mh, false));
    glideOcc('eye', occVisShare(OCC_EYE_PTS, cat, mw, mh, true));
    glideOcc('cheek', occVisShare(OCC_CHEEK_PTS, cat, mw, mh, false));
  }
  // Background sums for the light color: pixels of segmenter class 0, blown-out and dark ones excluded. Gray World adds the
  // pixels; with TUNING.lightColorEdge, Gray-Edge (van de Weijer, Gevers & Gijsenij 2007: first order, Minkowski p = 1, no
  // blur beyond the 128 px frame) adds per channel |difference| to the right and lower neighbour when both pass.
  function bgColorSums(cat, mw, mh, data, sw, sh) {
    let r = 0, g = 0, bl = 0, n = 0, er = 0, eg = 0, eb = 0;
    const edge = TUNING.lightColorEdge;
    const lin = edge ? new Float32Array(sw * sh * 3).fill(-1) : null;
    for (let y = 0; y < sh; y++) {
      for (let x = 0; x < sw; x++) {
        if (cat[Math.floor((y * mh) / sh) * mw + Math.floor((x * mw) / sw)] !== 0) continue;
        const q = (y * sw + x) * 4;
        const R = toLin(data[q] / 255), G = toLin(data[q + 1] / 255), B = toLin(data[q + 2] / 255);
        if (Math.max(R, G, B) > TUNING.clipLin || lumOf(R, G, B) < TUNING.darkLum) continue;
        r += R; g += G; bl += B; n++;
        if (edge) { const i = (y * sw + x) * 3; lin[i] = R; lin[i + 1] = G; lin[i + 2] = B; }
      }
    }
    if (edge) {
      for (let y = 0; y < sh; y++) {
        for (let x = 0; x < sw; x++) {
          const i = (y * sw + x) * 3;
          if (lin[i] < 0) continue;
          for (const j of [x + 1 < sw ? i + 3 : -1, y + 1 < sh ? i + sw * 3 : -1]) {
            if (j < 0 || lin[j] < 0) continue;
            er += Math.abs(lin[j] - lin[i]); eg += Math.abs(lin[j + 1] - lin[i + 1]); eb += Math.abs(lin[j + 2] - lin[i + 2]);
          }
        }
      }
    }
    return { r, g, bl, n, er, eg, eb };
  }
  function runSegmenter(now, forLight, forSkin) {
    if (!segmenter || segmentBusy || (!forLight && !forSkin)) return;
    const lightSnap = forLight ? statsCtx.getImageData(0, 0, stats.width, stats.height) : null;
    segmentBusy = true;
    if (forLight) lastSegmentAt = now;
    if (forSkin) lastFoundSegAt = now;
    const segT0 = performance.now();
    try {
      segmenter.segmentForVideo(video, now, (result) => {
        segmentBusy = false;
        const mask = result.categoryMask;
        if (!mask) return;
        if (forSkin && wantSkinMask()) applyFoundSkinMask(mask, result.confidenceMasks);
        if (!forLight || !lightSnap) return;
        const mw = mask.width, mh = mask.height, cat = mask.getAsUint8Array();
        const sw = lightSnap.width, sh = lightSnap.height;
        const sums = bgColorSums(cat, mw, mh, lightSnap.data, sw, sh);
        const r = sums.r, g = sums.g, bl = sums.bl, n = sums.n;
        light.bgFraction = n / (sw * sh);
        const Y = lumOf(r, g, bl);
        if (n > 0 && Y > 0) {
          const lo = TUNING.lightColorClamp[0], hi = TUNING.lightColorClamp[1];
          let est = [r / Y, g / Y, bl / Y];
          let chroma = Math.max(r, g, bl) / Math.max(1e-6, Math.min(r, g, bl));
          light.colorEdgeW = 0;
          const eY = lumOf(sums.er, sums.eg, sums.eb);
          if (TUNING.lightColorEdge && eY > 0) {
            const w = light.bgFraction < TUNING.bgMinFraction || chroma > TUNING.bgMaxChroma ? TUNING.lightColorEdgeMix[1] : TUNING.lightColorEdgeMix[0];
            const edge = [sums.er / eY, sums.eg / eY, sums.eb / eY];
            est = est.map((v, j) => v + w * (edge[j] - v));
            chroma = Math.max(est[0], est[1], est[2]) / Math.max(1e-6, Math.min(est[0], est[1], est[2]));
            light.colorEdgeW = w;
          }
          const c = [clamp(est[0], lo, hi), clamp(est[1], lo, hi), clamp(est[2], lo, hi)];
          const cy = lumOf(c[0], c[1], c[2]);
          const snap = light.snapColor;
          const kc = light.colorSamples++ === 0 || snap ? 1 : wbLocked ? TUNING.lightSmoothing : TUNING.lightSmoothingAuto;
          if (snap) light.snapColor = false;
          let delta = 0;
          for (let j = 0; j < 3; j++) {
            const d = c[j] / cy - light.color[j];
            delta = Math.max(delta, Math.abs(d));
            light.color[j] += kc * d;
          }
          light.colorDelta = delta;
          const ok = light.bgFraction >= TUNING.bgMinFraction && chroma <= TUNING.bgMaxChroma ? 1 : 0;
          light.colorConf += kc * (ok - light.colorConf);
        }
        postLightHint();
      });
      // The call (and its callback) runs on this thread: this is how long the frame stood still for it (HUD "seg").
      const segMs = performance.now() - segT0;
      foundSegMs = foundSegMs ? foundSegMs + 0.2 * (segMs - foundSegMs) : segMs;
    } catch (e) { segmentBusy = false; }
  }
  function sampleScene(now, W, H) {
    const t0 = performance.now();
    const sw = 128, sh = Math.max(1, Math.round((128 * H) / W));
    if (stats.width !== sw || stats.height !== sh) { stats.width = sw; stats.height = sh; }
    statsCtx.drawImage(video, 0, 0, sw, sh);
    const data = statsCtx.getImageData(0, 0, sw, sh).data;
    const linAt = (nx, ny) => {
      const x = clamp(Math.round(nx * sw), 0, sw - 1), y = clamp(Math.round(ny * sh), 0, sh - 1);
      const k = (y * sw + x) * 4;
      return [toLin(data[k] / 255), toLin(data[k + 1] / 255), toLin(data[k + 2] / 255)];
    };
    const lumAt = (nx, ny) => { const c = linAt(nx, ny); return lumOf(c[0], c[1], c[2]); };
    // Same redness measure as the shader: (r - g) / (r + g + b) in linear RGB.
    const redAt = (nx, ny) => { const c = linAt(nx, ny); return (c[0] - c[1]) / (c[0] + c[1] + c[2] + 1e-4); };
    // First sample is taken as-is so the defaults never show (e.g. over-bright lip highlights at start).
    const k = light.samples++ === 0 ? 1 : TUNING.lightSmoothing;

    // Lip body samples: lerp outer→inner lip line, skip mouth corners (indices 0 and 10).
    // Mesh vertices inside the lip mask can hit the open mouth or a highlight and flatten shading.
    const lipBody = [];
    for (let i = 0; i < LIPS_OUTER.length; i++) {
      if (i === 0 || i === 10) continue;
      const ox = sx[LIPS_OUTER[i]], oy = sy[LIPS_OUTER[i]];
      const ix = sx[LIPS_INNER[i]], iy = sy[LIPS_INNER[i]];
      for (const t of [1 / 3, 0.5, 2 / 3]) lipBody.push([ox + t * (ix - ox), oy + t * (iy - oy)]);
    }
    const lipLum = trimmedMean(lipBody.map((p) => lumAt(p[0], p[1])));
    // Upper lip = outer/inner indices 1..9, lower = 11..19 (3 samples each, corners skipped).
    const upperLum = trimmedMean(lipBody.slice(0, 27).map((p) => lumAt(p[0], p[1])));
    const lowerLum = trimmedMean(lipBody.slice(27).map((p) => lumAt(p[0], p[1])));
    if (upperLum && lowerLum) light.lipUpLow += k * (upperLum / lowerLum - light.lipUpLow);
    // Close-ups cut the face off: a vertex outside the frame would read the edge pixel and skew the
    // light (10-25: highlights on the lower rim of the lower lip, "light from below").
    const inFrame = (i) => sx[i] > 0.01 && sx[i] < 0.99 && sy[i] > 0.01 && sy[i] < 0.99;
    const skinIn = masks.skinVerts.filter((i) => meshNrm[i * 3 + 2] >= 0.35 && inFrame(i));
    const samples = [];
    for (const i of skinIn) {
      samples.push([meshNrm[i * 3], meshNrm[i * 3 + 1], meshNrm[i * 3 + 2], lumAt(sx[i], sy[i])]);
    }
    let blownN = 0;
    for (const i of skinIn) {
      const c = linAt(sx[i], sy[i]);
      if (Math.max(c[0], c[1], c[2]) > TUNING.clipLin) blownN++;
    }
    if (skinIn.length) light.blownFrac += k * (blownN / skinIn.length - light.blownFrac);
    const skinLum = trimmedMean(samples.map((s) => s[3]));
    if (lipLum) light.lipMeanLum += k * (lipLum - light.lipMeanLum);
    try {
      const cam = measureCamera(W, H);
      light.grain += k * (cam.grain - light.grain);
      light.blur += k * (cam.blur - light.blur);
    } catch (e) { /* grain and blur are best-effort */ }
    // Bare-lip color as the camera sees it (linear RGB): the layer below the virtual lipstick.
    const lipCols = lipBody.map((p) => linAt(p[0], p[1]));
    const lipColor = [0, 1, 2].map((j) => trimmedMean(lipCols.map((c) => c[j])));
    if (lipColor.every((v) => v !== null)) {
      for (let j = 0; j < 3; j++) light.lipColor[j] += k * (lipColor[j] - light.lipColor[j]);
    }
    const lipRed = trimmedMean(lipBody.map((p) => redAt(p[0], p[1])));
    const skinRed = trimmedMean(skinIn.map((i) => redAt(sx[i], sy[i])));
    if (lipRed !== null) light.lipRed += k * (lipRed - light.lipRed);
    if (skinRed !== null) light.skinRed += k * (skinRed - light.skinRed);
    if (skinLum) light.skinMeanLum += k * (skinLum - light.skinMeanLum);
    // Bare-skin color: the reference below paint that crosses the lip line onto the skin (overlip).
    const skinCols = skinIn.map((i) => linAt(sx[i], sy[i]));
    const skinColor = [0, 1, 2].map((j) => trimmedMean(skinCols.map((c) => c[j])));
    if (skinColor.every((v) => v !== null)) {
      for (let j = 0; j < 3; j++) light.skinColor[j] += k * (skinColor[j] - light.skinColor[j]);
      const lab = linToLab(light.skinColor);
      if (light.refSkinLab && cie76(lab, light.refSkinLab) > TUNING.lightChangeDelta) light.snapColor = true;
      light.refSkinLab = lab;
      postSkinTone(now, skinIn.length);
    }

    // Direction and strength only (skin color is not used): brightness ≈ a + b·n, refit without outliers.
    if (samples.length >= 30) {
      let fit = fitLight(samples);
      if (fit) {
        let r2, mean;
        if (TUNING.lightRobust) {
          const rob = fitLightRobust(samples);
          fit = rob.fit;
          let sumW = 0, sumY = 0, ssRes = 0, ssTot = 0;
          samples.forEach((s, i) => { sumW += rob.weights[i]; sumY += rob.weights[i] * s[3]; });
          mean = sumY / sumW;
          samples.forEach((s, i) => {
            const pred = fit[0] + fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2];
            ssRes += rob.weights[i] * (s[3] - pred) * (s[3] - pred);
            ssTot += rob.weights[i] * (s[3] - mean) * (s[3] - mean);
          });
          r2 = ssTot > 1e-9 ? 1 - ssRes / ssTot : 0;
        } else {
          const resid = samples.map((s) => Math.abs(s[3] - (fit[0] + fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2])));
          const cut = resid.slice().sort((p, q) => p - q)[Math.floor(resid.length * 0.8)];
          const kept = samples.filter((_, i) => resid[i] <= cut);
          fit = fitLight(kept) || fit;
          let ssRes = 0, ssTot = 0;
          mean = kept.reduce((s, v) => s + v[3], 0) / kept.length;
          for (const s of kept) {
            const pred = fit[0] + fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2];
            ssRes += (s[3] - pred) * (s[3] - pred);
            ssTot += (s[3] - mean) * (s[3] - mean);
          }
          r2 = ssTot > 1e-9 ? 1 - ssRes / ssTot : 0;
        }
        if (TUNING.lightModel === 'sh9') {
          // fit keeps the linear layout [a, b]: the direction, strength (a + |b|, the brightness toward the light) and
          // confidence code below is shared. R² is the Lambert fit's.
          const lam = fitLightLambert(samples);
          light.shUsed = !!lam;
          if (lam) {
            fit = lam.fit;
            light.shCond = lam.cond;
            let sumW = 0, sumY = 0, ssRes = 0, ssTot = 0;
            samples.forEach((s, i) => { sumW += lam.weights[i]; sumY += lam.weights[i] * s[3]; });
            mean = sumY / sumW;
            samples.forEach((s, i) => {
              ssRes += lam.weights[i] * (s[3] - lam.pred[i]) * (s[3] - lam.pred[i]);
              ssTot += lam.weights[i] * (s[3] - mean) * (s[3] - mean);
            });
            r2 = ssTot > 1e-9 ? 1 - ssRes / ssTot : 0;
          }
          const c = lambertToSH(fit);
          light.sh = light.sh.map((v, i) => v + k * (c[i] - v));
          const directional = clamp(Math.hypot(c[1], c[2], c[3]) / Math.max(Math.abs(c[0]), 1e-6), 0, 1);
          light.shDirectional += k * (directional - light.shDirectional);
        }
        // Directional part relative to the mean skin brightness: does not shrink on dark skin the way absolute differences do.
        light.fitR2 = r2;
        light.fitRel = Math.hypot(fit[1], fit[2], fit[3]) / Math.max(mean, 1e-6);
        let dx = fit[1], dy = fit[2], dz = Math.max(fit[3], 0);
        let mag = Math.hypot(dx, dy, dz), peak = fit[0] + mag;
        const match = TUNING.lightMatch
          ? matchLight(faceHeightGrid(scr, FACE_TRIANGLES, TUNING.lightMatchGrid), scr, meshNrm, skinIn, samples.map((s) => s[3]),
            TUNING.lightMatchSpread, TUNING.lightMatchMaxVerts)
          : null;
        light.matchR2 = match ? match.r2 : -1;
        if (match) { [dx, dy, dz] = match.dir; mag = 1; r2 = match.r2; peak = match.peak; }
        if (mag > 1e-6) {
          dx /= mag; dy /= mag; dz /= mag;
          if (dz < 0.15) { dz = 0.15; const m2 = Math.hypot(dx, dy, dz); dx /= m2; dy /= m2; dz /= m2; }
          const turn = Math.acos(clamp(dx * light.dir[0] + dy * light.dir[1] + dz * light.dir[2], -1, 1)) * 180 / Math.PI;
          const kd = TUNING.lightDirGlide && turn > TUNING.lightDirSnapDeg ? 1 : k;
          light.dir = [0, 1, 2].map((j) => light.dir[j] + kd * ([dx, dy, dz][j] - light.dir[j]));
          const dl = Math.hypot(light.dir[0], light.dir[1], light.dir[2]) || 1;
          light.dir = light.dir.map((v) => v / dl);
        }
        let conf = clamp((r2 - TUNING.lightConfR2[0]) / (TUNING.lightConfR2[1] - TUNING.lightConfR2[0]), 0, 1);
        if (TUNING.lightRobust) {
          conf = Math.max(conf, clamp((light.fitRel - TUNING.lightConfRel[0]) / (TUNING.lightConfRel[1] - TUNING.lightConfRel[0]), 0, 1));
        }
        light.dirConf += k * (conf - light.dirConf);
        const strength = clamp(peak / TUNING.skinRefLum, 0.3, 1.5);
        light.strength += k * (strength - light.strength);
      }
    }

    // Color: Gray World over background pixels (segmenter class 0), blown-out and dark pixels excluded.
    const segEvery = wbLocked ? TUNING.segmentEveryMs : TUNING.segmentEveryMsAuto;
    const lightDue = light.snapColor || (now - lastSegmentAt > segEvery && (lastSegmentAt < 0 || fps >= TUNING.segmentMinFps));
    const skinDue = wantSkinMask() && now - lastFoundSegAt > (fps >= TUNING.segmentMinFps || !foundSkinReady ? TUNING.foundSegEveryMs : TUNING.foundSegEveryLowFpsMs);
    runSegmenter(now, lightDue, skinDue);
    postLightHint();
    lightMs = performance.now() - t0;
  }

  // ── WebGL renderer ───────────────────────────────────────────────────
  const PRECISION = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH',
    'precision highp float;',
    '#else',
    'precision mediump float;',
    '#endif',
  ].join(NL);

  const BG_VERT = [
    'attribute vec2 aPos;',
    'varying vec2 vUv;',
    'void main() { vUv = vec2(0.5 - aPos.x * 0.5, 0.5 - aPos.y * 0.5); gl_Position = vec4(aPos, 0.0, 1.0); }',
  ].join(NL);
  const BG_FRAG = [
    PRECISION,
    'varying vec2 vUv;',
    'uniform sampler2D uVideo;',
    'void main() { gl_FragColor = vec4(texture2D(uVideo, vUv).rgb, 1.0); }',
  ].join(NL);

  const MESH_VERT = [
    'attribute vec3 aPos; attribute vec2 aUv; attribute vec3 aNormal; attribute vec3 aLidM;',
    'varying vec2 vUv; varying vec3 vNormal; varying vec3 vLidM;',
    'void main() { vUv = aUv; vNormal = aNormal; vLidM = aLidM; gl_Position = vec4(aPos, 1.0); }',
  ].join(NL);
  const MESH_FRAG = [
    PRECISION,
    'varying vec2 vUv; varying vec3 vNormal; varying vec3 vLidM;',
    'uniform sampler2D uVideo; uniform sampler2D uMask; uniform vec2 uViewport;',
    'uniform vec3 uLightColor; uniform vec3 uLightDir; uniform float uLightStrength; uniform float uLightConf; uniform float uExposure;',
    'uniform float uLightSH[9]; uniform float uLightModel;',
    'uniform float uLipMeanLum; uniform float uSkinMeanLum;',
    'uniform vec3 uLipAlbedo; uniform float uLipCov; uniform float uLipRough; uniform float uLipSpec; uniform float uLipFlake; uniform float uLipOn;',
    'uniform vec3 uBlushAlbedo; uniform float uBlushCov;',
    // Blush from the face points (soft peach coral look): two rotated ellipses in the face's UV space, each
    // clipped to below the eye. Off (0) → the default baked blush mask.
    'uniform float uBlushDyn; uniform vec4 uBlushE0; uniform vec3 uBlushR0; uniform vec4 uBlushE1; uniform vec3 uBlushR1; uniform float uBlushInner;',
    'uniform float uPearl;',
    'uniform vec3 uShadowAlbedo; uniform float uShadowCov; uniform float uShadowFlake; uniform float uShadowFlakeScale; uniform float uShadowFlakeDensity; uniform float uShadowSpec;',
    'uniform float uLidSparkle; uniform float uLidGlitter; uniform float uLidGrainRad; uniform float uLidMinGrainPx; uniform float uLidOpen; uniform float uLidGlitterPower; uniform float uLidGlitterGain; uniform float uLidGlitterBase;',
    'uniform float uLidShimmerBase; uniform float uLidSheen;',
    'uniform vec3 uShadow2Albedo; uniform float uShadow2Cov; uniform vec3 uInnerAlbedo; uniform float uInnerCov;',
    'uniform sampler2D uMask3; uniform vec4 uHlAreas; uniform float uHlLegacy; uniform vec3 uSkinColor;',
    'uniform vec4 uLipCenter; uniform float uCenterHalf; uniform float uCenterHl;',
    'uniform sampler2D uMask2; uniform vec3 uHlAlbedo; uniform float uHlCov; uniform float uHlFlake; uniform vec3 uContourAlbedo; uniform float uContourCov; uniform vec2 uVolume; uniform float uVolLight;',
    'uniform vec3 uFoundAlbedo; uniform float uFoundCov; uniform float uFoundOpaque; uniform float uFoundShadeMax; uniform vec2 uFoundHair; uniform vec2 uFoundTone; uniform sampler2D uFoundSkin; uniform float uFoundSkinOn; uniform float uFoundFloor; uniform vec2 uFoundLowerV; uniform float uOccOn; uniform vec3 uOccGate; uniform vec3 uBrowAlbedo; uniform float uBrowCov; uniform float uBrowPowder; uniform float uBrowLift; uniform float uBrowSoft;',
    'uniform vec2 uBrowSkin[12]; uniform vec2 uBrowHead[2]; uniform vec2 uBrowTail[2];',
    'uniform vec3 uFaceRough; uniform float uFaceSheen; uniform float uEyeHole; uniform float uCap; uniform float uCapFade; uniform float uPowderTint; uniform float uJawCap; uniform float uJawCullOn; uniform float uJawYaw;',
    'uniform sampler2D uEye; uniform vec4 uEyeRect; uniform vec3 uLinerAlbedo; uniform float uLinerCov; uniform float uLinerAA; uniform float uLinerSoft; uniform vec3 uMascaraAlbedo; uniform float uMascaraCov; uniform float uEyeSoft;',
    'uniform float uSpecMax; uniform float uFlakeDensity; uniform float uFlakeScale;',
    'uniform vec2 uTexel; uniform float uLipRed; uniform float uSkinRed; uniform float uRefine;',
    'uniform float uLipDetailGain; uniform float uLipGlint; uniform float uGlintThreshold;',
    'uniform float uDiffuseCap; uniform float uSkinRef;',
    'uniform float uSpecFill; uniform vec3 uLipColor; uniform float uPaperWhite; uniform float uRatioMax;',
    'uniform float uLipSpecMax; uniform vec2 uHlKeep;',
    'uniform float uLumGainMax; uniform float uCreaseCover;',
    'uniform float uLipTranslucent; uniform float uMaskBias; uniform float uLipSheen;',
    'uniform sampler2D uOutline; uniform vec4 uOutlineRect; uniform float uOutlineSoft;',
    'uniform sampler2D uForm; uniform vec2 uFormStep; uniform float uFormTilt; uniform float uLowPx; uniform float uLipVolume; uniform float uFormOn; uniform vec2 uGlossMax; uniform vec2 uLightSize; uniform float uWideGloss; uniform vec3 uMouthN; uniform float uGlossGain; uniform float uFrontGloss; uniform float uGlossFlat; uniform vec4 uGlossShape; uniform vec3 uGlossTone;',
    'uniform float uHlLocal; uniform vec2 uHlSat; uniform float uHlBlown; uniform float uOpaqueShadeGamma; uniform float uLipFill;',
    'uniform float uLipDetail; uniform vec2 uDetailNoise; uniform float uHlSparkle; uniform float uWideDetail; uniform float uGlossAniso; uniform float uGlossCavity;',
    'uniform vec2 uInner[20]; uniform float uTeethReach; uniform vec2 uTeethRed; uniform vec2 uTeethBright; uniform vec2 uTeethFirm; uniform float uTeethOn; uniform float uMouthOpen;',
    'uniform float uTeethGuard; uniform vec2 uTeethSat; uniform float uTeethDark;',
    // x: 1 inside the drawn inner lip ring; y: 1 inside or near it, fading to 0 at uTeethReach px outside (video px).
    'vec2 mouthZone(vec2 p) {',
    '  float d = 1e9; bool inside = false;',
    '  for (int i = 0; i < 20; i++) {',
    '    vec2 a = uInner[i]; vec2 b = i < 19 ? uInner[i + 1] : uInner[0];',
    '    vec2 ab = b - a; float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-4), 0.0, 1.0);',
    '    d = min(d, length(p - a - ab * t));',
    '    if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) inside = !inside;',
    '  }',
    '  return inside ? vec2(1.0) : vec2(0.0, 1.0 - smoothstep(0.5 * uTeethReach, uTeethReach, d));',
    '}',
    'float redness(vec3 c) { return (c.r - c.g) / (c.r + c.g + c.b + 1e-4); }',
    // Screen-space lip outline (video coordinates): r = paint area, g = lip form; 0 outside.
    'vec2 outline2(vec2 s) {',
    '  vec2 p = (s - uOutlineRect.xy) / uOutlineRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? vec2(0.0) : texture2D(uOutline, p).rg;',
    '}',
    'float outlineAt(vec2 s) { return outline2(s).r; }',
    // The unexpanded landmark outline (B): inside it the lip, between it and the overlip ring the skin.
    'float baseOutlineAt(vec2 s) {',
    '  vec2 p = (s - uOutlineRect.xy) / uOutlineRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? 0.0 : texture2D(uOutline, p).b;',
    '}',
    // Screen-space eye canvas (video coordinates): r = eyeliner, g = mascara, b = inner-corner pearl, a = brow.
    'vec4 eyeAt(vec2 s) {',
    '  vec2 p = (s - uEyeRect.xy) / uEyeRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? vec4(0.0) : texture2D(uEye, p);',
    '}',
    'float formAt(vec2 s) {',
    '  vec2 p = (s - uOutlineRect.xy) / uOutlineRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? 0.0 : texture2D(uForm, p).r;',
    '}',
    'vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }',
    'vec3 toSrgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }',
    'float lum(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }',
    'float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }',
    // GGX (Trowbridge-Reitz) with Smith-Schlick geometry and Schlick Fresnel, F0 = 0.04.
    'float ggx(vec3 n, vec3 l, vec3 v, float rough) {',
    '  vec3 h = normalize(l + v);',
    '  float nh = max(dot(n, h), 0.0); float nl = max(dot(n, l), 0.0); float nv = max(dot(n, v), 1e-3);',
    // Clamp a2 and the denominator so mediump GPUs never underflow to 0 (D = inf → NaN pixels).
    '  float a = rough * rough; float a2 = max(a * a, 1e-3);',
    '  float d = nh * nh * (a2 - 1.0) + 1.0;',
    '  float D = a2 / (3.14159 * max(d * d, 1e-4));',
    '  float k = (rough + 1.0) * (rough + 1.0) / 8.0;',
    '  float G = (nl / (nl * (1.0 - k) + k)) * (nv / (nv * (1.0 - k) + k));',
    '  float F = 0.04 + 0.96 * pow(1.0 - max(dot(h, v), 0.0), 5.0);',
    '  return D * G * F / (4.0 * nv);',
    '}',
    // Peak-normalized GGX lobe (1 where the normal faces the half vector).
    'float lobeN(float nh, float r) { float a2 = max(r * r * r * r, 1e-4); float q = a2 / (nh * nh * (a2 - 1.0) + 1.0); return q * q; }',
    // SH9 irradiance at n. The Lambert band factors Â_l (π, 2π/3, π/4) are already in the coefficients (lambertToSH).
    'float shE(vec3 n) {',
    '  return 0.282095 * uLightSH[0] + 0.488603 * (uLightSH[1] * n.y + uLightSH[2] * n.z + uLightSH[3] * n.x)',
    '    + 1.092548 * (uLightSH[4] * n.x * n.y + uLightSH[5] * n.y * n.z + uLightSH[7] * n.x * n.z)',
    '    + 0.315392 * uLightSH[6] * (3.0 * n.z * n.z - 1.0) + 0.546274 * uLightSH[8] * (n.x * n.x - n.y * n.y);',
    '}',
    // lobeN with roughness r(1 + k) along the tangent t and r / (1 + k) across it (peak 1, same as lobeN at k = 0).
    'float lobeA(vec3 nn, vec3 t, vec3 h, float r, float k) {',
    '  float a = max(r * r, 1e-2);',
    '  vec3 tt = normalize(t - nn * dot(nn, t)); vec3 bb = cross(nn, tt);',
    '  float hx = dot(h, tt) / (a * (1.0 + k)), hy = dot(h, bb) * (1.0 + k) / a, hz = dot(h, nn);',
    '  float q = 1.0 / max(hx * hx + hy * hy + hz * hz, 1e-4);',
    '  return hz > 0.0 ? q * q : 0.0;',
    '}',
    // Flakes are fixed to UV cells so they stay on the face when the head turns.
    'float flake(vec2 uv, vec3 n, vec3 l, vec3 v) {',
    '  vec2 cell = floor(uv * uFlakeScale);',
    '  if (hash(cell) < uFlakeDensity) return 0.0;',
    '  vec3 jitter = vec3(hash(cell + 1.3), hash(cell + 7.1), hash(cell + 3.7)) - 0.5;',
    '  vec3 fn = normalize(n + jitter * 0.9);',
    '  return pow(max(dot(fn, normalize(l + v)), 0.0), 60.0);',
    '}',
    // Density is the pearl share (0.2 = 20% of cells). Shimmer: silk grains. Glitter: small ellipses.
    'float lidGrain(vec2 uv) {',
    '  if (uShadowFlakeDensity < 0.001) return 0.0;',
    '  vec2 g = uv * uShadowFlakeScale;',
    '  vec2 cell = floor(g);',
    '  if (hash(cell) >= uShadowFlakeDensity) return 0.0;',
    '  vec2 f = fract(g) - 0.5;',
    '  vec2 stretch = vec2(1.0 + 0.4 * (hash(cell + 5.1) - 0.5), 1.0 + 0.4 * (hash(cell + 6.3) - 0.5));',
    '  float rad = 0.16;',
    '  float d = 1.0 - smoothstep(rad * 0.15, rad, length(f * stretch));',
    '  return d * (0.55 + 0.45 * hash(cell + 4.1));',
    '}',
    'float lidFlake(vec2 uv, vec3 n, vec3 l, vec3 v) {',
    '  float grain = lidGrain(uv);',
    '  if (grain < 0.001) return 0.0;',
    '  vec2 cell = floor(uv * uShadowFlakeScale);',
    '  vec3 jitter = vec3(hash(cell + 1.3), hash(cell + 7.1), hash(cell + 3.7)) - 0.5;',
    '  vec3 fn = normalize(n + jitter * 0.9);',
    '  float ndh = max(dot(fn, normalize(l + v)), 0.0);',
    '  return grain * pow(ndh, 6.0);',
    '}',
    // TUNING.lidSparkle: one grain per cell at a random spot, round on screen, radius never under lidMinGrainPx.
    'float lidGrain2(vec2 uv) {',
    '  if (uShadowFlakeDensity < 0.001) return 0.0;',
    '  vec2 g = uv * uShadowFlakeScale;',
    '  vec2 cell = floor(g);',
    '  if (hash(cell) >= uShadowFlakeDensity) return 0.0;',
    // vLidM: px^2 per cell^2 here, split into the cell size in pixels and a unit-area shape.
    '  vec3 Mc = vLidM;',
    '  float area = sqrt(max(Mc.x * Mc.z - Mc.y * Mc.y, 1e-6));',
    '  float px = max(sqrt(area), 1.0);',
    '  vec3 M = Mc / area;',
    '  vec2 ext = sqrt(max(M.zx, 0.05));',
    '  float rad = min(max(uLidGrainRad, uLidMinGrainPx / px), 0.45 / max(ext.x, ext.y));',
    '  vec2 c = (vec2(hash(cell + 8.3), hash(cell + 9.7)) - 0.5) * max(1.0 - 2.0 * rad * ext, 0.0);',
    '  vec2 f = (fract(g) - 0.5 - c) * vec2(1.0 + 0.4 * (hash(cell + 5.1) - 0.5), 1.0 + 0.4 * (hash(cell + 6.3) - 0.5));',
    '  float r = sqrt(max(f.x * f.x * M.x + 2.0 * f.x * f.y * M.y + f.y * f.y * M.z, 0.0));',
    '  float aa = 0.6 / px;',
    '  float d = 1.0 - smoothstep(rad - aa, rad + aa, r);',
    '  return d * (0.55 + 0.45 * hash(cell + 4.1));',
    '}',
    'vec3 lidFacet(vec2 uv, vec3 n, float spread) {',
    '  vec2 cell = floor(uv * uShadowFlakeScale);',
    '  vec3 jitter = vec3(hash(cell + 1.3), hash(cell + 7.1), hash(cell + 3.7)) - 0.5;',
    '  return normalize(n + jitter * spread);',
    '}',
    'float lidShimmer2(float grain, vec2 uv, vec3 n, vec3 l, vec3 v) {',
    '  if (grain < 0.001) return 0.0;',
    '  return grain * pow(max(dot(lidFacet(uv, n, 0.9), normalize(l + v)), 0.0), 6.0);',
    '}',
    // Glitter flashes toward a fixed light above the camera, so they follow the head, not the 0.5 s light estimate.
    'float lidGlint(float grain, vec2 uv, vec3 n, vec3 v) {',
    '  if (grain < 0.001) return 0.0;',
    '  vec3 h = normalize(normalize(vec3(0.0, 0.35, 1.0)) + v);',
    '  return grain * pow(max(dot(lidFacet(uv, n, 1.2), h), 0.0), uLidGlitterPower);',
    '}',
    'float shadowSheen(vec3 n, vec3 l, vec3 v, float rough) {',
    '  if (rough > 0.97) return 0.0;',
    '  float r = max(rough, 0.05);',
    '  float lobe = max(lobeN(max(dot(n, normalize(l + v)), 0.0), r), 0.55 * lobeN(max(dot(n, normalize(vec3(0.0, 0.3, 1.0) + v)), 0.0), r));',
    '  float sm = 1.0 - rough;',
    '  return lobe * sm * sm * uFaceSheen * uSkinMeanLum * 2.4;',
    '}',
    // Shimmer pearls peak above the pupil (mid lid) and fall off toward the crease and the lash line.
    'float lidPearlFade(float maskB) {',
    '  float t = clamp((maskB - 0.4) / 0.6, 0.0, 1.0);',
    '  float d = (t - 0.62) / 0.32;',
    '  return exp(-d * d);',
    '}',
    // Powder sheen (blush, shadow, highlighter): broad GGX lobe on the mesh normal, key light or the
    // always-present frontal source, peak by smoothness and scene brightness. Matte ≈ 0.
    'float powderSheen(vec3 n, vec3 l, vec3 v, float rough) {',
    '  float r = sqrt(rough * rough + 0.2);',
    '  float lobe = max(lobeN(max(dot(n, normalize(l + v)), 0.0), r), 0.6 * lobeN(max(dot(n, normalize(vec3(0.0, 0.3, 1.0) + v)), 0.0), r));',
    '  float sm = 1.0 - rough;',
    '  return lobe * sm * sm * sm * uFaceSheen * uSkinMeanLum * 3.0;',
    '}',
    // Product albedo under the current light, shaded by the real camera brightness relative to the zone mean.
    'vec3 layer(vec3 cam, vec3 albedo, float refLum, float shadeMax) {',
    '  float shade = clamp(lum(cam) / max(refLum, 1e-3), 0.0, shadeMax);',
    '  return albedo * uLightColor * shade * uExposure;',
    '}',
    // Translucent powder: the camera skin filtered by the pigment (thin film), so a light shade on deep
    // skin tints it instead of laying an ashy patch over it (LaPa 10-25).
    'vec3 powder(vec3 cam, vec3 albedo) {',
    '  vec3 tint = cam * sqrt(clamp(albedo / uPaperWhite, 0.0, 1.0));',
    '  return mix(layer(cam, albedo, uSkinMeanLum, 1.6), tint, uPowderTint);',
    '}',
    'vec3 hardLight(vec3 base, vec3 blend) {',
    '  vec3 lo = 2.0 * base * blend;',
    '  vec3 hi = vec3(1.0) - 2.0 * (vec3(1.0) - base) * (vec3(1.0) - blend);',
    '  return mix(lo, hi, step(vec3(0.5), blend));',
    '}',
    // One cheek: uv offset from the centre rotated into the ellipse's axes (r.x = cos, r.y = sin of the cheek's
    // tilt), falloff from the soft inner radius (uBlushInner) to the rim, and only below the lower lid (r.z, UV y points up).
    'float blushEll(vec2 uv, vec4 e, vec3 r) {',
    '  vec2 d = uv - e.xy;',
    '  vec2 q = vec2(r.x * d.x + r.y * d.y, -r.y * d.x + r.x * d.y) / e.zw;',
    '  float a = 1.0 - smoothstep(uBlushInner, 1.0, length(q));',
    '  return a * (1.0 - smoothstep(r.z - 0.012, r.z, uv.y));',
    '}',
    'void main() {',
    // Mip bias softens the mask edges as much as the camera image itself is blurred.
    '  vec4 m = texture2D(uMask, vUv, uMaskBias);',
    '  m.r = min(m.r * uLipFill, 1.0);',
    '  float blushM = uBlushDyn > 0.5 ? max(blushEll(vUv, uBlushE0, uBlushR0), blushEll(vUv, uBlushE1, uBlushR1)) : m.g;',
    // Matte/velvet (rough ~0.9): lift the falloff so the cheek edge looks powder-spread.
    // Glossy/sheer (rough ~0.16): steepen it so the patch looks creamier and tighter.
    '  float blushPow = mix(1.7, 0.5, clamp((uFaceRough.x - 0.16) / 0.74, 0.0, 1.0));',
    '  blushM = pow(max(blushM, 0.0), blushPow);',
    '  float blushA = blushM * uBlushCov; float shadowA = m.b * uShadowCov;',
    '  float lipZone = m.a * uLipOn;',
    '  vec2 suv = vec2(1.0 - gl_FragCoord.x / uViewport.x, 1.0 - gl_FragCoord.y / uViewport.y);',
    '  vec4 m2 = texture2D(uMask2, vUv, uMaskBias);',
    '  vec4 m3 = texture2D(uMask3, vUv, uMaskBias);',
    '  float hlMask = uHlLegacy > 0.5 ? m2.r : clamp(dot(m3, uHlAreas), 0.0, 1.0);',
    '  float hlA = hlMask * uHlCov; float contourA = m2.g * uContourCov; float darkA = m2.b * uShadow2Cov;',
    // Turned head: the far jaw's UV stretches onto the near cheek. Drop that side. Nose shading stays (uJawCullOn is 0).
    '  if (uJawCullOn > 0.5) {',
    '    float hideL = smoothstep(0.08, 0.25, uJawYaw) * (1.0 - smoothstep(0.42, 0.52, vUv.x));',
    '    float hideR = smoothstep(0.08, 0.25, -uJawYaw) * smoothstep(0.48, 0.58, vUv.x);',
    '    contourA *= 1.0 - max(hideL, hideR);',
    '    if (uFoundSkinOn > 0.5) contourA *= texture2D(uFoundSkin, suv).r;',
    '    if (uJawCullOn > 1.5) contourA = 0.0;',
    '  }',
    '  float foundA = m2.a * uFoundCov;',
    // Softened by the camera's own blur like the lip outline: crisp 1 px lashes on a soft phone image
    // read as pasted on.
    // 3×3 binomial at the measured blur width (5 taps at half of it still left lashes crisp on a
    // σ 2.5 px blurred frame); only read where the eye canvas is on.
    '  vec4 eyeC = vec4(0.0);',
    '  if (uEyeRect.x > -1.0) {',
    '    vec2 eo = uTexel * uEyeSoft;',
    '    eyeC = 4.0 * eyeAt(suv)',
    '      + 2.0 * (eyeAt(suv + vec2(eo.x, 0.0)) + eyeAt(suv - vec2(eo.x, 0.0)) + eyeAt(suv + vec2(0.0, eo.y)) + eyeAt(suv - vec2(0.0, eo.y)))',
    '      + eyeAt(suv + eo) + eyeAt(suv - eo) + eyeAt(suv + vec2(eo.x, -eo.y)) + eyeAt(suv + vec2(-eo.x, eo.y));',
    '    eyeC /= 16.0;',
    '  }',
    // Eyeliner (10-29): one flat ink, no finish. The camera-matched blur (eyeC) would spread a thin band and lower its
    // peak (a faint grey line), so the liner gets only a half-texel read against stair steps, then any texel the
    // drawn band covers past about half is snapped to full coverage, so the core is opaque even on a thin line.
    '  float linerR = 0.0;',
    '  if (uEyeRect.x > -1.0) {',
    '    vec2 ao = uTexel * uLinerAA;',
    '    linerR = (4.0 * eyeAt(suv).r + eyeAt(suv + vec2(ao.x, 0.0)).r + eyeAt(suv - vec2(ao.x, 0.0)).r + eyeAt(suv + vec2(0.0, ao.y)).r + eyeAt(suv - vec2(0.0, ao.y)).r) / 8.0;',
    '    linerR = smoothstep(0.05, 0.45, linerR);',
    '  }',
    // Smudge (geometry.linerSoftness): blend toward a wide read of the same drawn path. 0 leaves the line as is.
    '  if (uEyeRect.x > -1.0 && uLinerSoft > 0.001) {',
    '    vec2 so = uTexel * uEyeSoft * (2.0 + 3.0 * uLinerSoft);',
    '    float wide = (4.0 * eyeAt(suv).r',
    '      + 2.0 * (eyeAt(suv + vec2(so.x, 0.0)).r + eyeAt(suv - vec2(so.x, 0.0)).r + eyeAt(suv + vec2(0.0, so.y)).r + eyeAt(suv - vec2(0.0, so.y)).r)',
    '      + eyeAt(suv + so).r + eyeAt(suv - so).r + eyeAt(suv + vec2(so.x, -so.y)).r + eyeAt(suv + vec2(-so.x, so.y)).r) / 16.0;',
    // The wide read alone would just fade a thin line; boost it so the spread pigment stays dark near the line.
    '    linerR = max(linerR, mix(linerR, min(wide * (1.0 + 2.5 * uLinerSoft), 1.0), uLinerSoft));',
    '  }',
    '  float linerA = linerR * uLinerCov; float mascaraA = eyeC.g * uMascaraCov; float innerA = eyeC.b * uInnerCov;',
    '  float browG = eyeC.a;',
    '  if (uBrowCov > 0.0 && uEyeRect.x > -1.0) {',
    '    vec2 bo = uTexel * uBrowSoft;',
    '    browG = (4.0 * eyeC.a + 2.0 * (eyeAt(suv + vec2(bo.x, 0.0)).a + eyeAt(suv - vec2(bo.x, 0.0)).a + eyeAt(suv + vec2(0.0, bo.y)).a + eyeAt(suv - vec2(0.0, bo.y)).a)',
    '      + eyeAt(suv + bo).a + eyeAt(suv - bo).a + eyeAt(suv + vec2(bo.x, -bo.y)).a + eyeAt(suv + vec2(-bo.x, bo.y)).a) / 16.0;',
    '  }',
    '  float browA = browG * uBrowCov * mix(0.9, 1.0, clamp(normalize(vNormal).z, 0.0, 1.0));',
    // Eye-opening triangles carry only lashes (no shadow feather or lip band on the eyeball).
    '  if (uCap > 0.5) {',
    '    m = vec4(0.0); blushA = 0.0; shadowA = 0.0; lipZone = 0.0; hlA = 0.0; contourA = 0.0; linerA = 0.0; mascaraA = 0.0; darkA = 0.0; innerA = 0.0; browA = 0.0;',
    '    foundA = vUv.y * (1.0 - smoothstep(uCapFade, 1.0, vUv.x)) * uFoundCov;',
    '  }',
    '  if (uJawCap > 0.5) {',
    '    m = vec4(0.0); blushA = 0.0; shadowA = 0.0; lipZone = 0.0; hlA = 0.0; linerA = 0.0; mascaraA = 0.0; darkA = 0.0; innerA = 0.0; browA = 0.0; foundA = 0.0;',
    '    contourA = (1.0 - smoothstep(0.55, 1.0, vUv.x)) * uContourCov;',
    '    if (uFoundSkinOn > 0.5) contourA *= texture2D(uFoundSkin, suv).r;',
    '    else contourA = 0.0;',
    '  }',
    '  if (uEyeHole > 0.5) { blushA = 0.0; shadowA = 0.0; lipZone = 0.0; hlA = 0.0; contourA = 0.0; linerA = 0.0; darkA = 0.0; innerA = 0.0; foundA = 0.0; browA = 0.0; }',
    '  if (lipZone + blushA + shadowA + hlA + contourA + linerA + mascaraA + darkA + innerA + foundA + browA < 0.002) discard;',
    '  vec3 cam = toLin(texture2D(uVideo, suv).rgb);',
    '  vec3 n = normalize(vNormal); vec3 v = vec3(0.0, 0.0, 1.0); vec3 l = normalize(uLightDir);',
    '  float lipM = 0.0; float lipEdgeW = 0.0; float redN = 0.0; vec3 lipFormN = n; vec3 lipBaseN = n; vec3 lipDetailN = n; vec3 camN = cam;',
    '  vec2 lipDG = vec2(0.0);',
    '  float skinRefW = 0.0; float lipDepth = 0.0;',
    '  float lN = lum(cam);',
    '  float wideL = lN; float hlCap = 0.0; float hlPeak = 0.0; float hlWide = 0.0; float hlSpark = 0.0;',
    '  if (lipZone > 0.002) {',
    // Neighbors: local mean brightness (lip volume vs. wrinkles) and a denoised color for the edge test.
    '    vec2 o = uTexel * 1.5;',
    '    vec3 c1 = toLin(texture2D(uVideo, suv + vec2(o.x, 0.0)).rgb);',
    '    vec3 c2 = toLin(texture2D(uVideo, suv - vec2(o.x, 0.0)).rgb);',
    '    vec3 c3 = toLin(texture2D(uVideo, suv + vec2(0.0, o.y)).rgb);',
    '    vec3 c4 = toLin(texture2D(uVideo, suv - vec2(0.0, o.y)).rgb);',
    '    lN = 0.25 * (lum(c1) + lum(c2) + lum(c3) + lum(c4));',
    '    redN = redness(c1 + c2 + c3 + c4);',
    '    camN = 0.2 * (cam + c1 + c2 + c3 + c4);',
    // Relative brightness step across 3 px (video coordinates, like the form gradient below): the lip's own lines.
    '    lipDG = vec2(lum(c1) - lum(c2), lum(c3) - lum(c4)) / max(lN, 1e-4);',
    '    vec3 e1 = toLin(texture2D(uVideo, suv + uTexel * 3.0).rgb), e2 = toLin(texture2D(uVideo, suv - uTexel * 3.0).rgb);',
    '    vec3 e3 = toLin(texture2D(uVideo, suv + vec2(uTexel.x, -uTexel.y) * 3.0).rgb), e4 = toLin(texture2D(uVideo, suv + vec2(-uTexel.x, uTexel.y) * 3.0).rgb);',
    '    wideL = 0.25 * (lum(e1) + lum(e2) + lum(e3) + lum(e4));',
    // Light reflected by the lip: brighter than the lip and desaturated, and either a peak over the
    // local 3px mean or a wide reflection far above the lip mean. It is white, not red, but it is
    // still lip: it keeps the paint, and below it becomes the gloss and crease detail (device 10-25:
    // reflections were read as skin and left unpainted).
    '    float meanL0 = max(uLipMeanLum, 1e-3);',
    '    float camL0 = max(lum(cam), 1e-4);',
    '    float camSat = (max(cam.r, max(cam.g, cam.b)) - min(cam.r, min(cam.g, cam.b))) / max(max(cam.r, max(cam.g, cam.b)), 1e-4);',
    '    float desat = 1.0 - smoothstep(uHlSat.x, uHlSat.y, camSat);',
    '    hlCap = max(camL0 - uDiffuseCap * meanL0, 0.0) * desat;',
    // Peak: narrow reflection on a ridge or crease edge (the lip surface). Wide: the bare lip's wet shine.
    '    hlPeak = max(camL0 - uHlLocal * wideL, 0.0) * desat;',
    // Sparkle: a small spot brighter than its 3 px surround and whiter than its 4 neighbours. On a red lip a reflection is still
    // pinkish (median linear saturation 0.4–0.8 on 5 still faces), so the absolute hlSat test missed 95% of them on a lined lip.
    '    vec3 cR = c1 + c2 + c3 + c4;',
    '    float satR = (max(cR.r, max(cR.g, cR.b)) - min(cR.r, min(cR.g, cR.b))) / max(max(cR.r, max(cR.g, cR.b)), 1e-4);',
    '    hlSpark = max(camL0 - wideL, 0.0) * smoothstep(1.0, uHlLocal, camL0 / max(wideL, 1e-4)) * smoothstep(0.0, 0.1, satR - camSat);',
    '    hlWide = max(camL0 - uHlBlown * meanL0, 0.0) * desat;',
    // Teeth near the inner line: pale and bright at 1.5 px and 3 px alike (TUNING.teeth).
    '    float teethW = 0.0;',
    '    if (uTeethOn > 0.5) {',
    '      vec2 zone = mouthZone(suv * uViewport);',
    '      if (zone.y > 0.01) {',
    // A thin teeth band (a few px tall) has lip above and below it, so the 4-neighbour mean stays red. Inside the drawn
    // inner ring of an open mouth, the two neighbours along the mouth are enough; elsewhere (the lip side, closed lips with
    // their thin seam, a wet lower-lip streak) all four must be pale. The pixel itself must be pale too.
    '        vec2 ax = uLipCenter.zw * uTexel * 1.5;',
    '        float rA = max(redness(toLin(texture2D(uVideo, suv + ax).rgb)), redness(toLin(texture2D(uVideo, suv - ax).rgb)));',
    '        float redT = max(redness(cam), uMouthOpen * zone.x > 0.5 ? rA : redN);',
    '        float raw = (1.0 - smoothstep(uTeethRed.x * uLipRed, uTeethRed.y * uLipRed, redT)) * smoothstep(uTeethBright.x, uTeethBright.y, lN / meanL0);',
    '        teethW = smoothstep(uTeethFirm.x, uTeethFirm.y, raw) * zone.y;',
    '        if (uMouthOpen * zone.x > 0.5) {',
    '          float hiC = max(cam.r, max(cam.g, cam.b));',
    '          float satC = (hiC - min(cam.r, min(cam.g, cam.b))) / max(hiC, 1e-4);',
    '          float holePale = 1.0 - smoothstep(uTeethSat.x, uTeethSat.y, satC);',
    '          float holeNotRed = 1.0 - smoothstep(uTeethRed.x * uLipRed, uTeethRed.y * uLipRed, redness(cam));',
    '          teethW = max(teethW, holePale * holeNotRed);',
    '        }',
    '      }',
    '    }',
    // Outer edge and open-mouth hole from the screen-space outline, softened as much as the camera
    // image is blurred; the UV mask only adds the inner and corner fades. No per-pixel redness test:
    // at close range it grew lumps along the line (10-25). Reflections are inside the outline, so lip.
    '    vec2 so = uTexel * uOutlineSoft;',
    '    float o0 = outlineAt(suv);',
    '    float soft = (2.0 * o0 + outlineAt(suv + vec2(so.x, 0.0)) + outlineAt(suv - vec2(so.x, 0.0))',
    '      + outlineAt(suv + vec2(0.0, so.y)) + outlineAt(suv - vec2(0.0, so.y))) / 6.0;',
    // Open mouth: do not let the 5-tap average smear paint into the hole (teeth / inner mouth).
    '    float inside = mix(soft, o0, uMouthOpen * (1.0 - smoothstep(0.18, 0.55, o0)));',
    '    lipM = m.r * inside * (1.0 - teethW);',
    // Open mouth, along the inner line only (outline G): teeth (redness under the lip/skin midpoint, pale, not a small
    // peak like a lip reflection) and the dark mouth come out of the paint.
    '    if (uTeethGuard > 0.5) {',
    '      float band = outline2(suv).g;',
    '      float hiN = max(camN.r, max(camN.g, camN.b));',
    '      float satN = (hiN - min(camN.r, min(camN.g, camN.b))) / max(hiN, 1e-4);',
    '      float notRed = (1.0 - smoothstep(mix(uSkinRed, uLipRed, 0.15), mix(uSkinRed, uLipRed, 0.5), redN)) * uRefine;',
    '      float pale = 1.0 - smoothstep(uTeethSat.x, uTeethSat.y, satN);',
    '      float flatL = 1.0 - smoothstep(0.0, 0.06 * meanL0, hlPeak);',
    '      float dark = 1.0 - smoothstep(0.6 * uTeethDark * meanL0, uTeethDark * meanL0, lN);',
    '      lipM *= 1.0 - band * max(notRed * pale * flatL, dark);',
    '    }',
    // Overlip: the part of the paint outside the landmark outline lies on skin, not lip. Its share
    // (0 on the lip, 1 on the band) picks the bare-skin reference below, and highlights seen there are
    // skin shine, not lip shine.
    '    float insideBase = (2.0 * baseOutlineAt(suv) + baseOutlineAt(suv + vec2(so.x, 0.0)) + baseOutlineAt(suv - vec2(so.x, 0.0))',
    '      + baseOutlineAt(suv + vec2(0.0, so.y)) + baseOutlineAt(suv - vec2(0.0, so.y))) / 6.0;',
    '    skinRefW = clamp((inside - insideBase) / max(inside, 1e-3), 0.0, 1.0);',
    '    hlCap *= 1.0 - skinRefW; hlPeak *= 1.0 - skinRefW; hlWide *= 1.0 - skinRefW; hlSpark *= 1.0 - skinRefW;',
    // Lip form: the blurred form field says how deep inside each lip (1 deep inside, ~0.5 on its line)
    // and its slope points into the lip, so each lip is a rounded body whose normal tilts outward
    // toward its line (≈ 1 at the line, scaled by the rise width). Video coordinates run left and down
    // on the mirrored screen, hence the sign.
    '    if (lipM > 0.002) {',
    '      vec2 e = uTexel * uFormStep.x;',
    '      float h0 = formAt(suv);',
    '      vec2 grad = vec2(formAt(suv + vec2(e.x, 0.0)) - formAt(suv - vec2(e.x, 0.0)), formAt(suv + vec2(0.0, e.y)) - formAt(suv - vec2(0.0, e.y))) * 0.5 * uFormStep.y;',
    '      lipEdgeW = 1.0 - smoothstep(0.5, 0.97, h0);',
    '      lipDepth = h0;',
    // The mesh normal already tilts the lower lip up and the upper lip down (20–60°, coarse lip
    // vertices), which pushed a frontal-light highlight to the lower rim: its up/down part comes from
    // the mouth's mean orientation (a little of its own), while left/right keeps the mesh, so the lips
    // still wrap around the teeth and a turned face shows its near side. Tilt saturates at the line
    // (a steep tilt there drew a dark ring, LaPa 10-25).
    '      lipBaseN = normalize(vec3(n.x, mix(uMouthN.y, n.y, 0.3), n.z));',
    '      vec2 tilt = grad * inversesqrt(1.0 + dot(grad, grad)) * uFormTilt * uFormOn;',
    '      lipFormN = normalize(lipBaseN + vec3(tilt.x, tilt.y, 0.0));',
    // Detail: the camera's own lip lines on top of the form. Off near the outline and the inner line, where the step is lip vs
    // skin or teeth, and below the camera grain, where it is noise.
    '      vec2 dT = lipDG * uLipDetail * smoothstep(uDetailNoise.x, uDetailNoise.y, length(lipDG)) * smoothstep(0.55, 0.8, h0) * uFormOn;',
    '      dT *= inversesqrt(1.0 + dot(dT, dT));',
    '      lipDetailN = normalize(lipFormN + vec3(dT.x, dT.y, 0.0));',
    '    }',
    '  }',
    // Hand / cup / hair-on-eyes: clip color makeup to face-skin pixels only while that region looks covered.
    // Gate 1 leaves the amount unchanged (no occlusion). Foundation keeps its own bangs / lower-face path.
    '  if (uOccOn > 0.5) {',
    '    float occSkin = texture2D(uFoundSkin, suv).r;',
    '    lipM *= mix(occSkin, 1.0, uOccGate.x);',
    '    blushA *= mix(occSkin, 1.0, uOccGate.z); hlA *= mix(occSkin, 1.0, uOccGate.z);',
    '    contourA *= mix(occSkin, 1.0, uOccGate.z);',
    '    shadowA *= mix(occSkin, 1.0, uOccGate.y); linerA *= mix(occSkin, 1.0, uOccGate.y); mascaraA *= mix(occSkin, 1.0, uOccGate.y);',
    '    darkA *= mix(occSkin, 1.0, uOccGate.y); innerA *= mix(occSkin, 1.0, uOccGate.y);',
    '  }',
    '  if (lipM + blushA + shadowA + hlA + contourA + linerA + mascaraA + darkA + innerA + foundA + browA < 0.002) discard;',
    '  vec3 col = cam;',
    // Face → eyes → lips, each a product layer over the camera (a mixed product color shaded by the
    // camera brightness), so intensity 0 leaves the pixel as it was.
    // Foundation: opaque share = the product color shaded by the camera (the skin's color variation is covered); translucent
    // share = the skin filtered by the pigment (its own color shows through). Coverage moves between the two.
    '  if (foundA > 0.002) {',
    // Landmark oval includes bangs. Prefer selfie-multiclass face skin (class 3); brightness gate is fallback only.
    '    float skinM = uFoundSkinOn > 0.5 ? texture2D(uFoundSkin, suv).r : smoothstep(uFoundHair.x, uFoundHair.y, lum(cam) / max(uSkinMeanLum, 1e-3));',
    // Lower face: the mask is a screen-space texture a few frames old, so on a moving head its edge lags the face. Below the eyes the
    // paint keeps a floor (uFoundFloor, 0 while a hand or hair covers the lower face, and 0 without a mask) and follows the landmark
    // outline instead. The forehead cap and the upper face keep the mask.
    '    if (uCap < 0.5) skinM = max(skinM, uFoundFloor * (1.0 - smoothstep(uFoundLowerV.x, uFoundLowerV.y, vUv.y)));',
    '    foundA *= skinM;',
    // Tone gate: pixels whose colour (chromaticity, not brightness) is far from this face's skin get no foundation: coloured bangs
    // the mask missed. Brightness is left out so highlights and shadows on skin keep their coverage.
    '    float fdC = length(cam / max(lum(cam), 1e-4) - uSkinColor / max(lum(uSkinColor), 1e-4));',
    // Specular highlights shift toward white (less saturated than the skin); coloured bangs shift away from it (more saturated).
    // Only the second kind is cut, or the bright nose and cheeks turn into blotches.
    '    float fdSat = length(cam / max(lum(cam), 1e-4) - 1.0) / max(length(uSkinColor / max(lum(uSkinColor), 1e-4) - 1.0), 1e-3);',
    '    foundA *= 1.0 - smoothstep(uFoundTone.x, uFoundTone.y, fdC * smoothstep(0.9, 1.1, fdSat));',
    '    vec3 pigment = layer(cam, uFoundAlbedo, uSkinMeanLum, uFoundShadeMax);',
    '    vec3 film = cam * sqrt(clamp(uFoundAlbedo / uPaperWhite, 0.0, 1.0));',
    '    col = mix(col, mix(film, pigment, uFoundOpaque), foundA);',
    '  }',
    // Volume: 0 where the surface turns away, 1 where it faces the camera (blended toward the light by trust in it).
    '  float volFace = mix(clamp(n.z, 0.0, 1.0), clamp(dot(n, l), 0.0, 1.0), uLightConf * uVolLight);',
    '  contourA *= clamp(1.0 + uVolume.x * (0.7 - volFace), 0.6, 1.5);',
    '  hlA *= clamp(1.0 + uVolume.y * (volFace - 0.7), 0.7, 1.4);',
    '  if (contourA > 0.002) col = mix(col, powder(cam, uContourAlbedo), contourA);',
    '  if (blushA > 0.002) col = mix(col, powder(cam, uBlushAlbedo), blushA) + uBlushAlbedo * uLightColor * powderSheen(n, l, v, uFaceRough.x) * blushA;',
    // Highlighter: a little of its light color, then its own sheen and shimmer where the face meets the light.
    '  if (hlA > 0.002) {',
    '    col = mix(col, layer(cam, uHlAlbedo, uSkinMeanLum, 1.6), 0.35 * hlA);',
    '    col += mix(uHlAlbedo, vec3(1.0), 0.3) * uLightColor * powderSheen(n, l, v, uFaceRough.z) * hlA + vec3(uHlFlake * flake(vUv, n, l, v) * uLightStrength) * hlA;',
    '  }',
    '  if (shadowA > 0.002) {',
    '    vec3 tint = clamp(uShadowAlbedo / max(uPaperWhite, 1e-3), 0.0, 1.0);',
    '    float hasPearl = step(0.001, uShadowFlakeDensity);',
    '    float isGloss = (1.0 - hasPearl) * (1.0 - step(0.97, uFaceRough.y));',
    '    col = mix(col, col * tint, shadowA);',
    '    col += mix(uShadowAlbedo, vec3(1.0), 0.85) * uLightColor * shadowSheen(n, l, v, uFaceRough.y) * uShadowSpec * isGloss * 2.2 * shadowA;',
    '    float pearlW = lidPearlFade(m.b);',
    '    vec3 pearl = mix(uShadowAlbedo, vec3(0.93, 0.96, 1.0), 0.62);',
    '    if (uLidSparkle > 0.5) {',
    '      float grain = lidGrain2(vUv) * uLidOpen;',
    '      vec3 lS = normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf));',
    '      float spec = uLidGlitter > 0.5 ? lidGlint(grain, vUv, n, v) * uLidGlitterGain : lidShimmer2(grain, vUv, n, lS, v) * uLidShimmerBase;',
    '      float base = 0.85 * mix(uLidShimmerBase, uLidGlitterBase, uLidGlitter);',
    '      col += pearl * uLightColor * shadowSheen(n, lS, v, uFaceRough.y) * uShadowSpec * uLidSheen * hasPearl * pearlW * shadowA;',
    '      col += pearl * uLightColor * (hasPearl * pearlW * base * uShadowFlake * grain);',
    '      col += pearl * uLightColor * (hasPearl * pearlW * uShadowSpec * 1.4 * uShadowFlake * spec);',
    '    } else {',
    '      float grain = lidGrain(vUv);',
    '      float spec = lidFlake(vUv, n, l, v);',
    '      col += pearl * uLightColor * (hasPearl * pearlW * 0.85 * uShadowFlake * grain);',
    '      col += pearl * uLightColor * (hasPearl * pearlW * uShadowSpec * 1.4 * uShadowFlake * spec);',
    '    }',
    // Pearl without particles: the middle of the lid (mid-gradient of the shadow mask) gets brighter where its
    // normal faces the light, so the bright spot slides as the head moves. Brightness only, color kept.
    '    float lidMid = smoothstep(0.3, 0.55, m.b) * (1.0 - smoothstep(0.7, 0.95, m.b));',
    '    float lidLobe = lobeN(max(dot(n, normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf) + v)), 0.0), 0.5);',
    '    col *= 1.0 + uPearl * lidMid * lidLobe * shadowA;',
    '  }',
    // Second shadow color over the first, at the outer corner and the lower lash line.
    '  if (darkA > 0.002) col = mix(col, powder(cam, uShadow2Albedo), darkA);',
    // Inner-corner pearl: a light pearl over the shadow, with its own soft sheen.
    '  if (innerA > 0.002) col = mix(col, powder(cam, uInnerAlbedo), innerA) + uInnerAlbedo * uLightColor * powderSheen(n, l, v, 0.3) * innerA;',
    // Liner: one flat opaque ink over everything under it (eyeshadow included). Product color under the room
    // light only: no camera shading, sheen, highlight or texture. Mascara stays a camera-shaded pigment.
    '  if (linerA > 0.002) col = mix(col, uLinerAlbedo * uLightColor * uExposure, linerA);',
    // Brow, as a real product leaves it (no generated strands, no flat cover): 1) pencil/powder, a
    // translucent film over skin and hair inside the feathered brow shape, never brighter than the camera;
    // 2) brow mascara, only on hairs (darker than the bare skin just outside the brow): the camera
    // brightness keeps each hair, the chromaticity moves to the product's, and a dark hair lifts a little
    // toward a lighter shade. Hex unchanged (1-1).
    '  if (browA > 0.002) {',
    '    float camL = lum(cam);',
    '    vec2 bpx = suv / uTexel;',
    '    float selB = step(distance(bpx, 0.5 * (uBrowHead[1] + uBrowTail[1]) / uTexel), distance(bpx, 0.5 * (uBrowHead[0] + uBrowTail[0]) / uTexel));',
    '    float sBelow = 0.0; float sAbove = 0.0;',
    '    sBelow += lum(toLin(texture2D(uVideo, mix(uBrowSkin[0], uBrowSkin[6], selB)).rgb));',
    '    sBelow += lum(toLin(texture2D(uVideo, mix(uBrowSkin[1], uBrowSkin[7], selB)).rgb));',
    '    sBelow += lum(toLin(texture2D(uVideo, mix(uBrowSkin[2], uBrowSkin[8], selB)).rgb));',
    '    sAbove += lum(toLin(texture2D(uVideo, mix(uBrowSkin[3], uBrowSkin[9], selB)).rgb));',
    '    sAbove += lum(toLin(texture2D(uVideo, mix(uBrowSkin[4], uBrowSkin[10], selB)).rgb));',
    '    sAbove += lum(toLin(texture2D(uVideo, mix(uBrowSkin[5], uBrowSkin[11], selB)).rgb));',
    '    float skinRef = max(max(sBelow, sAbove) / 3.0, 1e-3);',
    '    float hairW = smoothstep(0.10, 0.45, 1.0 - camL / skinRef)',
    '      * (1.0 - smoothstep(0.85, 1.0, camL / max(uSkinMeanLum, 1e-3)));',
    '    col = mix(col, powder(cam, uBrowAlbedo), browA * uBrowPowder);',
    '    vec3 chromaP = uBrowAlbedo / max(dot(uBrowAlbedo, vec3(1.0)), 1e-4);',
    '    vec3 chromaC = cam / max(dot(cam, vec3(1.0)), 1e-4);',
    '    vec3 tinted = col * clamp(chromaP / max(chromaC, vec3(1e-4)), 0.0, 1.5);',
    '    float tL = max(lum(tinted), 1e-4);',
    '    float pL = lum(uBrowAlbedo * uLightColor * uExposure) * clamp(skinRef / max(uSkinMeanLum, 1e-3), 0.3, 1.2);',
    '    tinted *= mix(tL, max(tL, pL), uBrowLift) / tL;',
    '    col = mix(col, tinted, browA * hairW);',
    '  }',
    '  if (mascaraA > 0.002) col = mix(col, layer(cam, uMascaraAlbedo, uSkinMeanLum, 1.0), mascaraA);',
    '  if (lipM > 0.002) {',
    '    float core = smoothstep(0.5, 0.95, lipM);',
    '    float meanL = mix(max(uLipMeanLum, 1e-3), max(uSkinMeanLum, 1e-3), skinRefW);',
    '    float camL = max(lum(cam), 1e-4);',
    '    float hpAbs = camL - lN;',
    // Layering (AR_SPEC 6-5-3): camera = light × shading × bare-lip color. The lipstick only changes the
    // lip color, so multiply the camera pixel by (layered / bare) reflectance. Wrinkles, upper-lip
    // shade, lower-lip volume, light color, noise and blur all come from the real camera pixel.
    '    vec3 refCol = mix(uLipColor, uSkinColor, skinRefW);',
    '    vec3 rLip = max(refCol / max(uLightColor * uExposure, vec3(1e-3)), vec3(1e-3));',
    // Per-pixel bare lip: the mean lip reflectance with this pixel's own chromaticity. A redder upper
    // lip and a paler lower lip are both covered by the pigment, so the result is one lipstick color
    // (shaded by the camera) instead of the bare-lip color difference multiplied up.
    // Color direction from the 5-pixel mean: a single pixel's color noise, divided out here, came back
    // multiplied by the product/bare ratio.
    '    vec3 chromPx = camN / max(lum(camN), 1e-4);',
    '    vec3 chromLip = refCol / max(lum(refCol), 1e-4);',
    '    vec3 rPx = max(rLip * clamp(chromPx / max(chromLip, vec3(1e-3)), 0.25, 4.0), vec3(1e-3));',
    // Real lipstick sits unevenly: matte pigment collects in creases, gloss thins on ridges.
    '    float creaseW = clamp((wideL - camL) / (0.15 * meanL), -1.0, 1.0);',
    '    float smoothT = 1.0 - uLipRough;',
    '    float uneven = 1.0 + uCreaseCover * (max(creaseW, 0.0) * (1.0 - smoothT) - max(-creaseW, 0.0) * smoothT);',
    '    float cov = clamp(lipM * uLipCov * uneven, 0.0, 1.0);',
    // Coverage first moves the bare lip toward the product color; only the see-through share of the
    // film then tints it like the dye on white paper, by the dye's hue only (its brightness is already in
    // the mix above). Filtering by the full dye color darkened twice: a sheer nude made a red lip darker
    // (L* 43 vs 47, 10-25) and a sheer coral made a pale red lip darker than both (L* 50 → 41, 10-26).
    '    vec3 paint = mix(rPx, uLipAlbedo, cov);',
    '    vec3 filt = clamp(uLipAlbedo / uPaperWhite, 0.0, 1.0);',
    '    vec3 mixCol = paint * mix(vec3(1.0), filt / max(lum(filt), 1e-3), cov * uLipTranslucent);',
    // Light and shade come only from the camera and the light-driven lip form; no lightness or chroma
    // fixed by UV position (that drew the upper lip dark and the lower centre light whatever the light).
    '    vec3 ratio = clamp(mixCol / rPx, 0.0, uRatioMax);',
    // Chip hex is an estimate and often brighter than the real bullet: never lift the lip past bare × cap.
    '    float lumGain = dot(ratio * rPx, vec3(0.2126, 0.7152, 0.0722)) / max(lum(rPx), 1e-4);',
    // Pigment that covers the lip may lighten it (B1, 10-25: the cap left a thin film over dark lips);
    // the cap holds only for the uncovered, see-through share.
    '    float gainCap = mix(uRatioMax, uLumGainMax, uLipTranslucent * (1.0 - cov));',
    '    float gainScale = min(1.0, gainCap / max(lumGain, 1e-4));',
    '    ratio *= gainScale;',
    // Camera highlights are surface reflection, not lip color: take them out of the ratio, then keep
    // them by texture (matte dulls them, gloss keeps them). With no paint (cov 0) the pixel is unchanged.
    // Only real reflections: a desaturated peak over the local 3px mean (creases and ridges, kept by
    // every finish as surface detail), or a wide one far above the lip mean: the bare lip's wet shine,
    // which a matte pigment covers and a gloss keeps, so it counts by smoothness. A broadly brighter
    // (paler or lit) lower lip is diffuse shading, kept under the paint (device 10-25 white film).
    '    float hl = max(min(hlCap, max(hlPeak, hlWide * smoothT)), hlSpark * uHlSparkle) * core;',
    '    vec3 camDiffuse = cam * (1.0 - hl / camL);',
    // Texture detail: matte fills creases a little (pulls toward the local mean), gloss keeps them.
    '    float fill = 1.0 + (lN / camL - 1.0) * (1.0 - uLipDetailGain) * cov;',
    // Where pigment covers (coverage, every finish: the film's color is already mixed in mixCol) only
    // the camera's brightness (light, shade, creases) carries over. Per-channel ratios there multiplied
    // the camera's color noise (yellow-green speckle on a dark red lip under a nude, 10-25); the
    // uncovered share keeps the camera's own color.
    '    float opaqueW = cov * (1.0 - uLipTranslucent);',
    '    vec3 lumOnly = mixCol * gainScale * (lum(camDiffuse) / max(lum(rPx), 1e-4));',
    '    vec3 layered = mix(camDiffuse * ratio, lumOnly, cov) * clamp(fill, 0.6, 1.6);',
    // Opaque pigment hides the bare lip's own light/dark patches; the camera mixes those with real
    // shading, so under opaque paint the large-scale brightness swing is compressed (not removed):
    // upper-lip shade and lower-lip volume stay, a pale patch no longer glows through (10-25). Only
    // that low-pass part: the lip mean over 8 points at a share of the lip thickness (lip pixels only,
    // no skin or teeth). Fine creases ride on top untouched (compressing them too left a smooth
    // color sheet on flat selfies, 10-25).
    '    float sl = 0.0, sw = 0.0;',
    '    for (int k = 0; k < 8; k++) {',
    '      float a = float(k) * 0.785398;',
    '      vec2 q = suv + uTexel * uLowPx * vec2(cos(a), sin(a));',
    '      float w = outlineAt(q);',
    '      sl += w * min(lum(toLin(texture2D(uVideo, q).rgb)), uDiffuseCap * meanL); sw += w;',
    '    }',
    '    float sLow = sw > 1.0 ? sl / sw : lN;',
    '    float shadeRel = clamp(sLow / meanL, 0.15, 4.0);',
    '    layered *= pow(shadeRel, (uOpaqueShadeGamma - 1.0) * opaqueW);',
    // Skin under the outline is brighter because skin is lighter, not because it is lit more: opaque
    // paint on it takes the lip's base, so the line has no pale rim (sticker look, device 10-25).
    '    float skinW = (1.0 - smoothstep(mix(uSkinRed, uLipRed, 0.25), mix(uSkinRed, uLipRed, 0.75), redN)) * lipEdgeW * uRefine;',
    '    layered *= mix(1.0, min(1.0, meanL / max(uSkinMeanLum, 1e-3)), skinW * opaqueW);',
    // Volume: the paint follows the lip form under the estimated light (Lambert of the form normal
    // relative to the mesh), so it rounds off toward the line instead of a dark band (blurry close-ups
    // carry no camera shading of their own, 10-25). A weak light direction falls back to frontal.
    '    vec3 lV = normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf));',
    '    float form = max(dot(lipFormN, lV), 0.0) / max(dot(lipBaseN, lV), 0.2);',
    // SH9: the same ratio with the fitted irradiance; the floor is 0.2 of the irradiance toward the light, as 0.2 above is
    // of a Lambert peak of 1. A weak estimate falls back to the frontal Lambert ratio.
    '    if (uLightModel > 0.5) {',
    '      vec3 lF = normalize(vec3(0.0, 0.25, 1.0));',
    '      float formF = max(dot(lipFormN, lF), 0.0) / max(dot(lipBaseN, lF), 0.2);',
    '      float formSh = max(shE(lipFormN), 0.0) / max(shE(lipBaseN), 0.2 * max(shE(l), 1e-4));',
    '      form = mix(formF, formSh, uLightConf);',
    '    }',
    '    layered *= mix(1.0, clamp(form, 0.35, 1.0), uLipVolume * cov * uFormOn);',
    // Lip-centre highlight: brightness only (the color stays), a gaussian along the mouth axis around the
    // middle of the lips (landmarks 0 and 17), inside the lip body.
    '    float cd = dot(suv * uViewport - uLipCenter.xy, uLipCenter.zw) / max(uCenterHalf, 1.0);',
    '    layered *= 1.0 + uCenterHl * exp(-cd * cd) * smoothstep(0.6, 0.95, lipDepth) * cov * (1.0 - skinRefW);',
    // A light shade on a bright spot must stay that shade, not clip to white: soft knee on the peak
    // channel, whole color scaled (hue kept, light/dark order kept). Real speculars are added below.
    '    float pk = max(layered.r, max(layered.g, layered.b));',
    '    float pkSoft = pk < 0.7 ? pk : 0.7 + 0.3 * (1.0 - exp(-(pk - 0.7) / 0.3));',
    '    layered *= pkSoft / max(pk, 1e-4);',
    '    float smooth1 = smoothT;',
    '    float keepHl = mix(1.0, mix(uHlKeep.x, uHlKeep.y, smooth1), cov);',
    // Clear coat: GGX on the real mesh normal toward the estimated light, plus glints on lip ridges.
    '    float glint = max(hpAbs - uGlintThreshold * meanL, 0.0) * uLipGlint * smooth1 * smooth1;',
    '    float lightMix = max(uLightConf, uSpecFill);',
    '    float specPbr = ggx(n, l, v, uLipRough) * max(dot(n, l), 0.0) * uLightStrength * uExposure * uSkinRef * lightMix;',
    '    float peakMask = pow(max(dot(n, normalize(l + v)), 0.0), mix(28.0, 64.0, uLipRough)) * core;',
    // Broad glow and sheen: the smooth form, or part of the lip's own lines with it (wideDetail).
    '    vec3 lipMidN = uWideDetail > 0.0 ? normalize(mix(lipFormN, lipDetailN, uWideDetail)) : lipFormN;',
    '    float sheen = pow(max(dot(lipMidN, normalize(l + v)), 0.0), mix(4.0, 10.0, smooth1)) * smooth1 * smooth1 * uLipSheen * lightMix * core;',
    // Finish highlight on the lip form: GGX at the finish's roughness, the light's color and strength,
    // capped from a matte's faint sheen to a gloss's near-white streak. Lands where the form faces the
    // half vector: lower-lip centre and upper-lip ridge under frontal light, shifting with the light.
    // A gloss reflects the light source itself, so its peak follows the scene's brightness (skin
    // luminance), not the diffuse light-strength fit (0.06–0.56 on LaPa: the gloss vanished).
    '    float glossCap = mix(uGlossMax.x, uGlossMax.y, smooth1 * smooth1 * smooth1) * mix(0.25, uSkinMeanLum, uGlossShape.z) * uGlossGain;',
    // Two lobes, each the GGX shape at the finish roughness widened by a light size, peak-normalized:
    // the light source's own sharp reflection (a gloss's near-white spot) and the wide glow around it
    // (a satin's sheen). A rough finish makes both broad and alike. One lobe widened for a big light
    // read as satin on gloss (10-25, LaPa next to a real gloss).
    '    vec3 lG = normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf * uGlossShape.w));',
    // The sharp reflection sits on the lip's own lines (detail normal); the glow around it on lipMidN.
    // A selfie always has a soft frontal source too (phone screen, the room in front): with a strong
    // side key light no lip normal faces its half vector, but the gloss still catches the front.
    '    vec3 hK = normalize(lG + v), hF = normalize(vec3(0.0, 0.3, 1.0) + v);',
    '    float rS = sqrt(uLipRough * uLipRough + uLightSize.x * uLightSize.x);',
    '    float rW = sqrt(uLipRough * uLipRough + uLightSize.y * uLightSize.y);',
    '    vec3 mT = vec3(uLipCenter.zw, 0.0);',
    '    float sK = uGlossAniso > 0.0 ? lobeA(lipDetailN, mT, hK, rS, uGlossAniso) : lobeN(max(dot(lipDetailN, hK), 0.0), rS);',
    '    float sF = uGlossAniso > 0.0 ? lobeA(lipDetailN, mT, hF, rS, uGlossAniso) : lobeN(max(dot(lipDetailN, hF), 0.0), rS);',
    '    float wK = uGlossAniso > 0.0 ? lobeA(lipMidN, mT, hK, rW, uGlossAniso) : lobeN(max(dot(lipMidN, hK), 0.0), rW);',
    '    float wF = uGlossAniso > 0.0 ? lobeA(lipMidN, mT, hF, rW, uGlossAniso) : lobeN(max(dot(lipMidN, hF), 0.0), rW);',
    // The source's reflection has a defined edge (a window or panel is a shape, not a blur); the
    // smoother the finish, the crisper that edge.
    '    float edgeLo = mix(0.0, 0.3, smooth1 * smooth1);',
    '    float edgeHi = min(edgeLo + uGlossShape.x, 1.0);',
    '    float sharpK = smoothstep(edgeLo, edgeHi, sK), sharpF = smoothstep(edgeLo, edgeHi, sF);',
    '    float lobe = max(sharpK + uWideGloss * wK, uFrontGloss * (sharpF + uWideGloss * wF));',
    '    float formSpec = glossCap * lobe * core * uFormOn * mix(1.0, exp(-cd * cd), uGlossShape.y);',
    '    float camSpec = hl / max(meanL, 1e-3);',
    '    formSpec *= 1.0 + uGlossFlat * (1.0 - smoothstep(0.02, 0.12, camSpec)) * smooth1 * smooth1;',
    '    if (uGlossCavity > 0.0) { float cav = pow(clamp(camL / max(wideL, 1e-4), 0.3, 2.0), uGlossCavity); formSpec *= cav; sheen *= cav; }',
    '    float spec = (min(specPbr * uLipSpec * peakMask, uLipSpecMax) * (1.0 - uFormOn) + min(glint, 0.05) + sheen) * cov;',
    '    vec3 specTint = mix(uLipAlbedo, vec3(1.0), 0.16);',
    // Gloss is the color brightened toward the light: a clear coat (glossy) reflects the light's own
    // color, a pigmented satin or cream sheen stays the product color (no white band on satin lips).
    '    vec3 hue = uLipAlbedo / max(max(uLipAlbedo.r, max(uLipAlbedo.g, uLipAlbedo.b)), 1e-3);',
    '    float peakness = max(sharpK, sharpF);',
    '    vec3 sheenCol = mix(uLightColor, vec3(1.0), uGlossTone.y) * mix(hue, vec3(1.0), smooth1 * smooth1 * smooth1 * mix(uGlossTone.x, 1.0, peakness));',
    '    float fl = uLipFlake * flake(vUv, n, l, v) * uLightStrength * core;',
    '    col += layered + vec3(hl * keepHl) - cam + specTint * spec + vec3(fl) * lipM;',
    '    col += sheenCol * formSpec * cov * mix(vec3(1.0), vec3(1.0) - clamp(col, 0.0, 1.0), uGlossTone.z);',
    '  }',
    '  gl_FragColor = vec4(toSrgb(col), 1.0);',
    '}',
  ].join(NL);

  function createGLRenderer() {
    const opts = { alpha: false, antialias: false, premultipliedAlpha: false, depth: true };
    let gl = glCanvas.getContext('webgl2', opts);
    const version = gl ? 'webgl2' : 'webgl';
    if (!gl) gl = glCanvas.getContext('webgl', opts);
    if (!gl) return null;
    function shader(type, src) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader');
      return s;
    }
    function program(vs, fs, uniforms) {
      const p = gl.createProgram();
      gl.attachShader(p, shader(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || 'link');
      const u = {};
      for (const n of uniforms) u[n] = gl.getUniformLocation(p, n);
      return { p, u };
    }
    const bg = program(BG_VERT, BG_FRAG, ['uVideo']);
    const mesh = program(MESH_VERT, MESH_FRAG, ['uVideo', 'uMask', 'uViewport', 'uLightColor', 'uLightDir', 'uLightSH', 'uLightModel',
      'uLightStrength', 'uLightConf', 'uExposure', 'uLipMeanLum', 'uSkinMeanLum', 'uLipAlbedo', 'uLipCov',
      'uLipRough', 'uLipSpec', 'uLipFlake', 'uLipOn', 'uBlushAlbedo', 'uBlushCov', 'uBlushDyn', 'uBlushE0', 'uBlushR0', 'uBlushE1', 'uBlushR1', 'uBlushInner', 'uPearl', 'uShadowAlbedo', 'uShadowCov',
      'uShadowFlake', 'uShadowFlakeScale', 'uShadowFlakeDensity', 'uShadowSpec',
      'uLidSparkle', 'uLidGlitter', 'uLidGrainRad', 'uLidMinGrainPx', 'uLidOpen', 'uLidGlitterPower', 'uLidGlitterGain', 'uLidGlitterBase',
      'uLidShimmerBase', 'uLidSheen', 'uSpecMax', 'uFlakeDensity', 'uFlakeScale', 'uTexel', 'uLipRed', 'uSkinRed', 'uRefine', 'uLipDetailGain',
      'uLipGlint', 'uGlintThreshold', 'uDiffuseCap', 'uSkinRef',
      'uLipTranslucent', 'uMaskBias',
      'uSpecFill', 'uLipColor', 'uPaperWhite', 'uRatioMax', 'uLipSpecMax', 'uHlKeep',
      'uLumGainMax', 'uCreaseCover', 'uLipSheen',
      'uOutline', 'uOutlineRect', 'uOutlineSoft', 'uForm', 'uFormStep', 'uFormTilt', 'uLowPx', 'uLipVolume', 'uFormOn', 'uGlossMax', 'uLightSize', 'uWideGloss', 'uMouthN', 'uGlossGain', 'uFrontGloss', 'uGlossFlat', 'uGlossShape', 'uGlossTone',
      'uHlLocal', 'uHlSat', 'uHlBlown', 'uOpaqueShadeGamma', 'uLipFill', 'uLipDetail', 'uDetailNoise', 'uHlSparkle', 'uWideDetail', 'uGlossAniso', 'uGlossCavity', 'uInner', 'uTeethReach', 'uTeethRed', 'uTeethBright', 'uTeethFirm', 'uTeethOn', 'uMouthOpen',
      'uTeethGuard', 'uTeethSat', 'uTeethDark',
      'uShadow2Albedo', 'uShadow2Cov', 'uInnerAlbedo', 'uInnerCov', 'uMask3', 'uHlAreas', 'uHlLegacy', 'uSkinColor',
      'uLipCenter', 'uCenterHalf', 'uCenterHl', 'uMask2', 'uHlAlbedo', 'uHlCov', 'uHlFlake', 'uContourAlbedo', 'uContourCov', 'uVolume', 'uVolLight', 'uFaceRough', 'uFaceSheen', 'uEyeHole', 'uCap', 'uCapFade', 'uPowderTint', 'uJawCap', 'uJawCullOn', 'uJawYaw',
      'uEye', 'uEyeRect', 'uLinerAlbedo', 'uLinerCov', 'uLinerAA', 'uLinerSoft', 'uMascaraAlbedo', 'uMascaraCov', 'uEyeSoft',
      'uFoundAlbedo', 'uFoundCov', 'uFoundOpaque', 'uFoundShadeMax', 'uFoundHair', 'uFoundTone', 'uFoundSkin', 'uFoundSkinOn', 'uFoundFloor', 'uFoundLowerV', 'uOccOn', 'uOccGate', 'uBrowAlbedo', 'uBrowCov', 'uBrowPowder', 'uBrowLift', 'uBrowSoft', 'uBrowSkin', 'uBrowHead', 'uBrowTail']);
    const bgPos = gl.getAttribLocation(bg.p, 'aPos');
    const aPos = gl.getAttribLocation(mesh.p, 'aPos');
    const aUv = gl.getAttribLocation(mesh.p, 'aUv');
    const aNormal = gl.getAttribLocation(mesh.p, 'aNormal');
    const aLidM = gl.getAttribLocation(mesh.p, 'aLidM');

    function buffer(target, data, usage) {
      const b = gl.createBuffer();
      gl.bindBuffer(target, b);
      gl.bufferData(target, data, usage);
      return b;
    }
    const quadBuf = buffer(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const posBuf = buffer(gl.ARRAY_BUFFER, meshPos, gl.DYNAMIC_DRAW);
    const nrmBuf = buffer(gl.ARRAY_BUFFER, meshNrm, gl.DYNAMIC_DRAW);
    const lidMBuf = buffer(gl.ARRAY_BUFFER, lidMetric, gl.DYNAMIC_DRAW);
    const uvBuf = buffer(gl.ARRAY_BUFFER, new Float32Array(FACE_UV), gl.STATIC_DRAW);
    const idxBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(FACE_TRIANGLES), gl.STATIC_DRAW);
    const mouthBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(FACE_MOUTH_TRIANGLES), gl.STATIC_DRAW);
    const eyeHoleBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(EYE_HOLE_TRIANGLES), gl.STATIC_DRAW);
    const capPosBuf = buffer(gl.ARRAY_BUFFER, capPos, gl.DYNAMIC_DRAW);
    const capNrmBuf = buffer(gl.ARRAY_BUFFER, capNrm, gl.DYNAMIC_DRAW);
    const capUvBuf = buffer(gl.ARRAY_BUFFER, capUv, gl.STATIC_DRAW);
    const capIdxBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(capIdx), gl.STATIC_DRAW);
    const jawPosBuf = buffer(gl.ARRAY_BUFFER, jawPos, gl.DYNAMIC_DRAW);
    const jawNrmBuf = buffer(gl.ARRAY_BUFFER, jawNrm, gl.DYNAMIC_DRAW);
    const jawUvBuf = buffer(gl.ARRAY_BUFFER, jawUv, gl.STATIC_DRAW);
    const jawIdxBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(jawIdx), gl.STATIC_DRAW);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);

    const videoTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    const maskTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, maskTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, masks.size, masks.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, masks.rgba);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Highlighter (R) and contour (G) UV masks, painted once.
    const mask2Tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, mask2Tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, masks.size, masks.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, masks.rgba2);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Selectable highlighter areas (mask 3), painted once.
    const mask3Tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE6);
    gl.bindTexture(gl.TEXTURE_2D, mask3Tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, masks.size, masks.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, masks.rgba3);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Screen-space eye canvas (eyeliner, mascara), refreshed every frame they are on.
    const eyeTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE5);
    gl.bindTexture(gl.TEXTURE_2D, eyeTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Blurred lip form field, refreshed with the outline.
    const formTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE4);
    gl.bindTexture(gl.TEXTURE_2D, formTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Screen-space lip outline crop, refreshed every frame from outlineCanvas.
    const outlineTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE3);
    gl.bindTexture(gl.TEXTURE_2D, outlineTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    const foundSkinTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE7);
    gl.bindTexture(gl.TEXTURE_2D, foundSkinTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    let lost = false;
    // The GL resources are not rebuilt in place: tell the app, which restarts this page (a fresh page is the clean recovery).
    glCanvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost = true; post({ type: 'crash', reason: 'webgl context lost' }); });

    function attrib(loc, buf, size) {
      if (loc < 0) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    }
    function disableAll() {
      for (const loc of [bgPos, aPos, aUv, aNormal, aLidM]) if (loc >= 0) gl.disableVertexAttribArray(loc);
      if (aLidM >= 0) gl.vertexAttrib3f(aLidM, 1, 0, 1);
    }
    function material(zone) {
      return MATERIALS[zone && zone.texture] || MATERIALS.matte;
    }
    function shadowFinish(zone) {
      if (!zone) return SHADOW_FINISHES.matte;
      const g = zone.geometry || {};
      if (SHADOW_FINISHES[g.shadowFinish]) return SHADOW_FINISHES[g.shadowFinish];
      if (g.sparkle != null && g.sparkle <= 0) return SHADOW_FINISHES.matte;
      if (zone.texture === 'shimmer') return SHADOW_FINISHES.shimmer;
      if (zone.texture === 'glossy') return SHADOW_FINISHES.glossy;
      return SHADOW_FINISHES.matte;
    }

    return {
      name: version,
      get lost() { return lost; },
      // Snapshot the current camera frame before detection, so image and landmarks are the same frame.
      upload() {
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, videoTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
      },
      uploadFoundSkin(pixels, w, h) {
        if (lost) return;
        gl.activeTexture(gl.TEXTURE7);
        gl.bindTexture(gl.TEXTURE_2D, foundSkinTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      },
      render(W, H, checkCommand, checkRestore) {
        if (glCanvas.width !== W || glCanvas.height !== H) { glCanvas.width = W; glCanvas.height = H; }
        gl.viewport(0, 0, W, H);
        gl.disable(gl.SCISSOR_TEST);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, videoTex);

        // 1. Camera image (mirrored).
        disableAll();
        gl.disable(gl.DEPTH_TEST);
        gl.useProgram(bg.p);
        gl.uniform1i(bg.u.uVideo, 0);
        attrib(bgPos, quadBuf, 2);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        // Comparison (before | after): the left half stays the camera image, the makeup is drawn on the right half only.
        if (compare) {
          gl.enable(gl.SCISSOR_TEST);
          gl.scissor(Math.floor(W / 2), 0, W - Math.floor(W / 2), H);
        }

        const lip = makeup.lip, blush = makeup.blush, eye = makeup.eyeshadow;
        const liner = makeup.eyeliner || null;
        const browZ = makeup.brow || null;
        const foundZ = makeup.foundation || null;
        // Mascara paints on celebrity/style looks. Explore chips never set it.
        const mascara = makeup.mascara || null;
        const hl = makeup.highlighter || null;
        const contourZ = makeup.contour || null;
        if (!hasFace) return false;
        if (TUNING.faceFit && (hl || contourZ)) {
          faceFitStep(performance.now());
          const hlStyle = hl && hl.geometry && hl.geometry.hlStyle || '';
          const coStyle = contourZ && contourZ.geometry && contourZ.geometry.contourStyle || '';
          const key = hlStyle + '|' + coStyle + '|' + (faceFitState ? faceFitState.rec.join() : 'none');
          if (key !== faceFitKey && masks && masks.repaintHlContour) {
            faceFitKey = key;
            masks.repaintHlContour(hlStyle, coStyle, faceFitState ? faceFitState.fit : null);
            gl.activeTexture(gl.TEXTURE2);
            gl.bindTexture(gl.TEXTURE_2D, mask2Tex);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, masks.size, masks.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, masks.rgba2);
            gl.generateMipmap(gl.TEXTURE_2D);
            gl.activeTexture(gl.TEXTURE0);
          }
        }
        if (!(lip || blush || eye || liner || browZ || foundZ || mascara || hl || contourZ)) {
          if ((checkCommand || checkRestore) && gl.getError() !== gl.NO_ERROR) throw new Error('AR render failed');
          return !!checkRestore;
        }

        gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, meshPos);
        gl.bindBuffer(gl.ARRAY_BUFFER, nrmBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, meshNrm);

        // 2. Face mesh with makeup; depth test keeps the near side when the head turns.
        gl.enable(gl.DEPTH_TEST);
        gl.depthFunc(gl.LESS);
        gl.clear(gl.DEPTH_BUFFER_BIT);
        disableAll();
        gl.useProgram(mesh.p);
        attrib(aPos, posBuf, 3);
        attrib(aUv, uvBuf, 2);
        attrib(aNormal, nrmBuf, 3);
        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, maskTex);
        const u = mesh.u;
        gl.activeTexture(gl.TEXTURE2);
        gl.bindTexture(gl.TEXTURE_2D, mask2Tex);
        gl.uniform1i(u.uMask2, 2);
        const innerPt = eye && eye.geometry && eye.geometry.innerPoint ? eye.geometry.innerPoint : null;
        const eyesOn = liner || mascara || innerPt || browZ ? drawEyes(W, H, liner, mascara, eye, browZ) : false;
        gl.activeTexture(gl.TEXTURE5);
        gl.bindTexture(gl.TEXTURE_2D, eyeTex);
        if (eyesOn) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, eyeCanvas);
        gl.uniform1i(u.uEye, 5);
        if (eyesOn) gl.uniform4f(u.uEyeRect, eyeRect[0], eyeRect[1], eyeRect[2], eyeRect[3]);
        else gl.uniform4f(u.uEyeRect, -2, -2, 1, 1);
        gl.uniform1f(u.uEyeHole, 0);
        gl.uniform1f(u.uCap, 0);
        gl.uniform1f(u.uJawCap, 0);
        // With the skin mask the hairline is cut per pixel, so the cap's own top fade moves up out of the visible forehead.
        gl.uniform1f(u.uCapFade, foundZ && foundSkinReady ? TUNING.foundCapFadeMasked : TUNING.foundCapFade);
        gl.uniform1f(u.uEyeSoft, Math.max(0.6, 0.9 * light.blur));
        const hlMat = material(hl), blushMat = material(blush);
        const hlAlb = hl ? hexToLinear(hl.hex) : [0, 0, 0], contourAlb = contourZ ? hexToLinear(contourZ.hex) : [0, 0, 0];
        const linerAlb = liner ? hexToLinear(liner.hex) : [0, 0, 0], mascaraAlb = mascara ? hexToLinear(mascara.hex) : [0, 0, 0];
        const eyeAlb2 = eye && eye.hexTo ? hexToLinear(eye.hexTo) : [0, 0, 0];
        gl.uniform3f(u.uShadow2Albedo, eyeAlb2[0], eyeAlb2[1], eyeAlb2[2]);
        gl.uniform1f(u.uShadow2Cov, eye && eye.hexTo ? clamp01(eye.intensity) * TUNING.shadow2Coverage : 0);
        const innerAlb = innerPt ? hexToLinear(innerPt.hex) : [0, 0, 0];
        gl.uniform3f(u.uInnerAlbedo, innerAlb[0], innerAlb[1], innerAlb[2]);
        gl.uniform1f(u.uInnerCov, innerPt ? clamp01(innerPt.a1) : 0);
        gl.activeTexture(gl.TEXTURE6);
        gl.bindTexture(gl.TEXTURE_2D, mask3Tex);
        gl.uniform1i(u.uMask3, 6);
        const hlAreas = hl && hl.geometry && hl.geometry.areas;
        const hasArea = (name) => (hlAreas && hlAreas.indexOf(name) >= 0 ? 1 : 0);
        gl.uniform1f(u.uHlLegacy, hlAreas ? 0 : 1);
        gl.uniform4f(u.uHlAreas, hasArea('forehead'), hasArea('nose_bridge'), hasArea('under_eye'), hasArea('chin'));
        gl.uniform3f(u.uHlAlbedo, hlAlb[0], hlAlb[1], hlAlb[2]);
        const hlGain = hl && hl.geometry && hl.geometry.intensity != null ? clamp01(hl.geometry.intensity) : 1;
        gl.uniform1f(u.uHlCov, hl ? clamp01(hl.intensity) * TUNING.hlCoverage * hlGain : 0);
        gl.uniform1f(u.uHlFlake, hl ? hlMat.flake * TUNING.shimmerFlake * clamp01(hl.intensity) : 0);
        gl.uniform3f(u.uContourAlbedo, contourAlb[0], contourAlb[1], contourAlb[2]);
        gl.uniform2f(u.uVolume, TUNING.hlContourVolume ? TUNING.volumeGain[0] : 0, TUNING.hlContourVolume ? TUNING.volumeGain[1] : 0);
        gl.uniform1f(u.uVolLight, TUNING.volumeLight);
        const jawShade = !!(contourZ && contourZ.geometry && contourZ.geometry.contourStyle === 'jawline');
        gl.uniform1f(u.uContourCov, contourZ ? clamp01(contourZ.intensity) * (jawShade ? 0.85 : TUNING.contourCoverage) : 0);
        const eyeFinish = shadowFinish(eye);
        gl.uniform3f(u.uFaceRough, blushMat.roughness, eyeFinish.roughness, hlMat.roughness);
        gl.uniform1f(u.uFaceSheen, TUNING.faceSheen);
        gl.uniform1f(u.uPowderTint, jawShade ? 0.32 : TUNING.powderTint);
        gl.uniform3f(u.uLinerAlbedo, linerAlb[0], linerAlb[1], linerAlb[2]);
        const linerGeo = liner ? Object.assign({}, TUNING.liner, liner.geometry || {}) : null;
        gl.uniform1f(u.uLinerCov, liner ? EYELINER_DARK.opacity : 0);
        gl.uniform1f(u.uLinerAA, 0.5);
        gl.uniform1f(u.uLinerSoft, liner ? clamp01(linerGeo.linerSoftness || 0) : 0);
        gl.uniform3f(u.uMascaraAlbedo, mascaraAlb[0], mascaraAlb[1], mascaraAlb[2]);
        gl.uniform1f(u.uMascaraCov, mascara ? 0.5 + 0.45 * clamp01(mascara.intensity) : 0);
        const foundAlb = foundZ ? hexToLinear(foundZ.hex) : [0, 0, 0];
        gl.uniform3f(u.uFoundAlbedo, foundAlb[0], foundAlb[1], foundAlb[2]);
        const foundC = foundZ ? clamp01(foundZ.intensity) : 0;
        const span = (r) => r[0] + (r[1] - r[0]) * foundC;
        gl.uniform1f(u.uFoundCov, foundZ ? span(TUNING.foundCoverage) : 0);
        gl.uniform1f(u.uFoundOpaque, span(TUNING.foundOpaque));
        gl.uniform1f(u.uFoundShadeMax, TUNING.foundShadeMax);
        gl.uniform2f(u.uFoundHair, TUNING.foundHair[0], TUNING.foundHair[1]);
        gl.uniform2f(u.uFoundTone, TUNING.foundTone[0], TUNING.foundTone[1]);
        gl.activeTexture(gl.TEXTURE7);
        gl.bindTexture(gl.TEXTURE_2D, foundSkinTex);
        gl.uniform1i(u.uFoundSkin, 7);
        const jawCapOn = !!(contourZ && contourZ.geometry && contourZ.geometry.contourStyle === 'jawline');
        const jawSpan = Math.max(1e-4, Math.abs(sx[234] - sx[454]));
        const jawYaw = (sz[234] - sz[454]) / jawSpan;
        gl.uniform1f(u.uJawCullOn, jawCapOn ? (jawAb === 2 ? 2 : 1) : 0);
        gl.uniform1f(u.uJawYaw, jawYaw);
        gl.uniform1f(u.uFoundSkinOn, (foundZ || jawCapOn) && foundSkinReady ? 1 : 0);
        gl.uniform1f(u.uFoundFloor, foundZ && foundSkinReady ? TUNING.foundLowerFloor * foundOcc : 0);
        gl.uniform2f(u.uFoundLowerV, TUNING.foundLowerV[0], TUNING.foundLowerV[1]);
        const occOn = TUNING.makeupOcclusion && foundSkinReady && occMakeupOn();
        gl.uniform1f(u.uOccOn, occOn ? 1 : 0);
        gl.uniform3f(u.uOccGate, occOn ? occGate.lip : 1, occOn ? occGate.eye : 1, occOn ? occGate.cheek : 1);
        const browAlb = browZ ? hexToLinear(browZ.hex) : [0, 0, 0];
        gl.uniform3f(u.uBrowAlbedo, browAlb[0], browAlb[1], browAlb[2]);
        gl.uniform1f(u.uBrowCov, browZ ? clamp01(browZ.intensity) * EYEBROW_PRESET.baseOpacity : 0);
        gl.uniform1f(u.uBrowPowder, EYEBROW_PRESET.powder);
        gl.uniform1f(u.uBrowLift, EYEBROW_PRESET.lift);
        if (browZ) {
          const bg = browGuides(W, H);
          gl.uniform2fv(u.uBrowSkin, bg.skin);
          gl.uniform2fv(u.uBrowHead, bg.head);
          gl.uniform2fv(u.uBrowTail, bg.tail);
          gl.uniform1f(u.uBrowSoft, Math.max(1, EYEBROW_PRESET.softness * bg.height));
        } else gl.uniform1f(u.uBrowSoft, 1);
        const outlineOn = lip ? drawLipOutline(W, H, lip.geometry) : false;
        gl.activeTexture(gl.TEXTURE3);
        gl.bindTexture(gl.TEXTURE_2D, outlineTex);
        if (outlineOn) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, outlineCanvas);
        gl.uniform1i(u.uOutline, 3);
        // No outline (no lip shade) → rect off screen, so outlineAt is 0 everywhere.
        if (outlineOn) gl.uniform4f(u.uOutlineRect, outlineRect[0], outlineRect[1], outlineRect[2], outlineRect[3]);
        else gl.uniform4f(u.uOutlineRect, -2, -2, 1, 1);
        // Outline edge as soft as the camera's own blur; volume reach a share of this lip's thickness.
        gl.uniform1f(u.uOutlineSoft, clamp(TUNING.lipEdgeBlurK * light.blur, 0.5, TUNING.lipEdgeSoftMax));
        gl.activeTexture(gl.TEXTURE4);
        gl.bindTexture(gl.TEXTURE_2D, formTex);
        if (outlineOn && TUNING.lipForm) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, formCanvas);
        gl.uniform1i(u.uForm, 4);
        gl.uniform2f(u.uFormStep, formStep[0], formStep[1]);
        gl.uniform1f(u.uFormTilt, TUNING.formTilt);
        gl.uniform1f(u.uLowPx, Math.max(3, TUNING.lowReach * 0.5 * (lipThick.up + lipThick.low)));
        gl.uniform1f(u.uLipVolume, TUNING.lipVolume);
        gl.uniform1f(u.uFormOn, TUNING.lipForm ? 1 : 0);
        gl.uniform2f(u.uGlossMax, TUNING.glossMax[0], TUNING.glossMax[1]);
        if (TUNING.lightModel === 'sh9') {
          const sizeK = 1 + TUNING.lightShSizeSpread * (1 - 2 * clamp(light.shDirectional, 0, 1));
          gl.uniform2f(u.uLightSize, TUNING.lightSize[0] * sizeK, TUNING.lightSize[1] * sizeK);
        } else {
          gl.uniform2f(u.uLightSize, TUNING.lightSize[0], TUNING.lightSize[1]);
        }
        gl.uniform1f(u.uWideGloss, TUNING.wideGloss);
        gl.uniform3f(u.uMouthN, mouthN[0], mouthN[1], mouthN[2]);
        gl.uniform1f(u.uGlossGain, TUNING.glossGain);
        gl.uniform1f(u.uFrontGloss, TUNING.frontGloss);
        gl.uniform1f(u.uGlossFlat, TUNING.glossFlat);
        gl.uniform4f(u.uGlossShape, TUNING.glossShape[0], TUNING.glossShape[1], TUNING.glossShape[2], TUNING.glossShape[3]);
        gl.uniform3f(u.uGlossTone, TUNING.glossTone[0], TUNING.glossTone[1], TUNING.glossTone[2]);
        gl.uniform1f(u.uHlLocal, TUNING.hlLocal);
        gl.uniform1f(u.uHlBlown, TUNING.hlBlown);
        gl.uniform1f(u.uLipFill, TUNING.lipFill);
        gl.uniform1f(u.uTeethGuard, TUNING.lipTeethGuard && outlineOn && !mouthClosed() ? 1 : 0);
        gl.uniform2f(u.uTeethSat, TUNING.teethSat[0], TUNING.teethSat[1]);
        gl.uniform1f(u.uTeethDark, TUNING.teethDark);
        gl.uniform2f(u.uHlSat, TUNING.hlSat[0], TUNING.hlSat[1]);
        gl.uniform1f(u.uOpaqueShadeGamma, TUNING.opaqueShadeGamma);
        const lipMat = material(lip), eyeMat = material(eye);
        const lipAlb = lip ? hexToLinear(lip.hex) : [0, 0, 0];
        const blushAlb = blush ? hexToLinear(blush.hex) : [0, 0, 0];
        const eyeAlb = eye ? hexToLinear(eye.hex) : [0, 0, 0];
        const shown = glideLight(performance.now());
        const exposure = shown.exposure;
        gl.uniform1i(u.uVideo, 0);
        gl.uniform1i(u.uMask, 1);
        gl.uniform2f(u.uViewport, W, H);
        gl.uniform3f(u.uLightColor, shown.color[0], shown.color[1], shown.color[2]);
        if (TUNING.lightDirGlide) {
          gl.uniform3f(u.uLightDir, shown.dir[0], shown.dir[1], shown.dir[2]);
          gl.uniform1f(u.uLightStrength, shown.strength);
          gl.uniform1f(u.uLightConf, shown.conf);
        } else {
          gl.uniform3f(u.uLightDir, light.dir[0], light.dir[1], light.dir[2]);
          gl.uniform1f(u.uLightStrength, light.strength);
          gl.uniform1f(u.uLightConf, light.dirConf);
        }
        gl.uniform1f(u.uLightModel, TUNING.lightModel === 'sh9' && TUNING.lightShVolume ? 1 : 0);
        gl.uniform1fv(u.uLightSH, TUNING.lightDirGlide ? shown.sh : light.sh);
        gl.uniform1f(u.uExposure, exposure);
        gl.uniform1f(u.uLipMeanLum, light.lipMeanLum);
        gl.uniform1f(u.uSkinMeanLum, shown.skinMeanLum);
        gl.uniform3f(u.uLipAlbedo, lipAlb[0], lipAlb[1], lipAlb[2]);
        gl.uniform1f(u.uLipCov, lip ? lipCoverage(lip, lipMat) : 0);
        gl.uniform1f(u.uLipRough, lipMat.roughness);
        gl.uniform1f(u.uLipSpec, lipMat.specular);
        gl.uniform1f(u.uLipFlake, lip ? lipMat.flake * TUNING.shimmerFlake * clamp01(lip.intensity) : 0);
        gl.uniform1f(u.uLipOn, lipEffectEnabled(lip) ? 1 : 0);
        gl.uniform3f(u.uBlushAlbedo, blushAlb[0], blushAlb[1], blushAlb[2]);
        gl.uniform1f(u.uBlushCov, blush ? clamp01(blush.intensity) * TUNING.blushCoverage : 0);
        const blushGeo = blush && blush.geometry;
        const blushDyn = !!(blushGeo && (blushGeo.blushPlacement || blushGeo.blushSize != null || blushGeo.blushSoftness != null));
        gl.uniform1f(u.uBlushDyn, blushDyn ? 1 : 0);
        if (blushDyn) {
          const sh = blushShape(blushGeo.blushPlacement || 'apple', clamp(blushGeo.blushSize == null ? 1 : blushGeo.blushSize, 0.4, 2.5));
          gl.uniform4f(u.uBlushE0, sh[0].e[0], sh[0].e[1], sh[0].e[2], sh[0].e[3]);
          gl.uniform3f(u.uBlushR0, sh[0].r[0], sh[0].r[1], sh[0].r[2]);
          gl.uniform4f(u.uBlushE1, sh[1].e[0], sh[1].e[1], sh[1].e[2], sh[1].e[3]);
          gl.uniform3f(u.uBlushR1, sh[1].r[0], sh[1].r[1], sh[1].r[2]);
          gl.uniform1f(u.uBlushInner, 1 - 0.9 * clamp01(blushGeo.blushSoftness == null ? 0.6 : blushGeo.blushSoftness));
        }
        gl.uniform3f(u.uShadowAlbedo, eyeAlb[0], eyeAlb[1], eyeAlb[2]);
        gl.uniform1f(u.uShadowCov, eye ? clamp01(eye.intensity) * eyeFinish.opacity : 0);
        const eg = eye && eye.geometry;
        gl.uniform1f(u.uShadowFlake, eye && eyeFinish.sparkleDensity > 0 ? clamp01(eye.intensity) : 0);
        const isGlitter = eyeFinish.sparkleDensity >= 0.7;
        const sparkle2 = TUNING.lidSparkle && eye && eyeFinish.sparkleDensity > 0;
        if (sparkle2) {
          const scale = isGlitter ? TUNING.lidGlitterScale : TUNING.lidShimmerScale;
          const lid = lidSparkleState(W, H);
          gl.bindBuffer(gl.ARRAY_BUFFER, lidMBuf);
          gl.bufferSubData(gl.ARRAY_BUFFER, 0, fillLidMetric(W, H, scale));
          attrib(aLidM, lidMBuf, 3);
          gl.uniform1f(u.uShadowFlakeScale, scale);
          gl.uniform1f(u.uShadowFlakeDensity, isGlitter ? TUNING.lidGlitterDensity : eyeFinish.sparkleDensity);
          gl.uniform1f(u.uLidOpen, lid.open);
          gl.uniform1f(u.uLidGlitter, isGlitter ? 1 : 0);
          gl.uniform1f(u.uLidGrainRad, TUNING.lidGrainRad[isGlitter ? 1 : 0]);
          gl.uniform1f(u.uLidMinGrainPx, TUNING.lidMinGrainPx);
          gl.uniform1f(u.uLidGlitterPower, TUNING.lidGlitterPower);
          gl.uniform1f(u.uLidGlitterGain, TUNING.lidGlitterGain);
          gl.uniform1f(u.uLidGlitterBase, TUNING.lidGlitterBase);
          gl.uniform1f(u.uLidShimmerBase, TUNING.lidShimmerBase);
          gl.uniform1f(u.uLidSheen, TUNING.lidSheen);
        } else {
          gl.uniform1f(u.uShadowFlakeScale, isGlitter ? TUNING.glitterScale : TUNING.shimmerScale);
          gl.uniform1f(u.uShadowFlakeDensity, eyeFinish.sparkleDensity);
        }
        gl.uniform1f(u.uLidSparkle, sparkle2 ? 1 : 0);
        gl.uniform1f(u.uShadowSpec, eyeFinish.specular);
        gl.uniform1f(u.uPearl, eg && eg.pearl ? clamp(eg.pearl, 0, 0.5) : 0);
        gl.uniform1f(u.uSpecMax, TUNING.specMax);
        gl.uniform1f(u.uFlakeDensity, TUNING.flakeDensity);
        gl.uniform1f(u.uFlakeScale, (eyeMat.flake || hlMat.flake || lipMat.flake) ? TUNING.flakeScaleShimmer : TUNING.flakeScale);
        gl.uniform2f(u.uTexel, 1 / W, 1 / H);
        gl.uniform1f(u.uLipRed, light.lipRed);
        gl.uniform1f(u.uSkinRed, light.skinRed);
        gl.uniform1f(u.uRefine, clamp((light.lipRed - light.skinRed - TUNING.refineMinContrast) / TUNING.refineMinContrast, 0, 1));
        gl.uniform1f(u.uLipDetailGain, lipMat.detail * TUNING.creaseGain);
        gl.uniform1f(u.uLipTranslucent, lipMat.translucent);
        gl.uniform1f(u.uMaskBias, Math.log2(Math.max(1, light.blur)));
        gl.uniform1f(u.uLipGlint, TUNING.lipGlint);
        gl.uniform1f(u.uGlintThreshold, TUNING.glintThreshold);
        gl.uniform1f(u.uDiffuseCap, TUNING.diffuseCap);
        gl.uniform1f(u.uSkinRef, TUNING.skinRefLum);
        gl.uniform1f(u.uSpecFill, TUNING.specFill);
        gl.uniform3f(u.uLipColor, light.lipColor[0], light.lipColor[1], light.lipColor[2]);
        gl.uniform3f(u.uSkinColor, light.skinColor[0], light.skinColor[1], light.skinColor[2]);
        const mAx = (sx[291] - sx[61]) * W, mAy = (sy[291] - sy[61]) * H, mLen = Math.hypot(mAx, mAy) || 1;
        gl.uniform4f(u.uLipCenter, ((sx[0] + sx[17]) / 2) * W, ((sy[0] + sy[17]) / 2) * H, mAx / mLen, mAy / mLen);
        gl.uniform1f(u.uCenterHalf, TUNING.lipCenterWidth * mLen);
        const [dPx0, dPx1] = TUNING.lipDetailMouthPx;
        const dSize = clamp01((mLen - dPx0) / (dPx1 - dPx0));
        gl.uniform1f(u.uLipDetail, TUNING.lipDetail * TUNING.lipDetailTilt * dSize * dSize * (3 - 2 * dSize));
        const dGrain = Math.max(light.grain, TUNING.lipDetailGrainMin);
        gl.uniform2f(u.uDetailNoise, TUNING.lipDetailNoise[0] * dGrain, TUNING.lipDetailNoise[1] * dGrain);
        gl.uniform1f(u.uHlSparkle, TUNING.hlSparkle);
        gl.uniform1f(u.uWideDetail, TUNING.wideDetail);
        gl.uniform1f(u.uGlossAniso, TUNING.glossAniso);
        gl.uniform1f(u.uGlossCavity, TUNING.glossCavity);
        gl.uniform1f(u.uTeethOn, TUNING.teeth && outlineOn ? 1 : 0);
        gl.uniform2fv(u.uInner, innerRingPx);
        gl.uniform1f(u.uTeethReach, Math.max(1, TUNING.teethReach * 0.5 * (lipThick.up + lipThick.low)));
        gl.uniform2f(u.uTeethRed, TUNING.teethRed[0], TUNING.teethRed[1]);
        gl.uniform2f(u.uTeethBright, TUNING.teethBright[0], TUNING.teethBright[1]);
        gl.uniform2f(u.uTeethFirm, TUNING.teethFirm[0], TUNING.teethFirm[1]);
        gl.uniform1f(u.uMouthOpen, mouthClosed() ? 0 : 1);
        gl.uniform1f(u.uCenterHl, lip && lip.geometry && lip.geometry.centerHighlight ? clamp(lip.geometry.centerHighlight, 0, 0.5) : 0);
        gl.uniform1f(u.uPaperWhite, TUNING.paperWhite);
        gl.uniform1f(u.uRatioMax, TUNING.ratioMax);
        gl.uniform1f(u.uLipSpecMax, TUNING.lipSpecMax);
        gl.uniform2f(u.uHlKeep, TUNING.hlKeep[0], TUNING.hlKeep[1]);
        gl.uniform1f(u.uLumGainMax, TUNING.lumGainMax);
        gl.uniform1f(u.uCreaseCover, TUNING.creaseCover);
        gl.uniform1f(u.uLipSheen, TUNING.lipSheen);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
        gl.drawElements(gl.TRIANGLES, FACE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        // The mouth hole too: the outline paints the thin gap of closed lips and leaves an open mouth
        // (teeth) unpainted along the smooth inner curve, not the mesh's straight hole edges.
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mouthBuf);
        gl.drawElements(gl.TRIANGLES, FACE_MOUTH_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        // Eye openings: only lashes overhang them.
        if (mascara && eyesOn) {
          gl.uniform1f(u.uEyeHole, 1);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, eyeHoleBuf);
          gl.drawElements(gl.TRIANGLES, EYE_HOLE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        }
        // Forehead cap (foundation only), last so its own attributes do not leak into the mesh draws.
        if (foundZ) {
          gl.uniform1f(u.uEyeHole, 0);
          gl.uniform1f(u.uCap, 1);
          gl.bindBuffer(gl.ARRAY_BUFFER, capPosBuf);
          gl.bufferSubData(gl.ARRAY_BUFFER, 0, capPos);
          gl.bindBuffer(gl.ARRAY_BUFFER, capNrmBuf);
          gl.bufferSubData(gl.ARRAY_BUFFER, 0, capNrm);
          attrib(aPos, capPosBuf, 3);
          attrib(aUv, capUvBuf, 2);
          attrib(aNormal, capNrmBuf, 3);
          if (aLidM >= 0) { gl.disableVertexAttribArray(aLidM); gl.vertexAttrib3f(aLidM, 1, 0, 1); }
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, capIdxBuf);
          gl.drawElements(gl.TRIANGLES, capIdx.length, gl.UNSIGNED_SHORT, 0);
          gl.uniform1f(u.uCap, 0);
        }
        if (jawCapOn && foundSkinReady && jawAb !== 1) {
          gl.uniform1f(u.uEyeHole, 0);
          gl.uniform1f(u.uJawCap, 1);
          gl.bindBuffer(gl.ARRAY_BUFFER, jawPosBuf);
          gl.bufferSubData(gl.ARRAY_BUFFER, 0, jawPos);
          gl.bindBuffer(gl.ARRAY_BUFFER, jawNrmBuf);
          gl.bufferSubData(gl.ARRAY_BUFFER, 0, jawNrm);
          attrib(aPos, jawPosBuf, 3);
          attrib(aUv, jawUvBuf, 2);
          attrib(aNormal, jawNrmBuf, 3);
          if (aLidM >= 0) { gl.disableVertexAttribArray(aLidM); gl.vertexAttrib3f(aLidM, 1, 0, 1); }
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, jawIdxBuf);
          if (jawYaw < 0.12 && jawHingeOn[0] > 0) gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);
          if (jawYaw > -0.12 && jawHingeOn[1] > 0) gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 12);
          gl.uniform1f(u.uJawCap, 0);
        }
        if ((checkCommand || checkRestore) && gl.getError() !== gl.NO_ERROR) throw new Error('AR render failed');
        return checkRestore ? (!lip || outlineOn) : !!lip && outlineOn;
      },
    };
  }

  // ── Debug HUD (double-tap) ───────────────────────────────────────────
  let hudOn = false;
  let lastTap = 0;
  let fps = 0, fpsFrames = 0, fpsAt = 0;
  let wbLocked = false, colorTempK = null, wbTrack = null, wbStartAt = 0;
  function toggleHud() {
    hudOn = !hudOn;
    hud.style.display = hudOn ? 'block' : 'none';
    if (!hudOn) overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  }
  // HUD only: landmark outer lip line (white) and camera-measured lip edge (green = trusted,
  // red = not found / outlier). Same size and mirroring as the WebGL canvas, so dots sit on the video.
  function drawLipPoints(W, H) {
    const r = Math.max(1.5, W / 400);
    const dot = (x, y, color) => {
      overlayCtx.fillStyle = color;
      overlayCtx.beginPath(); overlayCtx.arc((1 - x) * W, y * H, r, 0, Math.PI * 2); overlayCtx.fill();
    };
    for (const i of LIPS_OUTER) dot(sx[i], sy[i], 'rgba(255,255,255,0.9)');
    for (let k = 0; k < LIP_RAYS; k++) {
      const e = rayEnds(k), t = lipEdge.t[k];
      dot(e[0] + t * (e[2] - e[0]), e[1] + t * (e[3] - e[1]), lipEdge.conf[k] > 0.5 ? '#3cff6a' : '#ff4040');
    }
  }
  // HUD only: MediaPipe upper-lid polyline + indices (and lower lid dashed). Drawn with eyeliner off.
  // Same overlay space as drawLipPoints. Landmark points, not the fitted lash line.
  function drawEyeLinePoints(W, H) {
    const r = Math.max(2, W / 320);
    const fs = Math.max(10, Math.round(W / 55));
    const lw = Math.max(1.5, W / 400);
    const toScreen = (i) => [(1 - sx[i]) * W, sy[i] * H];
    overlayCtx.font = 'bold ' + fs + 'px sans-serif';
    overlayCtx.textAlign = 'center';
    overlayCtx.textBaseline = 'top';
    overlayCtx.lineJoin = 'round';
    overlayCtx.lineCap = 'round';
    for (const e of EYE_LINES) {
      const up = e.upper.map(toScreen);
      overlayCtx.strokeStyle = 'rgba(94,232,255,0.95)';
      overlayCtx.lineWidth = lw;
      overlayCtx.setLineDash([]);
      overlayCtx.beginPath();
      up.forEach((q, k) => { if (k) overlayCtx.lineTo(q[0], q[1]); else overlayCtx.moveTo(q[0], q[1]); });
      overlayCtx.stroke();
      overlayCtx.strokeStyle = 'rgba(255,180,80,0.75)';
      overlayCtx.lineWidth = lw * 0.8;
      overlayCtx.setLineDash([lw * 3, lw * 2]);
      overlayCtx.beginPath();
      e.lower.map(toScreen).forEach((q, k) => { if (k) overlayCtx.lineTo(q[0], q[1]); else overlayCtx.moveTo(q[0], q[1]); });
      overlayCtx.stroke();
      overlayCtx.setLineDash([]);
      overlayCtx.lineWidth = Math.max(2, W / 400);
      for (let k = 0; k < e.upper.length; k++) {
        const i = e.upper[k], q = up[k];
        overlayCtx.fillStyle = '#5ee8ff';
        overlayCtx.beginPath(); overlayCtx.arc(q[0], q[1], r, 0, Math.PI * 2); overlayCtx.fill();
        overlayCtx.strokeStyle = 'rgba(0,0,0,0.7)';
        overlayCtx.strokeText(String(i), q[0], q[1] + r + 1);
        overlayCtx.fillStyle = '#5ee8ff';
        overlayCtx.fillText(String(i), q[0], q[1] + r + 1);
      }
    }
  }
  // ── Drawing guide: dashed lines on the live face (AR_SPEC 6-5-11) ──
  // Computed from the filtered landmarks every frame, so the lines follow the face. Points are in the
  // same mirrored screen space as the WebGL canvas; text is drawn upright.
  const NOSE_WING = [129, 358];
  const EYE_CORNERS = [{ inner: 133, outer: 33, iris: 468 }, { inner: 362, outer: 263, iris: 473 }];
  function vsub(a, b) { return [a[0] - b[0], a[1] - b[1]]; }
  function vadd(a, b) { return [a[0] + b[0], a[1] + b[1]]; }
  function vmul(a, k) { return [a[0] * k, a[1] * k]; }
  function vunit(a) { const n = Math.hypot(a[0], a[1]) || 1; return [a[0] / n, a[1] / n]; }
  function drawGuide(W, H) {
    const ctx = overlayCtx;
    const P = (i) => [(1 - sx[i]) * W, sy[i] * H];
    const lw = Math.max(2, W / 260);
    const WHITE = 'rgba(255,255,255,0.95)', WARM = '#ffb347', PINK = '#ff7aa8';
    ctx.save();
    ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.shadowColor = 'rgba(0,0,0,0.55)'; ctx.shadowBlur = lw * 2;
    const path = (pts, color, dashed, close) => {
      ctx.setLineDash(dashed ? [lw * 3.2, lw * 2.4] : []);
      ctx.strokeStyle = color;
      ctx.beginPath();
      pts.forEach((q, i) => { if (i) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]); });
      if (close) ctx.closePath();
      ctx.stroke();
    };
    const arrow = (from, to, color) => {
      path([from, to], color, false, false);
      const d = vunit(vsub(to, from)), n = [-d[1], d[0]], h = lw * 3.6;
      path([vadd(to, vadd(vmul(d, -h), vmul(n, h * 0.6))), to, vadd(to, vadd(vmul(d, -h), vmul(n, -h * 0.6)))], color, false, false);
    };
    const dot = (q, color) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(q[0], q[1], lw * 1.8, 0, Math.PI * 2); ctx.fill(); };
    const label = (text, q, color) => {
      ctx.setLineDash([]);
      ctx.font = 'bold ' + Math.round(W / 30) + 'px sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.lineWidth = lw * 1.6; ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.strokeText(text, q[0], q[1]);
      ctx.fillStyle = color; ctx.fillText(text, q[0], q[1]);
      ctx.lineWidth = lw;
    };
    const step = guide.step;

    for (let k = 0; k < 2; k++) {
      const ids = EYE_CORNERS[k], eye = EYES[k];
      const inner = P(ids.inner), outer = P(ids.outer);
      const lidRaw = eye.lid.map(P);
      // Outer corner first, so index 0 is the tail side on both eyes.
      const lid = dist(lidRaw[0], outer) <= dist(lidRaw[lidRaw.length - 1], outer) ? lidRaw : lidRaw.slice().reverse();
      const mid = Math.floor(lid.length / 2);
      const browMid = P(eye.brow[2]);
      const eyeW = dist(inner, outer);
      const axis = vunit(vsub(outer, inner));
      let up = vsub(browMid, lid[mid]);
      up = vunit(vsub(up, vmul(axis, up[0] * axis[0] + up[1] * axis[1])));

      if (step === 'eyebrow') {
        // Classic three lines from the nose wing: through the inner eye corner (start), the pupil
        // (highest point) and the outer corner (end), carried up to the brow.
        const wing = P(NOSE_WING[k]);
        const browLow = eye.brow.map(P);
        const startY = P(eye.brow[4])[1], peakY = Math.min.apply(null, browLow.map((q) => q[1])), endY = P(eye.brow[0])[1];
        const carry = (through, y) => {
          const dy = through[1] - wing[1];
          const t = Math.abs(dy) < 1e-3 ? 1 : (y - wing[1]) / dy;
          return vadd(wing, vmul(vsub(through, wing), t));
        };
        const marks = [carry(inner, startY), carry(P(ids.iris), peakY), carry(outer, endY)];
        marks.forEach((m, i) => { path([wing, m], WHITE, true, false); dot(m, PINK); label(String(i + 1), vadd(m, vmul(up, eyeW * 0.28)), WHITE); });
        path([marks[0], marks[1], marks[2]], PINK, true, false);
      } else if (step === 'eyeshadow') {
        // Base: the whole lid up to the crease. Shade: the outer third, in a warmer line.
        // Lens shape: the crease rises from both corners and peaks over the middle of the lid.
        const crease = lid.map((q, i) => vadd(q, vmul(up, eyeW * 0.4 * Math.sin((Math.PI * i) / (lid.length - 1)))));
        path(lid.concat(crease.slice().reverse()), WHITE, true, true);
        const n3 = Math.max(3, Math.round(lid.length * 0.45));
        path(lid.slice(0, n3).concat(crease.slice(0, n3).reverse()), WARM, true, true);
      } else if (step === 'eyeliner') {
        const style = String(guide.style || 'classic_winged');
        const theta = ((Number(guide.angle) || 15) * Math.PI) / 180;
        const len = clamp(Number(guide.length) || 0.18, 0.05, 0.6) * eyeW;
        const dir = vadd(vmul(axis, Math.cos(theta)), vmul(up, Math.sin(theta)));
        const tip = vadd(outer, vmul(dir, len));
        if (style === 'tightline') {
          // Fill between the lashes: dots on the lid landmarks, then a thin short tail.
          lid.forEach((q, i) => { if (i % 2 === 0) dot(q, WHITE); });
          path([outer, tip], WARM, false, false);
          arrow(outer, tip, WARM);
        } else if (style === 'puppy') {
          // Follow the lid, then a soft drop at the outer corner (angle is negative).
          path(lid.slice().reverse(), WHITE, true, false);
          arrow(outer, tip, WARM);
          arrow(lerp(inner, outer, 0.35), lerp(inner, outer, 0.85), WHITE);
          label(Math.round(Number(guide.angle) || -8) + String.fromCharCode(176), vadd(tip, vmul(up, -eyeW * 0.18)), WARM);
        } else {
          path(lid.slice().reverse(), WHITE, true, false);
          path([outer, vadd(outer, vmul(axis, len * 1.25))], 'rgba(255,255,255,0.55)', true, false);
          arrow(outer, tip, WARM);
          // Drawing direction: from the inner corner toward the tail, drawn just above the lid.
          arrow(vadd(lerp(inner, outer, 0.25), vmul(up, eyeW * 0.4)), vadd(lerp(inner, outer, 0.72), vmul(up, eyeW * 0.4)), WHITE);
          label(Math.round(Number(guide.angle) || 15) + String.fromCharCode(176), vadd(tip, vmul(up, eyeW * 0.22)), WARM);
        }
      }
    }

    if (step === 'lip') {
      path(LIPS_OUTER.map(P), WHITE, true, true);
      path(LIPS_INNER.map(P), 'rgba(255,255,255,0.6)', true, true);
      // Fill from the outer line inward, staying on the lip (toward the inner line, not into the mouth).
      for (const i of [2, 4, 6, 8, 12, 14, 16, 18]) {
        const o = P(LIPS_OUTER[i]);
        arrow(o, lerp(o, P(LIPS_INNER[i]), 0.8), WARM);
      }
    }
    ctx.restore();
  }
  // One pass per frame on the overlay canvas: HUD points, then the guide.
  function drawOverlay(W, H) {
    if (overlay.width !== W || overlay.height !== H) { overlay.width = W; overlay.height = H; }
    overlayCtx.clearRect(0, 0, W, H);
    if (!hasFace) return;
    if (hudOn) { drawLipPoints(W, H); drawEyeLinePoints(W, H); }
    if (guide) drawGuide(W, H);
  }
  let viewZoom = 1;
  let pinchStartZoom = 1;
  let pinchStartDist = 0;
  let pinching = false;
  let pinchUsed = false;
  function pinchDist(touches) {
    return Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY);
  }
  function applyViewZoom() {
    const t = viewZoom <= 1.001 ? 'none' : ('scale(' + viewZoom + ')');
    canvas.style.transform = t;
    overlay.style.transform = t;
  }
  document.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 2) return;
    pinching = true;
    pinchUsed = true;
    pinchStartDist = Math.max(1, pinchDist(e.touches));
    pinchStartZoom = viewZoom;
    e.preventDefault();
  }, { passive: false });
  document.addEventListener('touchmove', (e) => {
    if (!pinching || e.touches.length !== 2) return;
    e.preventDefault();
    const d = Math.max(1, pinchDist(e.touches));
    viewZoom = clamp(pinchStartZoom * (d / pinchStartDist), TUNING.zoomMin, TUNING.zoomMax);
    applyViewZoom();
  }, { passive: false });
  function onPinchEnd(e) {
    if (e.touches.length < 2) pinching = false;
    if (pinchUsed) {
      if (e.touches.length === 0) pinchUsed = false;
      lastTap = 0;
      return;
    }
    const t = Date.now();
    if (t - lastTap < 300) toggleHud();
    lastTap = t;
  }
  document.addEventListener('touchend', onPinchEnd);
  document.addEventListener('touchcancel', onPinchEnd);
  document.addEventListener('dblclick', toggleHud);
  function updateHud() {
    if (!hudOn) return;
    const f = (v) => v.toFixed(2);
    hud.textContent = [
      'fps ' + fps + '  ' + (renderer ? renderer.name : '-') + '  face ' + landmarkerDelegate + '  zoom ' + viewZoom.toFixed(2) + 'x',
      'light rgb ' + light.color.map(f).join(' ') + '  conf ' + f(light.colorConf),
      'bg ' + f(light.bgFraction) + '  seg ' + (segmenter ? 'on' : 'off') + (TUNING.lightColorEdge ? '  edge w ' + f(light.colorEdgeW) : ''),
      'found ' + (makeup.foundation ? 'on ' + makeup.foundation.hex + ' ' + f(makeup.foundation.intensity || 0) : 'off') + '  mask ' + (foundSkinReady ? 'ready' : 'none') + '  skin cat ' + f(foundSkinStat.cat) + ' prob ' + f(foundSkinStat.prob) + '  lower floor ' + f(foundSkinReady ? TUNING.foundLowerFloor * foundOcc : 0) + '  seg call ' + foundSegMs.toFixed(0) + 'ms',
      'occ ' + (TUNING.makeupOcclusion ? 'on lip ' + f(occGate.lip) + ' eye ' + f(occGate.eye) + ' cheek ' + f(occGate.cheek) : 'off'),
      'dir ' + light.dir.map(f).join(' ') + '  conf ' + f(light.dirConf) + (TUNING.lightMatch ? '  match r2 ' + f(light.matchR2) : '  fit'),
      'light ms ' + lightMs.toFixed(1) + (TUNING.lightDirGlide ? '  glide on' : '') + (TUNING.lightModel === 'sh9' ? '  sh9 ' + (light.shUsed ? 'fit' : 'linear') : ''),
      'strength ' + f(light.strength) + '  lip ' + f(light.lipMeanLum) + '  skin ' + f(light.skinMeanLum),
      'mouth gap ' + f(Math.hypot(sx[13] - sx[14], sy[13] - sy[14]) / Math.max(1e-4, Math.hypot(sx[61] - sx[291], sy[61] - sy[291]))) + (mouthClosed() ? ' closed' : ' open'),
      'lip thick up ' + lipThick.up.toFixed(1) + 'px low ' + lipThick.low.toFixed(1) + 'px  /w ' + f(lipThick.upRatio) + ' ' + f(lipThick.lowRatio),
      'thick base ' + (lipThick.upBase ? f(lipThick.upBase) + ' ' + f(lipThick.lowBase) + '  now/base ' + f(lipThick.upRatio / lipThick.upBase) + ' ' + f(lipThick.lowRatio / lipThick.lowBase) : '- (close mouth, face front)'),
      'edge ' + (TUNING.lipEdgePx * lipThick.uvScale).toFixed(1) + 'px  band ' + (TUNING.lipBandPx * lipThick.uvScale).toFixed(1) + 'px  (share of up ' + f(TUNING.lipEdgePx * lipThick.uvScale / Math.max(1e-4, lipThick.up)) + ')',
      'real edge / landmark  up ' + f(lipEdge.up) + '  low ' + f(lipEdge.low) + (lipEdge.samples ? '' : '  (no lip/skin contrast)'),
      'lip inner ' + (TUNING.lipInnerMeasure ? (mouthClosed() ? 'closed' : 'inset ' + f(Array.from(lipInner.t).reduce((s, v, j) => s + (lipInner.conf[j] >= 0.5 ? v : 0), 0) / Math.max(1, Array.from(lipInner.conf).filter((c) => c >= 0.5).length)) + ' rays ' + Array.from(lipInner.conf).filter((c) => c >= 0.5).length) : 'off') + '  teeth guard ' + (TUNING.lipTeethGuard ? 'on' : 'off') + '  edge pull ' + (TUNING.lipEdgePull ? 'on' : 'off'),
      'lip outline ' + outlineCanvas.width + 'x' + outlineCanvas.height + '  form reach ' + (TUNING.formReach * 0.5 * (lipThick.up + lipThick.low)).toFixed(1) + 'px',
      'lip up/low ' + f(light.lipUpLow),
      'lip rgb ' + light.lipColor.map(f).join(' ') + '  red lip ' + f(light.lipRed) + '  skin ' + f(light.skinRed) + '  grain ' + f(light.grain) + '  blur ' + f(light.blur),
      'lid fit  eye33 ' + lidHud[0] + '  eye263 ' + lidHud[1] + '  ' + lidFitMs.toFixed(1) + 'ms',
      'lid sparkle ' + (TUNING.lidSparkle ? 'on' : 'off') + '  px/cell shimmer ' + (lidSparkle.pxPerUv / TUNING.lidShimmerScale).toFixed(1) + ' glitter ' + (lidSparkle.pxPerUv / TUNING.lidGlitterScale).toFixed(1) + '  open ' + f(lidSparkle.open),
      'wb ' + (wbLocked ? 'locked' : 'auto') + (colorTempK ? '  ' + colorTempK + 'K' : ''),
    ].join(NL);
  }

  // ── Main loop ────────────────────────────────────────────────────────
  // Runs once per new camera frame: upload → detect on that frame → draw.
  function processFrame(now) {
    if (video.readyState < 2) return;
    const W = video.videoWidth, H = video.videoHeight;
    if (!W || !H) return;
    if (renderer.lost) {
      if (pendingRender || pendingRestore) {
        post(Object.assign({ type: pendingRestore ? 'restore_result' : 'render_result', status: 'failed' }, pendingRestore || pendingRender));
        pendingRender = null; pendingRestore = null;
      }
      setStatus('unavailable', 'webgl context lost'); return;
    }
    try { renderer.upload(); } catch (e) {
      if (pendingRender || pendingRestore) {
        post(Object.assign({ type: pendingRestore ? 'restore_result' : 'render_result', status: 'failed' }, pendingRestore || pendingRender));
        pendingRender = null; pendingRestore = null;
      }
      return;
    }

    let faceThisFrame = false;
    if (landmarker) {
      try {
        const result = landmarker.detectForVideo(video, now);
        const face = result.faceLandmarks && result.faceLandmarks[0];
        if (face) {
          filterLandmarks(face, now / 1000);
          faceThisFrame = true;
          hasFace = true;
          lastFaceAt = now;
          setStatus('tracking');
        } else if (now - lastFaceAt > 700) {
          hasFace = false;
          lipThick.upBase = 0; lipThick.lowBase = 0;
          lipEdge.samples = 0; lipEdge.conf.fill(0);
          filterReady = false;
          resetLidFit();
          shownLight.t = 0;
          setStatus('no-face');
          if (lastLightHint) { lastLightHint = null; post({ type: 'light_hint', value: null }); }
        }
      } catch (e) { /* skip frame */ }
    }

    if (hasFace) {
      updateMesh(W, H);
      if (TUNING.lipInnerMeasure && makeup.lip) {
        try { measureLipInner(W, H, now); } catch (e) { /* inner line measurement is best-effort */ }
      }
      if (makeup.contour && makeup.contour.geometry && makeup.contour.geometry.contourStyle === 'jawline' && now - lastJawBandAt > 500) {
        lastJawBandAt = now;
        const jawMsg = { type: 'jaw_band', build: 'b6981e1', ab: jawAb, ids: '132,58,172', hinge: jawHingeOn[0] + '/' + jawHingeOn[1], reach: jawReach[0] + '/' + jawReach[1], cat: jawCat[0] + '/' + jawCat[1], dir: jawDir[0] + '/' + jawDir[1], dy: jawDy[0] + '/' + jawDy[1], rise: jawRise[0] + '/' + jawRise[1], endCat: jawEndCat[0] + '/' + jawEndCat[1], capUsed: 0.9, hingeMax: TUNING.jawHingeMax };
        post(jawMsg);
        if (jawdbg) { jawdbg.style.display = 'block'; jawdbg.textContent = 'b6981e1 ab ' + ['both', 'uv', 'cap'][jawAb] + ' tap\njaw h ' + jawMsg.hinge + ' r ' + jawMsg.reach + ' c ' + jawMsg.cat + ' d ' + jawMsg.dir; }
      }
      if (now - lastLightAt > TUNING.lightEveryMs) {
        lastLightAt = now;
        try { sampleScene(now, W, H); } catch (e) { /* light estimation is best-effort */ }
        maybeLockWhiteBalance();
        measureLipThickness(W, H);
        try { measureLipEdge(W, H); } catch (e) { /* edge measurement is best-effort */ }
        updateHud();
      }
    }
    if (wantSkinMask()) {
      const skinDue = now - lastFoundSegAt > (fps >= TUNING.segmentMinFps || !foundSkinReady ? TUNING.foundSegEveryMs : TUNING.foundSegEveryLowFpsMs);
      try { runSegmenter(now, false, skinDue); } catch (e) { /* skin mask is best-effort */ }
    } else { foundSkinReady = false; occGate.lip = occGate.eye = occGate.cheek = 1; }

    fpsFrames++;
    if (now - fpsAt >= 1000) { fps = fpsFrames; fpsFrames = 0; fpsAt = now; }

    try {
      const frameRendered = renderer.render(W, H, !!pendingRender, !!pendingRestore);
      if ((pendingRender || pendingRestore) && faceThisFrame && frameRendered && !renderer.lost) {
        post(Object.assign({ type: pendingRestore ? 'restore_result' : 'render_result', status: 'rendered' }, pendingRestore || pendingRender));
        pendingRender = null; pendingRestore = null;
      }
    } catch (e) {
      if (pendingRender || pendingRestore) {
        post(Object.assign({ type: pendingRestore ? 'restore_result' : 'render_result', status: 'failed' }, pendingRestore || pendingRender));
        pendingRender = null; pendingRestore = null;
      }
    }
    if (hudOn || guide) drawOverlay(W, H);
  }
  // Prefer requestVideoFrameCallback (fires once per camera frame, AR_SPEC 6-1); else poll with rAF.
  function onVideoFrame() {
    video.requestVideoFrameCallback(onVideoFrame);
    processFrame(performance.now());
  }
  function onAnimationFrame(now) {
    requestAnimationFrame(onAnimationFrame);
    if (video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;
    processFrame(now);
  }
  function startLoop() {
    if (typeof video.requestVideoFrameCallback === 'function') video.requestVideoFrameCallback(onVideoFrame);
    else requestAnimationFrame(onAnimationFrame);
  }

  async function matchTrackToScreen(track) {
    if (!track || !track.applyConstraints) return;
    try {
      await track.applyConstraints({ height: { ideal: 720, max: 960 } });
    } catch (e) { /* keep the opened mode */ }
  }
  async function openFrontCamera() {
    const tries = [
      { facingMode: 'user', height: { ideal: 720, max: 960 } },
      { facingMode: 'user' },
    ];
    let lastErr = null;
    for (let i = 0; i < tries.length; i++) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: tries[i], audio: false });
        const track = stream.getVideoTracks()[0];
        await matchTrackToScreen(track);
        return stream;
      } catch (e) {
        lastErr = e;
        if (e && (e.name === 'NotAllowedError' || e.name === 'SecurityError')) throw e;
      }
    }
    throw lastErr || new Error('getUserMedia failed');
  }

  async function createLandmarker(vision, files, delegate) {
    return vision.FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate },
      runningMode: 'VIDEO',
      numFaces: 1,
      minFaceDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
  }
  async function createSegmenter(vision, files, delegate) {
    return vision.ImageSegmenter.createFromOptions(files, {
      baseOptions: { modelAssetPath: SEG_MODEL_URL, delegate },
      runningMode: 'VIDEO',
      outputCategoryMask: true,
      outputConfidenceMasks: true, // class 3 (face skin) probability for the foundation mask: soft bangs edge instead of a hard 0/1 cut
    });
  }

  // Camera info (6-6-1 ③): read color temperature, lock white balance after auto WB settles. Optional.
  // One attempt per camera start, once the camera's auto white balance has settled on this room: a face is
  // tracked (this runs from the face branch) and the last background color estimate barely moved.
  function maybeLockWhiteBalance() {
    if (!wbTrack) return;
    const age = performance.now() - wbStartAt;
    if (age < TUNING.wbLockMinMs) return;
    const settled = light.colorSamples >= 2 && light.colorDelta < TUNING.wbStableDelta;
    if (!settled && age < TUNING.wbLockMaxMs) return;
    const track = wbTrack;
    wbTrack = null;
    tryLockWhiteBalance(track);
  }
  function tryLockWhiteBalance(track) {
    try {
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      const settings = track.getSettings ? track.getSettings() : {};
      if (settings.colorTemperature) colorTempK = settings.colorTemperature;
      if (caps.whiteBalanceMode && caps.whiteBalanceMode.indexOf('manual') >= 0) {
        // Pass the current temperature along: 'manual' alone can jump to a default temperature on some phones
        // instead of freezing the one the camera settled on.
        const wb = { whiteBalanceMode: 'manual' };
        const ct = caps.colorTemperature;
        if (colorTempK && (!ct || (colorTempK >= ct.min && colorTempK <= ct.max))) wb.colorTemperature = colorTempK;
        track.applyConstraints({ advanced: [wb] })
          .then(() => { wbLocked = true; })
          .catch(() => {});
      }
    } catch (e) { /* not supported */ }
  }

  async function start() {
    setStatus('loading');
    post({ type: 'hello' });
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('unavailable', 'getUserMedia not supported');
      return;
    }
    let stream;
    try {
      stream = await openFrontCamera();
      video.srcObject = stream;
      await video.play();
    } catch (e) {
      const name = e && e.name;
      setStatus(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable', String(e && e.message));
      return;
    }
    const track = stream.getVideoTracks()[0];
    wbLocked = false;
    wbTrack = track || null;
    wbStartAt = performance.now();

    let bootError = '';
    try {
      masks = paintMasks();
      renderer = createGLRenderer();
    } catch (e) {
      renderer = null;
      bootError = String(e && e.message || e);
    }
    if (!renderer) {
      setStatus('unavailable', bootError ? 'webgl ' + bootError : 'webgl unavailable');
      return;
    }
    startLoop();

    let vision, files;
    try {
      vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@' + VERSION + '/vision_bundle.mjs');
      files = await vision.FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@' + VERSION + '/wasm');
      try { landmarker = await createLandmarker(vision, files, 'GPU'); landmarkerDelegate = 'gpu'; }
      catch (e) { landmarker = await createLandmarker(vision, files, 'CPU'); landmarkerDelegate = 'cpu'; }
    } catch (e) {
      setStatus('unavailable', 'model: ' + String(e && e.message));
      return;
    }
    // Segmenter feeds light color and the foundation face-skin mask; AR keeps running without it.
    try { segmenter = await createSegmenter(vision, files, 'GPU'); }
    catch (e) {
      try { segmenter = await createSegmenter(vision, files, 'CPU'); } catch (e2) { segmenter = null; }
    }
  }

  document.addEventListener('visibilitychange', () => {
    const stream = video.srcObject;
    if (!stream) return;
    stream.getVideoTracks().forEach((t) => { t.enabled = !document.hidden; });
  });
  // Release the models and the camera when the page goes away, so a quick tab switch does not stack two pages' GPU / WASM memory.
  window.addEventListener('pagehide', () => {
    try { if (landmarker) landmarker.close(); } catch (e) { /* closing is best-effort */ }
    try { if (segmenter) segmenter.close(); } catch (e) { /* closing is best-effort */ }
    landmarker = null;
    segmenter = null;
    try {
      const stream = video.srcObject;
      if (stream) stream.getTracks().forEach((t) => t.stop());
    } catch (e) { /* the stream may already be gone */ }
  });

  start();
</script>
</body>
</html>`;
