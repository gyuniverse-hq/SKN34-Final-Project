import * as profiles from '@/lib/applicationProfiles';
import { LOOK_STRENGTH_MIN, scaleLookOverrides, videoLookMakeup } from '@/lib/videoLookMakeup';
import * as styles from '@/lib/videoLookStyles';
import type { LookApplicationProfile, MakeupState, MakeupZone } from '@/types';

const makeup: MakeupState = {
  lip: { hex: '#E77671', intensity: 0.65, texture: 'glossy' },
  blush: { hex: '#FF928F', intensity: 0.45, texture: 'cream' },
  eyeshadow: null,
  foundation: { hex: '#F5DCCA', intensity: 0.45, texture: 'matte' },
};
const profile: LookApplicationProfile = {
  source: 'video-fit', videoId: 'e1gSkUdG6Bo', fitFrame: 'fit', validationFrame: 'left', validationView: 'left',
  fitErrorBefore: 20, fitErrorAfter: 10, validationErrorBefore: 20, validationErrorAfter: 10,
  lipOpenValidation: { frame: 'open', errorBefore: 20, errorAfter: 10 },
  lookHex: '#BA5F6A', overrides: { coverageMultiplier: 0.5 },
};
const options = {
  fromVideo: true, cameraActive: true, fittingProduct: false,
  lookId: 'celebrity-e1gSkUdG6Bo', modified: [] as MakeupZone[],
};

describe('validated look profiles', () => {
  let styleSpy: jest.SpyInstance;
  beforeEach(() => { styleSpy = jest.spyOn(styles, 'videoLookStyle').mockReturnValue(undefined); });
  afterEach(() => styleSpy.mockRestore());

  it('applies a look color to a copy of the video render without changing product state', () => {
    const spy = jest.spyOn(profiles, 'lookApplicationProfileFor').mockImplementation((id, zone) => id === profile.videoId && zone === 'lip' ? profile : undefined);
    try {
      const rendered = videoLookMakeup(makeup, options);
      expect(rendered.lip).toEqual({ ...makeup.lip, hex: '#BA5F6A', applicationProfile: profile.overrides });
      expect(rendered.blush).toBe(makeup.blush);
      expect(makeup.lip?.hex).toBe('#E77671');
      expect(makeup.lip?.applicationProfile).toBeUndefined();
    } finally { spy.mockRestore(); }
  });

  it('applies independent look settings to other zones without overriding a changed product', () => {
    const blushProfile: LookApplicationProfile = { ...profile, lookHex: '#AA7788', geometry: { blushPlacement: 'under_eye' } };
    const spy = jest.spyOn(profiles, 'lookApplicationProfileFor').mockImplementation((id, zone) => (
      id === profile.videoId && zone === 'blush' ? blushProfile : undefined
    ));
    try {
      const rendered = videoLookMakeup(makeup, options);
      expect(rendered.blush).toMatchObject({ hex: '#AA7788', geometry: { blushPlacement: 'under_eye' } });
      expect(rendered.lip).toBe(makeup.lip);
      expect(videoLookMakeup(makeup, { ...options, modified: ['blush'] })).toBe(makeup);
      expect(makeup.blush?.hex).toBe('#FF928F');
    } finally { spy.mockRestore(); }
  });
});

