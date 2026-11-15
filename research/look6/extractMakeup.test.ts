/** Offline extraction through the same video try-on hook and bundled catalog as the app. */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { DEMO_LOOK_AR, demoLookVideoId } from '@/lib/demoLookAr';
import { useVideoTryOn } from '@/hooks/useVideoTryOn';
import { videoLookMakeup } from '@/lib/videoLookMakeup';
import { useMakeupStore } from '@/store/makeupStore';

const { mkdirSync, writeFileSync } = require('fs') as {
  mkdirSync(path: string, options: { recursive: boolean }): void;
  writeFileSync(path: string, data: string): void;
};
const { join } = require('path') as { join(...parts: string[]): string };
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: [], isPending: false, isError: false }) }));
jest.mock('@/lib/api', () => ({ apiGet: jest.fn() }));

test('extract every bundled demo look using its real screen identifier', async () => {
  for (const videoId of Object.keys(DEMO_LOOK_AR)) {
    const id = `${['ZAozXs-ZZik', '4QR0tre9yBI', 'kWI7_DkDjZ0'].includes(videoId) ? 'style' : 'celebrity'}-${videoId}`;
    expect(demoLookVideoId(id)).toBe(videoId);
    useMakeupStore.getState().reset();
    let open!: () => void;
    function Screen() { open = useVideoTryOn([], id, videoId).open; return null; }
    let screen!: renderer.ReactTestRenderer;
    try {
      await act(async () => { screen = renderer.create(React.createElement(Screen)); });
      await act(async () => { open(); });
      const { makeup, selections } = useMakeupStore.getState();
      expect(Object.values(makeup).some(Boolean)).toBe(true);
      const out = join(process.cwd(), 'research', 'data', 'look6', videoId);
      mkdirSync(out, { recursive: true });
      writeFileSync(join(out, 'app_makeup.json'), JSON.stringify({ id, makeup, selections }, null, 2));
      // What the look AR camera paints: the store state with the render-only video look finish (app/(tabs)/ar.tsx).
      const shown = videoLookMakeup(makeup, { fromVideo: true, cameraActive: true, fittingProduct: false, lookId: id, modified: [] });
      writeFileSync(join(out, 'shown_makeup.json'), JSON.stringify({ id, makeup: shown }, null, 2));
      // The AR look strength slider at a few positions (research/look6/render_strength.py).
      for (const strength of [0.3, 0.6, 1, 1.35, 1.7]) {
        const scaled = videoLookMakeup(makeup, { fromVideo: true, cameraActive: true, fittingProduct: false, lookId: id, modified: [], strength });
        writeFileSync(join(out, `strength_${strength}_makeup.json`), JSON.stringify({ id, strength, makeup: scaled }, null, 2));
      }
    } finally {
      if (screen) await act(async () => { screen.unmount(); });
      useMakeupStore.getState().reset();
    }
  }
});
