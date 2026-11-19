import { ArHistorySession, ArPaletteView } from '@/lib/arHistory';
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
