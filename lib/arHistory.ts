import { uuid } from 'expo';
import { apiPost, ApiError } from './api';
import { cartEventIds, trackCartEvent } from './cartAttribution';
import type { ColorSwatch, NearbyDirection } from './nearbyColors';
import type { PickStrategy } from './arPalettePicks';
import type { CartItem, MakeupZone } from '@/types';

type ShadeKey = { productId: string; shadeId: string };
type PaletteCandidate = ShadeKey & { candidateId: string };
export type RankedArPalette = { requestId: string; candidates: PaletteCandidate[] };
type Sender = (resource: string, payload: unknown) => Promise<unknown>;
export function arCartEventIds(item: CartItem, ownerId: string) {
  return cartEventIds(item, 'arCartSources', ownerId);
}

export { waitForCartEvents as waitForArCartEvents } from './cartAttribution';

export async function postArHistory(owner: string, path: string, body: unknown) {
  const send = () => apiPost('/api/me/ar-history/' + path, body, { expectedUserId: owner, timeoutMs: 5000 });
  try { return await send(); } catch (error) {
    if (!(error instanceof ApiError) || (error.code !== 'network' && error.status < 500)) throw error;
    return send();
  }
}

// Retry a failed dependency on a later interaction, coalescing concurrent writes.
function once(write: () => Promise<unknown>) {
  let pending: Promise<unknown> | undefined;
  return () => pending ??= write().catch(error => { pending = undefined; throw error; });
}

export class ArPaletteView {
  private candidates = new Map<string, { candidateId: string; position: number }>();
  private seen = new Map<string, { id: string; save: () => Promise<unknown> }>();
  readonly register: () => Promise<unknown>;
  private readonly viewInstanceId = uuid.v4();

  constructor(private send: Sender, sessionId: string, makeupZone: MakeupZone, direction: NearbyDirection | PickStrategy, items: readonly ColorSwatch[], ranked?: RankedArPalette, displayOrder?: readonly ColorSwatch[]) {
    const position = (productId: string, shadeId: string, index: number) => displayOrder
      ? displayOrder.findIndex(({ product, shade }) => product.id === productId && shade.id === shadeId) + 1
      : index + 1;
    if (ranked) {
      ranked.candidates.forEach(({ productId, shadeId, candidateId }, i) => {
        if (items.some(item => item.product.id === productId && item.shade.id === shadeId)) {
          this.candidates.set(JSON.stringify([productId, shadeId]), { candidateId, position: position(productId, shadeId, i) });
        }
      });
      this.register = async () => {};
      return;
    }
    const candidates = items.map(({ product, shade }, i) => {
      const candidateId = uuid.v4();
      this.candidates.set(JSON.stringify([product.id, shade.id]), { candidateId, position: position(product.id, shade.id, i) });
      return { candidateId, productId: product.id, shadeId: shade.id };
    });
    const body = { requestId: uuid.v4(), sessionId, makeupZone, direction, candidates };
    this.register = once(() => send('requests', body));
  }

  exposure(productId: string, shadeId: string, interaction = false) {
    const candidate = this.candidates.get(JSON.stringify([productId, shadeId]));
    if (!candidate) throw new Error('Missing AR palette candidate');
    let entry = this.seen.get(candidate.candidateId);
    if (!entry) {
      const id = uuid.v4();
      const body = { impressionId: id, candidateId: candidate.candidateId, viewInstanceId: this.viewInstanceId,
        displayedPosition: candidate.position, occurredAt: new Date().toISOString(),
        visibilityPolicyVersion: interaction ? 'direct-interaction-v1' : 'arc-inner-500ms-v1' };
      entry = { id, save: once(async () => { await this.register(); return this.send('impressions', body); }) };
      this.seen.set(candidate.candidateId, entry);
    }
    return entry;
  }

  contains(productId: string, shadeId: string) {
    return this.candidates.has(JSON.stringify([productId, shadeId]));
  }
}

export class ArHistorySession {
  readonly id = uuid.v4();
  // The exact store selection object dies when it is removed/replaced, even by a different AR surface.
  private attribution = new WeakMap<ShadeKey, ArPaletteView>();
  constructor(readonly send: Sender, private readonly ownerId?: string) {}

  private prepare(type: 'try_on' | 'cart_add', selection: ShadeKey, makeupZone: MakeupZone, view?: ArPaletteView) {
    if (type === 'try_on' && view) this.attribution.set(selection, view);
    const origin = type === 'try_on' ? view : this.attribution.get(selection);
    const impression = origin?.exposure(selection.productId, selection.shadeId, true);
    const body = { eventId: uuid.v4(), sessionId: this.id, eventType: type, makeupZone,
      productId: selection.productId, shadeId: selection.shadeId, impressionId: impression?.id ?? null,
      occurredAt: new Date().toISOString() };
    return {
      eventId: body.eventId,
      impressionId: body.impressionId,
      save: once(async () => {
        if (impression) await impression.save();
        return this.send('events', body);
      }),
    };
  }

  async event(type: 'try_on' | 'cart_add', selection: ShadeKey, makeupZone: MakeupZone, view?: ArPaletteView) {
    await this.prepare(type, selection, makeupZone, view).save();
  }

  cartAdd(selection: ShadeKey, makeupZone: MakeupZone) {
    const { eventId, impressionId, save } = this.prepare('cart_add', selection, makeupZone);
    const source = this.ownerId && impressionId ? { ownerId: this.ownerId, eventId } : undefined;
    return {
      source,
      record: () => {
        const pending = save().catch(noteArFailure);
        if (source) trackCartEvent(eventId, pending);
      },
    };
  }
}

// Telemetry is best effort and never blocks makeup or shopping.
export function noteArFailure(error: unknown) {
  if (__DEV__) console.warn('AR history write unavailable', error instanceof ApiError ? error.code : 'unavailable');
}
