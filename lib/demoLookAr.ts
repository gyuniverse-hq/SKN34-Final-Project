import type { MascaraLookId } from '@/lib/mascaraLooks';
import type { MakeupZone } from '@/types';

/** One catalog shade per AR zone. Hexes come from catalog.json, not from this file. */
export type DemoLookSlot = {
  zone: MakeupZone;
  productId: string;
  shadeId: string;
  /** Closed mascara shape from the video product type (not measured from frames). */
  style?: MascaraLookId;
};

/**
 * Six demo looks from the 2026-11-04 AR try-on sheet (3 K-style, 3 K-celebrity).
 * These are catalog product+shade pairs for painting, not mappingVerified reviews.
 * Mascara slots use catalog shades that already store a hex (look camera only).
 */
export const DEMO_LOOK_AR: Record<string, DemoLookSlot[]> = {
  'ZAozXs-ZZik': [
    { zone: 'foundation', productId: 'oy-a000000233171', shadeId: '19nc' },
    { zone: 'contour', productId: 'oy-a000000201055', shadeId: '02-2' },
    { zone: 'brow', productId: 'oy-a000000138671', shadeId: '09' },
    { zone: 'eyeliner', productId: 'oy-a000000199182', shadeId: '05' },
    // Video SKU (neozen) has no stored hex; catalog mascara with a black shade.
    { zone: 'mascara', productId: 'oy-a000000255697', shadeId: '01', style: 'slim' },
    { zone: 'lip', productId: 'oy-a000000230581', shadeId: '14' },
  ],
  '4QR0tre9yBI': [
    { zone: 'foundation', productId: 'oy-a000000209870', shadeId: '21c' },
    { zone: 'contour', productId: 'oy-a000000145650', shadeId: '1' },
    { zone: 'eyeliner', productId: 'oy-a000000203438', shadeId: '02' },
    { zone: 'mascara', productId: 'oy-a000000198027', shadeId: '01', style: 'long' },
    { zone: 'lip', productId: 'oy-a000000187536', shadeId: '04' },
  ],
  'kWI7_DkDjZ0': [
    { zone: 'foundation', productId: 'oy-a000000247764', shadeId: '20-2' },
    { zone: 'highlighter', productId: 'oy-a000000234040', shadeId: '02' },
    { zone: 'eyeshadow', productId: 'oy-a000000250307', shadeId: '06' },
    { zone: 'mascara', productId: 'oy-a000000205718', shadeId: 'a000000205718-006', style: 'fine' },
    { zone: 'lip', productId: 'oy-a000000247262', shadeId: '03' },
  ],
  n5otfjJSSQc: [
    { zone: 'foundation', productId: 'oy-a000000251851', shadeId: '23n' },
    { zone: 'contour', productId: 'oy-a000000176894', shadeId: '02' },
    { zone: 'blush', productId: 'oy-a000000137964', shadeId: '16' },
    { zone: 'brow', productId: 'oy-a000000154277', shadeId: '02' },
    { zone: 'eyeshadow', productId: 'oy-a000000174309', shadeId: 'a000000174309-114' },
    { zone: 'eyeliner', productId: 'oy-a000000171017', shadeId: '01' },
    { zone: 'mascara', productId: 'oy-a000000185925', shadeId: '02', style: 'volume_skinny' },
    { zone: 'lip', productId: 'oy-a000000197341', shadeId: 'a000000197341-011' },
  ],
  e1gSkUdG6Bo: [
    { zone: 'contour', productId: 'oy-a000000180297', shadeId: '03' },
    { zone: 'highlighter', productId: 'oy-a000000232152', shadeId: '02' },
    { zone: 'blush', productId: 'oy-a000000225392', shadeId: '8' },
    { zone: 'brow', productId: 'oy-a000000138671', shadeId: '03' },
    { zone: 'eyeshadow', productId: 'oy-a000000168405', shadeId: '09' },
    { zone: 'eyeliner', productId: 'oy-a000000011412', shadeId: '02' },
    { zone: 'mascara', productId: 'oy-a000000185925', shadeId: '02', style: 'long_curl' },
    { zone: 'lip', productId: 'oy-a000000233656', shadeId: '01' },
  ],
  fDqBPI1SaWY: [
    { zone: 'foundation', productId: 'oy-a000000207117', shadeId: '01' },
    { zone: 'contour', productId: 'oy-a000000201055', shadeId: '02-2' },
    { zone: 'blush', productId: 'oy-a000000225392', shadeId: '04' },
    { zone: 'brow', productId: 'oy-a000000148567', shadeId: 'a000000148567-006' },
    { zone: 'eyeshadow', productId: 'oy-a000000174310', shadeId: 'a000000174310-009' },
    { zone: 'mascara', productId: 'oy-a000000255697', shadeId: '01', style: 'slim' },
    { zone: 'lip', productId: 'oy-a000000223676', shadeId: '02' },
  ],
};

export function demoLookVideoId(lookId: string): string {
  return lookId.replace(/^(celebrity|style)-/, '');
}

export function demoLookSlots(lookId: string): DemoLookSlot[] {
  return DEMO_LOOK_AR[demoLookVideoId(lookId)] ?? [];
}
