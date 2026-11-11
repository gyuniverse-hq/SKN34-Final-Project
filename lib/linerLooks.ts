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

/**
 * Liner shapes read from the six demo looks' finished-look eye photos (user, 11-11). Look recipes only: they are not try-on
 * chips (LINER_LOOK_IDS stays the six chips above). thickness = outer thickness / eye width, length = wing length / eye
 * width, angle in degrees (negative = droopy); values are visual estimates (about +-30%). Colour is always the look's own product.
 * 청초 물복숭아 has no liner in its video, so it has no entry.
 */
export const LOOK_LINERS = {
  /** 설윤 뿌까: bold, long wing swept up. */
  sullyoon_wing: style({ thickness: 0.13, length: 0.28, angle: 18, linerSoftness: 0.1, linerLower: false }),
  /** 딸기 토끼상: thin smudged line whose end droops a little. */
  strawberry_droop: style({ linerStyle: 'puppy', thickness: 0.07, length: 0.06, angle: -8, linerSoftness: 0.45, linerLower: false }),
  /** 연말 수상템: thin brown line, short wing. */
  yearend_brown: style({ thickness: 0.06, length: 0.1, angle: 8, linerSoftness: 0.3, linerLower: false }),
  /** 카리나 멧갈라: medium wing. */
  karina_wing: style({ thickness: 0.09, length: 0.14, angle: 8, linerSoftness: 0.2, linerLower: false }),
  /** 윈터 또렷 청초: thin dark-brown line, short wing. */
  winter_wing: style({ thickness: 0.07, length: 0.12, angle: 12, linerSoftness: 0.25, linerLower: false }),
} satisfies Record<string, ZoneGeometry>;
export type LookLinerId = keyof typeof LOOK_LINERS;
export const LOOK_LINER_IDS = Object.keys(LOOK_LINERS) as LookLinerId[];

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
