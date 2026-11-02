import { uuid } from 'expo';
import { createElement, useLayoutEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useArCommand } from '@/hooks/useArCommand';
import { apiPostOwned } from '@/lib/api';
import { useMakeupStore } from '@/store/makeupStore';
import type { MakeupZone, Product } from '@/types';

jest.mock('expo', () => ({ uuid: { v4: jest.fn() } }));
jest.mock('@/lib/api', () => ({ apiPostOwned: jest.fn() }));

const mockedPost = jest.mocked(apiPostOwned);
const owned = <T,>(data: T) => ({ data, owner: { kind: 'guest' as const, id: 'anonymous' } });
const lip = { id: 'lip-product', makeupZone: 'lip', texture: 'matte' } as unknown as Product;
const shade = { id: 'rose', name: 'Rose', hex: '#C25A6E' };
let commandId: string;
let id = 0;
let hook: ReturnType<typeof useArCommand>;
let view: ReactTestRenderer;
const initialOptions = { active: true, enabled: true, activeZone: 'lip' as const, locale: 'ko' as const, rendererId: 'renderer-1' };

function Harness(props: typeof initialOptions & { visibleZones?: MakeupZone[] | null }) {
  const result = useArCommand(props);
  useLayoutEffect(() => { hook = result; });
  return null;
}

function proposed(body: { requestId: string; arContext: { stateVersion: number } }) {
  return { answer: '', arResult: { requestId: body.requestId, status: 'proposed', actionProposal: {
    commandId, expectedStateVersion: body.arContext.stateVersion, action: 'set_intensity', zone: 'lip',
    value: 0.5, productId: lip.id, shadeId: shade.id,
  } } };
}

beforeEach(async () => {
  jest.clearAllMocks();
  commandId = `aaaaaaaa-aaaa-4aaa-8aaa-${String(++id).padStart(12, '0')}`;
  jest.mocked(uuid.v4).mockImplementation(() => `00000000-0000-4000-8000-${String(++id).padStart(12, '0')}`);
  const store = useMakeupStore.getState();
  store.endArSession();
  store.reset();
  store.applyShade(lip, shade);
  mockedPost.mockImplementation(async (path, body) => owned(path === '/api/chat' ? proposed(body as never) : { received: true }) as never);
  await act(async () => { view = create(createElement(Harness, initialOptions)); });
});

afterEach(async () => {
  await act(async () => { view.unmount(); });
  jest.useRealTimers();
});

it('commits only after the matching renderer result and sends APPLIED ACK', async () => {
  const before = useMakeupStore.getState().makeup.lip!.intensity;
  await act(async () => { await hook.send('립 진하기 50%'); });
  expect(hook.state).toBe('applying');
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(before);
  const render = hook.renderCommand!;
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: 'old-renderer', status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(before);
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.5);
  expect(hook.state).toBe('applied');
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ commandId, status: 'APPLIED' }), expect.anything());
});

it('cancels a pending render when the user changes the intensity', async () => {
  await act(async () => { await hook.send('립 진하기 50%'); });
  const render = hook.renderCommand!;
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  expect(hook.renderCommand).toEqual(expect.objectContaining({ kind: 'restore', makeup: expect.objectContaining({ lip: expect.objectContaining({ intensity: 0.2 }) }) }));
  expect(hook.restoreState).toBe('pending');
  expect(hook.state).toBe('rejected');
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.2);
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it.each(['rendered', 'failed'] as const)('records restore %s separately from the rejected command', async (result) => {
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  const restore = hook.renderCommand!;
  expect(restore.kind).toBe('restore');
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: restore.restoreId, commandId,
    renderSeq: restore.renderSeq, rendererId: restore.rendererId, status: result }); });
  expect(hook.restoreState).toBe(result === 'rendered' ? 'confirmed' : 'failed');
  expect(hook.state).toBe('rejected');
  expect(hook.renderCommand).toBeNull();
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.2);
  expect(mockedPost.mock.calls.filter(([path]) => path === '/api/chat/acks')).toHaveLength(1);
});

