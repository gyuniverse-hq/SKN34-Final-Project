import { resolveApiBaseUrl } from '@/lib/api';

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
