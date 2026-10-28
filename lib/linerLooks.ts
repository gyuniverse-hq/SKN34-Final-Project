import type { ZoneGeometry } from '@/types';

/** Try-on liner shape: lid wing and lash-line wing. */
export const LINER_LOOK_IDS = ['lid', 'line'] as const;
export type LinerLookId = (typeof LINER_LOOK_IDS)[number];

export const LINER_LOOKS: Record<LinerLookId, ZoneGeometry> = {
  lid: { linerStyle: 'classic_winged', angle: 17, length: 0.25, thickness: 0.15 },
  line: { linerStyle: 'classic_winged', angle: 24, length: 0.20, thickness: 0.05 },
};

function near(a: number | undefined, b: number | undefined): boolean {
  return Math.abs((a ?? 0) - (b ?? 0)) < 0.02;
}

export function matchingLinerLook(g?: ZoneGeometry): LinerLookId | null {
  if (!g) return null;
  for (const id of LINER_LOOK_IDS) {
    const p = LINER_LOOKS[id];
    if (near(g.angle, p.angle) && near(g.length, p.length) && near(g.thickness, p.thickness)) return id;
  }
  return null;
}