it('keeps restoration pending for an old renderer result and reports unknown after timeout', async () => {
  jest.useFakeTimers();
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  const restore = hook.renderCommand!;
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: restore.restoreId, commandId,
    renderSeq: restore.renderSeq, rendererId: 'old-renderer', status: 'rendered' }); });
  expect(hook.restoreState).toBe('pending');
  await act(async () => { jest.advanceTimersByTime(6000); });
  expect(hook.restoreState).toBe('unknown');
  expect(hook.state).toBe('rejected');
  expect(hook.renderCommand).toBeNull();
});

it('marks restoration unavailable if its renderer is replaced and ignores the old result', async () => {
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  const restore = hook.renderCommand!;
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, rendererId: 'renderer-2' })); });
  expect(hook.restoreState).toBe('unavailable');
  expect(hook.renderCommand).toBeNull();
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: restore.restoreId, commandId,
    renderSeq: restore.renderSeq, rendererId: restore.rendererId, status: 'rendered' }); });
  expect(hook.restoreState).toBe('unavailable');
});

it('does not send a new command until restoration of a candidate is resolved', async () => {
  await act(async () => { await hook.send('첫 요청'); });
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  await act(async () => { await hook.send('복구 중 요청'); });
  expect(mockedPost.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  const restore = hook.renderCommand!;
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: restore.restoreId, commandId,
    renderSeq: restore.renderSeq, rendererId: restore.rendererId, status: 'rendered' }); });
  await act(async () => { await hook.send('복구 후 요청'); });
  expect(mockedPost.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(2);
});

it('requests a newer restore after a further manual change and ignores the previous restore result', async () => {
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  const first = hook.renderCommand!;
  await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.4); });
  const latest = hook.renderCommand!;
  expect(latest.restoreId).not.toBe(first.restoreId);
  expect(latest.renderSeq).toBeGreaterThan(first.renderSeq);
  expect(latest.makeup.lip!.intensity).toBe(0.4);
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: first.restoreId, commandId,
    renderSeq: first.renderSeq, rendererId: first.rendererId, status: 'rendered' }); });
  expect(hook.restoreState).toBe('pending');
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: latest.restoreId, commandId,
    renderSeq: latest.renderSeq, rendererId: latest.rendererId, status: 'rendered' }); });
  expect(hook.restoreState).toBe('confirmed');
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.4);
});

it('restores only practice-visible zones and replaces the pending restore when visibility changes', async () => {
  const makeup = useMakeupStore.getState().makeup;
  const blush = { ...makeup.lip!, hex: '#FF8899' };
  const eye = { ...makeup.lip!, hex: '#554433' };
  await act(async () => { useMakeupStore.setState({ makeup: { ...makeup, blush, eyeshadow: eye } }); });
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, enabled: false, visibleZones: ['blush'] })); });
  const first = hook.renderCommand!;
  expect(first.kind).toBe('restore');
  expect(first.makeup.lip).toBeNull();
  expect(first.makeup.blush).toEqual(blush);
  expect(first.makeup.eyeshadow).toBeNull();

  await act(async () => { view.update(createElement(Harness, { ...initialOptions, enabled: false, visibleZones: ['lip'] })); });
  const second = hook.renderCommand!;
  expect(second.restoreId).not.toBe(first.restoreId);
  expect(second.renderSeq).toBeGreaterThan(first.renderSeq);
  expect(second.makeup.lip).toEqual(makeup.lip);
  expect(second.makeup.blush).toBeNull();
  expect(second.makeup.eyeshadow).toBeNull();
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: first.restoreId, commandId,
    renderSeq: first.renderSeq, rendererId: first.rendererId, status: 'rendered' }); });
  expect(hook.restoreState).toBe('pending');

  // Peek reveals the complete makeup again; old filtered results must still be ignored.
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, enabled: false, visibleZones: null })); });
  const peek = hook.renderCommand!;
  expect(peek.restoreId).not.toBe(second.restoreId);
  expect(peek.makeup).toEqual(expect.objectContaining({ lip: makeup.lip, blush, eyeshadow: eye }));
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: second.restoreId, commandId,
    renderSeq: second.renderSeq, rendererId: second.rendererId, status: 'rendered' }); });
  expect(hook.restoreState).toBe('pending');
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: peek.restoreId, commandId,
    renderSeq: peek.renderSeq, rendererId: peek.rendererId, status: 'rendered' }); });
  expect(hook.restoreState).toBe('confirmed');
});

