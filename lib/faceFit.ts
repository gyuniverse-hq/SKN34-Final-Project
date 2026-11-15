import type { ContourStyle, HighlighterStyle } from '@/types';

export const HIGHLIGHTER_STYLE_IDS: HighlighterStyle[] = [
  'natural_cheek',
  'glass_c_zone',
  'nose_tip',
  'under_eye_smile',
  'cupid_bow',
  'forehead_center',
];
export const CONTOUR_STYLE_IDS: ContourStyle[] = ['jawline', 'nose'];

/** Placement hints for the measured face (ratio words, not face-shape names). The shape name travels separately (`parseFaceShape`):
 * the shading and, since 11-11, the highlighter panel show it (AR_SPEC 6-5-4). */
export type FaceFitHint = 'cheek_wide' | 'cheek_narrow' | 'face_long' | 'face_short' | 'balanced';
const HINTS: readonly FaceFitHint[] = ['cheek_wide', 'cheek_narrow', 'face_long', 'face_short', 'balanced'];

/** Face shape classes the page can report. A name only: the probability stays on the device (HUD). */
export const FACE_SHAPES = ['round', 'square', 'oblong', 'heart', 'oval'] as const;
export type FaceShape = (typeof FACE_SHAPES)[number];

/** Parses the shape in a `face_fit` message; null when absent or unknown. */
export function parseFaceShape(message: { shape?: unknown }): FaceShape | null {
  return FACE_SHAPES.find((key) => key === message.shape) ?? null;
}

/** Shading state from the page: the default shading is on the screen in every state. */
export const FACE_FIT_STATUSES = ['default', 'analyzing', 'personalized', 'fallback'] as const;
export type FaceFitStatus = (typeof FACE_FIT_STATUSES)[number];

/** Parses a `face_fit_status` message; null when malformed. */
export function parseFaceFitStatus(message: { state?: unknown }): FaceFitStatus | null {
  return FACE_FIT_STATUSES.find((key) => key === message.state) ?? null;
}

/** Parses the page's `face_fit` message (ratios and hint keys only); null when malformed. */
export function parseFaceFit(message: { rec?: unknown }): FaceFitHint[] | null {
  if (!Array.isArray(message.rec)) return null;
  const rec = message.rec.filter((key): key is FaceFitHint => HINTS.includes(key as FaceFitHint));
  return rec.length ? rec : null;
}
