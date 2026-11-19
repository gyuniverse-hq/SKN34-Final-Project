import renderer, { act } from 'react-test-renderer';
import { useArHistory } from '@/hooks/useArHistory';
import type { ColorSwatch } from '@/lib/nearbyColors';

let mockOwner = 'subscriber';
let mockServerRanking = false;
let mockRankedProducts = ['ranked'];
const mockPost = jest.fn(async (path: string, body: unknown,
  { expectedUserId }: { expectedUserId: string }) => {
  if (path.endsWith('/status')) return { enabled: true, recommendations: expectedUserId === 'subscriber', serverRanking: mockServerRanking };
  if (path.endsWith('/palette')) {
    return { ratings: [{ productId: 'rated', rating: 4.8, reviews: 200 }], preferences: [] };
  }
  if (path.endsWith('/rank')) return { requestId: (body as { requestId: string }).requestId,
    candidates: mockRankedProducts.map((productId, index) => ({
      candidateId: index === 0 ? 'server-chip' : `server-chip-${index}`, productId, shadeId: 's',
    })) };
  return { ok: true };
});
jest.mock('@/lib/auth', () => ({ useAuth: () => ({ ready: true, user: mockOwner ? { id: mockOwner } : null }) }));
jest.mock('@/lib/api', () => ({ apiPost: (...args: Parameters<typeof mockPost>) => mockPost(...args) }));
beforeEach(() => { mockOwner = 'subscriber'; mockServerRanking = false; mockRankedProducts = ['ranked']; mockPost.mockClear(); });

it('presents an enrolled member with rated chips on entry, attributes only those chips, and clears them on account change', async () => {
  const items = ['ordinary', 'rated'].map(id => ({
    product: { id, texture: 'matte' }, shade: { id: 's', hex: '#C26471' },
  } as ColorSwatch));
  let result!: ReturnType<typeof useArHistory>;
  function Screen() {
    result = useArHistory({ active: true, zone: 'lip', direction: 'similar', nearby: null, catalog: items,
      visibleItems: items, paletteShown: true, careOpen: false });
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Screen />); });
  expect(result.recommendedItems?.size).toBe(1);
  expect(result.ordered).toEqual([items[1], items[0]]);
  expect(mockPost).toHaveBeenCalledWith('/api/me/ar-history/requests',
    expect.objectContaining({ direction: 'rating', candidates: [expect.objectContaining({ productId: 'rated' })] }),
    expect.objectContaining({ expectedUserId: 'subscriber' }));
  await act(async () => { result.visible?.(items[0]); result.visible?.(items[1]); });
  expect(mockPost.mock.calls.filter(([path]) => path.endsWith('/impressions'))).toHaveLength(1);
  mockOwner = 'ordinary-member';
  await act(async () => { screen.update(<Screen />); });
  expect(result.recommendedItems).toBeUndefined();
  expect(result.ordered).toEqual(items);
  expect(result.view).toBeNull();
  await act(async () => { screen.unmount(); });
});

it('moves the server-selected chip first and sends its server candidate ID for the impression', async () => {
  mockServerRanking = true;
  const items = ['rated', 'ranked'].map(id => ({
    product: { id, texture: 'matte' }, shade: { id: 's', hex: '#C26471' },
  } as ColorSwatch));
  let result!: ReturnType<typeof useArHistory>;
  function Screen() {
    result = useArHistory({ active: true, zone: 'lip', direction: 'similar', nearby: null, catalog: items,
      visibleItems: items, paletteShown: true, careOpen: false });
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Screen />); });
  expect(result.recommendedItems?.size).toBe(1);
  expect(result.ordered).toEqual([items[1], items[0]]);
  await act(async () => { result.visible?.(items[1]); });
  expect(mockPost).toHaveBeenCalledWith('/api/me/ar-history/impressions',
    expect.objectContaining({ candidateId: 'server-chip', displayedPosition: 1 }),
    expect.objectContaining({ expectedUserId: 'subscriber' }));
  expect(mockPost.mock.calls.some(([path]) => path.endsWith('/requests'))).toBe(false);
  expect(mockPost.mock.calls.some(([path]) => path.endsWith('/palette'))).toBe(false);
  await act(async () => { screen.unmount(); });
});

it.each([
  { selected: 'picked', start: ['second', 'picked', 'first', 'third', 'after'], position: 3 },
  { selected: 'first', start: ['third', 'first', 'second', 'picked', 'after'], position: 2 },
])('keeps the first recommendations around $selected after nearby exploration', async ({ selected, start, position }) => {
  mockServerRanking = true;
  mockRankedProducts = ['first', 'second', 'third'];
  const items = ['before', 'first', 'picked', 'after', 'second', 'third', 'a', 'b', 'c'].map(id => ({
    product: { id, texture: 'matte' }, shade: { id: 's', hex: '#C26471' },
  } as ColorSwatch));
  const anchor = items.find(item => item.product.id === selected)!;
  const nearbyItems = [anchor];
  let result!: ReturnType<typeof useArHistory>;
  function Screen({ nearby = false }: { nearby?: boolean }) {
    result = useArHistory({ active: true, zone: 'lip', direction: 'similar', nearby: nearby ? nearbyItems : null,
      catalog: items, visibleItems: items, paletteShown: true, careOpen: false });
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Screen />); });
  try {
    const first = result.recommendedItems;
    expect(first?.size).toBe(3);
    await act(async () => { result.beginNearby(); screen.update(<Screen nearby />); });
    expect(result.ordered).toBe(nearbyItems);
    expect(result.recommendedItems).toBeUndefined();
    await act(async () => { result.returnFromNearby(anchor); screen.update(<Screen />); });
    expect(result.ordered.slice(0, start.length).map(item => item.product.id)).toEqual(start);
    expect(new Set(result.ordered).size).toBe(items.length);
    expect(result.recommendedItems).toEqual(first);
    expect(mockPost.mock.calls.filter(([path]) => path.endsWith('/rank'))).toHaveLength(1);
    await act(async () => { result.visible?.(items[1]); });
    expect(mockPost).toHaveBeenCalledWith('/api/me/ar-history/impressions',
      expect.objectContaining({ candidateId: 'server-chip', displayedPosition: position }),
      expect.objectContaining({ expectedUserId: 'subscriber' }));
  } finally {
    await act(async () => { screen.unmount(); });
  }
});

it('keeps the normal palette for a guest and sends no recommendation or history requests', async () => {
  mockOwner = '';
  const items = ['a', 'b', 'c', 'rated'].map(id => ({
    product: { id, texture: 'matte' }, shade: { id: 's', hex: '#C26471' },
  } as ColorSwatch));
  let result!: ReturnType<typeof useArHistory>;
  function Screen() {
    result = useArHistory({ active: true, zone: 'lip', direction: 'similar', nearby: null, catalog: items,
      visibleItems: items, paletteShown: true, careOpen: false });
    return null;
  }
  let screen: renderer.ReactTestRenderer | undefined;
  try {
    await act(async () => { screen = renderer.create(<Screen />); });
    expect(result.recommendedItems).toBeUndefined();
    expect(result.ordered).toBe(items);
    expect(result.history).toBeNull();
    expect(result.visible).toBeUndefined();
    expect(mockPost).not.toHaveBeenCalled();
  } finally {
    await act(async () => { screen?.unmount(); });
  }
});
