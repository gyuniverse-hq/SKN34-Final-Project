import { LINER_LOOKS, LOOK_LINERS, type LinerLookId, type LookLinerId } from '@/lib/linerLooks';
import { MASCARA_LOOKS, mascaraGeometry, type MascaraLookId } from '@/lib/mascaraLooks';
import type {
  BlushPlacement,
  ContourStyle,
  HighlighterStyle,
  MakeupZone,
  ShadowFinish,
  ZoneGeometry,
} from '@/types';

const HL: HighlighterStyle[] = [
  'natural_cheek',
  'glass_c_zone',
  'nose_tip',
  'under_eye_smile',
  'cupid_bow',
  'forehead_center',
];
const CO: ContourStyle[] = ['jawline', 'nose'];
const BLUSH: BlushPlacement[] = ['apple', 'under_eye', 'side'];
const SHADOW: ShadowFinish[] = ['matte', 'shimmer', 'glitter', 'glossy'];
const LINER = Object.keys(LINER_LOOKS) as LinerLookId[];
const LOOK_LINER = Object.keys(LOOK_LINERS) as LookLinerId[];
const MASCARA = Object.keys(MASCARA_LOOKS) as MascaraLookId[];

function has<T extends string>(ids: readonly T[], style: string): style is T {
  return (ids as readonly string[]).includes(style);
}

/** Same mapping as backend `geometry_for_style` (look recipe step 5). */
export function geometryFromStyle(zone: MakeupZone, style: string): ZoneGeometry | null {
  if (zone === 'highlighter' && has(HL, style)) return { hlStyle: style };
  if (zone === 'contour' && has(CO, style)) return { contourStyle: style };
  if (zone === 'eyeliner' && has(LINER, style)) return { ...LINER_LOOKS[style] };
  if (zone === 'eyeliner' && has(LOOK_LINER, style)) return { ...LOOK_LINERS[style] };
  if (zone === 'blush' && has(BLUSH, style)) return { blushPlacement: style };
  if (zone === 'eyeshadow' && has(SHADOW, style)) return { shadowFinish: style };
  if (zone === 'lip' && style === 'full') return { overlip: 0 };
  if (zone === 'lip' && style === 'overlip') return { overlip: 0.03, peakOverdraw: 0.02 };
  if (zone === 'lip' && style === 'center_glow') return { centerHighlight: 0.15 };
  if (zone === 'mascara' && has(MASCARA, style)) return mascaraGeometry(style);
  return null;
}
