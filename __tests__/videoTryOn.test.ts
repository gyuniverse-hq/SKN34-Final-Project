import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { resolveVideoProducts, useVideoTryOn } from '@/hooks/useVideoTryOn';
import { useMakeupStore } from '@/store/makeupStore';
import type { Product, VideoProductMapping } from '@/types';

const mockPush = jest.fn();
let mockProducts: Product[] = [];
let mockQueryOptions: { queryFn: () => Promise<Product[]>; enabled: boolean };
jest.mock('expo-router', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('@tanstack/react-query', () => ({ useQuery: (options: typeof mockQueryOptions) => { mockQueryOptions = options; return { data: mockProducts, isPending: false, isError: false }; } }));
jest.mock('@/lib/api', () => ({ apiGet: jest.fn(async () => ({ products: [] })) }));
import { apiGet } from '@/lib/api';

const product = (id: string, zone: Product['makeupZone'], shadeId: string): Product => ({
  id, makeupZone: zone, shades: [{ id: shadeId, name: shadeId, hex: '#112233' }],
  brand: 'Brand', name: 'Product', nameKo: 'Product', category: 'lip', texture: 'matte',
  priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
});

test('paints a verified highlighter without dropping other AR zones', () => {
  const lip = product('lip', 'lip', 'red');
  const highlight = product('hl', 'highlighter', 'glow');
  const items: VideoProductMapping[] = [
    { mappingVerified: true, catalogProductId: 'lip', catalogShadeId: 'red' },
    { mappingVerified: true, catalogProductId: 'hl', catalogShadeId: 'glow' },
  ];
  expect(resolveVideoProducts(items, [lip, highlight]).map((item) => item.zone)).toEqual(['lip', 'highlighter']);
});

test('uses only verified exact shades, excludes placeholders and chooses one product per zone', () => {
  const lip = product('lip', 'lip', 'red');
  const eye = product('eye', 'eyeshadow', 'pink');
  const placeholder = product('brow', 'brow', 'brown');
  placeholder.shades[0].measureMethod = 'placeholder';
  const unknownTexture = product('unknown', 'blush', 'rose');
  unknownTexture.texture = null;
  const items: VideoProductMapping[] = [
    { catalogProductId: 'lip', catalogShadeId: 'red' },
    { mappingVerified: true, catalogProductId: 'lip', catalogShadeId: 'missing' },
    { mappingVerified: true, catalogProductId: 'lip', catalogShadeId: 'red' },
    { mappingVerified: true, catalogProductId: 'lip', catalogShadeId: 'red' },
    { mappingVerified: true, catalogProductId: 'brow', catalogShadeId: 'brown' },
    { mappingVerified: true, catalogProductId: 'unknown', catalogShadeId: 'rose' },
    { mappingVerified: true, catalogProductId: 'eye', catalogShadeId: 'pink' },
  ];
  expect(resolveVideoProducts(items, [lip, eye, placeholder, unknownTexture]).map((item) => item.index)).toEqual([2, 6]);
});

test('applies only confirmed products before opening AR; unmatched videos leave selections intact', async () => {
  useMakeupStore.getState().reset();
  mockPush.mockClear();
  const lip = product('lip', 'lip', 'red');
  mockProducts = [lip];
  let open!: () => void;
  function Screen({ items }: { items: VideoProductMapping[] }) {
    open = useVideoTryOn(items, 'video-1', 'Test').open;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(React.createElement(Screen, { items: [{ mappingVerified: true, catalogProductId: 'lip', catalogShadeId: 'red' }] })); });
  await act(async () => { open(); });
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: 'lip', shadeId: 'red' });
  expect(mockPush).toHaveBeenCalledWith({ pathname: '/ar', params: { video: '1' } });
  await act(async () => { screen.update(React.createElement(Screen, { items: [] })); });
  await act(async () => { open(); });
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: 'lip', shadeId: 'red' });
  expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/ar', params: {} });
  expect(useMakeupStore.getState().activeLook?.id).toBe('video-1');
  await act(async () => { screen.unmount(); });
  useMakeupStore.getState().reset();
});

