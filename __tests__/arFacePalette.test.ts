import {
  effectiveHighlighterAreas,
  HIGHLIGHT_FACES,
  HIGHLIGHTER_AREAS,
  HL_FACE_AREAS,
  highlighterFaceOf,
  toggleHighlighterArea,
} from '@/lib/arFacePalette';
import { FACE_SHAPES } from '@/lib/faceFit';
import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';

describe('AR face palette', () => {
  it('toggles a region in the painted set, keeps at least one on and keeps the chip order', () => {
    expect(toggleHighlighterArea(['forehead', 'nose_bridge', 'chin'], 'chin')).toEqual(['forehead', 'nose_bridge']);
    expect(toggleHighlighterArea(['chin'], 'forehead')).toEqual(['forehead', 'chin']);
    expect(toggleHighlighterArea(['forehead'], 'forehead')).toEqual(['forehead']);
    expect(HIGHLIGHTER_AREAS).toEqual(['forehead', 'under_eye', 'nose_bridge', 'philtrum', 'chin', 'cheekbone']);
  });

  // 11-11 user chart "얼굴형별 하이라이트 방법" and "하이라이트 기본 위치".
  it('turns on the regions of the reference chart for each face type', () => {
    expect(HL_FACE_AREAS.round).toEqual(['forehead', 'nose_bridge', 'chin']);
    expect(HL_FACE_AREAS.square).toEqual(['forehead', 'under_eye', 'nose_bridge', 'chin']);
    expect(HL_FACE_AREAS.oblong).toEqual(['forehead', 'under_eye', 'philtrum', 'chin', 'cheekbone']);
    expect(HL_FACE_AREAS.oval).toEqual(['forehead', 'under_eye', 'nose_bridge', 'philtrum', 'chin']);
    expect(HL_FACE_AREAS.heart).toEqual(['forehead', 'under_eye', 'nose_bridge', 'chin']);
    expect(HL_FACE_AREAS.gaunt).toEqual(['forehead', 'under_eye', 'nose_bridge', 'chin', 'cheekbone']);
    // Every shape the page can measure has a layout; gaunt is a user pick only.
    for (const shape of FACE_SHAPES) expect(HIGHLIGHT_FACES).toContain(shape);
    expect(FACE_SHAPES).not.toContain('gaunt' as never);
  });

  it('follows the user pick, else the measured shape, else oval; the chips show exactly the painted set', () => {
    expect(highlighterFaceOf(undefined, null)).toBe('oval');
    expect(highlighterFaceOf(undefined, 'round')).toBe('round');
    expect(highlighterFaceOf({ hlFace: 'gaunt' }, 'round')).toBe('gaunt');
    expect(effectiveHighlighterAreas(undefined, 'round')).toEqual(HL_FACE_AREAS.round);
    expect(effectiveHighlighterAreas({ hlFace: 'oblong' }, 'round')).toEqual(HL_FACE_AREAS.oblong);
    expect(effectiveHighlighterAreas({ areas: ['chin'] }, 'round')).toEqual(['chin']);
    expect(effectiveHighlighterAreas({ areas: [] }, null)).toEqual(HL_FACE_AREAS.oval);
  });

  it('keeps the page table identical to the app table (the page draws what the chips show)', () => {
    const block = FACE_TRACKER_HTML.match(/const HL_FACE_AREAS = \{([\s\S]*?)\};/);
    expect(block).not.toBeNull();
    const page = new Function(`return {${(block as RegExpMatchArray)[1]}};`)() as Record<string, string[]>;
    expect(page).toEqual(HL_FACE_AREAS);
    expect(FACE_TRACKER_HTML).toContain(`const HL_AREA_IDS = ${JSON.stringify(HIGHLIGHTER_AREAS).replace(/"/g, "'").replace(/,/g, ', ')};`);
  });
});