it('restores the latest makeup when the lip selection is removed during a candidate', async () => {
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { useMakeupStore.getState().clearZone('lip'); });
  const restore = hook.renderCommand!;
  expect(restore.kind).toBe('restore');
  expect(restore.makeup.lip).toBeNull();
  await act(async () => { hook.onRenderResult({ kind: 'restore', restoreId: restore.restoreId, commandId,
    renderSeq: restore.renderSeq, rendererId: restore.rendererId, status: 'rendered' }); });
  expect(hook.state).toBe('rejected');
  expect(hook.restoreState).toBe('confirmed');
  expect(useMakeupStore.getState().makeup.lip).toBeNull();
});

it('distinguishes leaving the screen from a confirmed restore', async () => {
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, active: false, enabled: false })); });
  expect(hook.restoreState).toBe('unavailable');
  expect(hook.renderCommand).toBeNull();
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it('reports NO_CHANGE after the renderer confirms the existing intensity', async () => {
  const store = useMakeupStore.getState();
  await act(async () => { store.setIntensity('lip', 0.5); });
  const version = useMakeupStore.getState().arVersion;
  await act(async () => { await hook.send('립 진하기 50%'); });
  const render = hook.renderCommand!;
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
  expect(hook.state).toBe('no_change');
  expect(useMakeupStore.getState().arVersion).toBe(version);
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'NO_CHANGE' }), expect.anything());
});

it('removes look-only zones from the render candidate while retaining the stored look', async () => {
  const makeup = useMakeupStore.getState().makeup;
  const lookOnly = { ...makeup.lip! };
  await act(async () => { useMakeupStore.setState({ makeup: { ...makeup, mascara: lookOnly, highlighter: lookOnly, contour: lookOnly } }); });
  await act(async () => { await hook.send('립 진하기 50%'); });
  expect(hook.renderCommand!.makeup).toEqual(expect.objectContaining({ mascara: null, highlighter: null, contour: null }));
  expect(useMakeupStore.getState().makeup).toEqual(expect.objectContaining({ mascara: lookOnly, highlighter: lookOnly, contour: lookOnly }));
});

it.each(['manual', 'leave'] as const)('rejects a delayed proposal after %s', async (event) => {
  let resolve!: (value: unknown) => void;
  let sentBody!: Parameters<typeof proposed>[0];
  mockedPost.mockImplementation((path, body) => {
    if (path !== '/api/chat') return Promise.resolve(owned({ received: true }) as never);
    sentBody = body as typeof sentBody;
    return new Promise((r) => { resolve = r; }) as never;
  });
  let sending!: Promise<void>;
  await act(async () => { sending = hook.send('립 진하기 50%'); await Promise.resolve(); });
  if (event === 'manual') await act(async () => { useMakeupStore.getState().setIntensity('lip', 0.2); });
  else await act(async () => { view.update(createElement(Harness, { ...initialOptions, active: false })); });
  await act(async () => { resolve(owned(proposed(sentBody))); await sending; });
  expect(hook.renderCommand).toBeNull();
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
  if (event === 'manual') expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.2);
});

it('keeps the new session request when a prior session reply arrives late', async () => {
  let resolveOld!: (value: unknown) => void;
  let oldBody!: Parameters<typeof proposed>[0];
  let chats = 0;
  mockedPost.mockImplementation((path, body) => {
    if (path !== '/api/chat') return Promise.resolve(owned({ received: true }) as never);
    if (++chats === 1) {
      oldBody = body as typeof oldBody;
      return new Promise((resolve) => { resolveOld = resolve; }) as never;
    }
    return Promise.resolve(owned(proposed(body as never)) as never);
  });
  let oldRequest!: Promise<void>;
  await act(async () => { oldRequest = hook.send('이전 요청'); await Promise.resolve(); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, active: false })); });
  await act(async () => { view.update(createElement(Harness, initialOptions)); });
  await act(async () => { await hook.send('새 요청'); });
  const render = hook.renderCommand!;
  const oldReply = proposed(oldBody);
  oldReply.arResult.actionProposal.commandId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  await act(async () => { resolveOld(owned(oldReply)); await oldRequest; });
  expect(hook.renderCommand).toEqual(render);
  expect(hook.state).toBe('applying');
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
  expect(hook.state).toBe('applied');
});

