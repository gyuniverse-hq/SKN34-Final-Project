const mockGetClaims = jest.fn();

jest.mock('@supabase/supabase-js', () => ({
  createClient: jest.fn(() => ({ auth: { getClaims: mockGetClaims } })),
}));

import { GET } from '@/app/api/me+api';
import { bearerToken, getAuthUser, userFromClaims } from '@/server/lib/auth';

function request(authorization?: string) {
  return new Request('http://localhost/api/me', {
    headers: authorization ? { Authorization: authorization } : {},
  });
}

const ENV_KEYS = ['EXPO_PUBLIC_SUPABASE_URL', 'EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY'];
const savedEnv = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));

function setConfigured(configured: boolean) {
  for (const k of ENV_KEYS) delete process.env[k];
  if (configured) {
    process.env.EXPO_PUBLIC_SUPABASE_URL = 'https://project.supabase.co';
    process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_test';
  }
}

afterEach(() => {
  mockGetClaims.mockReset();
});

afterAll(() => {
  for (const [k, v] of Object.entries(savedEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
});

describe('bearerToken', () => {
  it('extracts the token from the Authorization header', () => {
    expect(bearerToken(request('Bearer abc.def.ghi'))).toBe('abc.def.ghi');
    expect(bearerToken(request('bearer abc'))).toBe('abc');
  });

  it('rejects missing or malformed headers', () => {
    expect(bearerToken(request())).toBeNull();
    expect(bearerToken(request('Basic abc'))).toBeNull();
    expect(bearerToken(request('Bearer a b'))).toBeNull();
  });
});

describe('userFromClaims', () => {
  it('accepts signed-in users only', () => {
    expect(userFromClaims({ sub: 'u1', role: 'authenticated', email: 'a@b.c' })).toEqual({ id: 'u1', email: 'a@b.c' });
    expect(userFromClaims({ sub: 'u1', role: 'authenticated' })).toEqual({ id: 'u1', email: null });
    expect(userFromClaims({ sub: 'u1', role: 'anon' })).toBeNull();
    expect(userFromClaims({ role: 'authenticated' })).toBeNull();
  });
});

describe('getAuthUser and /api/me', () => {
  it('returns 503 when Supabase is not configured', async () => {
    setConfigured(false);
    const res = await GET(request('Bearer token'));
    expect(res.status).toBe(503);
    expect(mockGetClaims).not.toHaveBeenCalled();
  });

  it('returns 401 without a token or with an invalid one', async () => {
    setConfigured(true);
    expect((await GET(request())).status).toBe(401);

    mockGetClaims.mockResolvedValueOnce({ data: null, error: { message: 'invalid JWT' } });
    expect((await GET(request('Bearer bad'))).status).toBe(401);
    expect(mockGetClaims).toHaveBeenCalledWith('bad');
  });

  it('returns the user for a verified token', async () => {
    setConfigured(true);
    mockGetClaims.mockResolvedValueOnce({
      data: { claims: { sub: 'user-1', role: 'authenticated', email: 'me@example.com' } },
      error: null,
    });
    const res = await GET(request('Bearer good'));
    expect(res.status).toBe(200);
    expect(res.headers.get('Cache-Control')).toBe('no-store');
    expect(await res.json()).toEqual({ user: { id: 'user-1', email: 'me@example.com' } });
  });

  it('getAuthUser returns null when verification fails', async () => {
    setConfigured(true);
    mockGetClaims.mockResolvedValueOnce({ data: null, error: null });
    await expect(getAuthUser(request('Bearer x'))).resolves.toBeNull();
  });
});
