import { LINER_LOOKS, matchingLinerLook } from '@/lib/linerLooks';
import { shadowFinishOf } from '@/lib/shadowFinishes';
import { useMakeupStore } from '@/store/makeupStore';
import type { Product, Shade, ZoneSetting } from '@/types';

describe('liner looks', () => {
  beforeEach(() => useMakeupStore.getState().reset());

  it('has the lid wing and the lash-line wing', () => {
    expect(Object.keys(LINER_LOOKS)).toEqual(['lid', 'line']);
    expect(matchingLinerLook(LINER_LOOKS.lid)).toBe('lid');
    expect(matchingLinerLook(LINER_LOOKS.line)).toBe('line');
    expect(LINER_LOOKS.lid).toMatchObject({ angle: 17, length: 0.25, thickness: 0.15 });
    expect(LINER_LOOKS.line).toMatchObject({ angle: 24, length: 0.20, thickness: 0.05 });
    expect(matchingLinerLook({ angle: 15, length: 0.18, thickness: 0.09 })).toBeNull();
  });

  it('keeps hex when a liner look is patched', () => {
    const shade: Shade = { id: 'black', name: 'Black', hex: '#1A1414' };
    const product = { id: 'liner', makeupZone: 'eyeliner', texture: 'matte', shades: [shade] } as unknown as Product;
    useMakeupStore.getState().applyShade(product, shade);
    useMakeupStore.getState().patchGeometry('eyeliner', LINER_LOOKS.lid);
    const liner = useMakeupStore.getState().makeup.eyeliner;
    expect(liner?.hex).toBe('#1A1414');
    expect(liner?.geometry).toMatchObject(LINER_LOOKS.lid);
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
