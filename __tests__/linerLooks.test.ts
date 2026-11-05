import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { LINER_LOOK_IDS, LINER_LOOKS, matchingLinerLook } from '@/lib/linerLooks';
import { shadowFinishOf } from '@/lib/shadowFinishes';
import { useMakeupStore } from '@/store/makeupStore';
import type { Product, Shade, ZoneSetting } from '@/types';

describe('liner looks', () => {
  beforeEach(() => useMakeupStore.getState().reset());

  it('has the six styles and no lid wing', () => {
    expect(Object.keys(LINER_LOOKS)).toEqual(['natural', 'cat_wing', 'puppy', 'smoky', 'gyaru', 'under_point']);
    expect(Object.keys(LINER_LOOKS)).not.toContain('lid');
    for (const id of LINER_LOOK_IDS) expect(matchingLinerLook(LINER_LOOKS[id])).toBe(id);
    expect(matchingLinerLook({ angle: 15, length: 0.18, thickness: 0.09 })).toBeNull();
    // The old lid-wing numbers (17°, 0.25, 0.15) no longer select a chip.
    expect(matchingLinerLook({ angle: 17, length: 0.25, thickness: 0.15 })).toBeNull();
  });

  it('keeps hex when a liner look is patched', () => {
    const shade: Shade = { id: 'black', name: 'Black', hex: '#1A1414' };
    const product = { id: 'liner', makeupZone: 'eyeliner', texture: 'matte', shades: [shade] } as unknown as Product;
    useMakeupStore.getState().applyShade(product, shade);
    useMakeupStore.getState().patchGeometry('eyeliner', LINER_LOOKS.cat_wing);
    const liner = useMakeupStore.getState().makeup.eyeliner;
    expect(liner?.hex).toBe('#1A1414');
    expect(liner?.geometry).toMatchObject(LINER_LOOKS.cat_wing);
  });
});

describe('liner style presets', () => {
  it('selects each chip after it is patched over another one', () => {
    const shade: Shade = { id: 'black', name: 'Black', hex: '#1A1414' };
    const product = { id: 'liner', makeupZone: 'eyeliner', texture: 'matte', shades: [shade] } as unknown as Product;
    useMakeupStore.getState().reset();
    useMakeupStore.getState().applyShade(product, shade);
    for (const from of LINER_LOOK_IDS) {
      for (const to of LINER_LOOK_IDS) {
        useMakeupStore.getState().patchGeometry('eyeliner', LINER_LOOKS[from]);
        useMakeupStore.getState().patchGeometry('eyeliner', LINER_LOOKS[to]);
        expect(matchingLinerLook(useMakeupStore.getState().makeup.eyeliner?.geometry)).toBe(to);
      }
    }
    expect(LINER_LOOKS.natural.length).toBe(0);
    expect(LINER_LOOKS.puppy.angle).toBeLessThan(0);
    expect(LINER_LOOKS.smoky.linerLower).toBe(true);
  });

  it('keeps a look without the new fields drawing as before', () => {
    // Soft 0 skips the extra read; no linerLower draws no lower band.
    expect(FACE_TRACKER_HTML).toContain('uLinerSoft > 0.001');
    expect(FACE_TRACKER_HTML).toContain('liner ? clamp01(linerGeo.linerSoftness || 0) : 0');
    expect(FACE_TRACKER_HTML).toContain('if (g.linerLower) {');
    expect(FACE_TRACKER_HTML).toContain('smooth01(0.06, 0.14, lidGap)');
  });
});

describe('eyeshadow finish chips', () => {
  beforeEach(() => useMakeupStore.getState().reset());

  it('patches shadowFinish onto the current shade hex', () => {
    const shade: Shade = { id: 'champ', name: 'Champagne', hex: '#E8C9A8' };
    const product = { id: 'shadow', makeupZone: 'eyeshadow', texture: 'matte', shades: [shade] } as unknown as Product;
    useMakeupStore.getState().applyShade(product, shade);
    useMakeupStore.getState().patchGeometry('eyeshadow', { shadowFinish: 'glitter' });
    expect(useMakeupStore.getState().makeup.eyeshadow).toMatchObject({
      hex: '#E8C9A8',
      geometry: { shadowFinish: 'glitter' },
    });
    expect(shadowFinishOf(useMakeupStore.getState().makeup.eyeshadow)).toBe('glitter');
  });

  it('reads sparkle 0 as matte and product shimmer as shimmer', () => {
    const matte = { texture: 'shimmer', geometry: { sparkle: 0 } } as ZoneSetting;
    expect(shadowFinishOf(matte)).toBe('matte');
    expect(shadowFinishOf({ texture: 'shimmer' } as ZoneSetting)).toBe('shimmer');
    expect(shadowFinishOf({ texture: 'glossy' } as ZoneSetting)).toBe('glossy');
    expect(shadowFinishOf({ texture: 'matte' } as ZoneSetting)).toBe('matte');
  });
});
