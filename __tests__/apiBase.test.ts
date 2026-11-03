import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { useChat } from '@/hooks/useChat';
import { API_BASE_URL, CHAT_API_BASE_URL, ApiError, apiDelete, apiPost, resolveApiBaseUrl, resolveChatApiBaseUrl } from '@/lib/api';
import { getAccessToken } from '@/lib/auth';
import { getAnonymousChatId } from '@/lib/chatIdentity';

jest.mock('@/lib/auth', () => ({ getAccessToken: jest.fn() }));
jest.mock('@/lib/chatIdentity', () => ({ getAnonymousChatId: jest.fn() }));

describe('resolveApiBaseUrl', () => {
  it('prefers the configured backend URL without a trailing slash', () => {
    expect(resolveApiBaseUrl({ configured: 'https://api.vishue.app/', isDev: true, devHost: '10.0.0.5' })).toBe(
      'https://api.vishue.app'
    );
  });

  it('uses the local gateway on the dev machine in development', () => {
    expect(resolveApiBaseUrl({ isDev: true, devHost: '192.168.0.12' })).toBe('http://192.168.0.12:8080');
    expect(resolveApiBaseUrl({ isDev: true, devHost: null })).toBe('http://localhost:8080');
  });

  it('keeps paths relative in production builds without a configured URL', () => {
    expect(resolveApiBaseUrl({ isDev: false, devHost: '192.168.0.12' })).toBe('');
  });
});

describe('useChat integration', () => {
  it('round-trips ingredient evidence and exact selections through the real hook and HTTP adapter', async () => {
    jest.mocked(getAnonymousChatId).mockResolvedValue('anonymous-id');
    const chatContext = { version: 1 as const, issuedAt: 1000, candidateIds: ['p1', 'p2'],
      scopeIds: ['p1', 'p2'], selectedProductId: 'p2', shadeSelections: { p2: 'p2-03' },
      filters: { category: null, maxPriceKRW: null, fragranceFree: false, moisturizing: false, query: '' } };
    const screenContext = { screenId: 'chat', productId: 'p2', shadeId: 'p2-03' };
    const reply = { answer: '미확인', products: [], chatContext,
      ingredientResults: [{ productId: 'p2', shadeId: 'p2-03', verdict: 'UNKNOWN',
        status: 'unknown', mappingStatus: 'candidate', reviewStatus: 'unreviewed',
        ingredientCoverage: 'unknown', normalizationStatus: 'unverified',
        ingredients: [], conditions: [], reason: 'mapping_not_verified' }] };
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true, json: async () => reply,
    } as Response);
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false, gcTime: Infinity } } });
    let sendChat!: ReturnType<typeof useChat>['mutateAsync'];
    let renderer!: ReactTestRenderer;
    function Harness() { sendChat = useChat().mutateAsync; return null; }
    try {
      await act(async () => { renderer = create(createElement(QueryClientProvider, { client }, createElement(Harness))); });
      await act(async () => {
        const result = await sendChat({ message: '두 번째 상품 성분', locale: 'ko', category: 'ingredient', chatContext, screenContext });
        expect(result).toEqual(reply);
      });
      expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({
        message: '두 번째 상품 성분', locale: 'ko', requestType: 'beauty_consultation', chatContext, screenContext,
        requestId: expect.stringMatching(/^[0-9a-f-]{36}$/i),
      });
    } finally {
      await act(async () => { renderer?.unmount(); });
      client.clear();
      jest.restoreAllMocks();
    }
  });

  it('posts to the chat origin with the anonymous ID and chat-only timeout', async () => {
    jest.mocked(getAnonymousChatId).mockResolvedValue('anonymous-id');
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true, json: async () => ({ answer: 'answer', products: [] }),
    } as Response);
    const timeout = jest.spyOn(globalThis, 'setTimeout');
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false, gcTime: Infinity } } });
    let sendChat!: ReturnType<typeof useChat>['mutateAsync'];
    let renderer!: ReactTestRenderer;
    function Harness() {
      sendChat = useChat().mutateAsync;
      return null;
    }
    try {
      await act(async () => {
        renderer = create(createElement(QueryClientProvider, { client }, createElement(Harness)));
      });
      await act(async () => { await sendChat({ message: 'hello', locale: 'ko' }); });
      expect(fetchMock).toHaveBeenCalledWith(`${CHAT_API_BASE_URL}/api/chat`, expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-Vishue-Anonymous-Id': 'anonymous-id' }),
        body: expect.any(String),
      }));
      expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({
        message: 'hello', locale: 'ko', requestId: expect.stringMatching(/^[0-9a-f-]{36}$/i),
      });
      expect(timeout).toHaveBeenCalledWith(expect.any(Function), 90000);
    } finally {
      await act(async () => { renderer?.unmount(); });
      client.clear();
      jest.restoreAllMocks();
    }
  });
});

