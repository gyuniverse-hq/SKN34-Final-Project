import { apiPost, apiPostOwned } from '@/lib/api';
import { pendingArAcks, queueArAck, retryArAcks } from '@/lib/arCommandAck';
import { getSupabase, isAuthConfigured } from '@/lib/auth/client';
import { getAccessToken } from '@/lib/auth';
import { getAnonymousChatId } from '@/lib/chatIdentity';

jest.mock('@/lib/auth', () => ({ getAccessToken: jest.fn() }));
jest.mock('@/lib/auth/client', () => ({ getSupabase: jest.fn(), isAuthConfigured: jest.fn() }));
jest.mock('@/lib/chatIdentity', () => ({ getAnonymousChatId: jest.fn() }));

const guest = { kind: 'guest' as const, id: 'guest-a' };
const userA = { kind: 'user' as const, id: 'user-a' };
const body = { requestId: 'request-1', commandId: 'command-1', sessionId: 'session-1', status: 'APPLIED' as const, actualStateVersion: 2 };
let session: { access_token: string; user: { id: string } } | null;
let subject: string;
let claimError: Error | null;
const getSession = jest.fn(async () => ({ data: { session }, error: null }));
const getClaims = jest.fn(async () => ({ data: { claims: { sub: subject, role: 'authenticated' } }, error: claimError }));
let authListener: (event: string, nextSession: typeof session) => void;
const unsubscribeAuth = jest.fn();
const onAuthStateChange = jest.fn((listener: typeof authListener) => {
  authListener = listener;
  return { data: { subscription: { unsubscribe: unsubscribeAuth } } };
});
const response = (received = true) => ({ ok: true, json: async () => ({ received }) });
const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

beforeEach(() => {
  jest.clearAllMocks();
  session = null;
  subject = 'user-a';
  claimError = null;
  jest.mocked(getSupabase).mockReturnValue({ auth: { getSession, getClaims, onAuthStateChange } } as never);
  jest.mocked(isAuthConfigured).mockReturnValue(true);
  jest.mocked(getAnonymousChatId).mockResolvedValue(guest.id);
  jest.mocked(getAccessToken).mockResolvedValue(null);
  globalThis.fetch = jest.fn(async () => response() as Response);
});

it('binds a guest request to its anonymous ID with no Authorization header', async () => {
  const result = await apiPostOwned('/api/chat', {});
  expect(result.owner).toEqual(guest);
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  const headers = (jest.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit).headers;
  expect(headers).toMatchObject({ 'X-Vishue-Anonymous-Id': guest.id });
  expect(headers).not.toHaveProperty('Authorization');
});

it('rejects an in-flight response after A -> B -> A and removes the auth subscription', async () => {
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  let release!: (value: Response) => void;
  globalThis.fetch = jest.fn(() => new Promise<Response>((resolve) => { release = resolve; }));
  const pending = apiPostOwned('/api/chat', {});
  await flush();
  session = { access_token: 'token-b', user: { id: 'user-b' } };
  authListener('SIGNED_IN', session);
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  authListener('SIGNED_IN', session);
  release(response() as Response);
  await expect(pending).rejects.toMatchObject({ code: 'ar_owner_changed' });
  expect(unsubscribeAuth).toHaveBeenCalled();
});

it('keeps the same principal valid across a token refresh', async () => {
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  let release!: (value: Response) => void;
  globalThis.fetch = jest.fn(() => new Promise<Response>((resolve) => { release = resolve; }));
  const pending = apiPostOwned('/api/chat', {});
  await flush();
  session = { access_token: 'refreshed-a', user: { id: 'user-a' } };
  authListener('TOKEN_REFRESHED', session);
  release(response() as Response);
  await expect(pending).resolves.toMatchObject({ owner: userA });
});

it('uses a verified token once and does not send a guest fallback with it', async () => {
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  const result = await apiPostOwned('/api/chat', {});
  expect(result.owner).toEqual(userA);
  expect(getClaims).toHaveBeenCalledWith('token-a');
  const headers = (jest.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit).headers;
  expect(headers).toMatchObject({ Authorization: 'Bearer token-a' });
  expect(headers).not.toHaveProperty('X-Vishue-Anonymous-Id');
});

