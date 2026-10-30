import { useQuery } from '@tanstack/react-query';
import { ApiError, apiGet } from '@/lib/api';
import { useCelebrityVideos } from '@/lib/queries';

jest.mock('@tanstack/react-query', () => ({ useQuery: jest.fn() }));
jest.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number;
    constructor(message: string, mockStatus: number) { super(message); this.status = mockStatus; }
  }
  return { ApiError, apiGet: jest.fn() };
});

const query = jest.mocked(useQuery);
const get = jest.mocked(apiGet);
function queryFn() {
  useCelebrityVideos();
  return (query.mock.calls.at(-1)?.[0] as unknown as { queryFn: () => Promise<{ videos: { id: string }[] }> }).queryFn;
}

beforeEach(() => jest.clearAllMocks());

test('uses server videos when available', async () => {
  get.mockResolvedValueOnce({ videos: [{ id: 'remote' }] });
  await expect(queryFn()()).resolves.toEqual({ videos: [{ id: 'remote' }] });
});

test('development fallback contains all 34 videos', async () => {
  get.mockRejectedValueOnce(new ApiError('Not found', 404));
  await expect(queryFn()()).resolves.toMatchObject({ videos: expect.arrayContaining([expect.objectContaining({ id: 'Atr1JHUDBIg' })]) });
  get.mockRejectedValueOnce(new ApiError('Not found', 404));
  expect((await queryFn()()).videos).toHaveLength(34);
});

test('does not hide other server errors', async () => {
  get.mockRejectedValueOnce(new ApiError('Server error', 500));
  await expect(queryFn()()).rejects.toMatchObject({ status: 500 });
});

test('server and development copies match', () => {
  expect(require('@/lib/devCatalog/celebrityVideos.json')).toEqual(require('@/backend/api/app/catalog_data/celebrity_videos.json'));
});
