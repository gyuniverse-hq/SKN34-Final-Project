import { DEFAULT_PUPPY_ANGLE, DEFAULT_WING_ANGLE, DRAW_STEPS, eyelinerStyle, guideMessage, stepForZone } from '@/lib/drawGuide';
import { DEMO_LOOKS } from '@/lib/devCatalog/demo';
import { translate } from '@/lib/i18n';
import { LANGUAGES } from '@/lib/i18n/languages';

describe('drawing guide steps', () => {
  it('has a camera guide for the brow, shadow, liner and lip', () => {
    expect(DRAW_STEPS).toEqual(['eyebrow', 'eyeshadow', 'eyeliner', 'lip']);
  });

  it('maps zones to their camera guide, and leaves zones without lines alone', () => {
    expect(stepForZone('brow')).toBe('eyebrow');
    expect(stepForZone('eyeshadow')).toBe('eyeshadow');
    expect(stepForZone('eyeliner')).toBe('eyeliner');
    expect(stepForZone('lip')).toBe('lip');
    for (const z of ['blush', 'mascara', 'highlighter', 'contour', 'foundation'] as const) {
      expect(stepForZone(z)).toBeNull();
    }
  });

  it('takes the wing angle and length from the look, and falls back to the renderer defaults', () => {
    const stage = DEMO_LOOKS.find((l) => l.id === 'demo-look-stage-red')!;
    expect(guideMessage('eyeliner', stage.makeup.eyeliner?.geometry)).toEqual({
      step: 'eyeliner',
      angle: 15,
      length: 0.3,
      style: 'classic_winged',
    });
    const gal = DEMO_LOOKS.find((l) => l.id === 'demo-look-gal-classic')!;
    expect(guideMessage('eyeliner', gal.makeup.eyeliner?.geometry)).toMatchObject({ angle: 12, length: 0.42, style: 'classic_winged' });
    expect(guideMessage('lip')).toEqual({ step: 'lip', angle: DEFAULT_WING_ANGLE, length: 0.18, style: 'classic_winged' });
  });

  it('never draws a classic wing shorter than it can be read', () => {
    expect(guideMessage('eyeliner', { length: 0.02, linerStyle: 'classic_winged' }).length).toBeGreaterThanOrEqual(0.12);
  });

  it('picks puppy / tightline / classic from the look, or from a downward angle / short tail', () => {
    expect(eyelinerStyle({ linerStyle: 'puppy' })).toBe('puppy');
    expect(eyelinerStyle({ angle: -10 })).toBe('puppy');
    expect(guideMessage('eyeliner', { linerStyle: 'puppy' })).toMatchObject({ style: 'puppy', angle: DEFAULT_PUPPY_ANGLE });
    const peach = DEMO_LOOKS.find((l) => l.id === 'demo-look-soft-peach-coral')!;
    expect(guideMessage('eyeliner', peach.makeup.eyeliner?.geometry)).toMatchObject({ style: 'tightline', length: 0.08 });
    expect(guideMessage('eyeliner', { length: 0.05 }).style).toBe('tightline');
  });

  it('has the brow sentence and the practice strings in every language', () => {
    for (const lang of LANGUAGES) {
      for (const key of [
        'ar.guide.eyebrow',
        'ar.guide.text.eyebrow',
        'ar.practice.start',
        'ar.practice.title',
        'ar.practice.intro',
        'ar.practice.prev',
        'ar.practice.next',
        'ar.practice.finish',
        'ar.practice.peek',
        'ar.practice.peekOff',
        'ar.practice.exit',
      ] as const) {
        expect(translate(lang, key)).not.toBe(key);
      }
    }
  });
});
