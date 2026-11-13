import { useEffect } from 'react';
import renderer, { act } from 'react-test-renderer';
import { useNearbyExploration } from '@/hooks/useNearbyExploration';
import type { ColorSwatch } from '@/lib/nearbyColors';
import type { MakeupZone, Product, Texture } from '@/types';

const product = (id: string, hex: string, zone: MakeupZone = 'lip'): Product => ({
  id, brand: 'Test', name: id, nameKo: id, category: 'lip', makeupZone: zone, texture: 'matte',
  priceKRW: 0, volume: '', description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
  shades: [{ id: 'shade', name: 'Color', hex }],
});
const source = product('source', '#BE636A');
const candidate = product('candidate', '#C2636B');
const cheek = product('cheek', '#BE636A', 'blush');
const otherCheek = product('other-cheek', '#C2636B', 'blush');
const catalog = [source, candidate, cheek, otherCheek];
const swatch = (p: Product): ColorSwatch => ({ product: p, shade: p.shades[0] });
let latest: ReturnType<typeof useNearbyExploration>;
interface Props { zone?: MakeupZone; selected?: ColorSwatch; scope?: string; texture?: Texture | null; products?: Product[] }
function Harness({ zone = 'lip', selected, scope = '', texture = null, products = catalog }: Props) {
  const state = useNearbyExploration(products, zone, selected, texture, scope);
  useEffect(() => { latest = state; }, [state]);
  return null;
}

it('pins the source through preview/filter changes, explicitly rebases and goes back, then leaves without changing selection', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Harness selected={swatch(source)} />); });
  await act(async () => { latest.enter(); });
  expect(latest.anchor?.product.id).toBe('source');
  expect(latest.groups.similar.map((s) => s.product.id)).toEqual(['candidate']);
  await act(async () => { screen.update(<Harness selected={swatch(candidate)} />); });
  expect(latest.anchor?.product.id).toBe('source');
  expect(latest.canRebase).toBe(true);
  await act(async () => { screen.update(<Harness selected={swatch(candidate)} texture="glossy" />); });
  expect(latest.active).toBe(true);
  expect(latest.groups.similar).toEqual([]);
  await act(async () => { latest.rebase(); });
  expect(latest.anchor?.product.id).toBe('candidate');
  await act(async () => { latest.back(); });
  expect(latest.anchor?.product.id).toBe('source');
  expect(latest.canGoBack).toBe(false);
  await act(async () => { latest.leave(); });
  expect(latest.active).toBe(false);
  await act(async () => { latest.enter(); });
  expect(latest.anchor?.product.id).toBe('candidate');
  await act(async () => { screen.unmount(); });
});

it('resets on category, new route/recipe and removal of the reference; does not revive a stale session', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Harness selected={swatch(source)} />); });
  await act(async () => { latest.enter(); latest.setDirection('darker'); });
  await act(async () => { screen.update(<Harness zone="blush" selected={swatch(cheek)} />); });
  expect(latest.active).toBe(false);
  await act(async () => { latest.enter(); });
  expect(latest.direction).toBe('similar');
  expect(latest.groups.similar.map((s) => s.product.id)).toEqual(['other-cheek']);
  await act(async () => { screen.update(<Harness selected={swatch(source)} />); });
  expect(latest.active).toBe(false);
  await act(async () => { latest.enter(); });
  await act(async () => { screen.update(<Harness selected={swatch(source)} scope="new-route" />); });
  expect(latest.active).toBe(false);
  await act(async () => { latest.enter(); });
  await act(async () => { screen.update(<Harness selected={swatch(candidate)} scope="new-route" products={[candidate]} />); });
  expect(latest.active).toBe(false);
  await act(async () => { screen.unmount(); });
});

it('requires an eligible selected shade and does not offer other makeup zones', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Harness />); });
  expect(latest.canEnter).toBe(false);
  await act(async () => { latest.enter(); });
  expect(latest.active).toBe(false);
  await act(async () => { screen.update(<Harness zone="eyeshadow" selected={swatch(source)} />); });
  expect(latest.supported).toBe(false);
  expect(latest.canEnter).toBe(false);
  await act(async () => { screen.unmount(); });
});
