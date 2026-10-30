import { TERMS_VERSION } from '@/constants/legal';
import type { TermsStatus } from '@/types';
import { apiDelete, apiPost } from './api';

export function needsTermsConsent(terms: TermsStatus) {
  return terms.agreedVersion !== terms.version;
}

/** Records that the signed-in user agreed to the terms bundled in this app. */
export function agreeToTerms() {
  return apiPost<TermsStatus>('/api/me/terms', { version: TERMS_VERSION });
}

/** Deletes the Supabase account and the backend member record. Sign out afterwards. */
export function deleteAccount() {
  return apiDelete('/api/me');
}
