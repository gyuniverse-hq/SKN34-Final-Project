import { eyelinerStyle } from '@/lib/drawGuide';
import type { TranslationKey } from '@/lib/i18n';
import type { HighlightArea, MakeupState, MakeupZone } from '@/types';

/** Order a person would put the zones on when the look gives none: eyes first, lips last. */
export const GUIDE_ORDER: MakeupZone[] = ['foundation', 'brow', 'eyeshadow', 'eyeliner', 'mascara', 'blush', 'contour', 'highlighter', 'lip'];

type Params = Record<string, string | number>;
type Translate = (key: TranslationKey, params?: Params) => string;

export interface GuideStep {
  zone: MakeupZone;
  /** Main sentence, chosen from the look's own values for this zone. */
  textKey: TranslationKey;
  params?: Params;
  /** Extra sentences that apply to this look only (a thick line, no lower lashes, an overlip, ...). */
  extraKeys: TranslationKey[];
  /** Highlighter areas, named in the sentence. */
  areas?: HighlightArea[];
}

const LONG_WING = 0.3;
const SHORT_WING = 0.12;
const THICK_LINE = 0.06;
const THIN_LINE = 0.04;
const LONG_LASHES = 1.4;
const WIDE_BLUSH = 1.3;
/** Strength (intensity × the look's own multiple) below / above which the cheek and face steps say how much. */
const LIGHT_AMOUNT = 0.35;
const STRONG_AMOUNT = 0.6;

const k = (key: string) => key as TranslationKey;

function stepFor(zone: MakeupZone, makeup: MakeupState): GuideStep {
  const z = makeup[zone];
  const g = z?.geometry;
  const extraKeys: TranslationKey[] = [];
  if (z && (zone === 'blush' || zone === 'contour' || zone === 'highlighter')) {
    const amount = z.intensity * (g?.intensity ?? 1);
    if (amount <= LIGHT_AMOUNT) extraKeys.push(k('looks.guide.amount.light'));
    else if (amount >= STRONG_AMOUNT) extraKeys.push(k('looks.guide.amount.strong'));
  }
  switch (zone) {
    case 'eyeshadow': {
      if (z?.hexTo) extraKeys.push(k('looks.guide.eyeshadow.twoTone'));
      if (g?.innerPoint) extraKeys.push(k('looks.guide.eyeshadow.inner'));
      if (g?.pearl) extraKeys.push(k('looks.guide.eyeshadow.pearl'));
      if (z?.texture === 'shimmer' && g?.sparkle !== 0) extraKeys.push(k('looks.guide.eyeshadow.shimmer'));
      return { zone, textKey: k('looks.guide.eyeshadow'), extraKeys };
    }
    case 'eyeliner': {
      const style = eyelinerStyle(g);
      const len = g?.length ?? 0.18;
      const base = len >= LONG_WING ? 'long' : len <= SHORT_WING ? 'short' : 'normal';
      const thick = g?.thickness ?? 0.09;
      if (thick >= THICK_LINE) extraKeys.push(k('looks.guide.eyeliner.thick'));
      else if (thick <= THIN_LINE) extraKeys.push(k('looks.guide.eyeliner.thin'));
      if (z?.texture === 'glossy') extraKeys.push(k('looks.guide.eyeliner.liquid'));
      else if (z?.texture === 'matte') extraKeys.push(k('looks.guide.eyeliner.pencil'));
      const angle = Math.round(Math.abs(style === 'puppy' ? (g?.angle ?? -8) : (g?.angle ?? 15)));
      if (style === 'puppy') {
        return { zone, textKey: k('looks.guide.eyeliner.puppy'), params: { angle }, extraKeys };
      }
      if (style === 'tightline') {
        return { zone, textKey: k('looks.guide.eyeliner.tightline'), params: { angle }, extraKeys };
      }
      return {
        zone,
        textKey: k(base === 'normal' ? 'looks.guide.eyeliner' : `looks.guide.eyeliner.${base}`),
        params: { angle },
        extraKeys,
      };
    }
    case 'mascara': {
      if (g?.lower === false) extraKeys.push(k('looks.guide.mascara.upperOnly'));
      else if (g?.lower === true) extraKeys.push(k('looks.guide.mascara.lower'));
      return {
        zone,
        textKey: k((g?.length ?? 1) >= LONG_LASHES ? 'looks.guide.mascara.long' : 'looks.guide.mascara'),
        extraKeys,
      };
    }
    case 'blush': {
      if ((g?.blushSize ?? 1) >= WIDE_BLUSH) extraKeys.push(k('looks.guide.blush.wide'));
      return { zone, textKey: k(`looks.guide.blush.${g?.blushPlacement ?? 'apple'}`), extraKeys };
    }
    case 'highlighter': {
      const areas = g?.areas;
      return areas?.length
        ? { zone, textKey: k('looks.guide.highlighter.areas'), extraKeys, areas }
        : { zone, textKey: k('looks.guide.highlighter'), extraKeys };
    }
    case 'lip': {
      if ((g?.overlip ?? 0) > 0) extraKeys.push(k('looks.guide.lip.overlip'));
      const finish = z?.texture;
      const base =
        finish === 'matte' || finish === 'velvet'
          ? 'looks.guide.lip.matte'
          : finish === 'glossy' || finish === 'sheer'
            ? 'looks.guide.lip.gloss'
            : 'looks.guide.lip';
      return { zone, textKey: k(base), extraKeys };
    }
    default:
      return { zone, textKey: k(`looks.guide.${zone}`), extraKeys };
  }
}

/**
 * One how-to step for every zone the look uses, in the look's own order (`order`, then any zone it
 * left out in the default order). Every sentence comes from the look's own makeup values, so two looks
 * with different liners or lips read differently.
 */
export function buildGuideSteps(makeup: MakeupState, order: MakeupZone[] = []): GuideStep[] {
  const seq = [...new Set([...order, ...GUIDE_ORDER])];
  return seq.filter((zone) => !!makeup[zone]).map((zone) => stepFor(zone, makeup));
}

/** The step's sentences joined; `t` is the app's translate function. */
export function guideText(step: GuideStep, t: Translate): string {
  const params: Params = { ...step.params };
  if (step.areas) params.areas = step.areas.map((a) => t(k(`looks.area.${a}`))).join(', ');
  return [t(step.textKey, params), ...step.extraKeys.map((key) => t(key, params))].join(' ');
}
