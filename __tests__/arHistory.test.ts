import { ArHistorySession, ArPaletteView, waitForArCartEvents } from '@/lib/arHistory';
import type { ColorSwatch } from '@/lib/nearbyColors';

it('joins concurrent exposure, try-on and cart writes to one impression and keeps a new free selection separate', async () => {
  const send = jest.fn(async (_path: string, _body: unknown) => ({}));
  const session = new ArHistorySession(send);
  const selection = { productId: 'p', shadeId: 's' };
  const view = new ArPaletteView(send, session.id, 'lip', 'similar', [
    { product: { id: 'p' }, shade: { id: 's' } } as ColorSwatch,
  ]);
  await Promise.all([view.exposure('p', 's').save(), session.event('try_on', selection, 'lip', view)]);
  await session.event('cart_add', selection, 'lip');
  await session.event('try_on', { ...selection }, 'lip');
  const calls = send.mock.calls;
  expect(calls.map(([p]) => p)).toEqual(['requests', 'impressions', 'events', 'events', 'events']);
  const impression = (calls[1][1] as { impressionId: string }).impressionId;
  expect(calls.slice(2).map(([, body]) => (body as { impressionId: string | null }).impressionId))
    .toEqual([impression, impression, null]);
});

it('exposes the same AR cart event ID to checkout and waits for its active write', async () => {
  let complete!: (value: unknown) => void;
  const saved = new Promise(resolve => { complete = resolve; });
  const send = jest.fn(async (_path: string, body: unknown) => (body as { eventType?: string }).eventType === 'cart_add' ? saved : {});
  const session = new ArHistorySession(send, 'owner');
  const selection = { productId: 'p', shadeId: 's' };
  const view = new ArPaletteView(send, session.id, 'lip', 'rating', [
    { product: { id: 'p' }, shade: { id: 's' } } as ColorSwatch,
  ]);
  await session.event('try_on', selection, 'lip', view);
  const cart = session.cartAdd(selection, 'lip');
  expect(cart.source?.ownerId).toBe('owner');
  cart.record();
  const waiting = jest.fn();
  const settled = waitForArCartEvents([cart.source!.eventId]).then(waiting);
  expect(waiting).not.toHaveBeenCalled();
  complete({});
  await settled;
  expect(waiting).toHaveBeenCalledTimes(1);
  expect(send).toHaveBeenLastCalledWith('events', expect.objectContaining({ eventId: cart.source!.eventId, eventType: 'cart_add' }));
});
