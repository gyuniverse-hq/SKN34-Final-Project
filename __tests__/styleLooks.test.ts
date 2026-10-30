import { useQuery } from '@tanstack/react-query';
import { ApiError, apiGet } from '@/lib/api';
import { useStyleLooks } from '@/lib/queries';

jest.mock('@tanstack/react-query', () => ({ useQuery: jest.fn() }));
jest.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number;
    constructor(message: string, mockStatus: number) { super(message); this.status = mockStatus; }
  }
  return { ApiError, apiGet: jest.fn() };
});

const mockedUseQuery = jest.mocked(useQuery);
const mockedApiGet = jest.mocked(apiGet);

function queryFn() {
  useStyleLooks();
  return (mockedUseQuery.mock.calls.at(-1)?.[0] as unknown as { queryFn: () => Promise<{ looks: { id: string }[] }> }).queryFn;
}

beforeEach(() => jest.clearAllMocks());

test('uses the server style looks when available', async () => {
  mockedApiGet.mockResolvedValueOnce({ looks: [{ id: 'server-look' }] });
  await expect(queryFn()()).resolves.toEqual({ looks: [{ id: 'server-look' }] });
});

test('uses the bundled style looks when the development server has no endpoint', async () => {
  mockedApiGet.mockRejectedValueOnce(new ApiError('Not found', 404));
  const result = await queryFn()();
  expect(result.looks).toHaveLength(73);
});

test('does not hide other server errors', async () => {
  mockedApiGet.mockRejectedValueOnce(new ApiError('Server error', 500));
  await expect(queryFn()()).rejects.toMatchObject({ status: 500 });
});

test('bundled development looks match the server catalog', () => {
  const server = require('@/backend/api/app/catalog_data/style_looks.json');
  const bundled = require('@/lib/devCatalog/styleLooks.json');
  expect(bundled).toEqual(server);
});
