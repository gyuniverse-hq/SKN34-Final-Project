import type { FalseLashCluster } from '@/types';

/**
 * Attached lash styles for the look camera, drawn by our renderer with the mascara (AR_SPEC 6-5-5).
 * 11-07: the set follows the seven YouCam eyelash pattern types (Natural, Wispies, Upper, UpperDense,
 * Upper&Lower, Winged, Artistic). Only the type names and shapes are followed: YouCam processes uploaded
 * photos on its server and owns its pattern images, so nothing of theirs is called or copied.
 * u: inner corner 0 to outer corner 1. mm: strand length. Renderer ranges: mm 3-16, strands 1-8.
 */
type Bunch = Omit<FalseLashCluster, 'edge'>;
const upper = (b: Bunch): FalseLashCluster => ({ edge: 'upper', ...b });
const lower = (b: Bunch): FalseLashCluster => ({ edge: 'lower', ...b });

/** YouCam "Upper": even curled bunches over the whole upper lid. */
const UPPER: FalseLashCluster[] = [
  upper({ u: 0.18, mm: 9, strands: 3, spread: 0.05, converge: 0.35, lift: 1.1 }),
  upper({ u: 0.33, mm: 9, strands: 3, spread: 0.05, converge: 0.35, lift: 1.1 }),
  upper({ u: 0.48, mm: 10, strands: 3, spread: 0.05, converge: 0.35, lift: 1.1 }),
  upper({ u: 0.63, mm: 10, strands: 3, spread: 0.05, converge: 0.35, lift: 1.1 }),
  upper({ u: 0.78, mm: 11, strands: 3, spread: 0.05, converge: 0.35, lift: 1.1 }),
  upper({ u: 0.92, mm: 11, strands: 3, spread: 0.05, converge: 0.35, lift: 1.1 }),
];

export const FALSE_LASH_LOOKS = {
  /** YouCam "Natural": short, sparse two-strand bunches, low curl. */
  natural: [
    upper({ u: 0.25, mm: 8, strands: 2, spread: 0.04, converge: 0.2, lift: 0.8 }),
    upper({ u: 0.45, mm: 9, strands: 2, spread: 0.04, converge: 0.2, lift: 0.8 }),
    upper({ u: 0.65, mm: 9, strands: 2, spread: 0.04, converge: 0.2, lift: 0.8 }),
    upper({ u: 0.85, mm: 10, strands: 2, spread: 0.04, converge: 0.2, lift: 0.8 }),
  ],
  /** YouCam "Wispies": uneven lengths, tips pulled together into points. */
  wispies: [
    upper({ u: 0.25, mm: 9, strands: 3, spread: 0.06, converge: 0.75, lift: 1 }),
    upper({ u: 0.42, mm: 11, strands: 3, spread: 0.06, converge: 0.75, lift: 1 }),
    upper({ u: 0.58, mm: 9, strands: 3, spread: 0.06, converge: 0.75, lift: 1 }),
    upper({ u: 0.74, mm: 12, strands: 3, spread: 0.06, converge: 0.75, lift: 1 }),
    upper({ u: 0.9, mm: 10, strands: 3, spread: 0.06, converge: 0.75, lift: 1 }),
  ],
  upper: UPPER,
  /** YouCam "UpperDense": many full bunches, volume over the whole upper lid. */
  upper_dense: [0.12, 0.24, 0.36, 0.48, 0.6, 0.72, 0.84, 0.95].map((u, i) =>
    upper({ u, mm: 10 + Math.min(2, Math.floor(i / 3)), strands: 5, spread: 0.07, converge: 0.3, lift: 1.1 }),
  ),
  /** YouCam "Upper&Lower": the Upper set plus short lower bunches toward the outer corner. */
  upper_lower: [
    ...UPPER,
    lower({ u: 0.4, mm: 5, strands: 2, spread: 0.04, converge: 0.3, lift: 0.8 }),
    lower({ u: 0.6, mm: 6, strands: 2, spread: 0.04, converge: 0.3, lift: 0.8 }),
    lower({ u: 0.8, mm: 6, strands: 2, spread: 0.04, converge: 0.3, lift: 0.8 }),
  ],
  /** YouCam "Winged": lengths grow toward the outer corner, denser bunches there (cat eye). */
  winged: [
    upper({ u: 0.3, mm: 8, strands: 2, spread: 0.05, converge: 0.4, lift: 0.9 }),
    upper({ u: 0.5, mm: 9, strands: 3, spread: 0.05, converge: 0.4, lift: 0.9 }),
    upper({ u: 0.68, mm: 10, strands: 3, spread: 0.06, converge: 0.4, lift: 0.9 }),
    upper({ u: 0.84, mm: 12, strands: 4, spread: 0.07, converge: 0.45, lift: 0.9 }),
    upper({ u: 0.97, mm: 13, strands: 4, spread: 0.07, converge: 0.45, lift: 0.9 }),
  ],
  /** YouCam "Artistic": long dramatic bunches, strongly pointed and curled. Not used by a demo look. */
  artistic: [
    upper({ u: 0.2, mm: 12, strands: 6, spread: 0.07, converge: 0.8, lift: 1.3 }),
    upper({ u: 0.38, mm: 13, strands: 6, spread: 0.07, converge: 0.8, lift: 1.3 }),
    upper({ u: 0.56, mm: 14, strands: 6, spread: 0.07, converge: 0.8, lift: 1.3 }),
    upper({ u: 0.74, mm: 15, strands: 6, spread: 0.07, converge: 0.8, lift: 1.3 }),
    upper({ u: 0.9, mm: 15, strands: 6, spread: 0.07, converge: 0.8, lift: 1.3 }),
  ],
} satisfies Record<string, readonly FalseLashCluster[]>;

export type FalseLashLookId = keyof typeof FALSE_LASH_LOOKS;

export function falseLashClusters(id: FalseLashLookId): FalseLashCluster[] {
  return FALSE_LASH_LOOKS[id].map((cluster) => ({ ...cluster }));
}