it('rejects a delayed proposal after the screen is disabled and enabled again', async () => {
  let resolve!: (value: unknown) => void;
  let body!: Parameters<typeof proposed>[0];
  mockedPost.mockImplementation((path, payload) => {
    if (path !== '/api/chat') return Promise.resolve(owned({ received: true }) as never);
    body = payload as typeof body;
    return new Promise((r) => { resolve = r; }) as never;
  });
  let sending!: Promise<void>;
  await act(async () => { sending = hook.send('립 진하기 50%'); await Promise.resolve(); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, enabled: false })); });
  await act(async () => { view.update(createElement(Harness, initialOptions)); });
  await act(async () => { resolve(owned(proposed(body))); await sending; });
  expect(hook.renderCommand).toBeNull();
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it.each(['clarification', 'unsupported', 'noop'] as const)('shows a current %s response without applying a command', async (status) => {
  mockedPost.mockImplementation(async (path, body) => {
    if (path !== '/api/chat') return owned({ received: true }) as never;
    return owned({ answer: `current ${status}`, arResult: { requestId: (body as { requestId: string }).requestId, status } }) as never;
  });
  const before = useMakeupStore.getState().makeup;
  await act(async () => { await hook.send('명령'); });
  expect(hook.message).toBe(`current ${status}`);
  expect(hook.state).toBe('clarification');
  expect(hook.renderCommand).toBeNull();
  expect(useMakeupStore.getState().makeup).toEqual(before);
  expect(mockedPost.mock.calls.filter(([path]) => path === '/api/chat/acks')).toHaveLength(0);
});

it('shows an error for the current request and permits another request', async () => {
  mockedPost.mockRejectedValueOnce(new Error('network'));
  await act(async () => { await hook.send('첫 요청'); });
  expect(hook.state).toBe('failed');
  await act(async () => { await hook.send('다음 요청'); });
  expect(hook.state).toBe('applying');
});

describe.each(['disabled', 'left'] as const)('stale reply after screen %s', (transition) => {
  it.each(['clarification', 'unsupported', 'noop', 'error'] as const)(
    'does not overwrite a newer pending request when old result is %s', async (status) => {
      const requests: { body: { requestId: string }; resolve: (v: unknown) => void; reject: (v: Error) => void }[] = [];
      mockedPost.mockImplementation((path, body) => {
        if (path !== '/api/chat') return Promise.resolve(owned({ received: true }) as never);
        return new Promise((resolve, reject) => { requests.push({ body: body as { requestId: string }, resolve, reject }); }) as never;
      });
      let oldRequest!: Promise<void>;
      let newRequest!: Promise<void>;
      await act(async () => { oldRequest = hook.send('오래된 요청'); await Promise.resolve(); });
      const paused = transition === 'left' ? { ...initialOptions, active: false } : { ...initialOptions, enabled: false };
      await act(async () => { view.update(createElement(Harness, paused)); });
      await act(async () => { view.update(createElement(Harness, initialOptions)); });
      await act(async () => { newRequest = hook.send('새 요청'); await Promise.resolve(); });
      expect(requests).toHaveLength(2);
      expect(hook.state).toBe('interpreting');
      await act(async () => {
        if (status === 'error') requests[0].reject(new Error('stale network error'));
        else requests[0].resolve(owned({ answer: '오래된 답변', arResult: { requestId: requests[0].body.requestId, status } }));
        await oldRequest;
      });
      expect(hook.state).toBe('interpreting');
      expect(hook.message).toBe('');
      expect(hook.renderCommand).toBeNull();
      await act(async () => {
        requests[1].resolve(owned({ answer: '현재 답변', arResult: { requestId: requests[1].body.requestId, status: 'clarification' } }));
        await newRequest;
      });
      expect(hook.state).toBe('clarification');
      expect(hook.message).toBe('현재 답변');
    }
  );
});

