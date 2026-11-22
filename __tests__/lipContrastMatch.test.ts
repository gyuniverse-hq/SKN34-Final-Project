import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';

const html = FACE_TRACKER_HTML;

function materials(): Record<string, Record<string, number>> {
  const start = html.indexOf('const MATERIALS = {');
  const body = html.slice(start, html.indexOf('};', start));
  const out: Record<string, Record<string, number>> = {};
  for (const m of body.matchAll(/^\s*(\w+):\s*\{([^}]*)\}/gm)) {
    out[m[1]] = Object.fromEntries([...m[2].matchAll(/(\w+):\s*([\d.]+)/g)].map((f) => [f[1], Number(f[2])]));
  }
  return out;
}

describe('lip contrast match (plan C, 11-13)', () => {
  it('gives every lip material a contrast-match strength, opacity and overlay share in range', () => {
    const mats = materials();
    expect(Object.keys(mats).sort()).toEqual(['balm', 'cream', 'glossy', 'matte', 'oil', 'satin', 'sheer', 'shimmer', 'velvet']);
    for (const [name, m] of Object.entries(mats)) {
      expect([name, m.shadeMatch >= 0 && m.shadeMatch <= 1]).toEqual([name, true]);
      expect([name, m.opacity >= 0.5 && m.opacity <= 1]).toEqual([name, true]);
      expect([name, m.overlay >= 0 && m.overlay <= 0.5]).toEqual([name, true]);
      expect([name, m.cavity >= 0 && m.cavity <= 3]).toEqual([name, true]);
    }
    // The see-through finish no longer comes out more saturated than matte (sheer chroma 72.6 at 0.65 on the test face).
    expect(mats.sheer.opacity).toBeLessThan(mats.matte.opacity);
  });

  it('registers and sets the new uniforms (an unregistered uniform is silently off)', () => {
    for (const name of ['uDepthMatch', 'uSeamPx', 'uLipOpacity', 'uLipOverlay']) {
      expect(html).toContain(`'${name}'`);
      expect(html).toContain(`gl.uniform`);
      expect(html).toMatch(new RegExp(`gl\\.uniform[12]f\\(u\\.${name},`));
    }
  });

  it('keeps the gap: no seam term on an open mouth or at the corners, and the Overlay layer is on', () => {
    expect(html).toContain("seamW = mouthZone(suv * uViewport).y * (1.0 - uMouthOpen) * (1.0 - smoothstep(0.7, 0.9, along));");
    expect(html).toContain('lipOverlay: true,');
    expect(html).toContain("'      layered = toLin(mix(bs, mix(slt, ovl, ovW), uLipOverlay * cov));',");
    // Lift only, toward the bare lip's own depth: a darker shade (no extra depth) is left as it was.
    expect(html).toContain("'        float lt = lp + sW * max(extra, 0.0);',");
    expect(html).toContain("'    col = colPre + uLipOpacity * (col - colPre);',");
  });
});

describe('crease-following reflection per finish (11-15)', () => {
  it('orders the strength by how much the finish fills the lip lines', () => {
    const m = materials();
    // Velvet and satin show the lines most, a thick clear gloss least.
    expect(m.velvet.cavity).toBeGreaterThan(m.cream.cavity);
    expect(m.satin.cavity).toBeGreaterThan(m.cream.cavity);
    expect(m.glossy.cavity).toBeLessThan(m.cream.cavity);
    expect(m.shimmer.cavity).toBeLessThan(m.cream.cavity);
  });
});
