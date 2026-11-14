/** Research-only extraction through the same hook and bundle used by the video try-on screen. */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { useVideoTryOn } from '@/hooks/useVideoTryOn';
import { useMakeupStore } from '@/store/makeupStore';

const { mkdirSync, writeFileSync } = require('fs') as {
  mkdirSync(path: string, options: { recursive: boolean }): void;
  writeFileSync(path: string, data: string): void;
};
const { join } = require('path') as { join(...parts: string[]): string };

jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: [], isPending: false, isError: false }),
}));
jest.mock('@/lib/api', () => ({ apiGet: jest.fn() }));

test('extract the actual offline Karina look state', async () => {
  useMakeupStore.getState().reset();
  let open!: () => void;
  function Screen() {
    open = useVideoTryOn([], 'celebrity-n5otfjJSSQc', 'Karina').open;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(React.createElement(Screen)); });
  await act(async () => { open(); });
  const { makeup, selections } = useMakeupStore.getState();
  expect(makeup.lip?.hex).toBe('#9E5C52');
  expect(selections.lip).toEqual({ productId: 'oy-a000000229303', shadeId: '03' });
  const out = join(process.cwd(), 'research', 'data', 'karina_look');
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, 'app_makeup.json'), JSON.stringify({ makeup, selections }, null, 2));
  await act(async () => { screen.unmount(); });
  useMakeupStore.getState().reset();
});
