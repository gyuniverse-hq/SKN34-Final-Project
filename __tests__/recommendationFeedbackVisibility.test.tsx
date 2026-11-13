import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { useRecommendationFeedback } from '@/hooks/useRecommendationFeedback';
import { comparisonPost } from '@/lib/recommendationComparison';
import type { ComparisonProduct, RecommendationComparisonResult } from '@/types/recommendationComparison';

let mockAppChange: (state: string) => void;
let mockFocused = true;
jest.mock('react-native', () => ({ AppState: {
  currentState: 'active', addEventListener: jest.fn((_event, listener) => { mockAppChange = listener; return { remove: jest.fn() }; }),
} }));
jest.mock('expo-router', () => ({ useFocusEffect: (callback: () => (() => void) | undefined) => {
  const ReactModule = jest.requireActual('react');
  ReactModule.useEffect(() => mockFocused ? callback() : undefined, [callback, mockFocused]);
} }));
jest.mock('expo', () => ({ uuid: { v4: jest.fn(() => `id-${Math.random()}`) } }));
jest.mock('@/lib/api', () => ({ ApiError: class extends Error {} }));
jest.mock('@/lib/recommendationComparison', () => ({ comparisonPost: jest.fn() }));
const post = jest.mocked(comparisonPost);
const item = { candidateId: 'candidate', productId: 'p', optionId: 'o', rank: 1 } as ComparisonProduct;
const result = { history: { requestId: 'request', sessionId: 'session' }, v2: { matches: [item] } } as RecommendationComparisonResult;

test('requires continuous dwell; ignores hidden/background/blurred cards and cleans up on unmount', async () => {
  jest.useFakeTimers(); post.mockResolvedValue({});
  const intervals = jest.spyOn(globalThis, 'setInterval');
  const clearIntervalSpy = jest.spyOn(globalThis, 'clearInterval');
  let top = 200;
  function Probe() {
    const feedback = useRecommendationFeedback(result, 'member');
    React.useLayoutEffect(() => {
      // Stand-ins for native measurements; no screen exposure is inferred from mounting.
      Object.assign(feedback.viewportRef, { current: { measureInWindow: (fn: (...n: number[]) => void) => fn(0, 0, 100, 100) } });
      feedback.setCard(item, { measureInWindow: (fn: (...n: number[]) => void) => fn(0, top, 100, 100) } as never);
    });
    return null;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Probe />); });
  await act(async () => { jest.advanceTimersByTime(1000); });
  expect(post).not.toHaveBeenCalled();
  top = 0;
  await act(async () => { jest.advanceTimersByTime(400); });
  top = 200;
  await act(async () => { jest.advanceTimersByTime(200); });
  top = 0;
  await act(async () => { jest.advanceTimersByTime(400); mockAppChange('background'); jest.advanceTimersByTime(1000); });
  expect(post).not.toHaveBeenCalled();
  await act(async () => { mockAppChange('active'); jest.advanceTimersByTime(400); });
  expect(post).not.toHaveBeenCalled();
  mockFocused = false;
  await act(async () => { screen.update(<Probe />); });
  await act(async () => { jest.advanceTimersByTime(1000); });
  expect(post).not.toHaveBeenCalled();
  mockFocused = true;
  await act(async () => { screen.update(<Probe />); });
  await act(async () => { jest.advanceTimersByTime(800); });
  expect(post).toHaveBeenCalledTimes(1);
  await act(async () => { jest.advanceTimersByTime(2000); });
  expect(post).toHaveBeenCalledTimes(1);
  await act(async () => { screen.unmount(); });
  for (const interval of intervals.mock.results) expect(clearIntervalSpy).toHaveBeenCalledWith(interval.value);
  intervals.mockRestore(); clearIntervalSpy.mockRestore();
  jest.useRealTimers();
});
