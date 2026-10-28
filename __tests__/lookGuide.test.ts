import { buildGuideSteps, guideText } from '@/lib/lookGuide';
import { DEMO_LOOKS, DEMO_PRODUCTS } from '@/lib/devCatalog/demo';
import { translate, type TranslationKey } from '@/lib/i18n';
import { LANGUAGES } from '@/lib/i18n/languages';
import type { MakeupState } from '@/types';

const look = (id: string) => DEMO_LOOKS.find((l) => l.id === id)!;
const en = (key: TranslationKey, params?: Record<string, string | number>) => translate('en', key, params);

describe('how-to guide steps', () => {
  it('follows the look own order, and only the zones it wears', () => {
    const stage = look('demo-look-stage-red');
    expect(buildGuideSteps(stage.makeup, stage.stepOrder).map((s) => s.zone)).toEqual(stage.stepOrder);
    const peach = look('demo-look-soft-peach-coral');
    expect(buildGuideSteps(peach.makeup, peach.stepOrder)[0].zone).toBe('blush');
  });

  it('puts zones the order leaves out after it, in the default order', () => {
    const steps = buildGuideSteps(
      {
        lip: { hex: '#B3202E', intensity: 1, texture: 'matte' },
        blush: { hex: '#F4A78A', intensity: 0.5, texture: 'sheer' },
        eyeshadow: { hex: '#8A5A44', intensity: 0.5, texture: 'matte' },
      },
      ['lip']
    );
    expect(steps.map((s) => s.zone)).toEqual(['lip', 'eyeshadow', 'blush']);
    expect(buildGuideSteps({ lip: null, blush: null, eyeshadow: null }).length).toBe(0);
  });

  it('gives every demo look its own order', () => {
    const orders = DEMO_LOOKS.map((l) => buildGuideSteps(l.makeup, l.stepOrder).map((s) => s.zone).join('>'));
    expect(new Set(orders).size).toBe(DEMO_LOOKS.length);
  });

  it('describes each liner from the look: long and bold, long pencil, or short and thin', () => {
    const liner = (id: string) => {
      const l = look(id);
      return guideText(buildGuideSteps(l.makeup, l.stepOrder).find((s) => s.zone === 'eyeliner')!, en);
    };
    expect(liner('demo-look-stage-red')).toBe(
      [
        en('looks.guide.eyeliner.long', { angle: 15 }),
        en('looks.guide.eyeliner.thick'),
        en('looks.guide.eyeliner.liquid'),
      ].join(' ')
    );
    expect(liner('demo-look-gal-classic')).toContain('12°');
    expect(liner('demo-look-semi-gyaru-retro')).toContain(en('looks.guide.eyeliner.pencil'));
    expect(liner('demo-look-soft-peach-coral')).toBe(
      [
        en('looks.guide.eyeliner.tightline'),
        en('looks.guide.eyeliner.thin'),
        en('looks.guide.eyeliner.pencil'),
      ].join(' ')
    );
  });

  it('reads the look extras: two-tone and inner pearl shadow, lower lashes, overlip, wide blush, named glow areas', () => {
    const text = (id: string, zone: keyof MakeupState) => {
      const l = look(id);
      return guideText(buildGuideSteps(l.makeup, l.stepOrder).find((s) => s.zone === zone)!, en);
    };
    expect(text('demo-look-semi-gyaru-retro', 'eyeshadow')).toContain(en('looks.guide.eyeshadow.inner'));
    expect(text('demo-look-stage-red', 'eyeshadow')).toContain(en('looks.guide.eyeshadow.twoTone'));
    expect(text('demo-look-stage-red', 'mascara')).toContain(en('looks.guide.mascara.upperOnly'));
    expect(text('demo-look-gal-classic', 'mascara')).toContain(en('looks.guide.mascara.long'));
    expect(text('demo-look-semi-gyaru-retro', 'lip')).toContain(en('looks.guide.lip.overlip'));
    expect(text('demo-look-stage-red', 'lip')).toBe(en('looks.guide.lip.matte'));
    expect(text('demo-look-glass-rose', 'lip')).toBe(en('looks.guide.lip.gloss'));
    expect(text('demo-look-snake-eye-idol', 'blush')).toContain(en('looks.guide.blush.wide'));
    expect(text('demo-look-snake-eye-idol', 'highlighter')).toBe(
      ['Tap it onto the forehead, the nose bridge where the light lands.', en('looks.guide.amount.strong')].join(' ')
    );
    // How much: a faint daily cheek vs a strong stage flush; the peach glow is toned down by its own multiple.
    expect(text('demo-look-soft-berry', 'blush')).toContain(en('looks.guide.amount.light'));
    expect(text('demo-look-snake-eye-idol', 'blush')).toContain(en('looks.guide.amount.strong'));
    expect(text('demo-look-soft-peach-coral', 'highlighter')).not.toMatch(/once more|very light/);
  });

  it('only uses sentences that exist in every language', () => {
    for (const l of DEMO_LOOKS) {
      for (const step of buildGuideSteps(l.makeup, l.stepOrder)) {
        for (const key of [step.textKey, ...step.extraKeys]) {
          for (const lang of LANGUAGES) expect(translate(lang, key)).not.toBe(key);
        }
        for (const lang of LANGUAGES) expect(guideText(step, (k, p) => translate(lang, k, p))).not.toMatch(/\{|looks\./);
      }
    }
  });

  it('stage red velvet wears its seven zones and lists a product for each', () => {
    const stage = look('demo-look-stage-red');
    const order = stage.stepOrder ?? [];
    for (const zone of order) expect(stage.makeup[zone]).toBeTruthy();
    const zones = stage.items.map((i) => DEMO_PRODUCTS.find((p) => p.id === i.productId)?.makeupZone);
    expect([...zones].sort()).toEqual([...order].sort());
  });
});
