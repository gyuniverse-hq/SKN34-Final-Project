import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { AR_RECORDER_SCRIPT } from '@/components/ar/recorderScript';
import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { useArRecording } from '@/hooks/useArRecording';
import { parseRecorderMessage, recordingExtension, recordingFileName, recordingMimeType } from '@/lib/arRecording';
import * as arRecording from '@/lib/arRecording';

// Development-only AR recording (AR_SPEC 1-4, 11-02): the page never records; the recorder is injected in development.

describe('AR page vs the development recorder', () => {
  it('keeps recording out of the page itself, so a production page cannot record (1-4)', () => {
    expect(FACE_TRACKER_HTML).not.toMatch(/MediaRecorder|captureStream|__kbRec/);
  });

  it('is a script that parses, records only the AR canvas, and has no network, storage or audio', () => {
    expect(() => new Function(AR_RECORDER_SCRIPT)).not.toThrow();
    expect(AR_RECORDER_SCRIPT).toContain('document.getElementById("canvas")');
    expect(AR_RECORDER_SCRIPT).toContain('captureStream');
    expect(AR_RECORDER_SCRIPT).not.toMatch(/fetch\(|XMLHttpRequest|WebSocket|sendBeacon|localStorage|indexedDB|toDataURL|toBlob|getUserMedia|audio/i);
    // Everything it posts to the app is a rec_ message.
    const types = [...AR_RECORDER_SCRIPT.matchAll(/type: "([a-z_]+)"/g)].map((m) => m[1]);
    expect(types.length).toBeGreaterThan(0);
    expect(types.every((t) => t.startsWith('rec_'))).toBe(true);
    // A forgotten recording stops by itself.
    expect(Number(AR_RECORDER_SCRIPT.match(/MAX_MS = (\d+)/)?.[1])).toBeLessThanOrEqual(120000);
  });

  function run(blobBytes: number[]) {
    const posts: any[] = [];
    let stopped = 0;
    let rec: any = null;
    class FakeRecorder {
      static isTypeSupported = (t: string) => t === 'video/webm';
      state = 'inactive';
      mimeType = 'video/webm';
      ondataavailable: ((e: any) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: ((e: any) => void) | null = null;
      constructor(public stream: unknown, public opts: any) {
        rec = this;
      }
      start() {
        this.state = 'recording';
      }
      stop() {
        this.state = 'inactive';
        for (const size of blobBytes) {
          const bytes = new Uint8Array(size).map((_, i) => i % 251);
          this.ondataavailable?.({ data: { size, arrayBuffer: async () => bytes.buffer } });
        }
        this.onstop?.();
      }
    }
    const win: any = { ReactNativeWebView: { postMessage: (s: string) => posts.push(JSON.parse(s)) } };
    const doc = { getElementById: () => ({ captureStream: () => ({ getTracks: () => [{ stop: () => void stopped++ }] }) }) };
    new Function('window', 'document', 'MediaRecorder', 'btoa', AR_RECORDER_SCRIPT)(win, doc, FakeRecorder, (s: string) => btoa(s));
    return { win, posts, rec: () => rec, stopped: () => stopped };
  }
  const flush = () => new Promise((r) => setTimeout(r, 0));

  it('records, sends ordered base64 pieces of at most 192 KiB, then a done message with the byte count', async () => {
    const { win, posts, rec, stopped } = run([300000, 200000]);
    win.__kbRec.start();
    expect(posts[0]).toEqual({ type: 'rec_state', state: 'recording', mime: 'video/webm' });
    expect(rec().opts.mimeType).toBe('video/webm');
    expect(rec().opts.videoBitsPerSecond).toBeGreaterThan(0);
    win.__kbRec.stop();
    await flush();
    const chunks = posts.filter((p) => p.type === 'rec_chunk');
    expect(chunks.map((c) => c.n)).toEqual([0, 1, 2, 3]);
    const decoded = chunks.map((c) => atob(c.data).length);
    expect(decoded).toEqual([196608, 103392, 196608, 3392]);
    expect(Math.max(...decoded)).toBeLessThanOrEqual(196608);
    expect(posts.at(-1)).toMatchObject({ type: 'rec_done', mime: 'video/webm', bytes: 500000, chunks: 4 });
    expect(stopped()).toBe(1); // the capture stream is released
  });

  it('reports an error instead of recording when the canvas or MediaRecorder is missing', () => {
    const posts: any[] = [];
    const win: any = { ReactNativeWebView: { postMessage: (s: string) => posts.push(JSON.parse(s)) } };
    new Function('window', 'document', 'MediaRecorder', 'btoa', AR_RECORDER_SCRIPT)(win, { getElementById: () => null }, undefined, () => '');
    win.__kbRec.start();
    expect(posts).toEqual([{ type: 'rec_error', detail: 'unsupported' }]);
  });
});

describe('recording helpers', () => {
  it('names clips by local time and picks the extension from the recorded type', () => {
    const d = new Date(2026, 10, 2, 18, 5, 9);
    expect(recordingFileName(d, 'video/webm;codecs=vp9')).toBe('ar-20261102-180509.webm');
    expect(recordingFileName(d, 'video/mp4;codecs=avc1')).toBe('ar-20261102-180509.mp4');
    expect(recordingExtension('')).toBe('webm');
    expect(recordingMimeType('video/mp4')).toBe('video/mp4');
    expect(recordingMimeType('video/webm;codecs=vp8')).toBe('video/webm');
  });

  it('accepts only well-formed recorder messages', () => {
    expect(parseRecorderMessage({ type: 'rec_state', state: 'recording', mime: 'video/webm' })).toEqual({ type: 'rec_state', state: 'recording', mime: 'video/webm' });
    expect(parseRecorderMessage({ type: 'rec_chunk', n: 0, data: 'AAAA' })).toEqual({ type: 'rec_chunk', n: 0, data: 'AAAA' });
    expect(parseRecorderMessage({ type: 'rec_done', mime: 'video/webm', bytes: 10, chunks: 1, ms: 1000 })).toMatchObject({ type: 'rec_done', bytes: 10 });
    expect(parseRecorderMessage({ type: 'rec_error', detail: 'unsupported' })).toEqual({ type: 'rec_error', detail: 'unsupported' });
    for (const bad of [null, 'x', {}, { type: 'status' }, { type: 'rec_chunk', data: 5 }, { type: 'rec_chunk', n: 'a', data: 'x' }, { type: 'rec_done', bytes: 'x' }, { type: 'rec_state', state: 'idle' }]) {
      expect(parseRecorderMessage(bad)).toBeNull();
    }
  });
});

describe('useArRecording', () => {
  const sinks: any[] = [];
  let share: jest.SpyInstance;
  beforeEach(() => {
    sinks.length = 0;
    jest.spyOn(arRecording, 'RecordingSink').mockImplementation(function (this: any, mime: string) {
      this.mime = mime;
      this.appended = [] as string[];
      this.append = (d: string) => this.appended.push(d);
      this.finish = jest.fn(async (bytes: number) => ({ uri: 'file:///cache/ar.webm', bytes }));
      this.discard = jest.fn(async () => {});
      sinks.push(this);
    } as never);
    share = jest.spyOn(arRecording, 'shareRecording').mockResolvedValue(true);
  });
  afterEach(() => {
    jest.restoreAllMocks();
    (globalThis as any).__DEV__ = true;
  });

  function mount(onFail = jest.fn()) {
    let hook: ReturnType<typeof useArRecording>;
    function Probe() {
      hook = useArRecording(onFail);
      return null;
    }
    let tree: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<Probe />);
    });
    return { get: () => hook!, tree: tree!, onFail };
  }

  it('does nothing in a production build: no button, no recorder request, messages ignored', () => {
    (globalThis as any).__DEV__ = false;
    const h = mount();
    expect(h.get().available).toBe(false);
    act(() => h.get().toggle());
    expect(h.get().wanted).toBe(false);
    expect(h.get().state).toBe('idle');
    act(() => h.get().handleMessage({ type: 'rec_state', state: 'recording', mime: 'video/webm' }));
    expect(sinks).toHaveLength(0);
  });

  it('goes idle → starting → recording → saving, writes the pieces and opens the share sheet', async () => {
    const h = mount();
    expect(h.get().available).toBe(true);
    act(() => h.get().toggle());
    expect(h.get()).toMatchObject({ wanted: true, state: 'starting' });
    act(() => h.get().handleMessage({ type: 'rec_state', state: 'recording', mime: 'video/webm' }));
    expect(h.get().state).toBe('recording');
    act(() => h.get().handleMessage({ type: 'rec_chunk', n: 0, data: 'AAAA' }));
    act(() => h.get().handleMessage({ type: 'rec_chunk', n: 1, data: 'BBBB' }));
    expect(sinks[0].appended).toEqual(['AAAA', 'BBBB']);
    act(() => h.get().toggle()); // stop
    expect(h.get()).toMatchObject({ wanted: false, state: 'saving' });
    await act(async () => {
      h.get().handleMessage({ type: 'rec_done', mime: 'video/webm', bytes: 6, chunks: 2, ms: 2000 });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(sinks[0].finish).toHaveBeenCalledWith(6);
    expect(share).toHaveBeenCalledWith('file:///cache/ar.webm', 'video/webm');
    expect(h.get().state).toBe('idle');
    expect(h.onFail).not.toHaveBeenCalled();
  });

  it('drops the clip and reports a failure when the file is cut short or the recorder fails', async () => {
    const h = mount();
    act(() => h.get().toggle());
    act(() => h.get().handleMessage({ type: 'rec_state', state: 'recording', mime: 'video/webm' }));
    sinks[0].finish.mockRejectedValue(new Error('recording is 4 bytes, expected 6'));
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    await act(async () => {
      h.get().handleMessage({ type: 'rec_done', mime: 'video/webm', bytes: 6, chunks: 2, ms: 2000 });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(sinks[0].discard).toHaveBeenCalled();
    expect(share).not.toHaveBeenCalled();
    expect(h.onFail).toHaveBeenCalledWith('failed');
    expect(h.get().state).toBe('idle');

    act(() => h.get().toggle());
    act(() => h.get().handleMessage({ type: 'rec_error', detail: 'unsupported' }));
    expect(h.onFail).toHaveBeenLastCalledWith('unsupported');
    expect(h.get()).toMatchObject({ wanted: false, state: 'idle' });
  });

  it('tells the screen when the share sheet is not available', async () => {
    share.mockResolvedValue(false);
    const h = mount();
    act(() => h.get().toggle());
    act(() => h.get().handleMessage({ type: 'rec_state', state: 'recording', mime: 'video/webm' }));
    await act(async () => {
      h.get().handleMessage({ type: 'rec_done', mime: 'video/webm', bytes: 0, chunks: 0, ms: 100 });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(h.onFail).toHaveBeenCalledWith('share');
  });
});
