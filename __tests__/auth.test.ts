import { AuthFlowError, authErrorMessageKey } from '@/lib/auth/errors';

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
