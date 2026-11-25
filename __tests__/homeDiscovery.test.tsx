import type { ReactElement, ReactNode } from 'react';
import { FlatList, SectionList } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import HomeScreen from '@/app/(tabs)/index';
import RankingsScreen from '@/app/rankings';
import SearchScreen from '@/app/search';
import { HomeProductSection } from '@/components/home/HomeCatalog';
import { Chip } from '@/components/ui/Chip';
import { InlineState } from '@/components/ui/InlineState';
import type { Product, ProductCategory, ProductDiscoveryOrder } from '@/types';

jest.setTimeout(20000);

function product(id: string, category: ProductCategory): Product {
  return {
    id,
    category,
    brand: 'Brand',
    name: id,
    nameKo: id,
    makeupZone: null,
    texture: null,
    priceKRW: 18000,
    volume: '',
    shades: [],
    description: '',
    keyIngredients: [],
    tags: [],
    imageUrl: '',
    searchKeyword: id,
  };
}

const mockProducts = [product('first', 'lip'), product('second', 'lip'), product('cream', 'skincare'), product('other', 'lip')];
const mockDefaultOrder = { hot: ['cream'], makeup: ['second', 'first'], skincare: ['cream'], newArrivals: ['second', 'cream', 'first'] };
const mockPush = jest.fn();
const mockPreview = jest.fn();
const mockRefetchProducts = jest.fn();
const mockRefetchOrder = jest.fn();
let mockParams: { collection?: string };
let mockOrder: ProductDiscoveryOrder;
let mockStatus: 'pending' | 'error' | 'success';

jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  useLocalSearchParams: () => mockParams,
  useRouter: () => ({ push: mockPush }),
}));
jest.mock('@/lib/queries', () => ({
  useProducts: ({ category }: { category?: string } = {}) => ({
    data: category ? mockProducts.filter(product => product.category === category) : mockProducts,
    refetch: mockRefetchProducts,
  }),
  useProductDiscoveryOrder: (preview = false, enabled = true) => {
    mockPreview(preview, enabled);
    return {
      data: mockStatus === 'success' ? mockOrder : undefined,
      isPending: mockStatus === 'pending',
      isError: mockStatus === 'error',
      error: mockStatus === 'error' ? new Error('Offline') : null,
      refetch: mockRefetchOrder,
    };
  },
  useStyleLooks: () => ({ data: [] }),
}));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: ReactNode }) => children }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('@/components/home/HomeCatalog', () => ({ HomeCategories: () => null, HomeProductSection: () => null }));
jest.mock('@/components/home/HomeSearch', () => ({ HomeSearch: ({ children }: { children: ReactNode }) => children }));
jest.mock('@/components/celeb/KStyleCollection', () => ({ KStyleCollection: () => null }));
jest.mock('@/components/shop/ShopHeaderActions', () => ({ ShopHeaderActions: () => null }));
jest.mock('@/components/shop/ProductCard', () => ({ ProductCard: () => null }));
jest.mock('@/components/skin/SkinMatchSection', () => ({ SkinMatchSection: () => null }));
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: () => null }));
jest.mock('@/components/ui/StateViews', () => ({ EmptyState: () => null, ErrorState: () => null, LoadingState: () => null }));
jest.mock('@/hooks/useSkinMatchedProducts', () => ({ useSkinMatchedProducts: () => ({ concerns: [], products: {} }) }));

let view: ReactTestRenderer | undefined;

async function show(screen: ReactElement) {
  await act(async () => {
    if (view) view.update(screen);
    else view = create(screen);
  });
  return view!.root;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = {};
  mockStatus = 'success';
  mockOrder = mockDefaultOrder;
});

afterEach(async () => {
  await act(async () => { view?.unmount(); });
  view = undefined;
});

it('uses the server order in home previews and charts, with working navigation', async () => {
  const home = await show(<HomeScreen />);
  const chart = home.findAllByType(HomeProductSection).find(item => item.props.title === 'discovery.makeupRanking')!;
  expect(mockPreview).toHaveBeenCalledWith(true, true);
  expect(chart.props.products).toEqual([mockProducts[1], mockProducts[0]]);
  chart.props.onPress(chart.props.products[0]);
  chart.props.onViewAll();
  expect(mockPush).toHaveBeenNthCalledWith(1, { pathname: '/product/[id]', params: { id: 'second' } });
  expect(mockPush).toHaveBeenNthCalledWith(2, { pathname: '/rankings', params: { category: 'makeup' } });

  const rankings = await show(<RankingsScreen />);
  expect(mockPreview).toHaveBeenLastCalledWith(false, true);
  const sections = rankings.findByType(SectionList).props.sections;
  expect(sections[0].data).toEqual([{ product: mockProducts[1], rank: 1 }, { product: mockProducts[0], rank: 2 }]);
  expect(sections[1].data).toEqual([{ product: mockProducts[3] }]);
});

it('preserves the arrival order after selecting a search category', async () => {
  mockParams = { collection: 'new' };
  const search = await show(<SearchScreen />);
  const list = () => search.findByType(FlatList).props.data;
  expect(list()).toEqual([mockProducts[1], mockProducts[2], mockProducts[0]]);

  const lip = search.findAllByType(Chip).find(item => item.props.label === 'shop.cat.lip')!;
  await act(async () => { lip.props.onPress(); });
  expect(list()).toEqual([mockProducts[1], mockProducts[0]]);
});

it('shows loading, retries failed ordering, and handles an empty chart', async () => {
  mockStatus = 'pending';
  const rankings = await show(<RankingsScreen />);
  const status = () => rankings.findByType(InlineState).props;
  expect(status().status).toBe('loading');

  mockStatus = 'error';
  await show(<RankingsScreen />);
  expect(status().status).toBe('error');
  status().onRetry();
  expect(mockRefetchProducts).toHaveBeenCalledTimes(1);
  expect(mockRefetchOrder).toHaveBeenCalledTimes(1);

  mockStatus = 'success';
  mockOrder = { ...mockDefaultOrder, makeup: [] };
  await show(<RankingsScreen />);
  expect(status().status).toBe('empty');
  expect(rankings.findByType(SectionList).props.sections[1].data).toHaveLength(3);
});
