import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import {
  ENV_DISPLAY, ENV_IDS, ENV_MESSAGE_KEY, ENV_MUTED, initialEnvDisplay, parseEnvMessage, stepEnvDisplay, voicedEnvId, type EnvState,
} from '@/lib/arEnv';
import { en } from '@/lib/i18n/en';
import { ja } from '@/lib/i18n/ja';
import { ko } from '@/lib/i18n/ko';
import { zh } from '@/lib/i18n/zh';

const html = FACE_TRACKER_HTML;

// The page's envStep, run on its own (same source as the WebView).
function loadEnvStep() {
  const src = html.match(/function envStep\(id, enter, exit, sev, now, enterMs\) \{[\s\S]*?\n {2}\}/)![0];
  const TUNING = { env: { enterMs: 1500, exitMs: 1000 } };
  const envState = { on: {} as Record<string, boolean>, since: {} as Record<string, number>, sev: {} as Record<string, number> };
  // eslint-disable-next-line no-new-func
  const step = new Function('TUNING', 'envState', src + '; return envStep;')(TUNING, envState) as
    (id: string, enter: boolean, exit: boolean, sev: number, now: number, enterMs?: number) => boolean;
  return { step, envState };
}

const env = (primary: EnvState['primary'], ready = true): EnvState => ({ primary, level: primary ? 'ask' : 'ok', items: primary ? [primary] : [], ready });

