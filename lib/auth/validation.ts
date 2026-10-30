import type { TranslationKey } from '@/lib/i18n';

export const MIN_PASSWORD_LENGTH = 8;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(email: string) {
  return EMAIL_PATTERN.test(email.trim());
}

/** First problem with a new password, checked before Supabase so the message is specific. */
export function newPasswordError(password: string, confirm: string): TranslationKey | null {
  if (password.length < MIN_PASSWORD_LENGTH) return 'auth.error.passwordTooShort';
  if (password !== confirm) return 'auth.error.passwordMismatch';
  return null;
}
