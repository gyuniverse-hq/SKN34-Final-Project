import type { TranslationKey } from '@/lib/i18n';

/** App-side auth failures that Supabase does not report as errors. */
export class AuthFlowError extends Error {
  constructor(public code: 'not_configured' | 'user_already_exists') {
    super(code);
    this.name = 'AuthFlowError';
  }
}

const MESSAGE_BY_CODE: Record<string, TranslationKey> = {
  not_configured: 'auth.notConfigured',
  invalid_credentials: 'auth.error.invalidCredentials',
  email_not_confirmed: 'auth.error.emailNotConfirmed',
  user_already_exists: 'auth.error.userExists',
  email_exists: 'auth.error.userExists',
  weak_password: 'auth.error.weakPassword',
  over_email_send_rate_limit: 'auth.error.rateLimited',
  over_request_rate_limit: 'auth.error.rateLimited',
  otp_expired: 'auth.error.invalidCode',
  email_address_invalid: 'auth.error.invalidEmail',
  same_password: 'auth.error.samePassword',
};

export function authErrorCode(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | null)?.code;
  return typeof code === 'string' ? code : undefined;
}

export function authErrorMessageKey(error: unknown): TranslationKey {
  const code = authErrorCode(error);
  if (code && MESSAGE_BY_CODE[code]) return MESSAGE_BY_CODE[code];
  if ((error as { name?: unknown } | null)?.name === 'AuthRetryableFetchError') return 'common.networkError';
  return 'auth.error.generic';
}
