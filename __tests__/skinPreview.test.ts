import { SkinPreviewAssembler, skinPreviewHtml } from '@/lib/skinPreview';
import type { SkinBox, SkinPoint, SkinPreview } from '@/types/skin';

const outline: SkinPoint[] = Array.from({ length: 36 }, (_, i) => [0.5 + 0.3 * Math.cos(i * Math.PI / 18), 0.5 + 0.3 * Math.sin(i * Math.PI / 18)]);
const boxes: SkinBox[] = Array.from({ length: 6 }, (_, i) => [i / 10, .1, i / 10 + .1, .4]);
const start = { type: 'preview-start' as const, runId: 'test', width: 100, height: 200, outline, boxes, length: 4 };
const preview: SkinPreview = { runId: 'test', width: 100, height: 200, outline, boxes, jpeg: '/9j/' };

it('assembles only bounded, ordered, matching preview data', () => {
  const receiver = new SkinPreviewAssembler('test');
  receiver.push(start);
  receiver.push({ type: 'preview-chunk', runId: 'test', index: 0, data: '/9j/' });
  expect(receiver.push({ type: 'preview-end', runId: 'test' })).toEqual(preview);
  expect(() => receiver.push({ ...start, runId: 'other' })).toThrow();
  expect(() => receiver.push({ ...start, boxes: [[-1, 0, 1, 1]] })).toThrow();
  receiver.push(start);
  expect(() => receiver.push({ type: 'preview-chunk', runId: 'test', index: 1, data: '/9j/' })).toThrow();
  receiver.clear();
  expect(() => receiver.push({ type: 'preview-end', runId: 'test' })).toThrow();
});

it('clips actual model crops to the face outline and draws no invented survey or acne regions', () => {
  const html = skinPreviewHtml(preview, 'pores');
  expect(html).toContain('clip-path="url(#face)"');
  expect(html).toContain('<polygon points=');
  expect((html.match(/<rect /g) || [])).toHaveLength(2);
  expect(html).toContain('fill-opacity=".45"');
  expect(html).toContain('<feGaussianBlur');
  expect(html).toContain('clip-path="url(#crop4)"');
  expect(html).toMatch(/<rect [^>]*rx="[\d.]+" filter="url\(#feather4\)"/);
  expect((skinPreviewHtml(preview, 'pigmentation').match(/<rect /g) || [])).toHaveLength(3);
  expect((skinPreviewHtml(preview, 'wrinkles').match(/<rect /g) || [])).toHaveLength(4);
  expect((skinPreviewHtml(preview, 'dryness').match(/<rect /g) || [])).toHaveLength(3);
  for (const concern of ['blemish', 'oiliness', 'sensitivity']) expect(skinPreviewHtml(preview, concern)).not.toContain('<rect ');
  expect(html).toContain("default-src 'none'; img-src data:");
  expect(html).not.toContain('http:');
});

it('increases crop feathering by 20% and fades before both crop and face clipping', () => {
  const html = skinPreviewHtml({ ...preview, width: 1000, height: 1000,
    boxes: Array(6).fill([.1, .1, .3, .3]) }, 'pores');
  // A 200 px crop: sigma 20 -> 24 px; inset 48 px keeps the blur tail faint at the clip.
  const cropFilter = html.match(/<filter id="feather4"[^>]*><feGaussianBlur stdDeviation="([\d.]+)"/);
  expect(Number(cropFilter?.[1])).toBeCloseTo(24);
  expect(html).toContain('x="148" y="148"');
  expect(html).toContain('mask="url(#faceFade)"');
  expect(html).toContain('<feMorphology operator="erode"');
});