test('look try-on lists unmatched core zones instead of claiming a full seven-layer set', async () => {
  mockProducts = [product('lip', 'lip', 'red')];
  let missing!: string[];
  function Screen() {
    missing = useVideoTryOn([{ mappingVerified: true, catalogProductId: 'lip', catalogShadeId: 'red' }], 'video-1', 'Test').missingCore;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(React.createElement(Screen)); });
  expect(missing).toEqual(['foundation', 'brow', 'eyeshadow', 'eyeliner', 'mascara', 'blush']);
  await act(async () => { screen.unmount(); });
});

test('fetches product-only approvals in chunks and does not fetch unverified IDs', async () => {
  const items: VideoProductMapping[] = Array.from({ length: 21 }, (_, i) => ({ mappingVerified: true, catalogProductId: `product-${i}` }));
  items.push({ catalogProductId: 'unverified' });
  let screen!: renderer.ReactTestRenderer;
  function Screen() { useVideoTryOn(items, 'video', 'test'); return null; }
  await act(async () => { screen = renderer.create(React.createElement(Screen)); });
  expect(mockQueryOptions.enabled).toBe(true);
  await mockQueryOptions.queryFn();
  const requests = jest.mocked(apiGet).mock.calls.map(([url]) => String(url));
  expect(requests).toHaveLength(2);
  expect(requests.every((url) => !url.includes('unverified'))).toBe(true);
  expect(requests.map((url) => decodeURIComponent(url).split('ids=')[1].split(',').length).sort()).toEqual([1, 20]);
  await act(async () => { screen.unmount(); });
});

test('applies catalog shades for the six demo looks without treating them as mappingVerified', async () => {
  useMakeupStore.getState().reset();
  mockPush.mockClear();
  const contour = product('oy-a000000201055', 'contour', '02-2');
  const mascara = product('oy-a000000255697', 'mascara', '01');
  mockProducts = [contour, mascara];
  let open!: () => void;
  function Screen() {
    open = useVideoTryOn([], 'style-ZAozXs-ZZik', 'Strawberry').open;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(React.createElement(Screen)); });
  await act(async () => { open(); });
  expect(useMakeupStore.getState().makeup.contour?.hex).toBe('#112233');
  expect(useMakeupStore.getState().makeup.mascara?.hex).toBe('#112233');
  expect(useMakeupStore.getState().makeup.mascara?.geometry).toEqual({
    length: 1.28, thickness: 0.78, lower: true,
  });
  expect(useMakeupStore.getState().makeup.mascara?.intensity).toBe(0.72);
  expect(useMakeupStore.getState().selections.contour).toEqual({ productId: 'oy-a000000201055', shadeId: '02-2' });
  expect(useMakeupStore.getState().selections.mascara).toEqual({ productId: 'oy-a000000255697', shadeId: '01' });
  expect(mockPush).toHaveBeenCalledWith({ pathname: '/ar', params: { video: '1' } });
  await act(async () => { screen.unmount(); });
  useMakeupStore.getState().reset();
});

test('peach look mascara uses the fine lash shape without lower lashes', async () => {
  useMakeupStore.getState().reset();
  mockProducts = [product('oy-a000000205718', 'mascara', 'a000000205718-006')];
  let open!: () => void;
  function Screen() {
    open = useVideoTryOn([], 'style-kWI7_DkDjZ0', 'Peach').open;
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(React.createElement(Screen)); });
  await act(async () => { open(); });
  expect(useMakeupStore.getState().makeup.mascara?.geometry).toEqual({
    length: 1.12, thickness: 0.72, lower: false,
  });
  await act(async () => { screen.unmount(); });
  useMakeupStore.getState().reset();
});