describe('the Sullyoon video look finish', () => {
  it('paints the look colours, shapes and look-mode effects on a render copy only', () => {
    const rendered = videoLookMakeup(makeup, options);
    expect(rendered.lip).toMatchObject({ hex: '#B0686B', texture: 'glossy', geometry: { centerHighlight: 0.2, overlip: 0.025 } });
    expect(rendered.lip?.applicationProfile).toMatchObject({ material: { roughness: 0.03, specular: 1.9 } });
    expect(rendered.lip?.applicationProfile).toMatchObject({ coverageMultiplier: 0.3, lipColor: 0.2, lipGradient: 0.45, lipGloss: 2 });
    expect(rendered.blush).toMatchObject({
      hex: '#E46F8C', geometry: { blushPlacement: 'side' }, applicationProfile: { softLight: 2, blushColor: 0.8, coverageMultiplier: 0.5 },
    });
    expect(rendered.foundation?.applicationProfile).toMatchObject({ skinEven: 1, skin: { tint: '#EFC9D2', tone: 0.1, clean: 0.3 } });
    expect(rendered.foundation?.hex).toBe('#F5DCCA');
    expect(makeup.lip).toEqual({ hex: '#E77671', intensity: 0.65, texture: 'glossy' });
    expect(makeup.blush?.applicationProfile).toBeUndefined();
  });

  it('leaves other unfinished looks, product try-on and changed zones exactly as they were', () => {
    for (const id of ['style-kWI7_DkDjZ0']) {
      expect(videoLookMakeup(makeup, { ...options, lookId: id })).toBe(makeup);
    }
    for (const disabled of [
      { fromVideo: false }, { cameraActive: false }, { fittingProduct: true }, { lookId: null },
    ]) expect(videoLookMakeup(makeup, { ...options, ...disabled })).toBe(makeup);
    const changed = videoLookMakeup(makeup, { ...options, modified: ['lip'] });
    expect(changed.lip).toBe(makeup.lip);
    expect(changed.blush?.hex).toBe('#E46F8C');
    expect(videoLookMakeup({ ...makeup, lip: null }, options).lip).toBeNull();
  });

  it('scales coverage on looks without a per-zone finish when strength moves off 1', () => {
    const soft = videoLookMakeup(makeup, { ...options, lookId: 'style-kWI7_DkDjZ0', strength: 0.5 });
    const bold = videoLookMakeup(makeup, { ...options, lookId: 'style-kWI7_DkDjZ0', strength: 1.5 });
    expect(videoLookMakeup(makeup, { ...options, lookId: 'style-kWI7_DkDjZ0', strength: 1 })).toBe(makeup);
    expect(soft.lip?.applicationProfile?.coverageMultiplier).toBeCloseTo(0.5);
    expect(bold.blush?.applicationProfile?.coverageMultiplier).toBeCloseTo(1.5);
    expect(soft.lip?.hex).toBe(makeup.lip?.hex);
    expect(bold.blush?.hex).toBe(makeup.blush?.hex);
  });

  it('replaces the strawberry catalog mask, false lashes and lavender lip with the pair-fit finish', () => {
    const full: MakeupState = {
      ...makeup,
      mascara: { hex: '#282828', intensity: 0.8, texture: 'satin', geometry: { falseLash: [{ edge: 'upper', u: 0.5, mm: 10, strands: 3, spread: 0.06, converge: 0.75, lift: 1 }] } },
      contour: { hex: '#BAA08A', intensity: 0.55, texture: 'shimmer' },
    };
    const before = JSON.parse(JSON.stringify(full));
    const rendered = videoLookMakeup(full, { ...options, lookId: 'style-ZAozXs-ZZik' });
    expect(rendered.mascara?.geometry?.falseLash).toEqual([]);
    expect(rendered.lip).toMatchObject({ hex: '#D2504E', applicationProfile: { lipGradient: 1, coverageMultiplier: 0.55 } });
    expect(rendered.blush).toMatchObject({ hex: '#E2687A', geometry: { blushPlacement: 'apple', blushSize: 1.5 } });
    expect(rendered.contour?.hex).toBe('#B48C80');
    expect(rendered.foundation?.applicationProfile).toMatchObject({ skinEven: 1, skinWide: 0.45, coverageMultiplier: 0.25 });
    expect(full).toEqual(before);
  });

  it('gives the year-end look a cool under-eye flush and a muted sheer rose gloss', () => {
    const rendered = videoLookMakeup(makeup, { ...options, lookId: 'style-4QR0tre9yBI' });
    expect(rendered.blush).toMatchObject({ hex: '#EC8A9E', geometry: { blushPlacement: 'under_eye' } });
    expect(rendered.lip).toMatchObject({ hex: '#B85A6C', applicationProfile: { lipColor: 0.4, lipGloss: 2.8 } });
    expect(makeup.lip).toEqual({ hex: '#E77671', intensity: 0.65, texture: 'glossy' });
  });

  it('gives the Winter look a cool pink flush, no glitter lid and a rose gloss gradient', () => {
    const full: MakeupState = {
      ...makeup,
      eyeshadow: { hex: '#DFAEA8', intensity: 0.45, texture: 'shimmer', hexTo: '#453632', geometry: { glitter: true, sparkle: 1 } },
      contour: { hex: '#BAA08A', intensity: 0.55, texture: 'shimmer' },
    };
    const before = JSON.parse(JSON.stringify(full));
    const rendered = videoLookMakeup(full, { ...options, lookId: 'celebrity-fDqBPI1SaWY' });
    expect(rendered.blush).toMatchObject({ hex: '#E87090', geometry: { blushPlacement: 'apple', blushSize: 1.45 } });
    expect(rendered.eyeshadow).toMatchObject({
      hex: '#E8A8B0', hexTo: '#B87880', geometry: { glitter: false, sparkle: 0 },
      applicationProfile: { underEyePearl: 0.45 },
    });
    expect(rendered.lip).toMatchObject({ hex: '#A8586A', applicationProfile: { lipGradient: 1, lipGloss: 2.6 } });
    expect(rendered.foundation?.applicationProfile).toMatchObject({ skinEven: 1, skinWide: 0.45, coverageMultiplier: 0.25 });
    expect(rendered.contour?.hex).toBe('#A89898');
    expect(full).toEqual(before);
  });

  it('paints the Karina Met Gala look finish on a render copy only', () => {
    const full: MakeupState = {
      ...makeup,
      eyeliner: { hex: '#1F1D1C', intensity: 0.85, texture: 'satin' },
      mascara: { hex: '#0F0E0E', intensity: 0.85, texture: 'satin' },
      eyeshadow: { hex: '#F7CBCF', intensity: 0.45, texture: 'velvet', hexTo: '#5E3E31' },
      contour: { hex: '#D2B1A1', intensity: 0.55, texture: 'velvet' },
      highlighter: { hex: '#F1E3D5', intensity: 0.5, texture: 'shimmer' },
      brow: { hex: '#9F8162', intensity: 0.7, texture: 'satin' },
    };
    const before = JSON.parse(JSON.stringify(full));
    const rendered = videoLookMakeup(full, { ...options, lookId: 'celebrity-n5otfjJSSQc' });
    expect(rendered.lip).toMatchObject({
      hex: '#B87884',
      geometry: { centerHighlight: 0.08, overlip: 0.03 },
      applicationProfile: { lipGloss: 1, lipColor: 1, coverageMultiplier: 0.35 },
    });
    expect(rendered.blush).toMatchObject({
      hex: '#E06890',
      geometry: { blushPlacement: 'apple', blushSize: 1.4 },
      applicationProfile: { softLight: 3.3, blushColor: 1.1 },
    });
    expect(rendered.eyeliner?.geometry).toMatchObject({ length: 0.14, angle: 8, linerLower: false });
    expect(rendered.foundation?.applicationProfile).toMatchObject({ skinEven: 1, skinWide: 0.45, coverageMultiplier: 0.4 });
    expect(full).toEqual(before);
  });

  it('keeps eye, skin and contour improvements in the Sullyoon render copy', () => {
    const full: MakeupState = {
      ...makeup,
      eyeliner: { hex: '#332211', intensity: 0.8, texture: 'satin', geometry: { linerLower: false } },
      mascara: { hex: '#111111', intensity: 0.6, texture: 'satin' },
      eyeshadow: { hex: '#E9B09F', intensity: 0.45, texture: 'satin' },
      contour: { hex: '#D1B68D', intensity: 0.55, texture: 'velvet' },
      highlighter: { hex: '#DAB7B2', intensity: 0.5, texture: 'glossy' },
    };
    const before = JSON.parse(JSON.stringify(full));
    const rendered = videoLookMakeup(full, options);
    expect(rendered.eyeliner?.applicationProfile?.linerTaper).toBeGreaterThan(0);
    expect(rendered.eyeliner?.geometry?.linerLower).toBe(false);
    expect(rendered.mascara?.applicationProfile?.lashCurl).toBeGreaterThan(0);
    expect(rendered.eyeshadow?.applicationProfile?.underEyePearl).toBeGreaterThan(0);
    expect(rendered.eyeshadow?.hexTo).toBe('#8E6A66');
    expect(rendered.mascara?.hex).toBe('#3B2A24');
    expect(rendered.highlighter?.applicationProfile?.glow).toBeUndefined();
    expect(rendered.foundation?.applicationProfile?.skinWide).toBe(0);
    expect(rendered.foundation?.applicationProfile?.coverageMultiplier).toBe(0.2);
    expect(rendered.contour?.hex).not.toBe(full.contour?.hex);
    expect(rendered.lip?.intensity).toBe(full.lip?.intensity);
    expect(full).toEqual(before);
    expect(videoLookMakeup(full, { ...options, fittingProduct: true })).toBe(full);
  });

  it('the look strength slider scales coverage and effects, never colours or shapes', () => {
    const soft = videoLookMakeup(makeup, { ...options, strength: 0.5 });
    const bold = videoLookMakeup(makeup, { ...options, strength: 1.5 });
    expect(videoLookMakeup(makeup, { ...options, strength: 1 })).toEqual(videoLookMakeup(makeup, options));
    expect(soft.blush?.applicationProfile?.coverageMultiplier).toBeCloseTo(0.25);
    expect(soft.blush?.applicationProfile).toMatchObject({ softLight: 1, blushColor: 0.4 });
    expect(bold.blush?.applicationProfile?.coverageMultiplier).toBeCloseTo(0.75);
    expect(bold.blush?.applicationProfile).toMatchObject({ softLight: 3 });
    expect(bold.blush?.applicationProfile?.blushColor).toBeCloseTo(1.2);
    expect(bold.lip?.applicationProfile?.lipColor).toBeCloseTo(0.3);
    expect(bold.foundation?.applicationProfile?.skin?.tone).toBeCloseTo(0.15);
    expect(bold.foundation?.applicationProfile?.skin?.clean).toBeCloseTo(0.45);
    expect(bold.lip?.applicationProfile?.lipGradient).toBe(0.45);
    expect(bold.lip?.hex).toBe('#B0686B');
    expect(bold.blush?.geometry).toEqual(soft.blush?.geometry);
    // out-of-range and invalid values clamp to the slider range
    expect(scaleLookOverrides({ coverageMultiplier: 1, lipColor: 0.9 }, 99)).toEqual({ coverageMultiplier: 1.7, lipColor: 1 });
    expect(scaleLookOverrides({ softLight: 2 }, NaN)).toEqual({ softLight: 2 });
    expect(scaleLookOverrides({ softLight: 2 }, 0)).toEqual({ coverageMultiplier: LOOK_STRENGTH_MIN, softLight: 0.6 });
  });

  it('every style value is a renderable colour or a bounded number', () => {
    for (const look of Object.values(styles.VIDEO_LOOK_STYLES)) {
      for (const style of Object.values(look)) {
        for (const hex of [style?.hex, style?.hexTo, style?.overrides?.skin?.tint]) {
          if (hex !== undefined) expect(hex).toMatch(/^#[0-9A-F]{6}$/i);
        }
        const o = style?.overrides;
        if (o?.softLight !== undefined) expect(o.softLight).toBeLessThanOrEqual(8);
        if (o?.glow !== undefined) expect(o.glow).toBeLessThanOrEqual(4);
        if (o?.coverageMultiplier !== undefined) expect(o.coverageMultiplier).toBeLessThanOrEqual(2);
        for (const key of ['lipGradient', 'lashCurl', 'linerTaper', 'skinWide', 'underEyePearl', 'skinAdapt', 'skinWarmth', 'lightAdapt', 'toneMap'] as const) {
          if (o?.[key] !== undefined) {
            expect(o[key]).toBeGreaterThanOrEqual(0);
            expect(o[key]).toBeLessThanOrEqual(1);
          }
        }
      }
    }
    for (const videoId of ['n5otfjJSSQc', 'e1gSkUdG6Bo'] as const) {
      for (const zone of ['foundation', 'blush', 'lip'] as const) {
        expect(styles.videoLookStyle(videoId, zone)?.overrides?.lightAdapt).toBe(0.7);
      }
      expect(styles.videoLookStyle(videoId, 'foundation')?.overrides?.toneMap).toBe(0.55);
    }
    for (const videoId of ['ZAozXs-ZZik', '4QR0tre9yBI', 'fDqBPI1SaWY'] as const) {
      for (const zone of Object.keys(styles.VIDEO_LOOK_STYLES[videoId] ?? {})) {
        const o = styles.videoLookStyle(videoId, zone as 'lip')?.overrides;
        expect(o?.lightAdapt).toBeUndefined();
        expect(o?.toneMap).toBeUndefined();
      }
    }
  });
});
