import type { EyelinerStyle, MakeupZone, ZoneGeometry } from '@/types';

/**
 * The camera drawing guide (AR_SPEC 6-5-11): dashed lines on the live face that show where and in
 * which direction to draw. It only draws; it never changes a color (1-1) and sends nothing but the
 * step name, wing numbers and liner style into the AR page (1-4).
 */
export type DrawStep = 'eyebrow' | 'eyeshadow' | 'eyeliner' | 'lip';
export type { EyelinerStyle };

/** Top to bottom of the face, the order a person draws them. */
export const DRAW_STEPS: DrawStep[] = ['eyebrow', 'eyeshadow', 'eyeliner', 'lip'];

/** Wing angle when the look does not set one (same default the AR renderer draws). */
export const DEFAULT_WING_ANGLE = 15;
/** Wing length in eye widths (renderer default); the classic guide never draws it shorter than it can be read. */
export const DEFAULT_WING_LENGTH = 0.18;
const MIN_GUIDE_WING = 0.12;
/** Puppy liner: tail drops below the eye line (degrees). */
export const DEFAULT_PUPPY_ANGLE = -8;
/** Tightline: a short outer tick, as a share of eye width. */
export const DEFAULT_TIGHTLINE_LENGTH = 0.08;
const TIGHTLINE_LENGTH_MAX = 0.12;

export interface GuideMessage {
  step: DrawStep;
  /** Wing angle in degrees (negative = below the eye axis, puppy). */
  angle: number;
  /** Wing length in eye widths */
  length: number;
  /** Which eyeliner path to draw; ignored on brow/shadow/lip. */
  style: EyelinerStyle;
}

/** Look value, or a short tail / a downward angle when the look did not name a style. */
export function eyelinerStyle(g?: ZoneGeometry): EyelinerStyle {
  const named = g?.linerStyle;
  if (named === 'puppy' || named === 'tightline' || named === 'classic_winged') return named;
  if (typeof g?.angle === 'number' && g.angle < 0) return 'puppy';
  if (typeof g?.length === 'number' && g.length < TIGHTLINE_LENGTH_MAX) return 'tightline';
  return 'classic_winged';
}

const STEP_ZONE: Record<DrawStep, MakeupZone | null> = {
  eyebrow: 'brow',
  eyeshadow: 'eyeshadow',
  eyeliner: 'eyeliner',
  lip: 'lip',
};

/** The camera guide a zone has; zones without lines (blush, mascara, ...) have none. */
export function stepForZone(zone: MakeupZone): DrawStep | null {
  return DRAW_STEPS.find((step) => STEP_ZONE[step] === zone) ?? null;
}

/** What the AR page needs for one step (`liner` = the look's eyeliner geometry): its own wing angle and length, so the guide matches what is painted. */
export function guideMessage(step: DrawStep, liner?: ZoneGeometry): GuideMessage {
  const style = eyelinerStyle(liner);
  const hasAngle = Number.isFinite(liner?.angle);
  const hasLength = Number.isFinite(liner?.length);
  let angle = hasAngle ? (liner!.angle as number) : DEFAULT_WING_ANGLE;
  let length = hasLength ? (liner!.length as number) : DEFAULT_WING_LENGTH;
  if (style === 'puppy' && !(hasAngle && (liner!.angle as number) < 0)) angle = DEFAULT_PUPPY_ANGLE;
  if (style === 'tightline') {
    if (!hasLength) length = DEFAULT_TIGHTLINE_LENGTH;
    length = Math.min(TIGHTLINE_LENGTH_MAX, Math.max(0.05, length));
  } else {
    length = Math.max(MIN_GUIDE_WING, length);
  }
  return { step, angle, length, style };
}
