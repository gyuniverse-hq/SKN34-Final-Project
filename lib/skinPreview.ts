import type { SkinBox, SkinPoint, SkinPreview, SkinWebEvent } from '@/types/skin';

const CHUNK_SIZE = 48 * 1024;
const MAX_CHARS = 4 * 1024 * 1024;
type PreviewEvent = Extract<SkinWebEvent, { type: 'preview-start' | 'preview-chunk' | 'preview-end' }>;
const coordinate = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;

/** Temporary, bounded handoff. Never put the image into a persisted profile or a request. */
export class SkinPreviewAssembler {
  private meta?: Extract<PreviewEvent, { type: 'preview-start' }>;
  private chunks: string[] = [];
  private received = 0;
  constructor(private readonly runId: string) {}
  clear() { this.meta = undefined; this.chunks = []; this.received = 0; }
  push(event: PreviewEvent): SkinPreview | undefined {
    if (event.runId !== this.runId) throw new Error('preview');
    if (event.type === 'preview-start') {
      if (this.meta || !Number.isInteger(event.length) || event.length <= 0 || event.length > MAX_CHARS || event.length % 4 ||
          !Number.isInteger(event.width) || !Number.isInteger(event.height) || event.width < 1 || event.height < 1 ||
          event.width > 10000 || event.height > 10000 || !Array.isArray(event.outline) || event.outline.length !== 36 ||
          event.outline.some(p => !Array.isArray(p) || p.length !== 2 || !p.every(coordinate)) ||
          !Array.isArray(event.boxes) || event.boxes.length !== 6 || event.boxes.some(b =>
            !Array.isArray(b) || b.length !== 4 || !b.every(coordinate) || b[0] >= b[2] || b[1] >= b[3])) throw new Error('preview');
      this.meta = event;
    } else if (event.type === 'preview-chunk') {
      if (!this.meta || event.index !== this.chunks.length || typeof event.data !== 'string' ||
          !event.data.length || event.data.length > CHUNK_SIZE || event.data.length % 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(event.data) ||
          this.received + event.data.length > this.meta.length) throw new Error('preview');
      this.received += event.data.length; this.chunks.push(event.data);
    } else {
      if (!this.meta || this.received !== this.meta.length) throw new Error('preview');
      const jpeg = this.chunks.join('');
      if (!jpeg.startsWith('/9j/')) throw new Error('preview');
      const { runId, width, height, outline, boxes } = this.meta;
      this.clear();
      return { runId, width, height, outline: outline as SkinPoint[], boxes: boxes as SkinBox[], jpeg };
    }
  }
}

/** SVG uses the same image dimensions for the image, face contour and exact model crops. */
export function skinPreviewHtml(preview: SkinPreview, concern: string): string {
  const areas: Record<string, number[]> = { pores: [4, 5], pigmentation: [0, 4, 5], wrinkles: [0, 1, 2, 3] };
  const polygon = preview.outline.map(([x, y]) => `${x * preview.width},${y * preview.height}`).join(' ');
  const crops = (areas[concern] ?? []).map(i => {
    const [x1, y1, x2, y2] = preview.boxes[i];
    const x = x1 * preview.width, y = y1 * preview.height;
    const width = (x2 - x1) * preview.width, height = (y2 - y1) * preview.height;
    const shorter = Math.min(width, height);
    return {
      // Clip after blurring so feathering never spreads beyond the model input.
      definition: `<clipPath id="crop${i}"><path d="M${x},${y}h${width}v${height}h-${width}z"/></clipPath><filter id="feather${i}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="${shorter * .1}"/></filter>`,
      shape: `<g clip-path="url(#crop${i})"><rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${shorter * .4}" filter="url(#feather${i})"/></g>`,
    };
  });
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden}img,svg{position:absolute;width:100%;height:100%;inset:0}img{object-fit:fill}</style></head><body><img src="data:image/jpeg;base64,${preview.jpeg}"><svg viewBox="0 0 ${preview.width} ${preview.height}" preserveAspectRatio="none"><defs><clipPath id="face"><polygon points="${polygon}"/></clipPath>${crops.map(crop => crop.definition).join('')}</defs><g clip-path="url(#face)" fill="#d06488" fill-opacity=".45">${crops.map(crop => crop.shape).join('')}</g></svg></body></html>`;
}
