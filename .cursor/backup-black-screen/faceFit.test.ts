import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { CONTOUR_STYLE_IDS, HIGHLIGHTER_STYLE_IDS, parseFaceFit } from '@/lib/faceFit';

const script = FACE_TRACKER_HTML;

describe('face-fit hints', () => {
  it('keeps only known hint keys and rejects malformed messages', () => {
    expect(parseFaceFit({ rec: ['cheek_wide', 'face_long'] })).toEqual(['cheek_wide', 'face_long']);
    expect(parseFaceFit({ rec: ['round_face', 'balanced'] })).toEqual(['balanced']);
    expect(parseFaceFit({ rec: ['oval'] })).toBeNull();
    expect(parseFaceFit({})).toBeNull();
  });
});

describe('face-fit page', () => {
  it('has a template for every style id the app offers', () => {
    for (const id of HIGHLIGHTER_STYLE_IDS) expect(script).toContain('    ' + id + ': [');
    for (const id of CONTOUR_STYLE_IDS) expect(script).toContain('    ' + id + ': [');
    expect(CONTOUR_STYLE_IDS).toEqual(['jawline', 'nose']);
    expect(script).toContain("t: 'band'");
  });

  it('measures on frontal frames, freezes, and sends ratios and hint keys only', () => {
    expect(script).toContain('TUNING.faceFitYaw[0]');
    expect(script).toContain("post({ type: 'face_fit', ratios:");
    expect(script).not.toMatch(/face_fit[^\n]*(landmarks|image|frame)/);
  });

  it('redraws only when the style or the measurement changes, and leaves the default layers alone otherwise', () => {
    expect(script).toContain('if (key !== faceFitKey && masks && masks.repaintHlContour)');
    expect(script).toContain('const h = hlT ? layer(() => drawTemplate(hlT, fit), TUNING.hlFeatherPx) : highlight;');
    expect(script).toContain("const k = coT ? layer(() => drawTemplate(coT, fit), contourStyle === 'jawline' ? 10 : TUNING.contourFeatherPx) : contour;");
  });

  it('extends jawline shading only past 234 and 454, and only on face skin', () => {
    expect(script).toContain('jawHingeMax: 0.55');
    expect(script).toContain('const JAW_HINGE = [{ v: 234, cheek: 50 }, { v: 132, cheek: 50 }, { v: 454, cheek: 280 }, { v: 361, cheek: 280 }];');
    expect(script).toContain('if (uJawCap > 0.5)');
    expect(script).toContain("const jawCapOn = !!(contourZ && contourZ.geometry && contourZ.geometry.contourStyle === 'jawline');");
    expect(script).toContain('if (jawCapOn && foundSkinReady && jawAb !== 1)');
    expect(script).toContain('if (uJawCullOn > 0.5)');
    expect(script).toContain('const jawYaw = (sz[234] - sz[454]) / jawSpan;');
    expect(script).toContain('if (jawYaw < 0.12 && jawHingeOn[0] > 0) gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);');
    expect(script).toContain('if (jawYaw > -0.12 && jawHingeOn[1] > 0) gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 12);');
    expect(script).toContain("const jawline = makeup.contour && makeup.contour.geometry && makeup.contour.geometry.contourStyle === 'jawline';");
    expect(script).toContain('function jawHingeAllow(qx, qy, side)');
    expect(script).toContain('if (foundSkinBin[py * foundSkinW + px] < 80) return false;');
    expect(script).toContain('const ear = side ? 454 : 234;');
    expect(script).toContain('return qy >= sy[ear];');
    expect(script).toContain('foundSkinBin[i] = Math.round(t * t * (3 - 2 * t) * (cat[i] === 1 ? 0 : 1) * 255);');
    expect(script).toContain('if (uFoundSkinOn > 0.5) contourA *= texture2D(uFoundSkin, suv).r;');
    expect(script).not.toMatch(/JAW_HINGE[\s\S]{0,240}\b152\b/);
  });

  it('keeps jawline fill past the oval fade so the ear-side band is not zeroed', () => {
    expect(script).toContain("ids: [132, 58, 172, 136, 150, 149, 176, 148, 152]");
    expect(script).toContain('insets: [0.42, 0.40, 0.34, 0.28, 0.22, 0.18, 0.15, 0.13, 0.12]');
    expect(script).not.toContain('ids: [234, 132,');
    expect(script).toContain('jawHingeOn[side] = bestT > 0.08 ? 1 : 0;');
    expect(script).toContain("toward: 50");
    expect(script).toContain("const jawEdge = contourStyle === 'jawline';");
    expect(script).toContain('rgba2[i * 4 + 1] = Math.round(clamp01(k[i] * (jawEdge ? 1 : inside)) * 255);');
    expect(script).toContain('rgba2[i * 4] = Math.round(clamp01(h[i] * inside) * 255);');
    expect(script).toContain('jawUv[i * 4] = 0;');
    expect(script).toContain('jawUv[i * 4 + 2] = 0.9;');
  });

  it('never names a face shape', () => {
    expect(script).not.toMatch(/\b(round|oval|heart|square|diamond)_?face\b/i);
  });

  it('keeps the volume terms off by default and gates the light direction by its confidence', () => {
    expect(script).toContain('hlContourVolume: false');
    expect(script).toContain('TUNING.hlContourVolume ? TUNING.volumeGain[0] : 0');
    expect(script).toContain('uLightConf * uVolLight');
    expect(script).toContain('contourA *= clamp(1.0 + uVolume.x * (0.7 - volFace), 0.6, 1.5);');
  });
});
