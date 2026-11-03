import { ApiError, apiPostChat } from '@/lib/api';

type Session = { user: { id: string }; access_token: string } | null;
let mockSession: Session;
const mockListeners = new Set<(event: string, session: Session) => void>();
const mockGuest = jest.fn();
const mockClaims = jest.fn();
const mockClient = {
  auth: {
    getSession: async () => ({ data: { session: mockSession } }),
    getClaims: (...args: unknown[]) => mockClaims(...args),
    onAuthStateChange: (fn: (event: string, session: Session) => void) => {
      mockListeners.add(fn);
      return { data: { subscription: { unsubscribe: () => mockListeners.delete(fn) } } };
    },
  },
};
jest.mock('@/lib/auth', () => ({ getAccessToken: async () => null }));
jest.mock('@/lib/auth/client', () => ({ getSupabase: () => mockClient, isAuthConfigured: () => true }));
jest.mock('@/lib/chatIdentity', () => ({ getAnonymousChatId: () => mockGuest() }));

function transition(session: Session) {
  mockSession = session;
  mockListeners.forEach((fn) => fn(session ? 'SIGNED_IN' : 'SIGNED_OUT', session));
}

beforeEach(() => {
  mockSession = null;
  mockListeners.clear();
  mockGuest.mockReset().mockResolvedValue('guest-session-0123456789-abcdefghijk');
  mockClaims.mockReset().mockImplementation(async () => ({
    data: { claims: { sub: mockSession?.user.id, role: 'authenticated' } },
  }));
});
afterEach(() => { jest.restoreAllMocks(); });

it('pins the verified user token and does not provide anonymous fallback headers', async () => {
  mockSession = { user: { id: 'A' }, access_token: 'token-A' };
  const fetch = jest.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => ({ answer: 'ok' }) } as Response);
  await expect(apiPostChat({}, { expectedUserId: 'A' })).resolves.toEqual({ answer: 'ok' });
  const headers = fetch.mock.calls[0][1]?.headers as Record<string, string>;
  expect(headers.Authorization).toBe('Bearer token-A');
  expect(headers['X-Vishue-Anonymous-Id']).toBeUndefined();
  expect(mockListeners.size).toBe(0);
});

it('does not send a prior user session under a different account', async () => {
  mockSession = { user: { id: 'B' }, access_token: 'token-B' };
  const fetch = jest.spyOn(globalThis, 'fetch');
  await expect(apiPostChat({}, { expectedUserId: 'A' })).rejects.toMatchObject({ code: 'chat_owner_changed' });
  expect(fetch).not.toHaveBeenCalled();
});

it.each(['login', 'logout', 'different-account', 'logout-back', 'guest-rotation'])(
  'rejects a response after identity change: %s', async (kind) => {
    const initial: Session = kind === 'login' || kind === 'guest-rotation' ? null
      : { user: { id: 'A' }, access_token: 'token-A' };
    mockSession = initial;
    jest.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => {
      if (kind === 'guest-rotation') mockGuest.mockResolvedValue('another-guest-0123456789-abcdefghijk');
      else if (kind === 'login') transition({ user: { id: 'A' }, access_token: 'token-A' });
      else if (kind === 'different-account') transition({ user: { id: 'B' }, access_token: 'token-B' });
      else {
        transition(null);
        if (kind === 'logout-back') transition(initial);
      }
      return { answer: 'old owner response' };
    } } as Response);
    await expect(apiPostChat({}, { expectedUserId: initial?.user.id ?? null }))
      .rejects.toMatchObject({ code: 'chat_owner_changed' });
    expect(mockListeners.size).toBe(0);
  }
);

it('accepts token refresh for the same owner', async () => {
  mockSession = { user: { id: 'A' }, access_token: 'token-A' };
  jest.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => {
    transition({ user: { id: 'A' }, access_token: 'refreshed-token-A' });
    return { answer: 'same owner' };
  } } as Response);
  await expect(apiPostChat({}, { expectedUserId: 'A' })).resolves.toEqual({ answer: 'same owner' });
});

it('distinguishes a storage HTTP error from a network failure', async () => {
  const fetch = jest.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
    ok: false, status: 503, json: async () => ({ error: 'Unavailable', code: 'chat_session_unavailable' }),
  } as Response).mockRejectedValueOnce(new TypeError('offline'));
  await expect(apiPostChat({}, { expectedUserId: null })).rejects.toMatchObject({ status: 503, code: 'chat_session_unavailable' });
  await expect(apiPostChat({}, { expectedUserId: null })).rejects.toMatchObject({ status: 0, code: 'network' });
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('does not send session capabilities without an expected identity or with unverified credentials', async () => {
  const fetch = jest.spyOn(globalThis, 'fetch');
  await expect(apiPostChat({ chatContext: { session: { sessionToken: 'never send' } } }))
    .rejects.toBeInstanceOf(ApiError);
  mockSession = { user: { id: 'A' }, access_token: 'unverified' };
  mockClaims.mockResolvedValue({ error: new Error('invalid') });
  await expect(apiPostChat({}, { expectedUserId: 'A' })).rejects.toMatchObject({ code: 'chat_owner_unavailable' });
  expect(fetch).not.toHaveBeenCalled();
});
