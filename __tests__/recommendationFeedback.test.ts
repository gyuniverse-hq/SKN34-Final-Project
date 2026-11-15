import { ApiError } from '@/lib/api';
import { comparisonPost } from '@/lib/recommendationComparison';
import { halfVisible, recommendationContext, RecommendationFeedback, recommendationLink } from '@/lib/recommendationFeedback';
import type { ComparisonProduct } from '@/types/recommendationComparison';

jest.mock('expo', () => ({ ...jest.requireActual('expo'), uuid: { v4: jest.fn(() => `id-${Math.random()}`) } }));
jest.mock('@/lib/recommendationComparison', () => ({ comparisonPost: jest.fn() }));
const post = jest.mocked(comparisonPost);
const item = { candidateId: 'candidate', productId: 'p', optionId: 'o', rank: 1 } as ComparisonProduct;
beforeEach(() => { post.mockReset(); post.mockResolvedValue({}); });

test('clips both axes and rejects offscreen, less than half, and zero-area cards', () => {
  const viewport = { x: 0, y: 0, width: 100, height: 100 };
  expect(halfVisible({ ...viewport, y: 50 }, viewport)).toBe(true);
  expect(halfVisible({ ...viewport, y: 51 }, viewport)).toBe(false);
  expect(halfVisible({ ...viewport, x: 60 }, viewport)).toBe(false);
  expect(halfVisible({ ...viewport, y: -101 }, viewport)).toBe(false);
  expect(halfVisible({ ...viewport, height: 0 }, viewport)).toBe(false);
});

test('creation is not exposure and concurrent/repeated exposure posts once', async () => {
  const feedback = new RecommendationFeedback('owner', 'session');
  expect(post).not.toHaveBeenCalled();
  await Promise.all([feedback.impression(item), feedback.impression(item)]);
  await feedback.impression(item);
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith('/impressions', expect.objectContaining({
    candidateId: 'candidate', visibilityPolicyVersion: 'half-visible-500ms-v1', displayedPosition: 1,
  }), 'owner');
});

test('a lost response retries with identical payload; event waits for impression acknowledgement', async () => {
  post.mockRejectedValueOnce(new ApiError('Network error', 0, 'network'));
  const feedback = new RecommendationFeedback('owner', 'session');
  await feedback.event(item, 'product_view');
  expect(post.mock.calls.map(call => call[0])).toEqual(['/impressions', '/impressions', '/events']);
  expect(post.mock.calls[0][1]).toEqual(post.mock.calls[1][1]);
  expect(post.mock.calls[0][1]).toEqual(expect.objectContaining({ visibilityPolicyVersion: 'direct-interaction-v1' }));
  const impression = post.mock.calls[0][1] as { impressionId: string };
  expect(post.mock.calls[2][1]).toEqual(expect.objectContaining({ impressionId: impression.impressionId,
    productId: 'p', optionId: 'o', sessionId: 'session', eventType: 'product_view' }));
});

test('failed/foreign impressions never create events and use the same ID on a later retry', async () => {
  post.mockRejectedValueOnce(new ApiError('Not found', 404, 'candidate_not_found'));
  const feedback = new RecommendationFeedback('owner', 'session');
  await expect(feedback.event(item, 'cart_add')).rejects.toThrow('Not found');
  expect(post).toHaveBeenCalledTimes(1);
  await feedback.event(item, 'cart_add');
  expect(post.mock.calls[1][1]).toEqual(post.mock.calls[0][1]);
  expect(post.mock.calls[2][1]).toEqual(expect.objectContaining({ eventType: 'cart_add', optionId: null }));
});

test('opaque navigation context requires both its owner and matching product', () => {
  const feedback = new RecommendationFeedback('member-a', 'session');
  const link = recommendationLink(feedback, item);
  expect(recommendationContext(link, 'member-a', 'p')?.item).toBe(item);
  expect(recommendationContext(link, 'member-b', 'p')).toBeUndefined();
  expect(recommendationContext(link, 'member-a', 'other')).toBeUndefined();
  expect(recommendationContext('unknown', 'member-a', 'p')).toBeUndefined();
  recommendationLink(new RecommendationFeedback('member-b', 'other'), item);
  expect(recommendationContext(link, 'member-a', 'p')).toBeUndefined();
});
