import { apiGet } from '@/lib/api';
import { useProductVideos } from '@/lib/queries';
import { productVideoHref } from '@/lib/routes';

const mockUseQuery = jest.fn((options) => options);
jest.mock('@tanstack/react-query', () => ({ useQuery: (options: unknown) => mockUseQuery(options), keepPreviousData: jest.fn() }));
jest.mock('@/lib/api', () => ({ apiGet: jest.fn() }));

test('product video query uses the verified reverse API and is disabled without an ID', async () => {
  useProductVideos('product-1');
  const options = mockUseQuery.mock.calls[0][0] as { queryFn: () => Promise<unknown>; enabled: boolean };
  expect(options.enabled).toBe(true);
  await options.queryFn();
  expect(apiGet).toHaveBeenCalledWith('/api/products/product-1/videos');
  useProductVideos(undefined);
  expect((mockUseQuery.mock.calls[1][0] as { enabled: boolean }).enabled).toBe(false);
});

test('reverse links navigate to the matching video detail screen', () => {
  expect(productVideoHref('celebrity', 'c1')).toEqual({ pathname: '/celebrity-video/[id]', params: { id: 'c1' } });
  expect(productVideoHref('style', 's1')).toEqual({ pathname: '/style-look/[id]', params: { id: 's1' } });
});
