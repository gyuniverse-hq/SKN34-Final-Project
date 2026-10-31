import { test } from 'node:test';
import assert from 'node:assert/strict';
import { boot } from '../modules/skin-analysis/web/runtime.mjs';

function cameraEnvironment(getUserMedia) {
  const events = [], lifecycle = {};
  const video = { srcObject: null, play: async () => { events.push('playing'); } };
  const canvas = { width: 100, height: 100 }, button = { disabled: true };
  const original = new Map(['window', 'document', 'navigator'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const values = {
    window: { ReactNativeWebView: { postMessage: data => events.push(JSON.parse(data)) },
      addEventListener: (name, callback) => { lifecycle[name] = callback; } },
    document: { querySelector: name => ({ video, canvas, '#capture': button })[name], addEventListener: () => {} },
    navigator: { mediaDevices: { getUserMedia } },
  };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { configurable: true, value });
  return { events, lifecycle, video, canvas, button, restore() {
    for (const [key, descriptor] of original) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  } };
}

// Node rejects the face-tracker HTTPS import after playback, without making a request.
const config = { assetsUrl: 'https://invalid.example/skin-runtime/' };

test('opens video before loading the face guide and stops it if the guide fails', async () => {
  let stopped = false;
  const env = cameraEnvironment(async () => ({ getTracks: () => [{ stop: () => { stopped = true; } }] }));
  try {
    await boot(config);
    assert.deepEqual(env.events, [
      { type: 'camera', state: { guidance: 'openingCamera', progress: 0 } },
      'playing', { type: 'camera', state: { guidance: 'loadingGuide', progress: 0 } }, { type: 'error', code: 'guide' },
    ]);
    assert.equal(stopped, true);
    assert.equal(env.video.srcObject, null);
    assert.equal(env.canvas.width, 0);
  } finally { env.restore(); }
});

for (const [name, code] of [['NotAllowedError', 'permission'], ['NotReadableError', 'camera']]) {
  test(`reports ${name} before attempting model loading`, async () => {
    const env = cameraEnvironment(async () => { throw Object.assign(new Error('camera'), { name }); });
    try {
      await boot(config);
      assert.deepEqual(env.events.at(-1), { type: 'error', code });
      assert.equal(env.events.includes('playing'), false);
      assert.equal(env.button.disabled, true);
    } finally { env.restore(); }
  });
}

test('stops a late camera permission response when the screen has already been left', async () => {
  let resolveCamera, stopped = false;
  const env = cameraEnvironment(() => new Promise(resolve => { resolveCamera = resolve; }));
  try {
    const pending = boot(config);
    env.lifecycle.pagehide();
    resolveCamera({ getTracks: () => [{ stop: () => { stopped = true; } }] });
    await pending;
    assert.equal(stopped, true);
    assert.equal(env.video.srcObject, null);
    assert.equal(env.events.includes('playing'), false);
    assert.equal(env.events.some(event => event.type === 'error'), false);
  } finally { env.restore(); }
});
