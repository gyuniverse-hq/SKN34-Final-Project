import { SkinCaptureAssembler, CAPTURE_CHUNK_CHARS, MAX_CAPTURE_BYTES } from '@/lib/skinCapture';
import { adaptSkinServerResult, skinApiUrl, uploadSkinPhoto } from '@/lib/skinServer';
import { TRUSTED_SKIN_API_ORIGIN } from '@/constants/skinServer';
import { validateSkinAnalysis, writeSkinProfile, readSkinProfile } from '@/lib/skinProfile';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));
jest.mock('@/lib/auth', () => ({ getAccessToken: jest.fn() }));

const run = { runId: 'run', processId: 'process', firstInProcess: true, device: 'phone', androidVersion: 'android', build: 'test' };
const photo = { bytes: new Uint8Array([255, 216, 255]), captureMs: 4, alignmentMs: 1500, handoffMs: 1 };
const features = { acne: 0, pore_grade_cheek_image_left: 0, pore_grade_cheek_image_right: 1,
  pigmentation_grade_forehead: 1, pigmentation_grade_cheek_image_left: 2, pigmentation_grade_cheek_image_right: 3,
  wrinkle_grade_forehead: 1, wrinkle_grade_glabella: 2, wrinkle_grade_eye_image_left: 3, wrinkle_grade_eye_image_right: 4 };
function wire() {
  return { schema_version: 'skin-recommendation-features-v1', status: 'complete', features: { ...features },
    feature_status: Object.fromEntries(Object.keys(features).map(key => [key, 'predicted'])),
    roi_method: 'opencv_yunet_facebox_proportions_v1', validation_status: 'experimental_unvalidated',
    acne: { status: 'predicted', label: 0, score: .1, threshold: .5 },
    execution: { runtime: 'pytorch-cuda', bundleVersion: 'a'.repeat(64), serverMs: 50 } };
}

function start(size: number) {
  return { type: 'capture-start', captureId: 'run:jpeg', mime: 'image/jpeg', byteLength: size,
    chunkCount: Math.ceil(Math.ceil(size / 3) * 4 / CAPTURE_CHUNK_CHARS), captureMs: 4, alignmentMs: 1500 };
}

it('reassembles a JPEG larger than the WebView message limit without storage', () => {
  const input = new Uint8Array(100000).fill(97), encoded = btoa('a'.repeat(input.length));
  const assembler = new SkinCaptureAssembler('run:jpeg');
  expect(assembler.push(start(input.length))).toBeNull();
  for (let offset = 0, index = 0; offset < encoded.length; offset += CAPTURE_CHUNK_CHARS, index++) {
    const message = { type: 'capture-chunk', captureId: 'run:jpeg', index, data: encoded.slice(offset, offset + CAPTURE_CHUNK_CHARS) };
    expect(JSON.stringify(message).length).toBeLessThan(65536);
    expect(assembler.push(message)).toBeNull();
  }
  expect(assembler.push({ type: 'capture-end', captureId: 'run:jpeg' })?.bytes).toEqual(input);
  expect(() => assembler.push(start(1))).toThrow();
});

it.each(['missing', 'duplicate', 'out-of-order', 'wrong-id', 'oversize', 'bad-base64'])('rejects %s photo handoffs', kind => {
  const assembler = new SkinCaptureAssembler('run:jpeg');
  if (kind === 'oversize') { expect(() => assembler.push(start(MAX_CAPTURE_BYTES + 1))).toThrow(); return; }
  assembler.push(start(3));
  const chunk = { type: 'capture-chunk', captureId: 'run:jpeg', index: 0, data: '/9j/' };
  if (kind === 'missing') expect(() => assembler.push({ type: 'capture-end', captureId: 'run:jpeg' })).toThrow();
  if (kind === 'duplicate') { assembler.push(chunk); expect(() => assembler.push(chunk)).toThrow(); }
  if (kind === 'out-of-order') expect(() => assembler.push({ ...chunk, index: 1 })).toThrow();
  if (kind === 'wrong-id') expect(() => assembler.push({ ...chunk, captureId: 'old:jpeg' })).toThrow();
  if (kind === 'bad-base64') expect(() => assembler.push({ ...chunk, data: '????' })).toThrow();
});

