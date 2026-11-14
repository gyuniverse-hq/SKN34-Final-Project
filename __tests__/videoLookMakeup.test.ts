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
    expect(rendered.lip).toMatchObject({ hex: '#B0606C', texture: 'glossy', geometry: { centerHighlight: 0.2, overlip: 0.025 } });
    expect(rendered.lip?.applicationProfile).toMatchObject({ material: { roughness: 0.03, specular: 1.9 } });
    expect(rendered.lip?.applicationProfile).toMatchObject({ coverageMultiplier: 0.85, lipColor: 0.45, lipGradient: 0.45, lipGloss: 2 });
    expect(rendered.blush).toMatchObject({
      hex: '#E46F8C', geometry: { blushPlacement: 'apple' }, applicationProfile: { softLight: 2, blushColor: 1, coverageMultiplier: 0.65 },
    });
    expect(rendered.foundation?.applicationProfile).toMatchObject({ skinEven: 0.6, skin: { tint: '#EFC9D2', tone: 0.25, clean: 0 } });
    expect(rendered.foundation?.hex).toBe('#F5DCCA');
    expect(makeup.lip).toEqual({ hex: '#E77671', intensity: 0.65, texture: 'glossy' });
    expect(makeup.blush?.applicationProfile).toBeUndefined();
  });

  it('leaves other looks, product try-on and changed zones exactly as they were', () => {
    for (const id of ['style-ZAozXs-ZZik', 'style-4QR0tre9yBI', 'style-kWI7_DkDjZ0', 'celebrity-n5otfjJSSQc', 'celebrity-fDqBPI1SaWY']) {
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
    expect(rendered.eyeshadow?.hexTo).toBeUndefined();
    expect(rendered.foundation?.applicationProfile?.skinWide).toBe(0);
    expect(rendered.foundation?.applicationProfile?.coverageMultiplier).toBe(0.45);
    expect(rendered.contour?.hex).not.toBe(full.contour?.hex);
    expect(rendered.lip?.intensity).toBe(full.lip?.intensity);
    expect(full).toEqual(before);
    expect(videoLookMakeup(full, { ...options, fittingProduct: true })).toBe(full);
  });

  it('the look strength slider scales coverage and effects, never colours or shapes', () => {
    const soft = videoLookMakeup(makeup, { ...options, strength: 0.5 });
    const bold = videoLookMakeup(makeup, { ...options, strength: 1.5 });
    expect(videoLookMakeup(makeup, { ...options, strength: 1 })).toEqual(videoLookMakeup(makeup, options));
    expect(soft.blush?.applicationProfile?.coverageMultiplier).toBeCloseTo(0.325);
    expect(soft.blush?.applicationProfile).toMatchObject({ softLight: 1, blushColor: 0.5 });
    expect(bold.blush?.applicationProfile?.coverageMultiplier).toBeCloseTo(0.975);
    expect(bold.blush?.applicationProfile).toMatchObject({ softLight: 3, blushColor: 1.5 });
    expect(bold.lip?.applicationProfile?.lipColor).toBeCloseTo(0.675);
    expect(bold.foundation?.applicationProfile?.skin).toEqual({ tint: '#EFC9D2', tone: 0.375, clean: 0 });
    expect(bold.lip?.applicationProfile?.lipGradient).toBe(0.45);
    expect(bold.lip?.hex).toBe('#B0606C');
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
        for (const key of ['lipGradient', 'lashCurl', 'linerTaper', 'skinWide', 'underEyePearl', 'skinAdapt', 'skinWarmth'] as const) {
          if (o?.[key] !== undefined) {
            expect(o[key]).toBeGreaterThanOrEqual(0);
            expect(o[key]).toBeLessThanOrEqual(1);
          }
        }
      }
    }
  });
});
