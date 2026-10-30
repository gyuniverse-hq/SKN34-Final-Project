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

it('clips only actual model crops to the face outline and draws no invented survey or acne regions', () => {
  const html = skinPreviewHtml(preview, 'pores');
  expect(html).toContain('clip-path="url(#face)"');
  expect(html).toContain('<polygon points=');
  expect((html.match(/<rect /g) || [])).toHaveLength(2);
  expect((skinPreviewHtml(preview, 'pigmentation').match(/<rect /g) || [])).toHaveLength(3);
  expect((skinPreviewHtml(preview, 'wrinkles').match(/<rect /g) || [])).toHaveLength(4);
  for (const concern of ['blemish', 'dryness', 'oiliness', 'sensitivity']) expect(skinPreviewHtml(preview, concern)).not.toContain('<rect ');
  expect(html).toContain("default-src 'none'; img-src data:");
  expect(html).not.toContain('http:');
});
