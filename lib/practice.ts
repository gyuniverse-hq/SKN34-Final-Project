import { stepForZone, type DrawStep } from '@/lib/drawGuide';
import { buildGuideSteps } from '@/lib/lookGuide';
import type { MakeupState, MakeupZone } from '@/types';

/**
 * "Do the makeup yourself" (AR_SPEC 6-5-13): start from a bare face and press the steps of the look one
 * by one. A step puts its zone on the face as one more layer and shows its drawing guide. This module only
 * decides what is shown; it never writes to the makeup store, so leaving the mode gives back the finished look.
 */

/** `null` is the brow: it has a guide but no color. */
export type PracticeZone = MakeupZone | null;

const ALL_ZONES: MakeupZone[] = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour', 'brow', 'foundation'];

/** The brow first, then every zone the look wears in the look's own order. */
export function practiceZones(makeup: MakeupState, order: MakeupZone[] = []): PracticeZone[] {
  return [null, ...buildGuideSteps(makeup, order).map((s) => s.zone)];
}

/** The look with only the visited zones on; the rest stay off. */
export function revealedMakeup(makeup: MakeupState, visited: MakeupZone[]): MakeupState {
  const on = new Set(visited);
  const out = { ...makeup };
  for (const zone of ALL_ZONES) out[zone] = on.has(zone) ? (makeup[zone] ?? null) : null;
  return out;
}

/** The camera guide for a step; zones without lines (blush, mascara, ...) show color only. */
export function practiceDrawStep(zone: PracticeZone): DrawStep | null {
  return zone === null ? 'eyebrow' : stepForZone(zone);
}

/** Visiting a step keeps it on for the rest of the session. */
export function visit(visited: MakeupZone[], zone: PracticeZone): MakeupZone[] {
  return zone === null || visited.includes(zone) ? visited : [...visited, zone];
}
