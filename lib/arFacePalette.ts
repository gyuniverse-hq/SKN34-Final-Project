import type { HighlightArea } from '@/types';

export const HIGHLIGHTER_AREAS: HighlightArea[] = ['forehead', 'nose_bridge', 'under_eye', 'chin'];

export function toggleHighlighterArea(
  current: HighlightArea[] | undefined,
  area: HighlightArea
): HighlightArea[] | undefined {
  const on = current && current.length > 0 ? current : HIGHLIGHTER_AREAS;
  const next = on.includes(area) ? on.filter((item) => item !== area) : [...on, area];
  if (next.length === 0) return [area];
  return next;
}