describe('AR environment state (11-19)', () => {
  it('a condition needs to hold its enter test 1.5 s and its exit test 1 s (no flicker at the threshold)', () => {
    const { step } = loadEnvStep();
    let on = false;
    let switches = 0;
    // A value hovering around the enter threshold every 0.5 s: in for one sample, out for the next.
    for (let t = 0; t <= 20000; t += 500) {
      const inside = (t / 500) % 2 === 0;
      const now = step('dark', inside, !inside, 1, t);
      if (now !== on) { switches++; on = now; }
    }
    expect(switches).toBe(0);
    // Held: on after 1.5 s, off 1 s after it clears.
    const b = loadEnvStep();
    expect(b.step('dark', true, false, 1, 0)).toBe(false);
    expect(b.step('dark', true, false, 1, 1000)).toBe(false);
    expect(b.step('dark', true, false, 1, 1500)).toBe(true);
    expect(b.step('dark', false, true, 1, 2000)).toBe(true);
    expect(b.step('dark', false, true, 1, 2500)).toBe(true);
    expect(b.step('dark', false, true, 1, 3000)).toBe(false);
  });

  it('low light and a low light-estimate confidence are separate conditions; the old light_hint stays', () => {
    expect(html).toContain("envStep('dark', envM.frameLum < E.dark.frameLum[0] || (grainN > E.dark.grainN[0] && light.grain > E.dark.grain[0]),");
    expect(html).toContain('const grainN = light.grain * Math.sqrt(Math.max(1e-4, light.skinMeanLum));');
    // v2 (11-19 decision 2-b): page values at the measured page scale 0.64 (docs/AR_ENV_THRESHOLDS.md 4-2).
    expect(html).toContain('dark: { frameLum: [0.03, 0.04], grainN: [0.0128, 0.0093], grain: [0.064, 0.051] },');
    expect(html).toContain("envStep('estimating', light.colorSamples >= 1 && light.colorConf < E.estimating[0]");
    expect(html).toContain("post({ type: 'light_hint', value: hint });");
    // Dark is never judged from the skin brightness alone (a darker skin tone is not low light).
    const darkLine = html.match(/envStep\('dark'[^\n]*/)![0];
    expect(darkLine).not.toContain('faceLum');
    expect(darkLine).not.toContain('skinMeanLum');
  });

  it('the backlight ratio follows the 0.5 s scene sample from the last segmenter mask (no extra segmenter calls)', () => {
    expect(html).toContain('try { envKeepBackground(mask.getAsUint8Array(), mask.width, mask.height); }');
    expect(html).toContain('try { envMeasureScene(data, sw, sh, skinLum, skinIn, lumAt); }');
    expect(html).toContain('try { envEvaluate(now, W, H); }');
    expect(html).not.toMatch(/envEvaluate[^\n]*segmentForVideo/);
  });

  it('records what the camera allows for white balance (HUD), never claiming a lock it did not get', () => {
    expect(html).toContain(".then(() => { wbLocked = true; wbInfo.result = 'locked'; envCameraChanged(performance.now()); })");
    expect(html).toContain(".catch(() => { wbInfo.result = 'rejected'; });");
    expect(html).toContain("wbInfo.result = 'unsupported';");
  });

  it('step 2-a: the HUD reads the camera controls and frame / latency / jitter percentiles without requesting any control', () => {
    const cam = html.match(/function camHud\(\) \{[\s\S]*?\n {2}\}/)![0];
    expect(cam).toContain('getSupportedConstraints');
    expect(cam).toContain('getCapabilities');
    expect(cam).toContain('getSettings');
    expect(cam).not.toContain('applyConstraints');
    for (const k of ['whiteBalanceMode', 'colorTemperature', 'exposureMode', 'exposureTime', 'exposureCompensation', 'iso']) expect(html).toContain("['" + k + "'");
    expect(html).toContain('      camHud(),\n      perfHud(),');
    // Percentiles over the last 120 frames (ring buffer), run on their own.
    const src = html.match(/const PERF_N = 120;[\s\S]*?function perfPct\(key, q\) \{[\s\S]*?\n {2}\}/)![0];
    // eslint-disable-next-line no-new-func
    const { perfPush, perfPct } = new Function(src + '; return { perfPush, perfPct };')() as
      { perfPush: (k: string, v: number) => void; perfPct: (k: string, q: number) => number };
    expect(perfPct('frame', 0.5)).toBeNaN();
    for (let i = 1; i <= 300; i++) perfPush('frame', i <= 180 ? 1000 : i - 180);   // the first 180 drop out of the ring
    expect(perfPct('frame', 0.5)).toBeCloseTo(61, 0);
    expect(perfPct('frame', 0.95)).toBeCloseTo(114, 0);
  });

  it('step 3-a: a camera setting change holds the colour / light-change conditions, re-collects the backlight reference and snaps the light', () => {
    expect(html).toContain('camSettleMs: 1500,');
    const fn = html.match(/function envCameraChanged\(now\) \{[\s\S]*?\n {2}\}/)![0];
    expect(fn).toContain('envState.camHoldUntil = now + TUNING.env.camSettleMs;');
    expect(fn).toContain('envRef.face = 0; envRef.ratio = 0; envRef.n = 0;');
    expect(fn).toContain('light.snapColor = true;');
    expect(html).toContain("envStep('warmLight', !camHold && ");
    expect(html).toContain("envStep('colorCast', !camHold && ");
    expect(html).toContain("envStep('lightChanged', moving && !camHold, !moving, 1, now);");
    expect(html).toContain('if (snap && camSnapPending) { camSnapPending = false; shownLight.t = 0; }');
    // 3-c: the light colour is re-read every 500 ms from the change until 1 s after the hold, still face or not.
    expect(html).toContain('camResampleMs: 500, camResampleTailMs: 1000,');
    expect(html).toContain('return now < envState.camHoldUntil + TUNING.env.camResampleTailMs;');
    expect(html).toContain('(camSettling(now) && now - lastSegmentAt >= TUNING.env.camResampleMs)');
    expect(html).toContain('if (camSettling(now) || now - lastSceneAt >= ');
    // Low light, backlight, position etc. are not held (a real problem right after the lock still shows).
    expect(html).not.toMatch(/envStep\('(dark|blown|position|motion)', !camHold/);
    // The page's own envStep: a colour cast present from the lock onward switches on after the hold plus its 1.5 s dwell.
    const { step } = loadEnvStep();
    const holdUntil = 1500;
    let onAt = -1;
    for (let t = 0; t <= 6000 && onAt < 0; t += 500) if (step('warmLight', !(t < holdUntil) && true, false, 1, t)) onAt = t;
    expect(onAt).toBe(3000);
  });

  it('step 5-d: makeup exposure follows the drop from the session skin reference; the old formula runs without one', () => {
    expect(html).toContain('expRef: { follow: [0.15, 0.02], nearFrac: 0.75, floor: 0.02, keepMs: 10000 },');
    expect(html).toContain('const exposure = exposureFor(light.skinMeanLum);');
    expect(html).toContain('hlMat.flake * TUNING.shimmerFlake * hlS * pearlExposure(shownLight.skinMeanLum) : 0);');
    expect(html).toContain('clamp01(lip.intensity) * pearlExposure(shownLight.skinMeanLum) : 0);');
    // The reference is not collected while blown out, the light estimate moves, a camera change settles or the scene is dark.
    expect(html).toContain('envState.evals >= E.readyEvals && !envState.on.blown && !envState.on.lightChanged && now >= envState.camHoldUntil && notDark');
    // Kept through a face loss for keepMs, then cleared at the next evaluation.
    expect(html).toContain('if (now - expRef.lostAt > XR.keepMs) { expRef.skin = 0; expRef.n = 0; expRef.rb = 0; }');
    expect(html).toContain('if (expRef.n) expRef.lostAt = performance.now();');
    const src = html.match(/const expRef = \{ skin: 0, n: 0, lostAt: 0, rb: 0 \};[\s\S]*?function pearlExposure\(skin\) \{[\s\S]*?\n {2}\}/)![0];
    const make = () => {
      const TUNING = { skinRefLum: 0.34, exposureRange: [0.2, 1.6], env: { expRef: { floor: 0.02 } } };
      // eslint-disable-next-line no-new-func
      return new Function('TUNING', 'clamp', src + '; return { expRef, exposureFor, pearlExposure };')(TUNING, (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))) as
        { expRef: { skin: number; n: number }; exposureFor: (s: number) => number; pearlExposure: (s: number) => number };
    };
    const o = make();
    // No reference: exactly today's formula (skin / 0.34, 0.2 floor), pearls untouched.
    expect(o.exposureFor(0.34)).toBeCloseTo(1, 5);
    expect(o.exposureFor(0.02)).toBe(0.2);
    expect(o.pearlExposure(0.02)).toBe(1);
    // Very dark skin tone settled at 0.02: in its normal light the value is unchanged; 5x darker is 5x lower, not the floor.
    o.expRef.skin = 0.02; o.expRef.n = 1;
    expect(o.exposureFor(0.02)).toBe(0.2);
    expect(o.exposureFor(0.12)).toBeCloseTo(0.353, 3);   // brighter than the reference: still skin / 0.34
    expect(o.exposureFor(0.03)).toBe(0.2);                // today's 0.2 floor above the reference
    expect(o.exposureFor(0.004)).toBeCloseTo(0.04, 5);   // 0.2 x 0.004 / 0.02
    expect(o.pearlExposure(0.004)).toBeCloseTo(0.2, 5);
    expect(o.pearlExposure(0.03)).toBe(1);
    // Fair skin settled at 0.52: today's value above the reference, proportional below it, never under the floor share.
    o.expRef.skin = 0.52;
    expect(o.exposureFor(0.6)).toBeCloseTo(1.6, 5);
    expect(o.exposureFor(0.52)).toBeCloseTo(1.529, 3);
    expect(o.exposureFor(0.104)).toBeCloseTo(1.529 * 0.2, 3);
    expect(o.exposureFor(0.001)).toBeCloseTo(1.529 * 0.02, 3);
  });

  it('step 6-1a: the last trusted light colour is held at full strength; dropped on a skin-colour jump and after the face was gone', () => {
    expect(html).toContain('lightTrustHold: true, lightTrustKeepMs: 10000,');
    expect(html).toContain('const target = TUNING.lightTrustHold && light.trusted ? light.trusted : [');
    expect(html).toContain('if (snap) light.trusted = null;');
    expect(html).toContain('if (ok && light.colorConf > 0.5) light.trusted = light.color.slice();');
    expect(html).toContain('if (now - light.trustedLostAt > TUNING.lightTrustKeepMs) light.trusted = null;');
    expect(html).toContain('if (light.trusted) light.trustedLostAt = performance.now();');
    // The estimate and everything that reads it stay as they were: the hold only picks the colour the shader is given.
    expect(html).toContain('light.colorConf += kc * (ok - light.colorConf);');
    expect(html).toContain("envStep('estimating', light.colorSamples >= 1 && light.colorConf < E.estimating[0]");
    // The target pick, run on its own: held colour at full strength, else the confidence-weighted colour of before.
    const pick = (trusted: number[] | null, hold: boolean) =>
      // eslint-disable-next-line no-new-func
      new Function('TUNING', 'light', 'clamp', "const w = clamp(light.colorConf, 0, 1); return TUNING.lightTrustHold && light.trusted ? light.trusted : [1 + w * (light.color[0] - 1), 1 + w * (light.color[1] - 1), 1 + w * (light.color[2] - 1)];")(
        { lightTrustHold: hold }, { colorConf: 0.2, color: [1.2, 1, 0.8], trusted }, (v: number, a: number, b2: number) => Math.min(b2, Math.max(a, v))) as number[];
    expect(pick([1.1, 1, 0.9], true)).toEqual([1.1, 1, 0.9]);
    expect(pick(null, true)[0]).toBeCloseTo(1.04, 5);
    expect(pick([1.1, 1, 0.9], false)[0]).toBeCloseTo(1.04, 5);
  });

  it('step 6-2a: the skin red / blue against the session reference is a HUD measure only, no condition reads it', () => {
    expect(html).toContain("'skinrb ' + (expRef.rb ? ");
    expect(html).toContain('if (!envState.on.warmLight && !envState.on.colorCast && (!expRef.rb || (rbNow > 0.9 * expRef.rb && rbNow < 1.1 * expRef.rb)))');
    const uses = html.split('expRef.rb').length - 1;
    const inHud = (html.match(/skinrb[^\n]*/)![0].split('expRef.rb').length - 1);
    // Used by the reference update, its reset and the HUD line, and by nothing that decides anything.
    expect(html.match(/envStep\([^\n]*expRef\.rb/)).toBeNull();
    expect(uses).toBeGreaterThan(inHud);
  });

  it('step 4-a: the low-light inputs and the camera exposure sit in two short lines at the top of the HUD', () => {
    expect(html).toMatch(/hud\.textContent = \[\s*lowHud\(\),\s*expHud\(\),\s*'fps '/);
    expect(html).toContain("'low fr ' + n(envM.frameLum, 3) + ' face ' + n(envM.faceLum, 3) + ' gr ' + n(light.grain, 3) + ' gN '");
    expect(html).toContain("'exp t ' + v(set.exposureTime) + ' iso ' + v(set.iso)");
    // Read only: nothing that decides anything calls them.
    expect(html.split('lowHud(').length - 1).toBe(2);
    expect(html.split('expHud(').length - 1).toBe(2);
    // Longest the two lines can get stays inside a phone-wide HUD (about 52 monospace characters on the 11-20 captures).
    expect('low fr 0.123 face 0.123 gr 0.123 gN 0.0123 DARK'.length).toBeLessThanOrEqual(52);
    expect('exp t 3333.3 iso 3200 continuous  hold on  wb locked'.length).toBeLessThanOrEqual(52);
  });

  it('parses the page message and keeps only known conditions', () => {
    expect(parseEnvMessage({ primary: 'dark', level: 'ask', items: ['dark', 'x'], ready: true }))
      .toEqual({ primary: 'dark', level: 'ask', items: ['dark'], ready: true });
    expect(parseEnvMessage({ primary: null, level: 'ok', items: [], ready: true })).toEqual({ primary: null, level: 'ok', items: [], ready: true });
    expect(parseEnvMessage({ primary: 'nope' })).toBeNull();
  });

  it('every message has a key in all four dictionaries', () => {
    for (const key of Object.values(ENV_MESSAGE_KEY)) {
      for (const dict of [ko, en, ja, zh] as Record<string, string>[]) expect(typeof dict[key]).toBe('string');
    }
    expect(Object.keys(ENV_MESSAGE_KEY).sort()).toEqual([...ENV_IDS, 'normal', 'noFace'].sort());
    // No message claims the colours were corrected exactly.
    for (const dict of [ko, en, ja, zh] as Record<string, string>[]) {
      for (const key of Object.values(ENV_MESSAGE_KEY)) expect(dict[key]).not.toMatch(/정확하게 보정|accurately corrected/);
    }
  });

  it('display rules: the start-up note once, a minimum time, no repeat within the gap, a worse problem replaces at once', () => {
    let d = initialEnvDisplay();
    d = stepEnvDisplay(d, env(null), false, 0);
    expect(d.shown).toBe('normal');
    d = stepEnvDisplay(d, env(null), false, 1000);
    expect(d.shown).toBe('normal');
    d = stepEnvDisplay(d, env(null), false, ENV_DISPLAY.normalShowMs + 10);
    expect(d.shown).toBeNull();
    d = stepEnvDisplay(d, env(null), false, 20000);
    expect(d.shown).toBeNull();   // never again this session

    // Colour cast shows; it clears after 1 s but stays its minimum time.
    d = stepEnvDisplay(d, env('warmLight'), false, 30000);
    expect(d.shown).toBe('warmLight');
    d = stepEnvDisplay(d, env(null), false, 31000);
    expect(d.shown).toBe('warmLight');
    d = stepEnvDisplay(d, env(null), false, 33100);
    expect(d.shown).toBeNull();
    // Back within the repeat gap: not shown again.
    d = stepEnvDisplay(d, env('warmLight'), false, 36000);
    expect(d.shown).toBeNull();
    d = stepEnvDisplay(d, env('warmLight'), false, 33100 + ENV_DISPLAY.repeatGapMs + 1);
    expect(d.shown).toBe('warmLight');
    // A worse problem replaces it before its minimum time.
    d = stepEnvDisplay(d, env('blown'), false, 33100 + ENV_DISPLAY.repeatGapMs + 500);
    expect(d.shown).toBe('blown');
    // No face: the face message wins at once and hides at once when the face is back.
    d = stepEnvDisplay(d, env('blown'), true, 50000);
    expect(d.shown).toBe('noFace');
    d = stepEnvDisplay(d, env(null), false, 50200);
    expect(d.shown).toBeNull();
  });

  it('decision 4: left / right unevenness is measured but not voiced; the next active condition is shown instead', () => {
    // The page still measures and publishes it (HUD, items).
    expect(html).toContain("envStep('unevenLight', frontal && lr > E.uneven[0]");
    expect(ENV_MUTED.has('unevenLight')).toBe(true);
    const uneven: EnvState = { primary: 'unevenLight', level: 'degraded', items: ['unevenLight'], ready: true };
    const unevenWarm: EnvState = { primary: 'unevenLight', level: 'degraded', items: ['unevenLight', 'warmLight'], ready: true };
    expect(voicedEnvId(uneven)).toBeNull();
    expect(voicedEnvId(unevenWarm)).toBe('warmLight');
    expect(voicedEnvId(env('dark'))).toBe('dark');
    let d = { ...initialEnvDisplay(), normalDone: true };
    for (let t = 0; t <= 20000; t += 500) {
      d = stepEnvDisplay(d, uneven, false, t);
      expect(d.shown).toBeNull();
    }
    d = stepEnvDisplay(d, unevenWarm, false, 21000);
    expect(d.shown).toBe('warmLight');
  });

  it('a steady normal scene shows no message after the start-up note (no repeated "good")', () => {
    let d = initialEnvDisplay();
    const seen: (string | null)[] = [];
    for (let t = 0; t <= 60000; t += 500) { d = stepEnvDisplay(d, env(null), false, t); seen.push(d.shown); }
    expect(seen.filter((s) => s === 'normal').length).toBe(ENV_DISPLAY.normalShowMs / 500);
    expect(seen.slice(-50).every((s) => s === null)).toBe(true);
  });
});
