import { uuid } from 'expo';
import { ApiError } from './api';
import { comparisonPost } from './recommendationComparison';
import type { ComparisonProduct } from '@/types/recommendationComparison';

type FeedbackAction = 'product_view' | 'cart_add' | 'outbound_click';
type Impression = {
  impressionId: string; candidateId: string; viewInstanceId: string; displayedPosition: number;
  occurredAt: string; surface: 'v2_comparison';
  visibilityPolicyVersion: 'half-visible-500ms-v1' | 'direct-interaction-v1';
};
type Entry = { body: Impression; sent: boolean; pending?: Promise<void> };

async function send(path: string, body: unknown, owner: string) {
  try { await comparisonPost(path, body, owner); }
  catch (error) {
    // One bounded retry, retaining the original UUID and timestamp (including a lost response).
    if (!(error instanceof ApiError) || (error.code !== 'network' && error.status < 500)) throw error;
    await comparisonPost(path, body, owner);
  }
}

/** Memory-only attribution: no analytics tokens or analysis data in storage/deep links. */
export class RecommendationFeedback {
  readonly viewId = uuid.v4();
  private entries = new Map<string, Entry>();
  constructor(readonly owner: string, readonly sessionId: string) {}

  impression(item: ComparisonProduct, interaction = false): Promise<void> {
    if (!item.candidateId) return Promise.resolve();
    let entry = this.entries.get(item.candidateId);
    if (!entry) {
      entry = { sent: false, body: { impressionId: uuid.v4(), candidateId: item.candidateId,
        viewInstanceId: this.viewId, displayedPosition: item.rank, occurredAt: new Date().toISOString(),
        surface: 'v2_comparison', visibilityPolicyVersion: interaction ? 'direct-interaction-v1' : 'half-visible-500ms-v1' } };
      this.entries.set(item.candidateId, entry);
    }
    if (entry.sent) return Promise.resolve();
    if (!entry.pending) {
      const current = entry;
      current.pending = send('/impressions', current.body, this.owner).then(() => { current.sent = true; })
        .finally(() => { current.pending = undefined; });
    }
    return entry.pending!;
  }

  async event(item: ComparisonProduct, eventType: FeedbackAction) {
    if (!item.candidateId) return;
    const occurredAt = new Date().toISOString();
    const eventId = uuid.v4();
    // A deliberate click proves exposure even if it occurs before the 500 ms dwell threshold.
    await this.impression(item, true);
    await send('/events', { eventId, impressionId: this.entries.get(item.candidateId)!.body.impressionId,
      sessionId: this.sessionId, productId: item.productId, optionId: eventType === 'cart_add' ? null : item.optionId,
      eventType, occurredAt, surface: 'product_detail' }, this.owner);
  }
}

const links = new Map<string, { feedback: RecommendationFeedback; item: ComparisonProduct }>();
export function recommendationLink(feedback: RecommendationFeedback, item: ComparisonProduct): string {
  // Only recent navigation contexts are kept, and another account cannot reuse them.
  for (const [id, context] of links) if (context.feedback.owner !== feedback.owner) links.delete(id);
  if (links.size >= 20) links.delete(links.keys().next().value!);
  const id = uuid.v4();
  links.set(id, { feedback, item });
  return id;
}
export function recommendationContext(id: string | undefined, owner: string | undefined, productId: string | undefined) {
  const context = id ? links.get(id) : undefined;
  return context?.feedback.owner === owner && context?.item.productId === productId ? context : undefined;
}

export type Rect = { x: number; y: number; width: number; height: number };
export function halfVisible(card: Rect, viewport: Rect): boolean {
  const width = Math.max(0, Math.min(card.x + card.width, viewport.x + viewport.width) - Math.max(card.x, viewport.x));
  const height = Math.max(0, Math.min(card.y + card.height, viewport.y + viewport.height) - Math.max(card.y, viewport.y));
  return card.width > 0 && card.height > 0 && width * height >= card.width * card.height * 0.5;
}
