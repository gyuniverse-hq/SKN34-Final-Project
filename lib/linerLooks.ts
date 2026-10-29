import type { ZoneGeometry } from '@/types';

/** Try-on liner chips: six styles from the same parameters (no drawn template). */
export const LINER_LOOK_IDS = ['natural', 'cat_wing', 'puppy', 'smoky', 'gyaru', 'under_point'] as const;
export type LinerLookId = (typeof LINER_LOOK_IDS)[number];

/**
 * Every chip sets every liner field, so picking one clears what the previous chip left (patches merge).
 * Styles: the plan's thickness multipliers on the default band (0.09 of the eye width), wing length as a
 * share of the eye width, angle in degrees above the eye axis (negative = droopy), smudge 0..1.
 */
const style = (g: ZoneGeometry): ZoneGeometry => ({ linerStyle: 'classic_winged', ...g });

export const LINER_LOOKS: Record<LinerLookId, ZoneGeometry> = {
  natural: style({ thickness: 0.063, length: 0, angle: 0, linerSoftness: 0.2, linerLower: false }),
  cat_wing: style({ thickness: 0.108, length: 0.3, angle: 15, linerSoftness: 0.15, linerLower: false }),
  puppy: style({ linerStyle: 'puppy', thickness: 0.09, length: 0.12, angle: -10, linerSoftness: 0.2, linerLower: false }),
  smoky: style({ thickness: 0.144, length: 0.08, angle: 0, linerSoftness: 0.8, linerLower: true }),
  gyaru: style({ thickness: 0.144, length: 0.35, angle: 12, linerSoftness: 0.15, linerLower: true }),
  under_point: style({ thickness: 0.054, length: 0, angle: 0, linerSoftness: 0.4, linerLower: true }),
};

function near(a: number | undefined, b: number | undefined): boolean {
  return Math.abs((a ?? 0) - (b ?? 0)) < 0.02;
}

export function matchingLinerLook(g?: ZoneGeometry): LinerLookId | null {
  if (!g) return null;
  for (const id of LINER_LOOK_IDS) {
    const s = LINER_LOOKS[id];
    if (!near(g.angle, s.angle) || !near(g.length, s.length) || !near(g.thickness, s.thickness)) continue;
    if (near(g.linerSoftness, s.linerSoftness) && !!g.linerLower === !!s.linerLower) return id;
  }
  return null;
}
