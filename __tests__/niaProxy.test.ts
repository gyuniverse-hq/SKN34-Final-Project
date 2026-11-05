import { niaProxy } from '@/server/services/niaEvaluationService';

describe('NIA development gateway', () => {
  const originalEnv = process.env;
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    process.env = { ...originalEnv, NODE_ENV: 'development', NIA_EVAL_TOKEN: 'a'.repeat(32) };
    globalThis.fetch = jest.fn();
  });
  afterEach(() => { process.env = originalEnv; globalThis.fetch = originalFetch; });

  it.each(['production', 'test', undefined] as const)('blocks access in %s before contacting Python', async mode => {
    const next = { ...process.env };
    if (mode) next.NODE_ENV = mode;
    else Reflect.deleteProperty(next, 'NODE_ENV');
    process.env = next;
    const result = await niaProxy(new Request('http://localhost/api/dev/nia/status'), 'status');
    expect(result.status).toBe(404);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('requires a server-side secret', async () => {
    delete process.env.NIA_EVAL_TOKEN;
    const result = await niaProxy(new Request('http://localhost/api/dev/nia/status'), 'status');
    expect(result.status).toBe(503);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('forwards a photo profile request through the development gateway', async () => {
    (globalThis.fetch as jest.Mock).mockResolvedValue(new Response('{"id":"profile-job"}', { status: 200 }));
    const result = await niaProxy(new Request('http://localhost/api/dev/nia/profile', {
      method: 'POST', body: JSON.stringify({ image: 'fixture-base64' }),
    }), 'profile');
    const [target, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
    expect(String(target)).toBe('http://127.0.0.1:8765/profile');
    expect(JSON.parse(options.body)).toEqual({ image: 'fixture-base64' });
    expect(await result.json()).toEqual({ id: 'profile-job' });
  });

  it('forwards only allowed actions to loopback without exposing the token', async () => {
    (globalThis.fetch as jest.Mock).mockResolvedValue(new Response('{"models":[]}', { status: 200 }));
    const result = await niaProxy(new Request('http://localhost/api/dev/nia/status?url=https://other.test'), 'status');
    const [target, options] = (globalThis.fetch as jest.Mock).mock.calls[0];
    expect(String(target)).toBe('http://127.0.0.1:8765/status');
    expect(options.headers['X-NIA-Token']).toBe('a'.repeat(32));
    expect(await result.text()).toBe('{"models":[]}');
    expect(result.headers.get('Cache-Control')).toBe('no-store');
    expect((await niaProxy(new Request('http://localhost/api/dev/nia/train'), 'train')).status).toBe(404);
  });
});
