import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

/** What the development recorder script (components/ar/recorderScript.ts) sends over the bridge. */
export type RecorderMessage =
  | { type: 'rec_state'; state: 'recording'; mime: string }
  | { type: 'rec_chunk'; n: number; data: string }
  | { type: 'rec_done'; mime: string; bytes: number; chunks: number; ms: number }
  | { type: 'rec_error'; detail: string };

/** Narrow a parsed bridge message; null for anything that is not a well-formed recorder message. */
export function parseRecorderMessage(raw: unknown): RecorderMessage | null {
  if (!raw || typeof raw !== 'object') return null;
  const m = raw as Record<string, unknown>;
  const mime = typeof m.mime === 'string' ? m.mime : '';
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  switch (m.type) {
    case 'rec_state':
      return m.state === 'recording' ? { type: 'rec_state', state: 'recording', mime } : null;
    case 'rec_chunk':
      return typeof m.data === 'string' && num(m.n) !== null ? { type: 'rec_chunk', n: m.n as number, data: m.data } : null;
    case 'rec_done': {
      const bytes = num(m.bytes), chunks = num(m.chunks), ms = num(m.ms);
      return bytes !== null && chunks !== null && ms !== null ? { type: 'rec_done', mime, bytes, chunks, ms } : null;
    }
    case 'rec_error':
      return { type: 'rec_error', detail: typeof m.detail === 'string' ? m.detail : '' };
    default:
      return null;
  }
}

export function recordingExtension(mime: string): 'mp4' | 'webm' {
  return mime.toLowerCase().includes('mp4') ? 'mp4' : 'webm';
}

export function recordingMimeType(mime: string): string {
  return recordingExtension(mime) === 'mp4' ? 'video/mp4' : 'video/webm';
}

/** ar-20261102-184530.webm, in local time. */
export function recordingFileName(now: Date, mime: string): string {
  const p = (n: number) => String(n).padStart(2, '0');
  const day = `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}`;
  const time = `${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}`;
  return `ar-${day}-${time}.${recordingExtension(mime)}`;
}

/**
 * Receives the recording as base64 pieces, in order, and writes them to one file in the app cache (this device only).
 * Every piece is a complete base64 string, so the decoded bytes are simply appended. Writes run one after another.
 */
export class RecordingSink {
  private readonly file: File;
  private chain: Promise<void> = Promise.resolve();
  private failed: unknown = null;

  constructor(mime: string, now: Date = new Date()) {
    this.file = new File(Paths.cache, recordingFileName(now, mime));
    this.chain = this.chain.then(() => this.file.create({ overwrite: true })).catch((e) => void (this.failed = e));
  }

  append(base64: string): void {
    this.chain = this.chain
      .then(() => this.file.write(base64, { encoding: 'base64', append: true }))
      .catch((e) => void (this.failed = e));
  }

  /** Wait for the writes; the file must hold exactly the bytes the page counted, or the clip is cut short. */
  async finish(expectedBytes: number): Promise<{ uri: string; bytes: number }> {
    await this.chain;
    if (this.failed) throw this.failed;
    const bytes = this.file.size;
    if (bytes !== expectedBytes) throw new Error(`recording is ${bytes} bytes, expected ${expectedBytes}`);
    return { uri: this.file.uri, bytes };
  }

  /** Drop a clip that was not finished (screen left, error). */
  async discard(): Promise<void> {
    await this.chain;
    try {
      if (this.file.exists) this.file.delete();
    } catch {
      // The cache is cleaned by the system anyway.
    }
  }
}

/** Open the share sheet for the saved clip so it can go to Files, Photos, a drive or a chat. False when sharing is unavailable. */
export async function shareRecording(uri: string, mime: string): Promise<boolean> {
  if (!(await Sharing.isAvailableAsync())) return false;
  await Sharing.shareAsync(uri, { mimeType: recordingMimeType(mime), dialogTitle: 'AR' });
  return true;
}