it('rejects incomplete byte lengths and cleared runs', () => {
  const assembler = new SkinCaptureAssembler('run:jpeg'); assembler.push(start(3));
  assembler.push({ type: 'capture-chunk', captureId: 'run:jpeg', index: 0, data: 'YQ==' });
  expect(() => assembler.push({ type: 'capture-end', captureId: 'run:jpeg' })).toThrow();
  assembler.clear(); expect(() => assembler.push(start(3))).toThrow();
});

it('adapts and persists server results while keeping unmeasured timings null', async () => {
  const output = adaptSkinServerResult(wire(), run, photo, 70, 80);
  validateSkinAnalysis(output);
  expect(output.schema).toBe('skin-analysis-server-v1');
  expect(output.timing.models).toEqual([]); expect(output.timing.nativeMs).toBeNull();
  expect(output.timing.serverMs).toBe(50); expect(output.timing.requestMs).toBe(70);
  await writeSkinProfile({ version: 1, registeredAt: new Date().toISOString(), analysis: output,
    questionnaire: { tightness: 0, oiliness: 1, sensitivity: 'unknown' } });
  expect((await readSkinProfile())?.analysis).toEqual(output);
  expect(JSON.stringify(output)).not.toMatch(/base64|data:image|Bearer/);
});

it.each(['partial', 'missing', 'range', 'status', 'threshold', 'timing'])('rejects %s analysis responses', kind => {
  const input = wire();
  if (kind === 'partial') input.status = 'partial';
  if (kind === 'missing') delete (input.features as Partial<typeof features>).acne;
  if (kind === 'range') input.features.pore_grade_cheek_image_left = 6;
  if (kind === 'status') input.feature_status.acne = 'failed';
  if (kind === 'threshold') input.acne.label = input.features.acne = 1;
  if (kind === 'timing') input.execution.serverMs = NaN;
  expect(() => adaptSkinServerResult(input, run, photo, 70, 80)).toThrow();
});

it.each(['https://evil.example', 'http://192.168.75.231:8000', TRUSTED_SKIN_API_ORIGIN + '?token=x', 'http://user:secret@192.168.75.230:8000'])('rejects unapproved destination %s before obtaining a token', async url => {
  const dependencies = { fetch: jest.fn(), getToken: jest.fn(), url };
  await expect(uploadSkinPhoto(photo, run, new AbortController().signal, dependencies)).rejects.toThrow();
  expect(dependencies.getToken).not.toHaveBeenCalled(); expect(dependencies.fetch).not.toHaveBeenCalled();
});

it('uploads one JPEG with the user token, rejects redirects and never retries', async () => {
  expect(skinApiUrl(TRUSTED_SKIN_API_ORIGIN)).toBe(TRUSTED_SKIN_API_ORIGIN + '/analyze');
  const dependencies = { fetch: jest.fn().mockResolvedValue({ ok: true, json: async () => wire() }),
    getToken: jest.fn().mockResolvedValue('user-access-token'), url: TRUSTED_SKIN_API_ORIGIN };
  const output = await uploadSkinPhoto(photo, run, new AbortController().signal, dependencies);
  expect(output.features).toEqual(features); expect(dependencies.fetch).toHaveBeenCalledTimes(1);
  expect(dependencies.fetch).toHaveBeenCalledWith(TRUSTED_SKIN_API_ORIGIN + '/analyze', expect.objectContaining({
    method: 'POST', redirect: 'error', credentials: 'omit',
    headers: expect.objectContaining({ Authorization: 'Bearer user-access-token', 'Content-Type': 'image/jpeg' }),
  }));
});

it('aborts an in-flight upload on cancellation and on the 30 second timeout', async () => {
  jest.useFakeTimers();
  try {
    for (const timeout of [false, true]) {
      const controller = new AbortController();
      const dependencies = { getToken: jest.fn().mockResolvedValue('token'), url: TRUSTED_SKIN_API_ORIGIN,
        fetch: jest.fn((_url, init) => new Promise<never>((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new Error('aborted')));
        })) };
      const pending = uploadSkinPhoto(photo, run, controller.signal, dependencies);
      const assertion = expect(pending).rejects.toThrow('aborted');
      await Promise.resolve();
      if (timeout) jest.advanceTimersByTime(30000); else controller.abort();
      await assertion; expect(dependencies.fetch).toHaveBeenCalledTimes(1);
    }
  } finally { jest.useRealTimers(); }
});
