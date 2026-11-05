import { buildGuideSteps, guideText } from '@/lib/lookGuide';
import { translate, type TranslationKey } from '@/lib/i18n';
import { LANGUAGES } from '@/lib/i18n/languages';
import type { MakeupState, MakeupZone } from '@/types';

const en = (key: TranslationKey, params?: Record<string, string | number>) => translate('en', key, params);

const stage: MakeupState = {
  lip: { hex: '#B3202E', intensity: 0.85, texture: 'velvet' },
  blush: { hex: '#F08C7A', intensity: 0.5, texture: 'matte' },
  eyeshadow: { hex: '#8A5A44', hexTo: '#3E271E', intensity: 0.7, texture: 'shimmer' },
  eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.3, angle: 15, thickness: 0.06 } },
};
const stageOrder = ['eyeshadow', 'blush', 'eyeliner', 'lip'] as const;

const peach: MakeupState = {
  blush: { hex: '#F4A78A', intensity: 0.5, texture: 'sheer' },
  eyeshadow: { hex: '#F4A78A', intensity: 0.44, texture: 'shimmer' },
  eyeliner: {
    hex: '#3A2820',
    intensity: 0.7,
    texture: 'matte',
    geometry: { length: 0.08, linerStyle: 'tightline', thickness: 0.03 },
  },
  lip: { hex: '#F2735B', intensity: 0.55, texture: 'sheer' },
};
const peachOrder = ['blush', 'eyeshadow', 'eyeliner', 'lip'] as const;

const galLiner: MakeupState = {
  lip: null,
  blush: null,
  eyeshadow: null,
  eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.42, angle: 12 } },
};

const pencilLiner: MakeupState = {
  lip: { hex: '#C99A8A', intensity: 0.7, texture: 'cream', geometry: { overlip: 0.2 } },
  blush: null,
  eyeshadow: { hex: '#C9A27E', intensity: 0.5, texture: 'shimmer', geometry: { innerPoint: { hex: '#F3E9DF', a1: 0.4, radius: 0.12 } } },
  eyeliner: { hex: '#4A3026', intensity: 0.8, texture: 'matte', geometry: { length: 0.35, angle: 8 } },
};

const glossLip: MakeupState = {
  lip: { hex: '#C25A6E', intensity: 0.6, texture: 'glossy' },
  blush: null,
  eyeshadow: null,
};

const wideBlush: MakeupState = {
  lip: null,
  blush: { hex: '#EC9DB0', intensity: 0.85, texture: 'sheer', geometry: { blushSize: 1.4 } },
  eyeshadow: null,
};

const lightBlush: MakeupState = {
  lip: null,
  blush: { hex: '#E8899A', intensity: 0.25, texture: 'sheer' },
  eyeshadow: null,
};

describe('how-to guide steps', () => {
  it('follows the look own order, and only the zones it wears', () => {
    expect(buildGuideSteps(stage, [...stageOrder]).map((s) => s.zone)).toEqual([...stageOrder]);
    expect(buildGuideSteps(peach, [...peachOrder])[0].zone).toBe('blush');
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

  it('gives distinct orders for two different looks', () => {
    const a = buildGuideSteps(stage, [...stageOrder]).map((s) => s.zone).join('>');
    const b = buildGuideSteps(peach, [...peachOrder]).map((s) => s.zone).join('>');
    expect(a).not.toBe(b);
  });

  it('describes each liner from the look: long and bold, long pencil, or short and thin', () => {
    const liner = (makeup: MakeupState, order?: readonly MakeupZone[]) =>
      guideText(buildGuideSteps(makeup, order ? [...order] : []).find((s) => s.zone === 'eyeliner')!, en);
    expect(liner(stage, stageOrder)).toBe(
      [
        en('looks.guide.eyeliner.long', { angle: 15 }),
        en('looks.guide.eyeliner.thick'),
        en('looks.guide.eyeliner.liquid'),
      ].join(' ')
    );
    expect(liner(galLiner)).toContain('12°');
    expect(liner(pencilLiner)).toContain(en('looks.guide.eyeliner.pencil'));
    expect(liner(peach, peachOrder)).toBe(
      [
        en('looks.guide.eyeliner.tightline'),
        en('looks.guide.eyeliner.thin'),
        en('looks.guide.eyeliner.pencil'),
      ].join(' ')
    );
  });

  it('reads the look extras: two-tone and inner pearl shadow, overlip, wide blush', () => {
    const text = (makeup: MakeupState, zone: keyof MakeupState, order?: readonly MakeupZone[]) =>
      guideText(buildGuideSteps(makeup, order ? [...order] : []).find((s) => s.zone === zone)!, en);
    expect(text(pencilLiner, 'eyeshadow')).toContain(en('looks.guide.eyeshadow.inner'));
    expect(text(stage, 'eyeshadow', stageOrder)).toContain(en('looks.guide.eyeshadow.twoTone'));
    expect(text(pencilLiner, 'lip')).toContain(en('looks.guide.lip.overlip'));
    expect(text({ lip: { hex: '#B3202E', intensity: 1, texture: 'matte' }, blush: null, eyeshadow: null }, 'lip')).toBe(
      en('looks.guide.lip.matte')
    );
    expect(text(glossLip, 'lip')).toBe(en('looks.guide.lip.gloss'));
    expect(text(wideBlush, 'blush')).toContain(en('looks.guide.blush.wide'));
    expect(text(lightBlush, 'blush')).toContain(en('looks.guide.amount.light'));
    expect(text(wideBlush, 'blush')).toContain(en('looks.guide.amount.strong'));
  });

  it('only uses sentences that exist in every language', () => {
    for (const makeup of [stage, peach, galLiner, pencilLiner, glossLip, wideBlush, lightBlush]) {
      for (const step of buildGuideSteps(makeup)) {
        for (const key of [step.textKey, ...step.extraKeys]) {
          for (const lang of LANGUAGES) expect(translate(lang, key)).not.toBe(key);
        }
        for (const lang of LANGUAGES) expect(guideText(step, (k, p) => translate(lang, k, p))).not.toMatch(/\{|looks\./);
      }
    }
  });
});
