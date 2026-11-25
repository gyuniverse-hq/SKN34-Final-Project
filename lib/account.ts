import { TERMS_VERSION } from '@/constants/legal';
import type { TermsStatus } from '@/types';
import { apiDelete, apiPost } from './api';

export function needsTermsConsent(terms: TermsStatus) {
  return terms.agreedVersion !== terms.version || terms.cameraFeaturesConsent === null;
}

/** Records that the signed-in user agreed to the terms bundled in this app. */
export function agreeToTerms(userId: string, arActivityConsent: boolean | undefined, cameraFeaturesConsent: boolean) {
  return apiPost<TermsStatus>('/api/me/terms', { version: TERMS_VERSION, arActivityConsent, cameraFeaturesConsent }, { expectedUserId: userId });
}

export type ServiceConsentKind = 'arActivity' | 'cameraFeatures';

export function setServiceConsent(userId: string, kind: ServiceConsentKind, enabled: boolean) {
  return apiPost<TermsStatus>('/api/me/service-consents', { kind, enabled }, { expectedUserId: userId });
}

/** Deletes the Supabase account and the backend member record. Sign out afterwards. */
export function deleteAccount() {
  return apiDelete('/api/me');
}
