import { uuid } from 'expo';
import { apiPost, ApiError } from '@/lib/api';
import type { CartRecommendations } from '@/types';

const PATH = '/api/me/cart-recommendations';
type Zone = 'lip' | 'blush';
type ArRanks = Partial<Record<Zone, string>>;
let recentArRanks: { owner: string; ids: ArRanks } | undefined;

export function rememberCartArRank(owner: string, zone: Zone, requestId: string) {
  if (recentArRanks?.owner !== owner) recentArRanks = { owner, ids: {} };
  recentArRanks.ids[zone] = requestId;
}

export function clearCartArRanks(owner?: string) {
  if (!owner || recentArRanks?.owner === owner) recentArRanks = undefined;
}

async function post<T>(owner: string, suffix: string, body: unknown) {
  const send = () => apiPost<T>(PATH + suffix, body, { expectedUserId: owner, timeoutMs: 3000 });
  try {
    return await send();
  } catch (error) {
    if (!(error instanceof ApiError) || (error.code !== 'network' && error.status < 500)) throw error;
    return await send();
  }
}

export function requestCartRecommendations(owner: string, cartVisitId: string, items: { productId: string; shadeId?: string }[]) {
  if (recentArRanks?.owner !== owner) clearCartArRanks();
  return post<CartRecommendations | null>(owner, '', {
    cartVisitId, items, arRequestIds: recentArRanks?.ids,
  });
}

type Impression = {
  impressionId: string;
  canonical?: string;
  pending?: Promise<string>;
};

export class CartRecommendationFeedback {
  private impressions = new Map<string, Impression>();

  constructor(readonly owner: string, readonly cartVisitId: string) {}

  impression(candidateId: string, interaction = false): Promise<string> {
    let entry = this.impressions.get(candidateId);
    if (!entry) {
      entry = { impressionId: uuid.v4() };
      this.impressions.set(candidateId, entry);
    }
    if (entry.canonical) return Promise.resolve(entry.canonical);
    if (entry.pending) return entry.pending;
    const current = entry;
    const body = {
      cartVisitId: this.cartVisitId, candidateId, impressionId: current.impressionId,
      visibilityPolicyVersion: interaction ? 'direct-interaction-v1' : 'half-visible-500ms-v1',
    };
    current.pending = post<{ impressionId: string }>(this.owner, '/impressions', body)
      .then(({ impressionId }) => current.canonical = impressionId)
      .finally(() => { current.pending = undefined; });
    return current.pending;
  }

  async add(candidateId: string, eventId: string) {
    const impressionId = await this.impression(candidateId, true);
    await post(this.owner, '/cart-adds', { eventId, impressionId });
  }
}
