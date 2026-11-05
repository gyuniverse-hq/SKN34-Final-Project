import type { NiaAcneResult, NiaPhotoReport, NiaStatus } from '@/types/nia';

type AcneReport = Pick<NiaPhotoReport, 'acne'> & {
  ml_input?: Pick<NiaPhotoReport['ml_input'], 'acne'>;
};

export type NiaAcneView =
  | { status: 'predicted' | 'failed'; result: NiaAcneResult }
  | { status: 'ready' | 'unavailable' | 'outdated' | 'unsupported' };

export function getNiaAcneView(status?: Pick<NiaStatus, 'acne'>, report?: AcneReport | null): NiaAcneView {
  const result = report?.acne ?? report?.ml_input?.acne;
  if (result) return { status: result.status, result };
  if (!report) return { status: status?.acne?.present ? 'ready' : 'unavailable' };
  // A v1 result predates the independently configured acne model. It is not evidence
  // that the current service lacks support, and cannot be exported as a fresh result.
  return { status: status?.acne?.present ? 'outdated' : 'unsupported' };
}
