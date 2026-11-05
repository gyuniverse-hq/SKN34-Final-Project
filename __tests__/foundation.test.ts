import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { MIN_TONE_CONF, parseSkinTone, rankFoundationShades } from '@/lib/foundationMatch';
import type { Product, Shade } from '@/types';

const shade = (id: string, hex: string): Shade => ({ id, name: id, hex });
const product = { id: 'found', name: 'Foundation', makeupZone: 'foundation', texture: 'matte' } as unknown as Product;
const options = [shade('ivory', '#F3E0D0'), shade('beige', '#E6C7A8'), shade('sand', '#D2A679'), shade('tan', '#A8754F')].map(
  (s) => ({ product, shade: s })
);

describe('foundation in the AR page', () => {
  it('lays the color on by coverage: opaque pigment vs translucent film, no sheen or finish', () => {
    const html = FACE_TRACKER_HTML;
    expect(html).toContain("'    col = mix(col, mix(film, pigment, uFoundOpaque), foundA);',");
    expect(html).toContain("'    vec3 pigment = layer(cam, uFoundAlbedo, uSkinMeanLum, uFoundShadeMax);',");
    expect(html).not.toContain('powder(cam, uFoundAlbedo)');
    // The zone intensity is the coverage slider; the finish (texture) of a foundation product is never read.
    expect(html).toContain('const foundC = foundZ ? clamp01(foundZ.intensity) : 0;');
    expect(html).not.toMatch(/material\(foundZ\)|foundZ\.texture/);
    expect(html).toContain('foundCoverage: [0.3, 0.85],');
    expect(html).toContain('foundOpaque: [0.15, 0.9],');
  });

  it('glides the light values the shader sees instead of stepping every 0.5 s', () => {
    const html = FACE_TRACKER_HTML;
    expect(html).toContain('const shown = glideLight(performance.now());');
    expect(html).toContain('gl.uniform3f(u.uLightColor, shown.color[0], shown.color[1], shown.color[2]);');
    expect(html).toContain('gl.uniform1f(u.uSkinMeanLum, shown.skinMeanLum);');
    expect(html).toContain('const k = dt === Infinity ? 1 : 1 - Math.exp(-Math.max(0, dt) / TUNING.lightDisplaySec);');
    // A new face starts from its own light.
    expect(html).toContain('shownLight.t = 0;');
  });

  it('sends only skin-tone numbers to the app', () => {
    const html = FACE_TRACKER_HTML;
    const fn = html.slice(html.indexOf('function postSkinTone'), html.indexOf('let lastLightHint'));
    expect(fn).toContain("post({ type: 'skin_tone', lab: lab.map((v) => Math.round(v * 10) / 10), conf: Math.round(w * 100) / 100 });");
    expect(fn).not.toMatch(/fetch|XMLHttpRequest|localStorage|toDataURL|getImageData/);
  });
});

describe('foundation shade suggestion', () => {
  it('ranks only the given shades, closest to the measured skin first', () => {
    const ranked = rankFoundationShades({ L: 80, a: 6, b: 18, conf: 1 }, options);
    expect(ranked.map((m) => m.shade.id)).toEqual(['beige', 'ivory', 'sand', 'tan']);
    expect(ranked[0].deltaE).toBeLessThan(ranked[1].deltaE);
    expect(rankFoundationShades({ L: 52, a: 14, b: 25, conf: 1 }, options)[0].shade.id).toBe('tan');
  });

  it('reports whether the shade is lighter or darker than the skin', () => {
    const [best] = rankFoundationShades({ L: 60, a: 12, b: 26, conf: 1 }, options.slice(0, 2));
    expect(best.deltaL).toBeGreaterThan(0);
  });

  it('parses the page message and rejects malformed numbers', () => {
    expect(parseSkinTone({ lab: [70, 10, 20], conf: 0.8 })).toEqual({ L: 70, a: 10, b: 20, conf: 0.8 });
    expect(parseSkinTone({ lab: [70, 10], conf: 1 })).toBeNull();
    expect(parseSkinTone({ lab: [70, Number.NaN, 20] })).toBeNull();
    expect(parseSkinTone({ lab: [70, 10, 20], conf: 5 })?.conf).toBe(1);
    expect(MIN_TONE_CONF).toBeGreaterThan(0);
  });
});