it('blocks mismatched or unverifiable identity before an HTTP request', async () => {
  session = { access_token: 'token-b', user: { id: 'user-b' } };
  subject = 'user-b';
  await expect(apiPostOwned('/api/chat/acks', body, { expectedOwner: userA })).rejects.toMatchObject({ code: 'ar_owner_changed' });
  subject = 'user-a';
  claimError = new Error('verification unavailable');
  await expect(apiPostOwned('/api/chat/acks', body, { expectedOwner: userA })).rejects.toMatchObject({ code: 'ar_owner_unavailable' });
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it('blocks when the account changes during token verification', async () => {
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  getClaims.mockImplementationOnce(async () => {
    session = { access_token: 'token-b', user: { id: 'user-b' } };
    return { data: { claims: { sub: 'user-a', role: 'authenticated' } }, error: null };
  });
  await expect(apiPostOwned('/api/chat', {})).rejects.toMatchObject({ code: 'ar_owner_unavailable' });
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it('holds the request if the session user is absent or differs from verified claims', async () => {
  session = { access_token: 'token-a', user: { id: 'user-b' } };
  await expect(apiPostOwned('/api/chat', {})).rejects.toMatchObject({ code: 'ar_owner_unavailable' });
  session = { access_token: 'token-a', user: { id: '' } };
  await expect(apiPostOwned('/api/chat', {})).rejects.toMatchObject({ code: 'ar_owner_unavailable' });
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it('does not treat a login during guest identity lookup as a guest request', async () => {
  jest.mocked(getAnonymousChatId).mockImplementationOnce(async () => {
    session = { access_token: 'token-a', user: { id: 'user-a' } };
    return guest.id;
  });
  await expect(apiPostOwned('/api/chat', {})).rejects.toMatchObject({ code: 'ar_owner_unavailable' });
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it('keeps an ACK after loss and does not send it as another user', async () => {
  jest.mocked(globalThis.fetch).mockRejectedValueOnce(new Error('network'));
  queueArAck(body, guest);
  await flush();
  expect(pendingArAcks()).toBe(1);
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  await retryArAcks();
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  expect(pendingArAcks()).toBe(1);
  session = null;
  await retryArAcks();
  expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  expect(pendingArAcks()).toBe(0);
  expect((jest.mocked(globalThis.fetch).mock.calls[1][1] as RequestInit).body).toBe(JSON.stringify(body));
});

it('holds a user ACK on logout or account switch and resumes with a refreshed token for that user', async () => {
  const userBody = { ...body, commandId: 'user-command' };
  session = { access_token: 'token-a', user: { id: 'user-a' } };
  jest.mocked(globalThis.fetch).mockRejectedValueOnce(new Error('lost response'));
  queueArAck(userBody, userA);
  await flush();
  expect(pendingArAcks()).toBe(1);
  session = null;
  await retryArAcks();
  session = { access_token: 'token-b', user: { id: 'user-b' } };
  subject = 'user-b';
  await retryArAcks();
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  session = { access_token: 'refreshed-a', user: { id: 'user-a' } };
  subject = 'user-a';
  await retryArAcks();
  expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  expect((jest.mocked(globalThis.fetch).mock.calls[1][1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer refreshed-a' });
  expect(pendingArAcks()).toBe(0);
});

it('deduplicates concurrent ACK retries while a request is in flight', async () => {
  const concurrentBody = { ...body, commandId: 'concurrent-command' };
  let resolveFetch!: (value: Response) => void;
  jest.mocked(globalThis.fetch).mockImplementationOnce(() => new Promise((resolve) => { resolveFetch = resolve; }));
  queueArAck(concurrentBody, guest);
  await flush();
  const first = retryArAcks();
  const second = retryArAcks();
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  resolveFetch(response() as Response);
  await Promise.all([first, second]);
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  expect(pendingArAcks()).toBe(0);
});

it('keeps ordinary chat using the existing apiPost behavior', async () => {
  jest.mocked(getAccessToken).mockResolvedValue('ordinary-token');
  await apiPost('/api/chat', { message: 'hello' });
  expect((jest.mocked(globalThis.fetch).mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer ordinary-token' });
  expect(getClaims).not.toHaveBeenCalled();
});
