import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { useVideoTryOn } from '@/hooks/useVideoTryOn';
import * as profiles from '@/lib/applicationProfiles';
import { DEMO_LOOK_PRODUCTS } from '@/lib/demoLookBundle';
import { useMakeupStore } from '@/store/makeupStore';
import type { Product } from '@/types';

let mockProducts: Product[] = [];
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: mockProducts, isPending: false, isError: false }),
}));
jest.mock('@/lib/api', () => ({ apiGet: jest.fn() }));

test('the selected exact shade carries its profile to the makeup state without changing its hex', async () => {
  useMakeupStore.getState().reset();
  const controls = { material: { a1: 0.4 }, coverageMultiplier: 0.8 };
  const spy = jest.spyOn(profiles, 'applicationProfileFor').mockImplementation((productId, shadeId) => (
    productId === 'oy-a000000229303' && shadeId === '03' ? controls : undefined
  ));
  let open!: () => void;
  function Screen() {
    open = useVideoTryOn([], 'celebrity-n5otfjJSSQc', 'Karina').open;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(React.createElement(Screen)); });
    await act(async () => { open(); });
    const makeup = useMakeupStore.getState().makeup;
    expect(makeup.lip?.hex).toBe('#9E5C52');
    expect(makeup.lip?.applicationProfile).toEqual(controls);
    expect(makeup.blush?.applicationProfile).toBeUndefined();
  } finally {
    if (screen) await act(async () => { screen.unmount(); });
    spy.mockRestore();
    mockProducts = [];
    useMakeupStore.getState().reset();
  }
});

test('a shade-attached profile must pass the same evidence gate before reaching the renderer', async () => {
  useMakeupStore.getState().reset();
  const product = DEMO_LOOK_PRODUCTS.find((item) => item.id === 'oy-a000000229303');
  if (!product) throw new Error('missing bundled product');
  const profile = {
    source: 'video-fit' as const, videoId: 'example', fitFrameSeconds: 10, validationFrameSeconds: 20,
    validationView: 'different-angle' as const, fitErrorBefore: 10, fitErrorAfter: 8,
    validationErrorBefore: 12, validationErrorAfter: 9, overrides: { material: { a1: 0.3 } },
  };
  mockProducts = [{ ...product, shades: product.shades.map((shade) => (
    shade.id === '03' ? { ...shade, applicationProfile: profile } : shade
  )) }];
  let open!: () => void;
  function Screen() {
    open = useVideoTryOn([], 'celebrity-n5otfjJSSQc', 'Karina').open;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(React.createElement(Screen)); });
    await act(async () => { open(); });
    expect(useMakeupStore.getState().makeup.lip?.applicationProfile).toEqual(profile.overrides);
    mockProducts[0] = { ...mockProducts[0], shades: mockProducts[0].shades.map((shade) => (
      shade.id === '03' ? { ...shade, applicationProfile: { ...profile, validationErrorAfter: 13 } } : shade
    )) };
    await act(async () => { screen.update(React.createElement(Screen)); });
    await act(async () => { open(); });
    expect(useMakeupStore.getState().makeup.lip?.applicationProfile).toBeUndefined();
  } finally {
    if (screen) await act(async () => { screen.unmount(); });
    mockProducts = [];
    useMakeupStore.getState().reset();
  }
});
