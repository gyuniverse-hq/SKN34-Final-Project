import type { HighlightArea, HighlightFace, ZoneGeometry } from '@/types';

/** Highlighter region chips, in the order of the reference chart (forehead → chin), cheekbone last (11-11). */
export const HIGHLIGHTER_AREAS: HighlightArea[] = ['forehead', 'under_eye', 'nose_bridge', 'philtrum', 'chin', 'cheekbone'];

/** Face-type chips: the five measurable shapes, then gaunt (user pick only). */
export const HIGHLIGHT_FACES: HighlightFace[] = ['round', 'square', 'oblong', 'oval', 'heart', 'gaunt'];

/**
 * Regions each face type turns on (11-11 user reference chart "얼굴형별 하이라이트 방법"). The page keeps the same table
 * (`HL_FACE_AREAS` in faceTrackerHtml.ts, a test compares them). Oval = the base positions every face shares.
 */
export const HL_FACE_AREAS: Record<HighlightFace, HighlightArea[]> = {
  round: ['forehead', 'nose_bridge', 'chin'],
  square: ['forehead', 'under_eye', 'nose_bridge', 'chin'],
  oblong: ['forehead', 'under_eye', 'philtrum', 'chin', 'cheekbone'],
  oval: ['forehead', 'under_eye', 'nose_bridge', 'philtrum', 'chin'],
  heart: ['forehead', 'under_eye', 'nose_bridge', 'chin'],
  gaunt: ['forehead', 'under_eye', 'nose_bridge', 'chin', 'cheekbone'],
};

/** Face type the layout follows: the user's pick, else the measured shape, else oval (the shared base positions). */
export function highlighterFaceOf(geometry: ZoneGeometry | undefined, measured: HighlightFace | null): HighlightFace {
  if (geometry?.hlFace && HIGHLIGHT_FACES.includes(geometry.hlFace)) return geometry.hlFace;
  return measured && HIGHLIGHT_FACES.includes(measured) ? measured : 'oval';
}

/** Regions painted now: the user's own set, else the face type's. Exactly what the page draws, so the chips match it. */
export function effectiveHighlighterAreas(geometry: ZoneGeometry | undefined, measured: HighlightFace | null): HighlightArea[] {
  const own = geometry?.areas?.filter((a) => HIGHLIGHTER_AREAS.includes(a));
  return own && own.length > 0 ? own : HL_FACE_AREAS[highlighterFaceOf(geometry, measured)];
}

/** Turns one region on or off in the set that is painted now; at least one region stays on. */
export function toggleHighlighterArea(current: HighlightArea[], area: HighlightArea): HighlightArea[] {
  const next = current.includes(area) ? current.filter((item) => item !== area) : [...current, area];
  if (next.length === 0) return [area];
  return HIGHLIGHTER_AREAS.filter((a) => next.includes(a));
}
