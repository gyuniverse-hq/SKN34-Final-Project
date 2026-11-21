import type { CartItem } from '@/types';

export const CART_SOURCE_FIELDS = ['arCartSources', 'skincareCartSources'] as const;
type CartSourceField = typeof CART_SOURCE_FIELDS[number];
const pendingEvents = new Map<string, Promise<unknown>>();

export function cartEventIds(item: CartItem, field: CartSourceField, ownerId: string) {
  return [...new Set((item[field] ?? []).slice(0, item.quantity)
    .flatMap(source => source?.ownerId === ownerId ? [source.eventId] : []))];
}

export function trackCartEvent(id: string, event: Promise<unknown>) {
  pendingEvents.set(id, event);
  const clear = () => { if (pendingEvents.get(id) === event) pendingEvents.delete(id); };
  void event.then(clear, clear);
}

export async function waitForCartEvents(ids: readonly string[]) {
  const pending = ids.flatMap(id => {
    const event = pendingEvents.get(id);
    return event ? [event] : [];
  });
  if (!pending.length) return;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      Promise.allSettled(pending),
      new Promise(resolve => { timeout = setTimeout(resolve, 750); }),
    ]);
  } finally {
    clearTimeout(timeout);
  }
}
