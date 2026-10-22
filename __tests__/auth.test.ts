import { AuthFlowError, authErrorMessageKey } from '@/lib/auth/errors';
import { parseAuthRedirect } from '@/lib/auth/redirect';

describe('parseAuthRedirect', () => {
  it('reads tokens from the fragment', () => {
    expect(
      parseAuthRedirect('kbeautyar://auth/callback#access_token=abc.def&refresh_token=r1&token_type=bearer')
    ).toEqual({ type: 'session', accessToken: 'abc.def', refreshToken: 'r1' });
  });

  it('reads tokens from Expo Go style URLs with a query string', () => {
    expect(
      parseAuthRedirect('exp://192.168.0.2:8081/--/auth/callback?foo=1#access_token=a&refresh_token=b')
    ).toEqual({ type: 'session', accessToken: 'a', refreshToken: 'b' });
  });

  it('reports provider errors', () => {
    expect(
      parseAuthRedirect('kbeautyar://auth/callback?error=access_denied&error_description=User+cancelled+login')
    ).toEqual({ type: 'error', message: 'User cancelled login' });
  });

  it('returns none when the URL has no session', () => {
    expect(parseAuthRedirect('kbeautyar://auth/callback')).toEqual({ type: 'none' });
    expect(parseAuthRedirect('kbeautyar://auth/callback#access_token=only')).toEqual({ type: 'none' });
  });
});

describe('authErrorMessageKey', () => {
  it('maps Supabase error codes to user-facing messages', () => {
    expect(authErrorMessageKey({ code: 'invalid_credentials' })).toBe('auth.error.invalidCredentials');
    expect(authErrorMessageKey({ code: 'email_exists' })).toBe('auth.error.userExists');
    expect(authErrorMessageKey({ code: 'otp_expired' })).toBe('auth.error.invalidCode');
    expect(authErrorMessageKey({ code: 'over_email_send_rate_limit' })).toBe('auth.error.rateLimited');
  });

  it('maps app-side failures and network errors', () => {
    expect(authErrorMessageKey(new AuthFlowError('not_configured'))).toBe('auth.notConfigured');
    expect(authErrorMessageKey(new AuthFlowError('user_already_exists'))).toBe('auth.error.userExists');
    expect(authErrorMessageKey({ name: 'AuthRetryableFetchError' })).toBe('common.networkError');
  });

  it('falls back to a generic message', () => {
    expect(authErrorMessageKey({ code: 'something_new' })).toBe('auth.error.generic');
    expect(authErrorMessageKey(new Error('boom'))).toBe('auth.error.generic');
    expect(authErrorMessageKey(null)).toBe('auth.error.generic');
  });
});
