import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { FACE_MOUTH_TRIANGLES, FACE_TRIANGLES, FACE_UV } from '@/components/ar/faceUV';

const INNER_LIPS = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95];
const LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246];
const RIGHT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466];

describe('face mesh UV data (AR_SPEC 6-4)', () => {
  it('has a UV for each of the 468 mesh vertices, inside the unit square', () => {
    expect(FACE_UV).toHaveLength(468 * 2);
    for (const v of FACE_UV) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });

  it('only indexes mesh vertices (no iris points)', () => {
    expect(FACE_TRIANGLES.length % 3).toBe(0);
    for (const i of FACE_TRIANGLES) {
      expect(Number.isInteger(i)).toBe(true);
      expect(i).toBeGreaterThanOrEqual(0);
      expect(i).toBeLessThan(468);
    }
  });

  it.each([
    ['mouth', INNER_LIPS],
    ['left eye', LEFT_EYE],
    ['right eye', RIGHT_EYE],
  ])('leaves the %s open so it is never painted', (_, contour) => {
    const set = new Set(contour);
    for (let t = 0; t < FACE_TRIANGLES.length; t += 3) {
      const tri = FACE_TRIANGLES.slice(t, t + 3);
      expect(tri.every((v) => set.has(v))).toBe(false);
    }
  });

  it('keeps the mouth hole separately, for closed lips only', () => {
    const inner = new Set(INNER_LIPS);
    expect(FACE_MOUTH_TRIANGLES.length).toBeGreaterThan(0);
    expect(FACE_MOUTH_TRIANGLES.length % 3).toBe(0);
    for (const v of FACE_MOUTH_TRIANGLES) expect(inner.has(v)).toBe(true);
  });

  it('is embedded in the AR page', () => {
    expect(FACE_TRACKER_HTML).toContain(JSON.stringify(FACE_TRIANGLES));
    expect(FACE_TRACKER_HTML).toContain(JSON.stringify(FACE_UV));
    expect(FACE_TRACKER_HTML).toContain(JSON.stringify(FACE_MOUTH_TRIANGLES));
  });
});
