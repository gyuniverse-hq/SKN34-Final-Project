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

export function isAccountDeletionReceipt(value: string | null | undefined): value is string {
  return !!value && /^[0-9a-f]{32}\.[0-9a-f]{64}$/.test(value);
}

export async function deleteAccount(owner: string): Promise<{ phase: 'pending' | 'complete'; receipt?: string }> {
  try {
    await apiDelete('/api/me', { expectedUserId: owner, expectedStatus: 204 });
    return { phase: 'complete' };
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.code === 'account_deletion_in_progress') {
      return { phase: 'pending', receipt: isAccountDeletionReceipt(error.deletionReceipt) ? error.deletionReceipt : undefined };
    }
    throw error;
  }
}

export async function accountDeletionStatus(receipt: string) {
  const result = await apiPost<{ status: 'pending' | 'complete' }>('/api/me/deletion-status', { receipt }, { anonymous: true });
  if (result?.status !== 'pending' && result?.status !== 'complete') {
    throw new ApiError('Invalid account deletion status', 502);
  }
  return result.status;
}

export function hasAccountDeletionFence(error: unknown) {
  return error instanceof ApiError && error.status === 403 && error.code === 'account_unavailable';
}
