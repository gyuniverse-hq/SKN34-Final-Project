import React from 'react';
import renderer, { act } from 'react-test-renderer';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import type { Product } from '@/types';

const products = (require('@/lib/devCatalog/oyCatalog.json') as { products: Product[] }).products;
const lip = products.find((product) => product.id === 'oy-a000000120880')!;
const blush = products.find((product) => product.makeupZone === 'blush' && product.texture && product.shades.length)!;
const shade = lip.shades.find((item) => item.id === '23')!;

jest.mock('react-native-safe-area-context', () => {
  const actual = jest.requireActual('react-native-safe-area-context') as typeof import('react-native-safe-area-context');
  return { ...actual, useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: 0, left: 0 }) };
});
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [{ granted: true, canAskAgain: true }, jest.fn()] }));
jest.mock('expo-haptics', () => ({
  selectionAsync: jest.fn(() => Promise.resolve()),
  notificationAsync: jest.fn(() => Promise.resolve()),
  NotificationFeedbackType: { Success: 'success' },
}));
jest.mock('expo-router', () => {
  const { useEffect } = require('react') as typeof import('react');
  const navigation = { setOptions: jest.fn() };
  const router = { push: jest.fn(), back: jest.fn(), canGoBack: () => false };
  return {
    useRouter: () => router,
    useLocalSearchParams: () => ({}),
    useNavigation: () => navigation,
    useFocusEffect: (cb: () => void | (() => void)) => {
      useEffect(() => {
        const cleanup = cb();
        return typeof cleanup === 'function' ? cleanup : undefined;
      }, [cb]);
    },
  };
});
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/components/ar/ArFaceView', () => ({ ArFaceView: 'ArFaceView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, language: 'ko' }) }));
jest.mock('@/hooks/useArRouteSelection', () => ({ useArRouteSelection: () => ({ product: {} }) }));
jest.mock('@/lib/queries', () => {
  const products = (require('@/lib/devCatalog/oyCatalog.json') as { products: Product[] }).products;
  return { useTryOnProducts: () => ({ data: products.filter((p) => p.id === 'oy-a000000120880' || p.makeupZone === 'blush').slice(0, 1000) }) };
});

jest.mock('@/lib/api', () => ({ apiPostOwned: jest.fn() }));
import { apiPostOwned } from '@/lib/api';
import { AppState, TextInput } from 'react-native';
const post = jest.mocked(apiPostOwned);
let screen: renderer.ReactTestRenderer;
let serial = 0;
const owned = (data: unknown) => ({ data, owner: { kind: 'guest', id: 'guest-test' } });
function proposal(body: any) {
  return owned({ answer: '', arResult: { requestId: body.requestId, status: 'proposed',
    actionProposal: { commandId: `aaaaaaaa-aaaa-4aaa-8aaa-${String(++serial).padStart(12, '0')}`, expectedStateVersion: body.arContext.stateVersion,
      action: 'set_intensity', zone: 'lip', value: Number(body.message.match(/\d+/)[0]) / 100,
      productId: lip.id, shadeId: shade.id } } });
}
function face() { return screen.root.findByType('ArFaceView' as never); }
async function send(text: string) {
  await act(async () => { screen.root.findByType(TextInput).props.onChangeText(text); });
  await act(async () => { screen.root.findByType(TextInput).props.onSubmitEditing(); });
}
beforeEach(async () => {
  jest.clearAllMocks();
  Object.defineProperty(AppState, 'currentState', { configurable: true, value: 'active' });
  useMakeupStore.getState().endArSession();
  useMakeupStore.getState().reset();
  useMakeupStore.getState().applyShade(lip, shade);
  useMakeupStore.getState().applyShade(blush, blush.shades[0]);
  useSettingsStore.setState({ cameraConsent: true });
  post.mockImplementation(async (path, body) => (path === '/api/chat' ? proposal(body) : owned({ received: true })) as never);
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  await act(async () => {
    screen.root.findAllByProps({ accessibilityRole: 'tab' }).find((tab) => tab.findAllByProps({ children: 'ar.mode.chat' }).length)!.props.onPress();
  });
  await act(async () => { face().props.onStatus('tracking'); });
});
afterEach(async () => { await act(async () => { screen.unmount(); }); });

it.each([0, 1, 50, 100])('keeps real catalog selection while proposing and rendering %s percent', async (percent) => {
  const before = useMakeupStore.getState().makeup.lip!;
  await send(`립 진하기를 ${percent}%로 설정해 줘.`);
  const render = face().props.renderCommand;
  expect(render).toBeTruthy();
  expect(useMakeupStore.getState().makeup.lip).toEqual(before);
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  expect((post.mock.calls.find(([path]) => path === '/api/chat')![1] as any).arContext.lip)
    .toEqual({ productId: lip.id, shadeId: shade.id, intensity: before.intensity });
  await act(async () => { face().props.onRenderResult({ ...render, makeup: undefined, status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip).toEqual({ ...before, intensity: percent / 100 });
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: lip.id, shadeId: shade.id });
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'APPLIED' }), expect.anything());
});

