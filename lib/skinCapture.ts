/** A single, bounded JPEG handoff. Image bytes never enter React state or storage. */
export const MAX_CAPTURE_BYTES = 10 * 1024 * 1024;
export const CAPTURE_CHUNK_CHARS = 48 * 1024;

export interface CapturedSkinPhoto {
  bytes: Uint8Array;
  captureMs: number;
  alignmentMs: number;
  handoffMs: number;
}

export class SkinCaptureAssembler {
  private chunks: string[] = [];
  private size = 0;
  private expectedChunks = 0;
  private encodedLength = 0;
  private captureMs = 0;
  private alignmentMs = 0;
  private handoffAt = 0;
  private started = false;
  private finished = false;

  constructor(private readonly captureId: string) {}

  clear() {
    this.chunks = [];
    this.finished = true;
  }

  push(message: Record<string, unknown>): CapturedSkinPhoto | null {
    try { return this.accept(message); }
    catch { this.clear(); throw new Error('skin.analysisFailed'); }
  }

  private accept(message: Record<string, unknown>): CapturedSkinPhoto | null {
    if (message.captureId !== this.captureId || this.finished) throw new Error('capture');
    if (message.type === 'capture-start') {
      if (this.started || !Number.isInteger(message.byteLength) ||
          (message.byteLength as number) < 1 || (message.byteLength as number) > MAX_CAPTURE_BYTES ||
          message.mime !== 'image/jpeg' ||
          typeof message.captureMs !== 'number' || !Number.isFinite(message.captureMs) || message.captureMs < 0 ||
          typeof message.alignmentMs !== 'number' || !Number.isFinite(message.alignmentMs) || message.alignmentMs < 0) throw new Error('capture');
      this.size = message.byteLength as number;
      this.expectedChunks = Math.ceil((Math.ceil(this.size / 3) * 4) / CAPTURE_CHUNK_CHARS);
      if (message.chunkCount !== this.expectedChunks) throw new Error('capture');
      this.captureMs = message.captureMs;
      this.alignmentMs = message.alignmentMs;
      this.handoffAt = performance.now();
      this.started = true;
      return null;
    }
    if (!this.started) throw new Error('capture');
    if (message.type === 'capture-chunk') {
      if (message.index !== this.chunks.length || this.chunks.length >= this.expectedChunks ||
          typeof message.data !== 'string' || !message.data.length ||
          message.data.length > CAPTURE_CHUNK_CHARS || message.data.length % 4 !== 0 ||
          !/^[A-Za-z0-9+/]*={0,2}$/.test(message.data) ||
          (this.chunks.length < this.expectedChunks - 1 && message.data.length !== CAPTURE_CHUNK_CHARS)) throw new Error('capture');
      this.encodedLength += message.data.length;
      if (this.encodedLength > Math.ceil(this.size / 3) * 4) throw new Error('capture');
      this.chunks.push(message.data);
      return null;
    }
    if (message.type !== 'capture-end' || this.chunks.length !== this.expectedChunks ||
        this.encodedLength !== Math.ceil(this.size / 3) * 4) throw new Error('capture');
    const decoded = atob(this.chunks.join(''));
    if (decoded.length !== this.size) throw new Error('capture');
    const bytes = Uint8Array.from(decoded, char => char.charCodeAt(0));
    this.clear();
    return { bytes, captureMs: this.captureMs, alignmentMs: this.alignmentMs, handoffMs: performance.now() - this.handoffAt };
  }
}