describe.each(['intensity', 'shade'] as const)('stale reply after manual %s change during interpretation', (change) => {
  it.each(['clarification', 'unsupported', 'noop', 'error'] as const)(
    'ignores the old %s result and preserves the new command and ACK', async (status) => {
      type RequestBody = Parameters<typeof proposed>[0] & { arContext: { lip: { shadeId: string } } };
      const requests: { body: RequestBody; resolve: (value: unknown) => void; reject: (error: Error) => void }[] = [];
      mockedPost.mockImplementation((path, body) => {
        if (path !== '/api/chat') return Promise.resolve(owned({ received: true }) as never);
        return new Promise((resolve, reject) => { requests.push({ body: body as RequestBody, resolve, reject }); }) as never;
      });
      let oldRequest!: Promise<void>;
      let nextRequest!: Promise<void>;
      await act(async () => { oldRequest = hook.send('이전 요청'); await Promise.resolve(); });
      expect(hook.state).toBe('interpreting');
      await act(async () => {
        if (change === 'intensity') useMakeupStore.getState().setIntensity('lip', 0.2);
        else useMakeupStore.getState().applyShade(lip, { ...shade, id: 'coral', hex: '#F06050' });
      });
      expect(hook.state).toBe('idle');
      expect(hook.message).toBe('');
      await act(async () => { nextRequest = hook.send('현재 요청'); await Promise.resolve(); });
      expect(requests).toHaveLength(2);
      expect(hook.state).toBe('interpreting');
      await act(async () => {
        if (status === 'error') requests[0].reject(new Error('old error'));
        else requests[0].resolve(owned({ answer: '이전 답변', arResult: { requestId: requests[0].body.requestId, status } }));
        await oldRequest;
      });
      expect(hook.state).toBe('interpreting');
      expect(hook.message).toBe('');
      expect(hook.renderCommand).toBeNull();

      const currentReply = proposed(requests[1].body);
      currentReply.arResult.actionProposal.shadeId = requests[1].body.arContext.lip.shadeId;
      await act(async () => { requests[1].resolve(owned(currentReply)); await nextRequest; });
      expect(hook.state).toBe('applying');
      const render = hook.renderCommand!;
      await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
      expect(hook.state).toBe('applied');
      expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'APPLIED', commandId }), expect.anything());
      expect(useMakeupStore.getState().selections.lip!.shadeId).toBe(requests[1].body.arContext.lip.shadeId);
    }
  );
});

it('does not replace an already completed newer response with an older clarification', async () => {
  let resolveOld!: (value: unknown) => void;
  let oldId = '';
  let calls = 0;
  mockedPost.mockImplementation((path, body) => {
    if (path !== '/api/chat') return Promise.resolve(owned({ received: true }) as never);
    const requestId = (body as { requestId: string }).requestId;
    if (++calls === 1) {
      oldId = requestId;
      return new Promise((resolve) => { resolveOld = resolve; }) as never;
    }
    return Promise.resolve(owned({ answer: '최신 답변', arResult: { requestId, status: 'unsupported' } }) as never);
  });
  let oldRequest!: Promise<void>;
  await act(async () => { oldRequest = hook.send('과거'); await Promise.resolve(); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, enabled: false })); });
  await act(async () => { view.update(createElement(Harness, initialOptions)); });
  await act(async () => { await hook.send('최신'); });
  expect(hook.message).toBe('최신 답변');
  await act(async () => {
    resolveOld(owned({ answer: '과거 답변', arResult: { requestId: oldId, status: 'clarification' } }));
    await oldRequest;
  });
  expect(hook.message).toBe('최신 답변');
  expect(hook.state).toBe('clarification');
});