describe('chat backend URL', () => {
  it('uses the configured chat URL without whitespace or trailing slashes', () => {
    expect(resolveChatApiBaseUrl(' https://chat.example.test/// ', 'https://api.example.test'))
      .toBe('https://chat.example.test');
  });

  it('falls back to the existing gateway, including a relative production origin', () => {
    expect(resolveChatApiBaseUrl(undefined, 'https://api.example.test')).toBe('https://api.example.test');
    expect(resolveChatApiBaseUrl('  ', '')).toBe('');
  });
});

describe('apiPost backend selection', () => {
  const mockToken = jest.mocked(getAccessToken);
  const response = { ok: true, json: async () => ({ ok: true }) } as Response;

  afterEach(() => {
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it('uses the chat origin and preserves the auth and anonymous headers', async () => {
    mockToken.mockResolvedValueOnce('access-token');
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);
    await apiPost('/api/chat', { message: 'hello', locale: 'en' }, {
      baseUrl: 'https://chat.example.test/',
      headers: { 'X-Vishue-Anonymous-Id': 'anonymous-id' },
    });
    expect(fetchMock).toHaveBeenCalledWith('https://chat.example.test/api/chat', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token', 'X-Vishue-Anonymous-Id': 'anonymous-id' }),
      body: JSON.stringify({ message: 'hello', locale: 'en' }),
    }));
  });

  it('keeps the shared origin for other requests and allows a relative origin', async () => {
    mockToken.mockResolvedValue(null);
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValue(response);
    const timeout = jest.spyOn(globalThis, 'setTimeout');
    await apiPost('/api/payments', {});
    await apiPost('/api/chat', {}, { baseUrl: '' });
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE_URL}/api/payments`);
    expect(fetchMock.mock.calls[1][0]).toBe('/api/chat');
    expect(timeout).toHaveBeenCalledWith(expect.any(Function), 12000);
  });

  it('uses the shared origin and access token for account deletion', async () => {
    mockToken.mockResolvedValueOnce('access-token');
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValueOnce({ ok: true } as Response);
    await apiDelete('/api/me');
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE_URL}/api/me`, expect.objectContaining({
      method: 'DELETE',
      headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
    }));
  });

  it('rejects an invalid separate URL before sending a request or auth token', async () => {
    const fetchMock = jest.spyOn(globalThis, 'fetch');
    await expect(apiPost('/api/chat', {}, { baseUrl: 'https://user:pass@chat.example.test' }))
      .rejects.toMatchObject({ code: 'invalid_base_url' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('uses a longer timeout only when supplied', async () => {
    jest.useFakeTimers();
    mockToken.mockResolvedValue(null);
    const request: { signal?: AbortSignal } = {};
    jest.spyOn(globalThis, 'fetch').mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      request.signal = init?.signal as AbortSignal;
      request.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    }));
    const result = apiPost('/api/chat', {}, { baseUrl: 'https://chat.example.test', timeoutMs: 90000 })
      .catch((error: ApiError) => error);
    await Promise.resolve();
    await jest.advanceTimersByTimeAsync(12000);
    expect(request.signal?.aborted).toBe(false);
    await jest.advanceTimersByTimeAsync(78000);
    await expect(result).resolves.toMatchObject({ message: 'Request timed out', code: 'network' });
  });
});
