import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { ArSheet } from '@/components/ar/ArSheet';
import { ZONE_WHEEL_HUB_CENTER_FROM_BOTTOM } from '@/components/ar/ArZoneWheel';
import { OpenArcPalette } from '@/components/ar/OpenArcPalette';
import { ArConversationShades } from '@/components/ar/ArConversationPalette';
import { shadeTone, type ShadePreference } from '@/lib/arShadePreference';
import { colorFamily } from '@/lib/colorFamily';
import { isLipBaseCare, lipCareKind } from '@/lib/lipCare';
import { LOOK_STRENGTH_DEFAULT, LOOK_STRENGTH_MIN } from '@/lib/videoLookMakeup';
import ArTryOnScreen from '@/app/(tabs)/ar';
import { AR_PAINT_ZONES, useLookMakeupStore, useMakeupStore } from '@/store/makeupStore';
import { useSettingsStore } from '@/store/settingsStore';
import { useCartStore } from '@/store/cartStore';
import type { MakeupZone, Product } from '@/types';
import evaluationData from './fixtures/arControlEvaluation.json';

const products = (require('@/lib/devCatalog/oyCatalog.json') as { products: Product[] }).products;
const lip = products.find((product) => product.id === 'oy-a000000120880')!;
const blush = products.find((product) => product.makeupZone === 'blush' && product.texture && product.shades.length)!;
const shade = lip.shades.find((item) => item.id === '23')!;

let mockBottomInset = 0;
jest.mock('react-native-safe-area-context', () => {
  const actual = jest.requireActual('react-native-safe-area-context') as typeof import('react-native-safe-area-context');
  return { ...actual, useSafeAreaInsets: () => ({ top: 0, right: 0, bottom: mockBottomInset, left: 0 }) };
});
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
let mockPermission = { granted:true, canAskAgain:true };
const mockRequestPermission = jest.fn();
let mockParams: Record<string,string> = {};
let mockCatalog: {data:Product[];isError?:boolean;isPending?:boolean;refetch?:()=>Promise<unknown>};
const mockOpenBrowser = jest.fn();
jest.mock('expo-web-browser', () => ({openBrowserAsync:(url:string) => mockOpenBrowser(url)}));
jest.mock('expo-camera', () => ({ useCameraPermissions: () => [mockPermission, mockRequestPermission] }));
jest.mock('expo-speech', () => ({ speak: jest.fn(), stop: jest.fn(async () => {}) }));
import * as speech from 'expo-speech';
let mockMicLevel = -90;
async function finishTestUtterance() {
  await act(async () => { jest.advanceTimersByTime(400); });
  mockMicLevel = -90;
  await act(async () => { jest.advanceTimersByTime(1300); });
}
jest.mock('expo-audio', () => ({
  requestRecordingPermissionsAsync: async () => ({ granted: true }),
  setAudioModeAsync: async () => {},
  RecordingPresets: { HIGH_QUALITY: { ios: {}, android: {} } },
  AudioModule: { AudioRecorder: class {
    uri = 'file:///voice-test.m4a';
    record() {}
    getStatus() { return { isRecording: true, metering: mockMicLevel }; }
    async prepareToRecordAsync() {}
    async stop() {}
    release() {}
  } },
}));
jest.mock('expo-file-system', () => ({
  ...jest.requireActual('expo-file-system'),
  File: class { async arrayBuffer() { return new ArrayBuffer(8); } },
}));
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
    useLocalSearchParams: () => mockParams,
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
jest.mock('@/lib/queries', () => ({
  useMe: () => ({ data: undefined, isPending: false }),
  useTryOnProducts: () => mockCatalog,
}));

jest.mock('@/lib/api', () => ({ apiPostOwned: jest.fn(), subscribeArIdentityChange: () => () => {} }));
import { apiPostOwned } from '@/lib/api';
import { useRouter } from 'expo-router';
import { Alert, AppState, StyleSheet, Text, TextInput, type ViewStyle } from 'react-native';
const post = jest.mocked(apiPostOwned);
let screen: renderer.ReactTestRenderer;
let serial = 0;
const owned = <T,>(data: T) => ({ data, owner: { kind: 'guest', id: 'guest-test' } });
function proposal(body: any) {
  return owned({ answer: '', arResult: { requestId: body.requestId, status: 'proposed',
    actionProposal: { commandId: `aaaaaaaa-aaaa-4aaa-8aaa-${String(++serial).padStart(12, '0')}`, expectedStateVersion: body.arContext.stateVersion,
      action: 'set_intensity', zone: 'lip', value: Number(body.message.match(/\d+/)[0]) / 100,
      productId: lip.id, shadeId: shade.id } } });
}
function tool(choice: string, fixedId?: string, args: Record<string, unknown> = {}) {
  post.mockImplementation(async (path, body: any) => {
    if (path === '/api/chat') {
      expect(body.arContext.control.choices).toContain(choice);
      return owned({ arResult: { requestId:body.requestId, status:'proposed', actionProposal:{
        action:'ar_control', commandId:fixedId ?? `aaaaaaaa-aaaa-4aaa-8aaa-${String(++serial).padStart(12, '0')}`,
        expectedStateVersion:body.arContext.stateVersion, choice, ...args,
      } } }) as never;
    }
    if (path === '/api/chat/ar-control/reply') return owned({answer:'테스트 응답'}) as never;
    return owned({received:true}) as never;
  });
}
function feedback() {
  const calls = post.mock.calls.filter(([path]) => path === '/api/chat/ar-control/reply');
  return JSON.parse((calls[calls.length - 1][1] as {result:string}).result);
}
function face() { return screen.root.findByType('ArFaceView' as never); }
function conversationToggle() { return screen.root.findByProps({ testID: 'ar-conversation-toggle' }); }
async function toggleConversation() {
  await act(async () => { conversationToggle().props.onPress(); });
}
async function openTestKeyboard() {
  const toggle = screen.root.findAllByProps({ testID: 'ar-conversation-toggle' })[0];
  if (toggle && !toggle.props.accessibilityState.expanded) await toggleConversation();
  if (!screen.root.findAllByType(TextInput).length) {
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.testKeyboard' }).props.onPress(); });
  }
}
async function send(text: string) {
  await openTestKeyboard();
  await act(async () => { screen.root.findByType(TextInput).props.onChangeText(text); });
  await act(async () => { screen.root.findByType(TextInput).props.onSubmitEditing(); });
}
beforeEach(async () => {
  jest.clearAllMocks();
  mockBottomInset = 0;
  mockPermission = {granted:true,canAskAgain:true};
  mockParams = {};
  useCartStore.getState().clear();
  mockCatalog = {data:products.filter(p=>p.id===lip.id || p.makeupZone==='blush')};
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
  expect(screen.root.findAllByProps({ children: `립 진하기를 ${percent}%로 설정해 줘.` }).length).toBeGreaterThan(0);
  expect(screen.root.findAllByProps({ children: 'ar.command.applied' })).toHaveLength(0);
  const render = face().props.renderCommand;
  expect(render).toBeTruthy();
  expect(useMakeupStore.getState().makeup.lip).toEqual(before);
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  expect((post.mock.calls.find(([path]) => path === '/api/chat')![1] as any).arContext.lip)
    .toEqual({ productId: lip.id, shadeId: shade.id, intensity: before.intensity });
  await act(async () => { face().props.onRenderResult({ ...render, makeup: undefined, status: 'rendered' }); });
  expect(screen.root.findAllByProps({ children: 'ar.command.applied' }).length).toBeGreaterThan(0);
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

it('keeps direct recording available and excludes recording from voice command choices', async () => {
  await act(async () => {
    screen.root.findAllByProps({ accessibilityRole: 'tab' }).find((tab) => tab.findAllByProps({ children: 'ar.mode.direct' }).length)!.props.onPress();
  });
  await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.arc.tools' }).props.onPress(); });
  const start = screen.root.findByProps({ accessibilityLabel: 'ar.rec.start' });
  await act(async () => { start.props.onPress(); });
  expect(face().props.recording).toBe(true);
  expect(face().props.onRecorder).toEqual(expect.any(Function));
  await act(async () => { screen.root.findByType(ArSheet).props.onClose(); });
  await act(async () => {
    screen.root.findAllByProps({ accessibilityRole: 'tab' }).find((tab) => tab.findAllByProps({ children: 'ar.mode.chat' }).length)!.props.onPress();
  });

  await send('립 진하기를 50%로 설정해 줘.');
  const [, request] = post.mock.calls.find(([path]) => path === '/api/chat')!;
  const { arContext } = request as { arContext: { control: { choices: string[] } } };
  expect(arContext.control.choices.some((choice) => choice.startsWith('control_recording/'))).toBe(false);
  const render = face().props.renderCommand;
  expect(render).toBeTruthy();
  expect(face().props.recording).toBe(true);
  await act(async () => { face().props.onRenderResult({ ...render, status: 'rendered' }); });

  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.5);
  expect(face().props.recording).toBe(true);
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'APPLIED' }), expect.anything());
});

