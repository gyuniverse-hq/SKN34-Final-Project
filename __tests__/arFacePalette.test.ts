import { HIGHLIGHTER_AREAS, toggleHighlighterArea } from '@/lib/arFacePalette';

describe('AR face palette', () => {
  it('toggles highlighter areas and keeps at least one on', () => {
    expect(toggleHighlighterArea(undefined, 'chin')).toEqual(['forehead', 'nose_bridge', 'under_eye']);
    expect(toggleHighlighterArea(['forehead'], 'nose_bridge')).toEqual(['forehead', 'nose_bridge']);
    expect(toggleHighlighterArea(['forehead'], 'forehead')).toEqual(['forehead']);
    expect(toggleHighlighterArea(['forehead', 'nose_bridge', 'under_eye'], 'chin')).toEqual(HIGHLIGHTER_AREAS);
    expect(HIGHLIGHTER_AREAS).toHaveLength(4);
  });
});
