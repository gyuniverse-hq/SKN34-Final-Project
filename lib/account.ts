import { TERMS_VERSION } from '@/constants/legal';
import type { TermsStatus } from '@/types';
import { ApiError, apiDelete, apiPost } from './api';

export function needsTermsConsent(terms: TermsStatus) {
  return terms.agreedVersion !== terms.version;
}

/** Records that the signed-in user agreed to the terms bundled in this app. */
export function agreeToTerms() {
  return apiPost<TermsStatus>('/api/me/terms', { version: TERMS_VERSION });
}

export async function deleteAccount(owner: string): Promise<'pending' | 'complete'> {
  try {
    await apiDelete('/api/me', { expectedUserId: owner, expectedStatus: 204 });
    return 'complete';
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.code === 'account_deletion_in_progress') {
      return 'pending';
    }
    throw error;
  }
}

export function hasAccountDeletionFence(error: unknown) {
  return error instanceof ApiError && error.status === 403 && error.code === 'account_unavailable';
}
