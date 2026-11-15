import { apiPost } from '@/lib/api';
import { getSupabase } from '@/lib/auth/client';

jest.mock('@/lib/auth', () => ({ getAccessToken: jest.fn() }));
jest.mock('@/lib/auth/client', () => ({ getSupabase: jest.fn(), isAuthConfigured: () => true }));
jest.mock('@/lib/chatIdentity', () => ({ getAnonymousChatId: jest.fn() }));

afterEach(() => jest.restoreAllMocks());
function credentials(id: string) {
  const session = { access_token: `token-${id}`, user: { id } };
  const auth = { getSession: jest.fn(async () => ({ data: { session } })),
    getClaims: jest.fn(async () => ({ data: { claims: { sub: id, role: 'authenticated' } } })) };
  jest.mocked(getSupabase).mockReturnValue({ auth } as never);
  return auth;
}

test('feedback pins the verified owner token to the configured comparison backend', async () => {
  credentials('member-a');
  const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => ({ ok: true }) } as Response);
  await apiPost('/api/dev/recommendations/events', { eventId: 'event' }, {
    baseUrl: 'http://localhost:8082', expectedUserId: 'member-a',
  });
  expect(fetchMock).toHaveBeenCalledWith('http://localhost:8082/api/dev/recommendations/events',
    expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token-member-a' }) }));
});

test('another user cannot submit old recommendation context', async () => {
  credentials('member-b');
  const fetchMock = jest.spyOn(globalThis, 'fetch');
  await expect(apiPost('/api/dev/recommendations/events', {}, { expectedUserId: 'member-a' }))
    .rejects.toMatchObject({ code: 'owner_changed' });
  expect(fetchMock).not.toHaveBeenCalled();
});

test('identity changing during token verification sends no request', async () => {
  const auth = credentials('member-a');
  auth.getSession.mockResolvedValueOnce({ data: { session: { access_token: 'token-member-a', user: { id: 'member-a' } } } });
  auth.getSession.mockResolvedValue({ data: { session: { access_token: 'token-member-b', user: { id: 'member-b' } } } });
  const fetchMock = jest.spyOn(globalThis, 'fetch');
  await expect(apiPost('/api/dev/recommendations/events', {}, { expectedUserId: 'member-a' })).rejects.toThrow();
  expect(fetchMock).not.toHaveBeenCalled();
});
