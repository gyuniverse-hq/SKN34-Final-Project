# AR environment checks (11-19)

Offline counterparts of the renderer's environment measures (`components/ar/faceTrackerHtml.ts` `sampleScene`,
`measureCamera`, `bgColorSums`, `envEvaluate`), used to set the `TUNING.env` thresholds and the Gray-Edge mix.

- `lapa_env_eval.py`: LaPa test faces (label 0 = background, 1 = skin), normal + synthetic dark room, dark room with auto
  exposure, backlight, side light, warm / cool light, blown face, and four painted walls (light unchanged).
- `skin_tone_env_eval.py`: Roboflow `skin-tone-9drvk` (dark / fair / light), skin and background from the app's Selfie
  Multiclass model; same conditions. Checks that a rule does not fire more for one skin tone.
- `lapa_pose.py`: the renderer's landmark yaw / pitch formula against the Face Landmarker transformation matrix.
- `manifest.py`: the exact source list (SHA-1, licence) and a fixed per-image split (select 60 / tune 20 / test 20).
- `analyze_thresholds.py`: baseline v1 rates on the test split, candidate search on select, check on tune.
- `headless/`: clips, page driver and offline grain for the page-vs-offline grain scale (run one at a time).
  - `make_env_y4m.py ... lamp` (11-20 step 4-a): the phone "stand only" scene, face and wall at 1/10 light with a warm lamp
    above the head; `drive_env.mjs` also records the HUD `low` / `exp t` lines and their pixel width.
  - `sim_cam_settle.mjs` (11-19 step 3): the page's own env code, sliced from a built page, driven by the test-split
    measures (normal / warm) at phone timing around a white-balance lock; compares the 3-a hold and other candidates.
    `node sim_cam_settle.mjs <page.html> research/data/env_eval_runs/2026-11-19 lib/arEnv.ts <out.json>` (seconds).
  - `sim_exposure_ref.mjs` (11-19 step 5-d): the page's session skin reference (`expRef`, `exposureFor`) driven in time
    order (normal -> dark, dark -> normal, auto exposure, slow fade, face lost) by the test-split measures; makeup-to-skin
    brightness against normal light, today's formula vs the new one. Same arguments as `sim_cam_settle.mjs` minus `lib/arEnv.ts`.
  - `../step4b_sim.py` (11-20 step 4-b): the phone "stand only" room (dark face, lamp keeps the frame mean up) on the
    select / test images; tone-based and face-based dark-rule candidates against today's rule, per skin tone group.
  - `../step6_sim.py` (11-19 step 6): last trusted light colour on painted walls (the page's colour path replicated), and
    the skin red / blue ratio against the session reference as a colour-light cue when the face fills the frame.
  - `../exposure_predictors.py` (11-19 step 5-b): which picture measure could stand for the light level per skin tone.
  - `render_cmp.mjs` + `analyze_step5.py` (11-19 step 5): headless renders of a page variant (bare + four makeup sets,
    then the HUD perf line) and the per-region colour difference / float index / perf table across variants.
    `node render_cmp.mjs <page.html> <clip.y4m> <out_dir> <label>`, then
    `python analyze_step5.py <out_dir> research/data/env_eval_runs/models/face_landmarker.task <montage_dir>`.
- `results/`: the committed summary JSON and the SHA-1 of the run logs. Report: `docs/AR_ENV_THRESHOLDS.md`.

Data stays under the git-ignored `research/data/reference/` (`lapa/`, `roboflow_env/` with `SOURCE.md`). The two
MediaPipe models are the public ones the app loads (`face_landmarker.task`, `selfie_multiclass_256x256.tflite`).
Synthetic light changes are not phone footage, and the page-vs-offline grain scale is unconfirmed (same-frame check
0.60-0.68, not the 0.45 in the code), so phone thresholds still need the HUD `env` line.