it('invalidates a delayed proposal after a manual blush edit', async () => {
  let resolve!: (value: any) => void;
  let body: any;
  post.mockImplementationOnce((_path, payload) => { body = payload; return new Promise((r) => { resolve = r; }); });
  await send('립 진하기를 50%로 설정해 줘.');
  await act(async () => { useMakeupStore.getState().setIntensity('blush', 0.25); });
  expect(useMakeupStore.getState().makeup.blush!.intensity).toBe(0.25);
  await act(async () => { resolve(proposal(body)); });
  expect(face().props.renderCommand).toBeNull();
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it('restores latest Store state after a manual edit cancels a rendered candidate', async () => {
  await send('립 진하기를 50%로 설정해 줘.');
  const old = face().props.renderCommand;
  await act(async () => { useMakeupStore.getState().setIntensity('blush', 0.25); });
  const restore = face().props.renderCommand;
  expect(restore.kind).toBe('restore');
  expect(restore.makeup.lip.intensity).toBe(useMakeupStore.getState().makeup.lip!.intensity);
  await act(async () => { face().props.onRenderResult({ ...old, status: 'rendered' }); });
  expect(face().props.renderCommand.kind).toBe('restore');
  await act(async () => { face().props.onRenderResult({ ...restore, status: 'rendered' }); });
  expect(face().props.renderCommand).toBeNull();
  expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it('does not run a second local phrase handler while the first frame is pending', async () => {
  await send('립 진하기를 50%로 설정해 줘.');
  const pending = face().props.renderCommand;
  const before = useMakeupStore.getState().makeup;
  await send('립스틱 좀 더 연한 거 없어?');
  expect(face().props.renderCommand).toBe(pending);
  expect(useMakeupStore.getState().makeup).toBe(before);
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  await act(async () => { face().props.onRenderResult({ ...pending, status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.5);
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

it('leaves the renderer unchanged when AR Action asks for clarification', async () => {
  post.mockImplementationOnce(async (_path, body: any) => owned({ arResult: {
    requestId: body.requestId, status: 'clarification',
  } }) as never);
  const before = useMakeupStore.getState().makeup;
  await send('코랄 룩 보여주고 립 진하기를 50%로 설정해 줘.');
  expect(useMakeupStore.getState().makeup).toBe(before);
  expect(face().props.renderCommand).toBeNull();
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
  expect(screen.root.findAllByType(TextInput)).toHaveLength(0);
  expect(screen.root.findByProps({ accessibilityLabel: 'ar.voice.start' })).toBeTruthy();
  await openTestKeyboard();
  await act(async () => { screen.root.findByType(TextInput).props.onChangeText('립 진하기를 50%로 설정해 줘.'); });
  await act(async () => {
    screen.root.findByType(TextInput).props.onSubmitEditing();
    screen.root.findByProps({ accessibilityLabel: 'ar.send' }).props.onPress();
  });
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
});

it('sends the spoken request from the mic button, applies it and speaks after the frame is painted', async () => {
  jest.useFakeTimers();
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  try {
    const message = '볼 색을 좀만 연하게 해줘';
    tool('adjust_intensity/blush/down');
    post.mockResolvedValueOnce(owned({ text: message }) as never);
    expect(screen.root.findAllByProps({ accessibilityLabel: 'ar.voice.about' })).toHaveLength(0);
    expect(screen.root.findAllByProps({ children: 'ar.voice.consent' })).toHaveLength(0);
    mockMicLevel = -22;
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.start' }).props.onPress(); });
    expect(alert).not.toHaveBeenCalled();
    await finishTestUtterance();
    expect(screen.root.findAllByType(TextInput)).toHaveLength(0);
    expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
    expect(post).toHaveBeenCalledWith('/api/chat', expect.objectContaining({ message }), expect.anything());
    expect(speech.speak).not.toHaveBeenCalled();
    const before = useMakeupStore.getState().makeup.blush!.intensity;
    const frame = face().props.renderCommand;
    await act(async () => { face().props.onRenderResult({ ...frame, status: 'rendered' }); });
    expect(useMakeupStore.getState().makeup.blush!.intensity).toBeLessThan(before);
    expect(speech.speak).toHaveBeenCalledWith('테스트 응답', expect.anything());
    expect(conversationToggle().props.accessibilityState.expanded).toBe(false);
    expect(screen.root.findAllByProps({ children: message })).toHaveLength(0);
    await toggleConversation();
    expect(screen.root.findAllByProps({ children: message }).length).toBeGreaterThan(0);
    expect(screen.root.findAllByProps({ children: '테스트 응답' }).length).toBeGreaterThan(0);
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.finish' }).props.onPress(); });
  } finally {
    alert.mockRestore();
    jest.useRealTimers();
  }
});

it.each([
  ['거울 크게 열어줘.', 'set_view/mirror/on', 'set_view/mirror/off'],
  ['안내를 열어줘.', 'set_view/panel/info', 'set_view/panel/closed'],
])('opens %s and accepts the spoken follow-up in the same session', async (message, openChoice, closeChoice) => {
  jest.useFakeTimers();
  const opened = () => openChoice.startsWith('set_view/mirror/')
    ? screen.root.findAllByProps({ accessibilityLabel: 'ar.mirror.exit' }).length > 0
    : screen.root.findAllByType(ArSheet).length > 0;
  try {
    tool(openChoice);
    post.mockResolvedValueOnce(owned({ text: message }) as never);
    mockMicLevel = -22;
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.start' }).props.onPress(); });
    await finishTestUtterance();
    expect(opened()).toBe(true);
    expect(feedback()).toMatchObject({ choice: openChoice, status: 'APPLIED' });
    expect(screen.root.findByProps({ accessibilityLabel: 'ar.voice.finish' })).toBeTruthy();

    tool(closeChoice);
    post.mockResolvedValueOnce(owned({ text: '이제 닫아줘.' }) as never);
    mockMicLevel = -22;
    await act(async () => { jest.mocked(speech.speak).mock.lastCall?.[1]?.onDone?.(); });
    await finishTestUtterance();
    expect(opened()).toBe(false);
    expect(feedback()).toMatchObject({ choice: closeChoice, status: 'APPLIED' });
    expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(2);
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.finish' }).props.onPress(); });
  } finally {
    mockMicLevel = -90;
    jest.useRealTimers();
  }
});

it('starts voice from a product fitting screen and adds only its fixed shade', async () => {
  await act(async () => { screen.unmount(); });
  useMakeupStore.getState().startFit(lip, shade);
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  await act(async () => { face().props.onStatus('tracking'); });
  expect(screen.root.findAllByProps({ accessibilityRole: 'tab' })).toHaveLength(0);

  jest.useFakeTimers();
  try {
    tool('add_to_cart/fit_product');
    post.mockResolvedValueOnce(owned({ text: '지금 이 호수 하나 담아줘.' }) as never);
    mockMicLevel = -22;
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.start' }).props.onPress(); });
    await finishTestUtterance();
    const [, request] = post.mock.calls.find(([path]) => path === '/api/chat')!;
    const offered = (request as { arContext: { control: { choices: string[] } } }).arContext.control.choices;
    expect(offered).toContain('add_to_cart/fit_product');
    expect(offered).not.toContain('apply_shade/lip/pick');
    expect(useCartStore.getState().items).toMatchObject([{ productId: lip.id, shadeId: shade.id, quantity: 1 }]);
    await act(async () => { screen.root.findByProps({ accessibilityLabel: 'ar.voice.finish' }).props.onPress(); });
  } finally {
    mockMicLevel = -90;
    jest.useRealTimers();
  }
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

it('blocks both relative and absolute changes without tracking', async () => {
  await act(async () => { face().props.onStatus('no-face'); });
  const before = useMakeupStore.getState().makeup.blush!.intensity;
  tool('adjust_intensity/blush/down');
  await send('블러셔를 조금 더 은은하게 해줘');
  expect(feedback().status).toBe('REJECTED');
  expect(useMakeupStore.getState().makeup.blush!.intensity).toBe(before);
  tool('set_intensity/lip/half');
  await send('립은 지금 반 정도로 해줄래?');
  expect(feedback().status).toBe('REJECTED');
  expect(face().props.renderCommand).toBeNull();
  tool('get_state/lip');
  await send('그럼 지금 입에 올린 색은 뭐야?');
  expect(feedback()).toMatchObject({status:'OK', data:{product:{shadeId:shade.id}}});
});


it.each([
  ['지금 입에 바른 게 뭐야?', 'get_state/lip', 'OK'],
  ['눈썹 색도 구경할래.', 'select_zone/brow', 'APPLIED'],
  ['분홍 계열도 있어?', 'find_shades/lip/pink', 'OK'],
  ['전체 색을 다시 보여줘.', 'set_palette_filter/reset', 'NO_CHANGE'],
  ['가운데 색을 입에 올려봐.', 'apply_shade/palette_center', 'NO_CHANGE'],
  ['오일만 빼줘.', 'clear_layer/lipCare', 'NO_CHANGE'],
  ['아이섀도 반짝이만 빼줄래?', 'set_style/eyeshadow/matte', 'REJECTED'],
  ['이 룩 원래 눈화장으로 해줘.', 'restore_makeup/eyeshadow', 'REJECTED'],
  ['덜 쨍한 립도 좀 볼래.', 'explore_nearby/show/muted', 'APPLIED'],
  ['피부색에 가까운 파운데이션은 뭐야?', 'get_recommendations/foundation_match', 'REJECTED'],
  ['안 바른 쪽이랑 나란히 보고 싶어.', 'set_view/compare/on', 'APPLIED'],
  ['이 립 상세 페이지 좀 열어줘.', 'navigate/product', 'APPLIED'],
  ['이 립 하나만 담아줘.', 'add_to_cart/current_product', 'APPLIED'],
  ['나도 이 메이크업 따라해볼래.', 'control_practice/start', 'APPLIED'],
  ['이 룩 전체를 가볍게 해줘.', 'set_look_strength/down', 'REJECTED'],
  ['카메라 말고 색만 볼래.', 'control_camera/swatches_only', 'APPLIED'],
  ['색상이 안 뜨네. 다시 불러줄래?', 'retry_catalog', 'NO_CHANGE'],
])('routes single-turn chat through the mounted screen: %s', async (message,choice,status) => {
  tool(choice);
  const before = useMakeupStore.getState().makeup;
  await send(message);
  const res = feedback();
  expect(res).toMatchObject({choice,status});
  expect(useMakeupStore.getState().makeup).toBe(before);
  if (choice === 'select_zone/brow') expect(res.data).toEqual({activeZone:'brow',count:0});
  if (choice === 'get_state/lip') expect(res.data.product.shadeId).toBe(shade.id);
  if (choice === 'set_view/compare/on') expect(face().props.compare).toBe(true);
  if (choice === 'add_to_cart/current_product') expect(res.data).toMatchObject([{shadeId:shade.id,quantity:1}]);
  if (choice === 'control_camera/swatches_only') expect(screen.root.findAllByType('ArFaceView' as never)).toHaveLength(0);
});

it.each([
  ['볼이 너무 도드라져. 살짝만 빼줘.', 'adjust_intensity/blush/down', 'rendered', 'APPLIED'],
  ['옆에 있는 색도 입에 올려봐.', 'step_shade/next', 'rendered', 'APPLIED'],
  ['지금 바른 립 반 정도만 남겨줘.', 'set_intensity/lip/half', 'failed', 'FAILED'],
])('waits for frame before speaking: %s', async (message,choice,frame,status) => {
  tool(choice);
  const before = useMakeupStore.getState().makeup;
  await send(message);
  const cmd = face().props.renderCommand;
  expect(cmd).toBeTruthy();
  expect(useMakeupStore.getState().makeup).toBe(before);
  expect(post.mock.calls.some(([path]) => path === '/api/chat/ar-control/reply')).toBe(false);
  expect(speech.speak).not.toHaveBeenCalled();
  await act(async () => { face().props.onRenderResult({...cmd,status:frame}); });
  expect(feedback()).toMatchObject({choice,status});
  expect(speech.speak).toHaveBeenCalledWith('테스트 응답', expect.objectContaining({ language:'ko-KR' }));
  if (status === 'FAILED') expect(useMakeupStore.getState().makeup).toBe(before);
  else expect(useMakeupStore.getState().makeup).not.toBe(before);
});

async function refresh() { await act(async()=>{screen.update(<ArTryOnScreen />);}); }
async function startBareChat(catalog: Product[]) {
  await act(async () => { screen.unmount(); });
  useMakeupStore.getState().reset();
  mockCatalog = {data:catalog};
  await act(async () => { screen = renderer.create(<ArTryOnScreen />); });
  await act(async () => {
    screen.root.findAllByProps({accessibilityRole:'tab'}).find(tab =>
      tab.findAllByProps({children:'ar.mode.chat'}).length)!.props.onPress();
    face().props.onStatus('tracking');
  });
  expect(Object.values(useMakeupStore.getState().selections).filter(Boolean)).toEqual([]);
  expect(screen.root.findByProps({ testID: 'ar-conversation-guide' })).toBeTruthy();
}

it.each([0, 34])('aligns the microphone with the direct exploration hub at bottom inset %i', async (bottomInset) => {
  mockBottomInset = bottomInset;
  await refresh();
  const dock = screen.root.findByProps({ testID: 'ar-conversation-dock' });
  const mic = screen.root.findByProps({ accessibilityRole: 'button', accessibilityLabel: 'ar.voice.start' });
  const paddingBottom = StyleSheet.flatten<ViewStyle>(dock.props.style)?.paddingBottom;
  const micHeight = StyleSheet.flatten<ViewStyle>(mic.props.style)?.height;
  const centerFromBottom = Number(paddingBottom) + Number(micHeight) / 2;
  expect(centerFromBottom).toBe(Math.max(24, bottomInset) + ZONE_WHEEL_HUB_CENTER_FROM_BOTTOM);
});

it('replaces the entry guide with the confirmed product’s own shades and keeps them after a failed product change', async () => {
  const [first, second] = lip.shades;
  const product = { ...lip, shades: [first, second] };
  const other = { ...lip, id: 'other-lip', shades: [{ ...first, name: '다른 립의 호수', hex: '#D26280' }] };
  await startBareChat([product, other]);
  expect(conversationToggle().props.accessibilityState.expanded).toBe(false);
  const guide = screen.root.findByProps({ testID: 'ar-conversation-guide' });
  const cardText = guide.findAllByType(Text).map(node => node.props.children);
  expect(cardText).toEqual([
    'ar.conversation.step', 'ar.conversation.startMic',
    'ar.conversation.step', 'ar.conversation.askProduct',
    'ar.conversation.step', 'ar.conversation.tryColor',
  ]);
  expect(screen.root.findAllByProps({ testID: 'ar-conversation-shades' })).toHaveLength(0);

  tool('apply_shade/product_shade', undefined, { productId: product.id, shadeId: first.id });
  await send('이 립 한번 발라줘.');
  await toggleConversation();
  expect(screen.root.findByProps({ testID: 'ar-conversation-guide' })).toBeTruthy();
  expect(screen.root.findAllByProps({ testID: 'ar-conversation-shades' })).toHaveLength(0);
  await act(async () => { face().props.onRenderResult({ ...face().props.renderCommand, status: 'rendered' }); });

  const chip = (label: string) => screen.root.findByProps({ testID: 'ar-conversation-shades' })
    .findByProps({ accessibilityRole: 'radio', accessibilityLabel: label });
  expect(screen.root.findAllByProps({ testID: 'ar-conversation-guide' })).toHaveLength(0);
  expect(chip(first.name).props.accessibilityState.checked).toBe(true);
  expect(chip(second.name).props.accessibilityState.checked).toBe(false);
  expect(screen.root.findAllByProps({ accessibilityLabel: other.shades[0].name })).toHaveLength(0);
  await act(async () => { chip(second.name).props.onPress(); });
  expect(chip(second.name).props.accessibilityState.checked).toBe(true);
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: product.id, shadeId: second.id });
  expect(face().props.makeup.lip.hex).toBe(second.hex);
  await act(async () => { chip(second.name).props.onPress(); });
  expect(useMakeupStore.getState().selections.lip?.shadeId).toBe(second.id);

  tool('apply_shade/product_shade', undefined, { productId: other.id, shadeId: other.shades[0].id });
  await send('다른 제품도 궁금해.');
  await act(async () => { face().props.onRenderResult({ ...face().props.renderCommand, status: 'failed' }); });
  expect(feedback().status).toBe('FAILED');
  expect(chip(second.name).props.accessibilityState.checked).toBe(true);
  expect(screen.root.findAllByProps({ accessibilityLabel: other.shades[0].name })).toHaveLength(0);
});

it('retains requests and replies across a closed conversation and camera suspension', async () => {
  expect(useMakeupStore.getState().selections.lip?.shadeId).toBe(shade.id);
  expect(screen.root.findByProps({ testID: 'ar-conversation-guide' })).toBeTruthy();
  const turns = [
    { message: '눈화장은 어떻게 할까?', answer: '눈꼬리에만 살짝 포인트를 줘 보세요.' },
    { message: '립은 어떤 느낌이 어울릴까?', answer: '차분한 장밋빛도 잘 어울릴 거예요.' },
  ];
  post.mockImplementation(async (_path, body: any) => owned({
    answer: turns.find(turn => turn.message === body.message)!.answer,
    arResult: { requestId: body.requestId, status: 'noop' },
  }) as never);
  for (const turn of turns) await send(turn.message);
  await toggleConversation();
  for (const text of turns.flatMap(turn => [turn.message, turn.answer])) {
    expect(screen.root.findAllByProps({ children: text })).toHaveLength(0);
  }
  const [, onAppStateChange] = jest.mocked(AppState.addEventListener).mock.calls.find(([event]) => event === 'change')!;
  await act(async () => { onAppStateChange('inactive'); });
  expect(screen.root.findAllByType('ArFaceView' as never)).toHaveLength(0);
  await act(async () => { onAppStateChange('active'); });
  expect(face()).toBeTruthy();
  await toggleConversation();
  const messages = screen.root.findAllByType(Text).map(node => node.props.children);
  const ordered = turns.flatMap(turn => [turn.message, turn.answer]);
  expect(messages.filter(message => ordered.includes(message))).toEqual(ordered);
  expect(post.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(2);
});

it('can send the first chat while the camera and catalog are starting', async () => {
  await startBareChat([]);
  mockCatalog = {data:[],isPending:true};
  await refresh();
  await act(async () => {face().props.onStatus('loading');});
  const choice = 'apply_shade/blush/pick';
  tool(choice);
  let issue!: () => void;
  post.mockImplementationOnce((_path, body:any) => new Promise(resolve => {
    expect(body.arContext.lip).toBeNull();
    issue = () => resolve(owned({arResult:{requestId:body.requestId,status:'proposed',
      actionProposal:{action:'ar_control',choice,commandId:'cccccccc-cccc-4ccc-8ccc-000000000001',
        expectedStateVersion:body.arContext.stateVersion}}}) as never);
  }));
  await send('볼에 블러셔 하나 발라줘');
  mockCatalog = {data:[{...blush,shades:[blush.shades[0]]}]};
  await refresh();
  await act(async () => {face().props.onStatus('tracking');});
  await act(async () => {issue();});
  const cmd = face().props.renderCommand;
  expect(cmd.makeup.blush.hex).toBe(blush.shades[0].hex);
  await act(async () => {face().props.onRenderResult({...cmd,status:'rendered'});});
  expect(feedback()).toMatchObject({status:'APPLIED'});
  expect(useMakeupStore.getState().selections.lip).toBeUndefined();
});

it.each([...AR_PAINT_ZONES,'oil','balm'])('starts %s in chat with a bare face and focuses its actual selection', async target => {
  const care = target === 'oil' || target === 'balm';
  const zone = care ? 'lip' : target as MakeupZone;
  const product = products.find(p => p.makeupZone === zone && p.texture && p.shades.length &&
    (zone !== 'lip' || !isLipBaseCare(p) && lipCareKind(p) === (care ? target : null)))!;
  await startBareChat([{...product,shades:[product.shades[0]]}]);
  tool('apply_shade/' + zone + '/' + (care ? target : 'pick'));
  await send('이 제품 한번 발라줘');
  const cmd = face().props.renderCommand;
  expect(cmd.makeup[care ? 'lipCare' : zone]).toBeTruthy();
  expect(Object.values(useMakeupStore.getState().selections).filter(Boolean)).toEqual([]);
  await act(async () => {face().props.onRenderResult({...cmd,status:'rendered'});});
  const outcome = feedback();
  expect(outcome.status).toBe('APPLIED');
  const row = screen.root.findByProps({testID:'ar-current-product'});
  const displayedText = row.findAllByType(Text).map(node => React.Children.toArray(node.props.children).join(''));
  expect(displayedText).toContain(`ar.zone.${zone} · ${outcome.featuredShade.shade}`);
  const selected = screen.root.findByProps({ testID: 'ar-conversation-shades' })
    .findByProps({ accessibilityRole: 'radio', accessibilityLabel: outcome.featuredShade.shade });
  expect(selected.props.accessibilityState.checked).toBe(true);
  expect(useMakeupStore.getState().selections.lip == null).toBe(zone !== 'lip' || care);
});
async function chat(choice:string,text:string) { tool(choice); await send(text); return feedback(); }

it('shows the filter intersection even if empty and never wears a substitute',async()=>{
  const matte={...lip,id:'matte',texture:'matte' as const,shades:[{...shade,hex:'#ad3120'}]};
  const pink={...lip,texture:'glossy' as const,shades:[{...shade,hex:'#ea76b2'}]};
  mockCatalog={data:[matte,pink]};
  await refresh();
  const before=useMakeupStore.getState().makeup;
  expect(await chat('set_palette_filter/matte','보송한 것만 볼래.')).toMatchObject({status:'APPLIED',data:{texture:'matte',count:1}});
  expect(await chat('get_state/lip','지금 입에 바른 색이 뭐야?')).toMatchObject({data:{product:{productId:pink.id},center:{productId:matte.id}}});
  expect(await chat('set_palette_filter/pink/matte','핑크 중에 보송한 것만 보여줘.')).toMatchObject({status:'APPLIED',data:{count:0}});
  expect(await chat('apply_shade/palette_center','가운데 거 입에 올려봐.')).toMatchObject({status:'REJECTED'});
  expect(useMakeupStore.getState().makeup).toBe(before);
});

it('keeps the nearby anchor and direction when filtering only the texture', async () => {
  const matte = { ...lip, id: 'nearby-matte', texture: 'matte' as const, shades: [{ ...shade, hex: '#9F596D' }] };
  mockCatalog = { data: [lip, matte] };
  await refresh();
  const opened = await chat('explore_nearby/show/muted', '지금 색 기준으로 차분한 색들 볼래.');
  expect(opened).toMatchObject({ status: 'APPLIED', data: { anchor: { productId: lip.id, shadeId: shade.id }, direction: 'muted' } });
  const narrowed = await chat('set_palette_filter/matte', '여기서 보송한 제형만 남겨줘.');
  expect(narrowed).toMatchObject({ status: 'APPLIED', data: {
    nearby: true, anchor: opened.data.anchor, direction: 'muted', texture: 'matte', count: expect.any(Number),
  } });
});

it('shows nearby candidates in a horizontal conversation strip and applies the tapped product shade', async () => {
  const first = { ...lip, id: 'nearby-a', name: '비슷한 립 A', shades: [shade] };
  const second = { ...lip, id: 'nearby-b', name: '비슷한 립 B', shades: [shade] };
  mockCatalog = { data: [lip, second, first] };
  await refresh();
  const opened = await chat('explore_nearby/show/similar', '지금 입술이랑 비슷한 색 좀 볼래.');
  expect(opened.data.shades.map((item: { productId: string }) => item.productId)).toEqual([first.id, second.id]);
  expect(screen.root.findAllByType(OpenArcPalette)).toHaveLength(0);
  const strip = screen.root.findByType(ArConversationShades);
  expect(strip.props.items.map((item: { product: Product }) => item.product.id)).toEqual([first.id, second.id]);
  const secondChip = strip.findByProps({ accessibilityRole: 'radio', accessibilityLabel: [second.brand, second.name, shade.name].join(' · ') });
  await act(async () => { secondChip.props.onPress(); });
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: second.id, shadeId: shade.id });
});
it('reports the actual active zone, including zero results and a repeated selection',async()=>{
  mockCatalog={data:[{...blush,makeupZone:'brow',shades:blush.shades.slice(0,1).concat(shade)}]};
  await refresh();
  expect(await chat('select_zone/brow','눈썹도 좀 볼래.')).toMatchObject({status:'APPLIED',data:{activeZone:'brow',count:2}});
  mockCatalog={data:[]}; await refresh();
  expect(await chat('select_zone/brow','눈썹도 좀 볼래.')).toMatchObject({status:'NO_CHANGE',data:{count:0}});
});
it('uses measured skin for recommendations, including a loaded empty foundation catalog',async()=>{
  const base={...blush,makeupZone:'foundation' as const,shades:[0,1,2,3].map((n)=>({...shade,id:String(n),hex:['#aa6040','#e2be9d','#ddba95','#edccaf'][n]}))};
  mockCatalog={data:[base]}; await refresh();
  await act(async()=>face().props.onSkinTone({L:80,a:8,b:20,conf:0.9}));
  const out=await chat('get_recommendations/foundation_match','내 피부색이랑 가까운 게 뭐야?');
  expect(out.status).toBe('OK'); expect(out.data).toHaveLength(3);
  expect(useMakeupStore.getState().selections.foundation).toBeUndefined();
  mockCatalog={data:[]}; await refresh();
  expect(await chat('get_recommendations/foundation_match','내 피부색이랑 가까운 게 뭐야?')).toMatchObject({status:'OK',data:[]});
});

it('applies and opens the exact second shade from the shown recommendation list', async () => {
  const foundation: Product = { ...blush, id: 'rank-test-foundation', makeupZone: 'foundation',
    shades: ['#AA6040', '#E2BE9D', '#DDBA95', '#EDCCAF'].map((hex, i) =>
      ({ ...shade, hex, id: String(i), name: 'Foundation ' + i })) };
  mockCatalog = { data: [foundation] };
  await refresh();
  await act(async () => { face().props.onSkinTone({ L: 80, a: 8, b: 20, conf: 0.9 }); });
  await chat('select_zone/foundation', '파운데이션도 좀 볼래.');
  const shown = await chat('get_recommendations/foundation_match', '내 피부색에 가까운 색 몇 개 보여줘.');
  expect(shown).toMatchObject({ status: 'OK', data: expect.arrayContaining([expect.objectContaining({ productId: foundation.id })]) });
  const strip = screen.root.findByType(ArConversationShades);
  expect(strip.props.items.map((item: { shade: { id: string } }) => item.shade.id))
    .toEqual(shown.data.map((item: { shadeId: string }) => item.shadeId));
  expect(useMakeupStore.getState().selections.foundation).toBeUndefined();
  const second = shown.data[1];
  // A fresh skin tone can change a later ranking, but the displayed order is still the user's reference.
  await act(async () => { face().props.onSkinTone({ L: 53, a: 19, b: 40, conf: 0.9 }); });
  tool('apply_recommendation/foundation_match/2');
  await send('추천한 것 중에 두 번째로 발라줘.');
  const frame = face().props.renderCommand;
  expect(frame.makeup.foundation.hex).toBe(foundation.shades.find(s => s.id === second.shadeId)?.hex);
  await act(async () => { face().props.onRenderResult({ ...frame, status: 'rendered' }); });
  expect(feedback()).toMatchObject({ status: 'APPLIED', after: { product: { productId: second.productId, shadeId: second.shadeId } } });
  expect(useMakeupStore.getState().selections.foundation).toEqual({ productId: second.productId, shadeId: second.shadeId });
  expect(await chat('navigate/recommendation/foundation_match/2', '그 두 번째 제품 자세히 볼래.'))
    .toMatchObject({ status: 'APPLIED', data: { productId: second.productId, shadeId: second.shadeId } });
  expect(useRouter().push).toHaveBeenCalledWith({
    pathname: '/product/[id]', params: { id: second.productId, shade: second.shadeId },
  });
  mockCatalog = { data: [{ ...foundation, shades: foundation.shades.filter(s => s.id !== second.shadeId) }] };
  await refresh();
  let offered: string[] | undefined;
  post.mockImplementationOnce(async (_path, body: any) => {
    offered = body.arContext.control.choices;
    return owned({ arResult: { requestId: body.requestId, status: 'clarification' } }) as never;
  });
  await send('아까 추천 두 번째 다시 보여줘.');
  expect(offered).toBeDefined();
  expect(offered).not.toContain('apply_recommendation/foundation_match/2');
});

it('changes only the eyeshadow accent and keeps the shade that was worn underneath', async () => {
  const base = { ...shade, id: 'eye-base', name: '베이지', hex: '#906C58' };
  const accent = { ...shade, id: 'eye-accent', name: '브라운', hex: '#704434' };
  const plum = { ...shade, id: 'eye-plum', name: '플럼', hex: '#854458' };
  const product: Product = { ...blush, id: 'eye-accent-test', makeupZone: 'eyeshadow', shades: [base, accent, plum] };
  mockCatalog = { data: [...mockCatalog.data, product] };
  await refresh();
  await act(async () => { useMakeupStore.getState().applyShade(product, base); });
  const before = useMakeupStore.getState().makeup.eyeshadow;

  tool('set_shadow_point/product_shade', undefined, { productId: product.id, shadeId: accent.id });
  await send('이 색은 눈꼬리에만 얹어줘.');
  const addFrame = face().props.renderCommand;
  expect(addFrame.makeup.eyeshadow).toMatchObject({ hex: base.hex, hexTo: accent.hex });
  expect(useMakeupStore.getState().makeup.eyeshadow).toEqual(before);
  await act(async () => { face().props.onRenderResult({ ...addFrame, status: 'rendered' }); });
  expect(feedback()).toMatchObject({ status: 'APPLIED', data: { pointShade: { shadeId: accent.id } } });
  const pointChip = (name: string) => screen.root.findByProps({ testID: 'ar-conversation-shades' })
    .findByProps({ accessibilityRole: 'radio', accessibilityLabel: name });
  expect(pointChip(accent.name).props.accessibilityState.checked).toBe(true);
  await act(async () => { pointChip(plum.name).props.onPress(); });
  expect(pointChip(plum.name).props.accessibilityState.checked).toBe(true);
  expect(face().props.makeup.eyeshadow).toMatchObject({ hex: base.hex, hexTo: plum.hex });
  expect(useMakeupStore.getState().selections.eyeshadow).toEqual({ productId: product.id, shadeId: base.id });

  tool('step_shade/previous');
  await send('바로 전 색으로 해볼까?');
  const previousFrame = face().props.renderCommand;
  expect(previousFrame.makeup.eyeshadow).toMatchObject({ hex: base.hex, hexTo: accent.hex });
  await act(async () => { face().props.onRenderResult({ ...previousFrame, status: 'rendered' }); });
  expect(pointChip(accent.name).props.accessibilityState.checked).toBe(true);
  tool('set_shadow_point/clear');
  await send('눈꼬리에 얹은 포인트 색만 빼줘.');
  const clearFrame = face().props.renderCommand;
  await act(async () => { face().props.onRenderResult({ ...clearFrame, status: 'rendered' }); });
  expect(feedback()).toMatchObject({ status: 'APPLIED', after: { point: null } });
  expect(useMakeupStore.getState().selections.eyeshadow).toEqual({ productId: product.id, shadeId: base.id });
  expect(useMakeupStore.getState().makeup.eyeshadow).toEqual(before);
});

it('selects a shade while the face is lost and leaves the frame result pending', async () => {
  const nextShade = lip.shades.find(s => s.id !== shade.id)!;
  await act(async () => { face().props.onStatus('no-face'); });
  tool('apply_shade/product_shade', undefined, { productId: lip.id, shadeId: nextShade.id });
  await send('다른 립 색으로 바꿔줄래?');
  expect(face().props.renderCommand).toBeNull();
  expect(feedback()).toMatchObject({ status: 'OK', renderPending: true, featuredShade: { shade: nextShade.name } });
  expect(useMakeupStore.getState().selections.lip).toEqual({ productId: lip.id, shadeId: nextShade.id });
  await act(async () => { face().props.onStatus('tracking'); });
  expect(face().props.makeup.lip.hex).toBe(nextShade.hex);
});
it('opens only the worn product merchant link and handles missing target independently of palette center',async()=>{
  const url='https://example.com/product';
  mockCatalog={data:[{...lip,sourceUrl:url}]}; await refresh();
  expect(await chat('navigate/store','이 립 판매처 열어줘.')).toMatchObject({status:'APPLIED',data:{productId:lip.id}});
  expect(mockOpenBrowser).toHaveBeenCalledWith(url);
  mockCatalog={data:[{...lip,sourceUrl:undefined}]}; await refresh();
  expect(await chat('navigate/store','이 립 판매처 열어줘.')).toMatchObject({status:'REJECTED'});
  expect(mockOpenBrowser).toHaveBeenCalledTimes(1);
  await act(async()=>{useMakeupStore.getState().clearZone('lip');});
  expect(await chat('add_to_cart/current_product','이 립 하나만 담아줘.')).toMatchObject({status:'REJECTED'});
  expect(await chat('explore_nearby/show/similar','이 색이랑 비슷한 거 보여줘.')).toMatchObject({status:'REJECTED'});
});
it.each([true,false])('distinguishes a catalog reload from another failure (%s)',async(ok)=>{
  mockCatalog={data:[],isError:true,refetch:async()=> {
    const data=ok?[{...lip,shades:[shade,shade,shade]}]:[];
    mockCatalog={data,isError:!ok}; return mockCatalog;
  }};
  await refresh();
  const out=await chat('retry_catalog','색이 안 떠. 다시 불러줄래?');
  expect(out.status).toBe(ok?'APPLIED':'FAILED');
  if(ok) expect(out.data.count).toBe(3);
});
it('rejects mirror and a denied camera permission in swatch mode',async()=>{
  await chat('control_camera/swatches_only','색만 구경할래.');
  expect(await chat('control_camera/swatches_only','색만 구경할래.')).toMatchObject({status:'NO_CHANGE'});
  expect(await chat('set_view/mirror/on','얼굴만 크게 볼래.')).toMatchObject({status:'REJECTED'});
  mockPermission={granted:false,canAskAgain:true};mockRequestPermission.mockResolvedValue({granted:false});
  await refresh();
  expect(await chat('control_camera/request_access','얼굴에 올려서 보고 싶어.')).toMatchObject({status:'REJECTED'});
  expect(screen.root.findAllByType('ArFaceView' as never)).toHaveLength(0);
});
it('starts practice and reports the last next step as exiting the active look',async()=>{
  await act(async()=>{useMakeupStore.setState({activeLook:{id:'demo',title:'Demo'}});});
  const start=await chat('control_practice/start','이 메이크업 따라 해볼래.');
  expect(start).toMatchObject({status:'APPLIED',data:{key:expect.any(String),text:expect.any(String)}});
  let step=start;
  for(let i=0;i<12 && step.data.active!==false;i++) step=await chat('control_practice/next','다음 단계로 넘겨줘.');
  expect(step).toMatchObject({status:'APPLIED',data:{active:false}});
});
it('confirms whole video look strength with the renderer and respects its lower limit', async () => {
  mockParams = { video: '1' };
  await act(async () => {
    useLookMakeupStore.getState().reset();
    useLookMakeupStore.getState().applyShade(lip, shade);
    useLookMakeupStore.setState({ activeLook: { id: 'celebrity-e1gSkUdG6Bo', title: 'Look' } });
  });
  await refresh();
  await act(async () => {
    screen.root.findAllByProps({ accessibilityRole: 'tab' }).find(tab =>
      tab.findAllByProps({ children: 'ar.mode.chat' }).length)!.props.onPress();
    face().props.onStatus('tracking');
  });
  const productMakeup = useMakeupStore.getState().makeup;
  const lookIntensity = useLookMakeupStore.getState().makeup.lip!.intensity;
  tool('adjust_intensity/lip/down');
  await send('립만 조금 연하게 해줘.');
  await act(async () => {
    face().props.onRenderResult({ ...face().props.renderCommand, status: 'rendered' });
  });
  expect(feedback().status).toBe('APPLIED');
  expect(useLookMakeupStore.getState().makeup.lip!.intensity).toBeLessThan(lookIntensity);
  expect(useMakeupStore.getState().makeup).toBe(productMakeup);

  tool('set_look_strength/down');
  const steps = Math.ceil((LOOK_STRENGTH_DEFAULT - LOOK_STRENGTH_MIN) * 10);
  for (let step = 0; step < steps; step++) {
    await send('이 룩 전체를 가볍게 해줘.');
    const pending = face().props.renderCommand;
    expect(pending).toBeTruthy();
    await act(async () => { face().props.onRenderResult({ ...pending, status: 'rendered' }); });
    expect(feedback()).toMatchObject({
      status: 'APPLIED',
      data: {
        before: expect.closeTo(LOOK_STRENGTH_DEFAULT - step / 10),
        after: expect.closeTo(Math.max(LOOK_STRENGTH_MIN, LOOK_STRENGTH_DEFAULT - (step + 1) / 10)),
      },
    });
  }
  expect(await chat('set_look_strength/down', '이 룩 전체를 가볍게 해줘.')).toMatchObject({
    status: 'NO_CHANGE',
    data: { before: LOOK_STRENGTH_MIN, after: LOOK_STRENGTH_MIN },
  });
});

it('adds only the current lip and does not replay a duplicate command',async()=>{
  await act(async()=>{useCartStore.getState().add({productId:lip.id,shadeId:shade.id});});
  tool('add_to_cart/current_product','bbbbbbbb-bbbb-4bbb-8bbb-000000000001');
  for (let n=0;n<2;n++) {
    await send('이 립 하나만 담아줘.');
    expect(feedback()).toMatchObject({status:'APPLIED',data:[{productId:lip.id,beforeQuantity:1,quantity:2}]});
  }
  expect(useCartStore.getState().items).toMatchObject([{productId:lip.id,quantity:2}]);
});
// Optional: start the local chatbot with its configured model; no camera or member data is transmitted.
const livePort = Number(process.env.AR_CONTROL_TEST_PORT);

type EvalTurn = {
  message: string; proposal: Record<string, unknown> | null; status: string;
  answer: string; elapsedMs: number; after: unknown; history: unknown; result?: unknown;
};
type EvaluationCase = {
  id: string; group: string; message: string; expected: string;
  setup?: { manual?: string; say?: string; intensity?: number; zone?: MakeupZone }[];
  check: {
    choice?: string; params?: Record<string, string | number | boolean>; shade?: string;
    zone?: MakeupZone; intensity?: number; unchanged?: boolean; readonly?: boolean;
    clarification?: boolean; status?: string; history?: number; scope?: string;
  };
};
const arEvaluationCases = evaluationData as EvaluationCase[];
type EvalRecord = { id: string; group: string; message: string; expected: string;
  start?: unknown; setup: unknown[]; turns: EvalTurn[]; passed: boolean; error?: string };
const evalRecords: EvalRecord[] = [];
const evalReport = process.env.AR_EVAL_REPORT;

(evalReport && livePort ? it.each : it.skip.each)(arEvaluationCases)('AR_EVAL $id $group $message', async (sample: EvaluationCase) => {
  const row: EvalRecord = {id:sample.id,group:sample.group,message:sample.message,expected:sample.expected,
    setup:[],turns:[],passed:false};
  evalRecords.push(row);
  const state = useMakeupStore.getState;
  const snapshot = () => JSON.parse(JSON.stringify({
    selections:state().selections, makeup:state().makeup, history:state().tryOnHistory,
  }));
  const guest = 'ar-eval-' + require('node:crypto').randomUUID();
  const events: {path:string;body:any;data:any}[] = [];
  const transportErrors: string[] = [];
  post.mockImplementation(async (path, body:any) => {
    const data = await new Promise<any>((resolve,reject) => {
      const req = require('node:http').request({
        hostname:process.env.AR_CONTROL_TEST_HOST || '127.0.0.1',port:livePort,path,method:'POST',
        headers:{'content-type':'application/json','x-vishue-anonymous-id':guest},
      }, (res:any) => {
        let text='';res.setEncoding('utf8');res.on('data',(chunk:string)=>{text+=chunk;});
        res.on('end',()=>{
          if(res.statusCode!==200) {
            transportErrors.push(path+' HTTP '+res.statusCode+' '+text);
            reject(new Error(transportErrors.at(-1)));
          } else resolve(JSON.parse(text));
        });
      });
      req.setTimeout(65000,()=>req.destroy(new Error('HTTP timeout')));
      req.on('error',(error:Error)=>{transportErrors.push(error.message);reject(error);});
      req.end(JSON.stringify(body));
    });
    events.push({path,body,data});
    return owned(data) as never;
  });
  async function until(predicate:()=>boolean) {
    const end=Date.now()+70000;
    while(!predicate() && !transportErrors.length && Date.now()<end) {
      await act(async()=>{await new Promise(resolve=>setTimeout(resolve,50));});
    }
    if(transportErrors.length) throw new Error(transportErrors.join('\n'));
    if(!predicate()) throw new Error('Timed out waiting for app response');
  }
  async function turn(message:string) {
    const offset=events.length, started=Date.now();
    await send(message);
    await until(()=>events.slice(offset).some(event=>event.path==='/api/chat'));
    const response=events.slice(offset).find(event=>event.path==='/api/chat')!.data;
    const proposal=response.arResult?.actionProposal ?? null;
    if(proposal) {
      await until(()=>!!face().props.renderCommand || events.slice(offset).some(event=>event.path.endsWith('/reply')));
      const command=face().props.renderCommand;
      if(command) await act(async()=>{
        face().props.onRenderResult({...command,status:'rendered'});
      });
    }
    const feedbackEvent=()=>events.slice(offset).find(event=>event.path.endsWith('/reply'));
    const answer=()=>proposal?.onAppliedReply && screen.root.findAllByType(Text).some(node=>node.props.children===proposal.onAppliedReply)
      ? proposal.onAppliedReply as string : feedbackEvent()?.data.answer ?? (!proposal ? response.answer : '');
    await until(()=>!!answer());
    if(proposal) await until(()=>events.slice(offset).some(event=>event.path==='/api/chat/acks'));
    const ack=events.slice(offset).find(event=>event.path==='/api/chat/acks');
    const feedback=feedbackEvent();
    const outcome=feedback ? JSON.parse(feedback.body.result) : undefined;
    const recorded: EvalTurn = {
      message,proposal,status:outcome?.status ?? ack?.body.status ?? response.arResult?.status ?? 'unknown',
      answer:answer(),elapsedMs:Date.now()-started,after:snapshot(),history:state().tryOnHistory,
      result:outcome,
    };
    row.turns.push(recorded);
    return recorded;
  }
  try {
    await act(async()=>{
      const s=state();s.reset();
      if(sample.group!=='체험순서') {
        s.applyShade(lip,shade);s.applyShade(blush,blush.shades[0]);
        s.setIntensity('lip',0.55);s.setIntensity('blush',0.55);
      }
      useMakeupStore.setState({tryOnHistory:[]});
    });
    mockCatalog={data:products};
    await refresh();
    row.start=snapshot();
    for(const step of sample.setup ?? []) {
      if(step.say) {
        const result=await turn(step.say);
        row.setup.push({say:step.say,status:result.status});
        if(result.status!=='APPLIED') throw new Error('Preparation did not apply: '+step.say);
      } else await act(async()=>{
        if(step.manual) {
          const product=step.manual==='blush'?blush:lip;
          const selected=step.manual==='blush'?product.shades[0]:product.shades.find(s=>s.id===step.manual)!;
          state().applyShade(product,selected);
        }
        if(step.intensity!==undefined) state().setIntensity(step.zone ?? 'lip',step.intensity);
        row.setup.push({...step,state:snapshot()});
      });
    }
    const before=snapshot(), history=[...(state().tryOnHistory ?? [])];
    const actual=await turn(sample.message);
    const check=sample.check, proposal=actual.proposal;
    if(check.choice) expect(proposal?.choice).toBe(check.choice);
    if(check.params) expect(proposal).toMatchObject(check.params);
    const zone=check.zone ?? 'lip';
    if(check.shade) expect(state().selections[zone]).toEqual({productId:lip.id,shadeId:check.shade});
    if(check.intensity!==undefined) expect(state().makeup[zone]?.intensity).toBeCloseTo(check.intensity,6);
    if(check.unchanged) {
      expect(state().selections).toEqual(before.selections);
      expect(state().makeup).toEqual(before.makeup);
    }
    if(check.readonly) expect(!proposal || /^(get_state|find_shades)\//.test(String(proposal.choice))).toBe(true);
    if(check.clarification) expect(['noop','clarification','unsupported','REJECTED']).toContain(actual.status);
    if(check.status) expect(actual.status).toBe(check.status);
    if(check.history) {
      const entries=check.scope==='all'?history:history.filter(entry=>entry.zone===zone);
      const entry=entries[check.history-1];
      expect(entry).toBeDefined();
      expect(state().selections[zone]).toEqual({productId:entry.productId,shadeId:entry.shadeId});
    }
    if(!check.unchanged && !check.status) expect(actual.status).toBe('APPLIED');
    for(const other of AR_PAINT_ZONES.filter(part=>part!==zone)) {
      expect(state().selections[other]).toEqual(before.selections[other]);
      expect(state().makeup[other]).toEqual(before.makeup[other]);
    }
    const selection=state().selections[zone];
    if(selection) {
      const product=products.find(item=>item.id===selection.productId)!;
      const selected=product.shades.find(item=>item.id===selection.shadeId)!;
      expect(state().makeup[zone]?.hex).toBe(selected.hex);
    }
    expect(actual.answer.trim().length).toBeGreaterThan(0);
    row.passed=true;
  } catch(error) {
    row.error=error instanceof Error ? error.message : String(error);
    throw error;
  } finally {
    console.info('AR_EVAL_RESULT',row.id,row.passed?'PASS':'FAIL',row.turns.at(-1)?.answer ?? row.error);
  }
},180000);

afterAll(()=>{
  if(!evalReport || !evalRecords.length) return;
  const groups=[...new Set(evalRecords.map(row=>row.group))];
  const safe=(text:string)=>text.replace(/\|/g,'／').replace(/\n/g,' ');
  const lines=[
    '# AR 제어 평가 결과',
    '',
    '2026-11-16 실제 로컬 챗봇과 Redis, gpt-6-luna를 연결한 40개 독립 시나리오의 1회 실행 결과.',
    '',
    'React Native 화면을 마운트하고 실제 /api/chat 응답을 앱의 기존 조작 경로로 실행했다. 카메라와 얼굴 렌더러는 테스트 대역이며 렌더 완료 신호를 주입했다. 카탈로그는 앱의 oyCatalog.json 전체다. 수동 준비는 팔레트가 쓰는 applyShade 함수를 호출했다. STT와 스마트폰 스피커는 평가에 포함하지 않았다.',
    '',
    '각 사례는 별도 익명 사용자와 새 착용 이력에서 시작했다. 기본 화면은 립 팔레트, 립과 블러셔 강도 0.55다. 체험순서 사례는 맨얼굴에서 시작했다. 기대값은 실행 전에 fixture에 고정했다. 준비 대화도 실제 모델로 실행했다.',
    '',
    '## 결과',
    '',
    '| 유형 | 성공 / 실행 | 성공률 |','|---|---:|---:|',
    ...groups.map(group=>{
      const rows=evalRecords.filter(row=>row.group===group), passed=rows.filter(row=>row.passed).length;
      return '| '+group+' | '+passed+' / '+rows.length+' | '+(passed/rows.length*100).toFixed(1)+'% |';
    }),
    '',
    '호수명과 체험 복원은 제품·호수 ID 및 실제 착용색을 검사했다. 색감은 지정 조건의 툴 인자, 카탈로그의 실제 호수 적용, 다른 부위 유지 여부를 검사했다. 추천 호수의 지각적 적합성은 별도 평가가 필요하다. 멀티턴은 Redis 확인 결과에 따른 부위·방향·변화 폭과 다른 부위 유지를 검사했다. 답변 전문은 아래 기록에 남겼으며 페르소나와 문장 자연스러움은 자동 성공률에 포함하지 않았다.',
    '',
    '## 전체 평가셋',
    '',
    '| ID | 유형 | 사용자 입력 | 기대 결과 | 결과 |',
    '|---|---|---|---|---|',
    ...evalRecords.map(row=>'| '+[row.id,row.group,row.message,row.expected,row.passed?'PASS':'FAIL'].map(safe).join(' | ')+' |'),
    '',
    '## 실패 사례',
    '',
    ...evalRecords.filter(row=>!row.passed).flatMap(row=>[
      '### '+row.id+' '+row.message,'','기대 결과는 '+row.expected+'이다.','','```text',row.error ?? '', '```','',
    ]),
    '',
    '## 시작 상태와 실제 대화 기록',
    '',
    ...evalRecords.flatMap(row=>[
      '### '+row.id+' '+row.message,'',
      '```json',JSON.stringify(row,null,2),'```','',
    ]),
    '## 재실행',
    '',
    '```powershell',
    "$env:AR_CONTROL_TEST_PORT='8080'",
    "$env:AR_EVAL_REPORT='docs/AR_CONTROL_EVALUATION.md'",
    "npm.cmd test -- --runInBand --runTestsByPath __tests__/arIntegration.test.tsx -t AR_EVAL",
    '```',
    '',
    '모델 호출에 요금이 발생한다. 문장과 기대값은 __tests__/fixtures/arControlEvaluation.json에 있다. 이번 평가용 문장을 프롬프트에 추가하지 않았다.',
  ];
  require('node:fs').writeFileSync(evalReport,lines.join('\n'),'utf8');
});

function connectLiveChat() {
  const { request } = require('node:http');
  const guest = 'ar-control-lab-' + require('node:crypto').randomUUID();
  const replies: string[] = [];
  const results: {choice:string;status:string}[] = [];
  const proposals: ({choice:string;onAppliedReply?:string;fineAdjustment?:boolean;commandId:string;productId?:string;shadeId?:string} & ShadePreference)[] = [];
  const errors: string[] = [];
  post.mockImplementation(async (path, body:any) => {
    const data = await new Promise<any>((resolve,reject) => {
      const req = request({hostname:process.env.AR_CONTROL_TEST_HOST || '127.0.0.1',port:livePort,path,method:'POST',headers:{
        'content-type':'application/json','x-vishue-anonymous-id':guest,
      }}, (res: {statusCode:number;setEncoding:(encoding:string)=>void;on:(event:string,callback:(chunk:string)=>void)=>void}) => {
        let buf=''; res.setEncoding('utf8');res.on('data',chunk=>{buf+=chunk;});
        res.on('end',()=>{if(res.statusCode!==200){errors.push(path+': '+res.statusCode);reject(new Error(errors.join(', ')));}else resolve(JSON.parse(buf));});
      });
      req.on('error',reject); req.end(JSON.stringify(body));
    });
    if (data.arResult?.actionProposal) proposals.push(data.arResult.actionProposal);
    if (path === '/api/chat' && !data.arResult?.actionProposal) errors.push('No proposal: '+data.answer);
    if (path.endsWith('/reply')) {replies.push(data.answer);results.push(JSON.parse(body.result));}
    return owned(data) as never;
  });
  async function until(predicate:()=>boolean) {
    const end=Date.now()+60000;
    while (!predicate() && !errors.length && Date.now()<end) await act(async()=>{await new Promise(r=>setTimeout(r,60));});
    expect(errors).toEqual([]);
    expect(predicate()).toBe(true);
  }
  return {replies, results, proposals, until};
}

(livePort ? it : it.skip)('distinguishes real shade names from color descriptions with real Luna', async () => {
  await startBareChat(products.filter(p => p.makeupZone === 'lip' && p.texture));
  const {proposals, replies, results, until} = connectLiveChat();
  for (const [index, message] of [
    '페이드 레드 발라줘', '차분한 레드로 발라줘', '번트하트로 발라줘',
    '페이드 레드는 바르지 말고 지금 립 이름만 알려줘',
  ].entries()) {
    const before = useMakeupStore.getState().selections.lip;
    await send(message);
    await until(() => !!face().props.renderCommand || replies.length > index);
    if (index === 3) {
      expect(face().props.renderCommand).toBeNull();
      expect(useMakeupStore.getState().selections.lip).toEqual(before);
      expect(proposals[index].choice).toBe('get_state/lip');
      continue;
    }
    const cmd = face().props.renderCommand;
    expect(cmd).toBeTruthy();
    if (index === 1) {
      expect(proposals[index]).toMatchObject({choice:'apply_shade/lip/by_color',family:'red',chroma:'muted'});
    } else {
      expect(proposals[index]).toMatchObject({
        choice:'apply_shade/product_shade', productId:lip.id, shadeId:index === 0 ? '24' : '04',
      });
    }
    await act(async () => { face().props.onRenderResult({...cmd,status:'rendered'}); });
    await until(() => replies.length > index);
    if (index !== 1) expect(useMakeupStore.getState().selections.lip).toEqual({
      productId:lip.id, shadeId:index === 0 ? '24' : '04',
    });
    expect(results[index].status).toBe('APPLIED');
    console.info('Catalog identity dialogue:', message, proposals[index], useMakeupStore.getState().selections.lip, replies[index]);
  }
},150000);

(livePort ? it : it.skip)('recalls the exact wear order across manual palette and real Luna try-ons', async () => {
  const otherLip = products.find(p => p.id === 'oy-a000000218780')!;
  await startBareChat([lip, otherLip, blush]);
  const { proposals, replies, until } = connectLiveChat();
  const state = useMakeupStore.getState;
  async function switchMode(mode: 'direct' | 'chat') {
    const tab = screen.root.findAllByProps({accessibilityRole:'tab'}).find(item =>
      item.findAllByProps({children:'ar.mode.' + mode}).length)!;
    await act(async () => { tab.props.onPress(); });
  }
  async function pickManually(product: Product, shadeId: string) {
    await switchMode('direct');
    const palette = screen.root.findByType(OpenArcPalette).props as React.ComponentProps<typeof OpenArcPalette>;
    const swatch = palette.items.find(item => item.product.id === product.id && item.shade.id === shadeId);
    expect(swatch).toBeDefined();
    await act(async () => { palette.onSelect(swatch!); });
    await switchMode('chat');
  }
  async function chatAndPaint(message: string) {
    const count = replies.length;
    await send(message);
    await until(() => !!face().props.renderCommand || replies.length > count);
    const frame = face().props.renderCommand;
    expect(frame).toBeTruthy();
    await act(async () => { face().props.onRenderResult({...frame, status:'rendered'}); });
    await until(() => replies.length === count + 1);
    return replies[count];
  }
  await pickManually(lip, '04');
  const first = state().selections.lip;
  await chatAndPaint('볼에도 블러셔 하나 발라줄래?');
  const cheek = state().selections.blush;
  await chatAndPaint('이번에는 선명한 레드 립 하나 골라서 발라줘.');
  const second = state().selections.lip!;
  const chosenProduct = [lip, otherLip].find(p => p.id === second.productId)!;
  const chosenShade = chosenProduct.shades.find(s => s.id === second.shadeId)!;
  expect(second).not.toEqual(first);
  expect(state().makeup.lip!.hex).toBe(chosenShade.hex);
  const thirdProduct = chosenProduct.id === lip.id ? otherLip : lip;
  const thirdShade = thirdProduct.shades.find(s => s.id !== second.shadeId)!;
  await pickManually(thirdProduct, thirdShade.id);
  expect(state().selections.lip).toEqual({productId:thirdProduct.id, shadeId:thirdShade.id});
  expect(state().tryOnHistory).toEqual([
    {...first, zone:'lip'}, {...cheek, zone:'blush'}, {...second, zone:'lip'}, {...state().selections.lip, zone:'lip'},
  ]);
  const answer = await chatAndPaint('아까 두 번째로 발라본 립 다시 발라줘.');
  expect(proposals.at(-1)).toMatchObject({choice:'reapply_try_on/lip', ordinal:2});
  expect(state().selections.lip).toEqual(second);
  expect(state().selections.blush).toEqual(cheek);
  expect(state().makeup.lip!.hex).toBe(chosenShade.hex);
  expect(answer.replace(/\s/g,'')).toContain(chosenShade.name.replace(/\s/g,''));
  console.info('Second lip restored:', second, state().selections.lip, chosenProduct.nameKo, chosenShade.name, answer);
  await chatAndPaint('맨 처음 발라봤던 입술 색으로 돌아가 볼까?');
  expect(proposals.at(-1)).toMatchObject({choice:'reapply_try_on/lip', ordinal:1});
  expect(state().selections.lip).toEqual(first);
}, 150000);

(livePort ? it.each : it.skip.each)([
  ['lip', '립 좀 연하게 해줘', '조금 더', 'down', 0.55, 0.45, 0.40],
  ['blush', '볼에 생기를 더 줘. 블러셔를 진하게 해줘', '조금 더', 'up', 0.55, 0.65, 0.70],
  ['lip', '입술 발색 좀 줄여줘', '거기서 딱 한 끗만 더', 'down', 0.55, 0.45, 0.40],
  ['lip', '지금 바른 립은 반 정도만 남겨줘', '조금 더', 'down', 0.60, 0.30, 0.15],
] as const)('continues a confirmed Redis adjustment for %s: %s / %s', async (zone, first, followup, direction, start, coarse, fine) => {
  const {proposals, replies, until} = connectLiveChat();
  await act(async () => { useMakeupStore.getState().setIntensity(zone, start); });
  const other = zone === 'lip' ? 'blush' : 'lip';
  const otherBefore = useMakeupStore.getState().makeup[other]!.intensity;
  for (const [index, utterance, expected] of [[0, first, coarse], [1, followup, fine]] as const) {
    await send(utterance);
    await until(() => !!face().props.renderCommand);
    const command = face().props.renderCommand;
    if (index === 1) {
      const requests = post.mock.calls.filter(([path]) => path === '/api/chat');
      const previousContext = (requests[1][1] as {arContext:{previousAdjustmentId?:string;stateVersion:number}}).arContext;
      const ack = post.mock.calls.find(([path]) => path === '/api/chat/acks')?.[1];
      expect(previousContext.previousAdjustmentId).toBe(proposals[0].commandId);
      expect(ack).toMatchObject({actualStateVersion:previousContext.stateVersion, intensityChange:{zone,after:coarse}});
    }
    const relativeChoice = `adjust_intensity/${zone}/${direction}`;
    if (index === 0) expect([relativeChoice, `set_intensity/${zone}/half`]).toContain(proposals[index].choice);
    else expect(proposals[index].choice).toBe(relativeChoice);
    expect(!!proposals[index].fineAdjustment).toBe(index === 1);
    expect(command.makeup[zone].intensity).toBeCloseTo(expected);
    await act(async () => { face().props.onRenderResult({...command, status:'rendered'}); });
    const draft = proposals[index].onAppliedReply;
    await until(() => draft ? screen.root.findAllByProps({children:draft}).length > 0 : replies.length > 0);
    expect(useMakeupStore.getState().makeup[zone]!.intensity).toBeCloseTo(expected);
    expect(useMakeupStore.getState().makeup[other]!.intensity).toBe(otherBefore);
    console.info('AR dialogue:', utterance, proposals[index].choice, expected, draft ?? replies.at(-1));
  }
  const turns = post.mock.calls.filter(([path]) => path === '/api/chat');
  expect(turns[1][1]).toMatchObject({arContext:{previousAdjustmentId:proposals[0].commandId}});
}, 150000);
(livePort ? it.each : it.skip.each)([
  ['맨얼굴', '', '', '섹시한 립스틱 발라줘봐'],
  ['플럼 립','oy-a000000257259','26','블러셔 하나 추천해줘'],
  ['오렌지 립','oy-a000000218780','a000000218780-006','블러셔 하나 추천해줘'],
])('uses real Luna for styling from %s', async (start, productId, shadeId, message) => {
  const {replies, results, proposals, until} = connectLiveChat();
  await startBareChat(products.filter(p => p.makeupZone === 'lip' || p.makeupZone === 'blush'));
  if (productId) {
    const p = products.find(p => p.id === productId)!;
    await act(async () => {useMakeupStore.getState().applyShade(p,p.shades.find(s => s.id === shadeId)!);});
  }
  await send(message);
  await until(() => !!face().props.renderCommand || replies.length > 0);
  const cmd = face().props.renderCommand;
  if (!cmd) throw new Error(JSON.stringify({message,proposals,results,replies}));
  await act(async () => {face().props.onRenderResult({...cmd,status:'rendered'});});
  await until(() => replies.length === 1);
  const selection = useMakeupStore.getState().selections[productId ? 'blush' : 'lip']!;
  const selected = products.find(p => p.id === selection.productId)!;
  const shade = selected.shades.find(s => s.id === selection.shadeId)!;
  console.info('AR STYLING '+JSON.stringify({start,message,choice:proposals[0].choice,
    family:proposals[0].family,lightness:proposals[0].lightness,chroma:proposals[0].chroma,
    lipType:proposals[0].lipType,product:selected.nameKo,shade:shade.name,hex:shade.hex,answer:replies[0]}));
  if (productId) {
    expect(results[0]).toMatchObject({status:'APPLIED',matchedTo:[{zone:'lip'}]});
    expect(useMakeupStore.getState().selections.lip).toEqual({productId,shadeId});
  } else {
    expect(proposals[0]).toMatchObject({choice:'apply_shade/lip/by_color',lipType:'lipstick'});
    expect(selected.tags).toContain('립스틱');
    expect(results[0].status).toBe('APPLIED');
  }
},90000);
(livePort ? it.each : it.skip.each)([
  ['blush','볼에 블러셔 하나 발라줘'], ['eyeshadow','눈두덩이에 섀도 하나 골라 발라줘'],
  ['eyeliner','오늘은 아이라이너부터 그려줘'], ['brow','눈썹부터 한번 채워줘'],
  ['highlighter','하이라이터 하나 골라 발라줘'], ['contour','쉐딩 먼저 해볼래. 하나 골라서 발라줘'],
  ['foundation','내 피부색에 가까운 파운데이션 하나 골라 발라줘'], ['oil','립 오일 먼저 발라줘'],
  ['balm','립밤으로 시작해볼래. 하나 발라줘'],
])('uses real Luna for a first %s product from an empty chat screen', async (target,message) => {
  const {replies,results,proposals,until} = connectLiveChat();
  await startBareChat(products);
  if (target === 'foundation') await act(async () => {face().props.onSkinTone({L:70,a:9,b:16,conf:0.9});});
  await send(message);
  await until(() => !!face().props.renderCommand || replies.length > 0);
  const cmd = face().props.renderCommand;
  if (!cmd) throw new Error(JSON.stringify({message,proposals,replies,results}));
  await act(async () => {face().props.onRenderResult({...cmd,status:'rendered'});});
  await until(() => replies.length === 1);
  const care = target === 'oil' || target === 'balm';
  const zone = care ? 'lip' : target as MakeupZone;
  const state = useMakeupStore.getState();
  const selected = care ? state.careSelection : state.selections[zone];
  expect(selected).toBeTruthy();
  expect(state.selections.lip).toBeUndefined();
  expect(results[0]).toMatchObject({status:'APPLIED'});
  console.info('AR FIRST PRODUCT '+JSON.stringify({message,choice:proposals[0].choice,selected,answer:replies[0]}));
},90000);
(livePort ? it : it.skip)('uses real Luna to pick shades for independently described moods', async () => {
  const {replies, results, proposals, until} = connectLiveChat();
  await startBareChat(products.filter(p => p.makeupZone === 'lip' && p.texture));
  for (const message of ['여리여리한 느낌으로 추천해줘', '쨍한 핑크 말고 차분한 핑크로 해줘']) {
    await act(async () => {useMakeupStore.getState().clearZone('lip');});
    const index = replies.length;
    await send(message);
    await until(() => !!face().props.renderCommand || replies.length > index);
    const cmd = face().props.renderCommand;
    if (!cmd) throw new Error(JSON.stringify({message,proposal:proposals[index],outcome:results[index],answer:replies[index]}));
    expect(useMakeupStore.getState().selections.lip).toBeUndefined();
    await act(async () => {face().props.onRenderResult({...cmd,status:'rendered'});});
    await until(() => replies.length === index + 1);
    const {productId,shadeId} = useMakeupStore.getState().selections.lip!;
    const p = mockCatalog.data.find(item => item.id === productId)!;
    const shade = p.shades.find(item => item.id === shadeId)!;
    const {choice,family,lightness,chroma} = proposals[index];
    const tone = shadeTone(shade.hex)!;
    console.info('AR COLOR CASE '+JSON.stringify({message,choice,family,lightness,chroma,
      brand:p.brand,product:p.nameKo || p.name,shade:shade.name,productId,shadeId,hex:shade.hex,
      actualFamily:colorFamily(shade.hex),actualLightness:tone.lightness,actualChroma:tone.chroma,answer:replies[index]}));
    expect(results[index]).toMatchObject({choice:'apply_shade/lip/by_color',status:'APPLIED',
      featuredShade:{product:p.name,shade:shade.name,lightness:tone.lightness,chroma:tone.chroma}});
    expect(chroma).toBe('muted');
    if (index === 0) {
      expect(family == null).toBe(true);
      expect(lightness).toBe('light');
    } else {
      expect(family).toBe('pink');
    }
    if (family) expect(colorFamily(shade.hex)).toBe(family);
    if (lightness) expect(tone.lightness).toBe(lightness);
    expect(tone.chroma).toBe(chroma);
    expect(screen.root.findAllByProps({children:replies[index]}).length).toBeGreaterThan(0);
  }
},150000);
(livePort ? it : it.skip)('uses real Luna from the mounted chat screen and narrates only after frame confirmation', async () => {
  const {replies, results, proposals, until} = connectLiveChat();
  const initial=useMakeupStore.getState().makeup.lip!.intensity;
  await send('이거 조금만 연하게 해줘.');
  await until(()=>!!face().props.renderCommand);
  expect(replies).toHaveLength(0);
  expect(proposals[0].choice).toBe('adjust_intensity/lip/down');
  const draft = proposals[0].onAppliedReply!;
  expect(draft).toMatch(/[가-힣]/);
  expect(screen.root.findAllByProps({children:draft})).toHaveLength(0);
  const cmd=face().props.renderCommand;
  expect(cmd.makeup.lip.intensity).toBeCloseTo(initial-0.1);
  await act(async()=>{face().props.onRenderResult({...cmd,status:'rendered'});});
  await until(()=>screen.root.findAllByProps({children:draft}).length>0);
  expect(replies).toHaveLength(0);
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBeCloseTo(initial-0.1);
  expect(draft).not.toMatch(/0\.\d+/);
  await act(async()=>{useMakeupStore.getState().clearZone('lip');});
  await send('지금 입에 바른 게 뭐야?');
  await until(()=>replies.length===1);
  expect(results[0]).toMatchObject({choice:'get_state/lip',status:'OK', data:{product:null,intensity:null}});
  expect(replies[0]).toMatch(/않|없|전이에요|전이네요|전이에|맨입술|바르기 전|아직/);
  expect(useMakeupStore.getState().selections.lip).toBeUndefined();
  expect(screen.root.findAllByProps({children:replies[0]}).length).toBeGreaterThan(0);
  mockCatalog = {data:products.filter(p => p.makeupZone === 'lip' && p.texture)};
  await refresh();
  await send('핑크핑크한 걸로 추천해줘.');
  await until(()=>!!face().props.renderCommand);
  expect(useMakeupStore.getState().selections.lip).toBeUndefined();
  const pick = face().props.renderCommand;
  await act(async()=>{face().props.onRenderResult({...pick,status:'rendered'});});
  await until(()=>replies.length===2);
  const selection = useMakeupStore.getState().selections.lip!;
  const product = mockCatalog.data.find(p=>p.id===selection.productId)!;
  const chosen = product.shades.find(s=>s.id===selection.shadeId)!;
  expect(results[1]).toMatchObject({choice:'apply_shade/lip/by_color',status:'APPLIED',
    featuredShade:{family:'pink',product:product.name,shade:chosen.name}});
  expect(replies[1]).toMatch(/핑크|분홍/);
  expect(replies[1].replace(/\s/g,'')).toContain(chosen.name.replace(/\s/g,''));
  expect(replies[1]).not.toMatch(/%|퍼센트|검색|[\d,]+\s*개|0\.\d+/);
  await send('분홍 계열도 있어?');
  await until(()=>replies.length===3);
  expect(results[2]).toMatchObject({choice:expect.stringMatching(/^find_shades\/lip\/(pink|by_color)$/),status:'OK'});
  expect(useMakeupStore.getState().selections.lip).toEqual(selection);
  console.info('Luna AR:', [draft, ...replies].join(' / '));
},150000);

it('confirms 40%, a step down, and one undo in the same AR session', async () => {
  for (const [text, value, undo] of [
    ['립 강도 40%로', 0.4, false], ['조금 더 연하게', 0.3, false], ['방금 변경 취소', 0.4, true],
  ] as const) {
    post.mockImplementationOnce(async (_path, body: any) => {
      if (undo) expect(body.arContext.undo).toEqual({ zone: 'lip', value: 0.4 });
      const response = proposal({ ...body, message: String(value * 100) });
      response.data.arResult.actionProposal.action = undo ? 'undo' : 'set_intensity';
      return response as never;
    });
    await send(text);
    const render = face().props.renderCommand;
    expect(render.makeup.lip.intensity).toBe(value);
    await act(async () => { face().props.onRenderResult({ ...render, status: 'rendered' }); });
    expect(useMakeupStore.getState().makeup.lip?.intensity).toBe(value);
    expect(post).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({
      commandId: render.commandId, status: 'APPLIED',
    }), expect.anything());
  }
  expect(useMakeupStore.getState().arUndo).toBeNull();
});