it('does not show a stale clarification after disabling and re-enabling without a new request', async () => {
  let resolveOld!: (value: unknown) => void;
  let oldId = '';
  mockedPost.mockImplementationOnce((_path, body) => {
    oldId = (body as { requestId: string }).requestId;
    return new Promise((resolve) => { resolveOld = resolve; }) as never;
  });
  let oldRequest!: Promise<void>;
  await act(async () => { oldRequest = hook.send('과거'); await Promise.resolve(); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, enabled: false })); });
  await act(async () => { view.update(createElement(Harness, initialOptions)); });
  await act(async () => {
    resolveOld(owned({ answer: '과거 답변', arResult: { requestId: oldId, status: 'clarification' } }));
    await oldRequest;
  });
  expect(hook.state).toBe('idle');
  expect(hook.message).toBe('');
});

it('abandons the loading state when the renderer changes during interpretation', async () => {
  let resolveOld!: (value: unknown) => void;
  let body!: Parameters<typeof proposed>[0];
  mockedPost.mockImplementationOnce((_path, payload) => {
    body = payload as typeof body;
    return new Promise((resolve) => { resolveOld = resolve; }) as never;
  });
  let request!: Promise<void>;
  await act(async () => { request = hook.send('이전 요청'); await Promise.resolve(); });
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, rendererId: 'renderer-2' })); });
  await act(async () => { resolveOld(owned({ answer: '오래된 답변', arResult: { requestId: body.requestId, status: 'clarification' } })); await request; });
  expect(hook.state).toBe('idle');
  expect(hook.message).toBe('');
  await act(async () => { await hook.send('새 요청'); });
  expect(hook.state).toBe('applying');
});

it('rejects the pending command when its renderer instance changes', async () => {
  const before = useMakeupStore.getState().makeup.lip!.intensity;
  await act(async () => { await hook.send('립 진하기 50%'); });
  const render = hook.renderCommand!;
  await act(async () => { view.update(createElement(Harness, { ...initialOptions, rendererId: 'renderer-2' })); });
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(before);
  expect(hook.renderCommand).toBeNull();
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'REJECTED' }), expect.anything());
});

it('does not commit when rendering fails', async () => {
  const status = 'failed';
  const before = useMakeupStore.getState().makeup.lip!.intensity;
  await act(async () => { await hook.send('립 진하기 50%'); });
  const render = hook.renderCommand!;
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status }); });
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(before);
  expect(hook.restoreState).toBe('pending');
  expect(hook.renderCommand).toEqual(expect.objectContaining({ kind: 'restore' }));
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: status.toUpperCase() }), expect.anything());
});

it('reports UNKNOWN on renderer timeout', async () => {
  jest.useFakeTimers();
  await act(async () => { await hook.send('립 진하기 50%'); });
  await act(async () => { jest.advanceTimersByTime(6000); });
  expect(hook.state).toBe('unknown');
  expect(mockedPost).toHaveBeenCalledWith('/api/chat/acks', expect.objectContaining({ status: 'UNKNOWN' }), expect.anything());
});

it('retries a lost ACK without sending the command or rendering again', async () => {
  let ackCalls = 0;
  mockedPost.mockImplementation(async (path, body) => {
    if (path === '/api/chat') return owned(proposed(body as never)) as never;
    if (++ackCalls === 1) throw new Error('network');
    return owned({ received: true }) as never;
  });
  await act(async () => { await hook.send('립 진하기 50%'); });
  const render = hook.renderCommand!;
  await act(async () => { hook.onRenderResult({ commandId, renderSeq: render.renderSeq, rendererId: render.rendererId, status: 'rendered' }); });
  expect(hook.ackPending).toBe(1);
  await act(async () => { await hook.retryAck(); });
  expect(hook.ackPending).toBe(0);
  expect(mockedPost.mock.calls.filter(([path]) => path === '/api/chat')).toHaveLength(1);
  expect(mockedPost.mock.calls.filter(([path]) => path === '/api/chat/acks')).toHaveLength(2);
  expect(useMakeupStore.getState().makeup.lip!.intensity).toBe(0.5);
});
