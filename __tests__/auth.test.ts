import { needsTermsConsent } from '@/lib/account';
import { AuthFlowError, authErrorMessageKey } from '@/lib/auth/errors';
import { parseAuthRedirect } from '@/lib/auth/redirect';
import { isValidEmail, newPasswordError } from '@/lib/auth/validation';

describe('sign-up input checks', () => {
  it('accepts only addresses with a user, a domain and a dot', () => {
    expect(isValidEmail(' a@b.co ')).toBe(true);
    expect(isValidEmail('a@b')).toBe(false);
    expect(isValidEmail('a b@c.co')).toBe(false);
    expect(isValidEmail('')).toBe(false);
  });

  it('reports a short password before a mismatch', () => {
    expect(newPasswordError('short', 'other')).toBe('auth.error.passwordTooShort');
    expect(newPasswordError('long-enough', 'different')).toBe('auth.error.passwordMismatch');
    expect(newPasswordError('long-enough', 'long-enough')).toBeNull();
  });
});

describe('needsTermsConsent', () => {
  it('asks until the current version is agreed', () => {
    const terms = { version: 'v2', agreedVersion: null, agreedAt: null };
    expect(needsTermsConsent(terms)).toBe(true);
    expect(needsTermsConsent({ ...terms, agreedVersion: 'v1', agreedAt: '2026-01-01T00:00:00Z' })).toBe(true);
    expect(needsTermsConsent({ ...terms, agreedVersion: 'v2', agreedAt: '2026-01-01T00:00:00Z' })).toBe(false);
  });
});

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