it('keeps same-intensity NO_CHANGE distinct from a new application', async () => {
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.5); });
  await send('립 진하기를 50%로 설정해 줘.');
  const render = face().props.renderCommand;
  await act(async () => { face().props.onRenderResult({ ...render, status: 'rendered' }); });
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'NO_CHANGE' }), expect.anything());
});

it('invalidates a delayed proposal when the local blush command is used', async () => {
  let resolve!: (value: any) => void;
  let body: any;
  post.mockImplementationOnce((_path, payload) => { body = payload; return new Promise((r) => { resolve = r; }); });
  await send('립 진하기를 50%로 설정해 줘.');
  const before = useMakeupStore.getState().makeup.blush!.intensity;
  await send('블러셔를 조금 더 은은하게 해줘');
  expect(useMakeupStore.getState().makeup.blush!.intensity).toBe(Math.max(0.12, before - 0.18));
  await act(async () => { resolve(proposal(body)); });
  expect(face().props.renderCommand).toBeNull();
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it('restores latest Store state after a local command cancels a rendered candidate', async () => {
  await send('립 진하기를 50%로 설정해 줘.');
  const old = face().props.renderCommand;
  await send('블러셔를 조금 더 은은하게 해줘');
  const restore = face().props.renderCommand;
  expect(restore.kind).toBe('restore');
  expect(restore.makeup.lip.intensity).toBe(useMakeupStore.getState().makeup.lip!.intensity);
  await act(async () => { face().props.onRenderResult({ ...old, status: 'rendered' }); });
  expect(face().props.renderCommand.kind).toBe('restore');
  await act(async () => { face().props.onRenderResult({ ...restore, status: 'rendered' }); });
  expect(face().props.renderCommand).toBeNull();
});

it('rejects the old candidate when develop WebView crash recovery creates a new instance', async () => {
  await send('립 진하기를 50%로 설정해 줘.');
  const old = face().props.renderCommand;
  await act(async () => { face().props.onCrash(); });
  await act(async () => { face().props.onStatus('tracking'); });
  await act(async () => { face().props.onRenderResult({ ...old, status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).not.toBe(0.5);
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it('neither executes nor calls the server for a compound request', async () => {
  const before = useMakeupStore.getState().makeup;
  await send('코랄 룩 보여주고 립 진하기를 50%로 설정해 줘.');
  expect(useMakeupStore.getState().makeup).toBe(before);
  expect(post).not.toHaveBeenCalled();
});

it('does not execute a local fallback when the server fails, and allows an explicit retry', async () => {
  const before = useMakeupStore.getState().makeup;
  post.mockRejectedValueOnce(new Error('network'));
  await send('립 진하기를 50%로 설정해 줘.');
  expect(useMakeupStore.getState().makeup).toBe(before);
  expect(face().props.renderCommand).toBeNull();
  await send('립 진하기를 50%로 설정해 줘.');
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(2);
  expect(face().props.renderCommand).toBeTruthy();
});

it('submits only once when the keyboard and send button fire together', async () => {
  await act(async () => { screen.root.findByType(TextInput).props.onChangeText('립 진하기를 50%로 설정해 줘.'); });
  await act(async () => {
    screen.root.findByType(TextInput).props.onSubmitEditing();
    screen.root.findByProps({ accessibilityLabel: 'ar.send' }).props.onPress();
  });
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
});

it('returns from zero to fifty with the same real product, shade, color and texture', async () => {
  const before = useMakeupStore.getState().makeup.lip!;
  for (const percent of [0, 50]) {
    await send(`립 진하기를 ${percent}%로 설정해 줘.`);
    const render = face().props.renderCommand;
    await act(async () => { face().props.onRenderResult({ ...render, status: 'rendered' }); });
    expect(useMakeupStore.getState().makeup.lip).toEqual({ ...before, intensity: percent / 100 });
    expect(useMakeupStore.getState().selections.lip).toEqual({ productId: lip.id, shadeId: shade.id });
  }
});

it('preserves local adjustment without tracking but keeps server execution disabled', async () => {
  await act(async () => { face().props.onStatus('no-face'); });
  const before = useMakeupStore.getState().makeup.blush!.intensity;
  await send('블러셔를 조금 더 은은하게 해줘');
  expect(useMakeupStore.getState().makeup.blush!.intensity).toBe(Math.max(0.12, before - 0.18));
  await send('립 진하기를 50%로 설정해 줘.');
  expect(post).not.toHaveBeenCalled();
});
