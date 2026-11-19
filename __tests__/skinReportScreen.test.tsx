import React from 'react';
import { StyleSheet, Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import SkinRecommendationsScreen from '@/app/skin-recommendations';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import { recommendationContext } from '@/lib/recommendationFeedback';
import { apiPost } from '@/lib/api';

const mockPush = jest.fn();
jest.mock('@/lib/api', () => ({ apiPost: jest.fn().mockResolvedValue({}) }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]), useRouter: () => ({ push: mockPush, replace: jest.fn(), canGoBack: () => false }) }));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, language: 'ko' }) }));
jest.mock('@/components/skin/SkinSolution', () => ({ SkinSolution: 'SolutionContent', SkinRoutine: 'RoutineContent' }));
jest.mock('@/components/skin/SkinReportDetail', () => ({ SkinReportDetail: 'ResultContent', SkinConcernRail: 'ConcernRail' }));
jest.mock('@/components/ui/StateViews', () => ({ LoadingState: 'LoadingState' }));
let mockResults: object | undefined;
jest.mock('@/components/shop/ProductLineCard', () => ({ ProductLineCard: 'ProductCard' }));
jest.mock('@/hooks/useSkinReport', () => ({ useSkinReport: () => ({
  report: require('@/lib/skinReport').buildSkinReport(require('@/constants/skinCare').SKIN_REPORT_EXAMPLE), example: false, loading: false, loadFailed: false,
  activeConcern: 'dryness', ingredients: [], live: Boolean(mockResults),
  recommendation: { owner: 'member', query: { isFetching: false, data: mockResults } }, setActive: jest.fn(),
}) }));

it('opens report information by default and keeps the sticky tabs in a horizontal inner row', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
  try {
    const info = screen.root.find(node => node.props.accessibilityState?.expanded === true && typeof node.props.onPress === 'function');
    expect(info).toBeDefined();
    expect(JSON.stringify(screen.toJSON())).toContain('report.review');
    expect(JSON.stringify(screen.toJSON())).toContain('skincare.requestPrompt');
    const rendered = JSON.stringify(screen.toJSON());
    expect(rendered.indexOf('SolutionContent')).toBeLessThan(rendered.indexOf('report.products'));
    expect(rendered.indexOf('report.products')).toBeLessThan(rendered.indexOf('RoutineContent'));
    expect(JSON.stringify(screen.toJSON())).not.toContain('report.sampleProducts');
    expect(JSON.stringify(screen.toJSON())).not.toContain('report.date');
    expect(JSON.stringify(screen.toJSON())).not.toContain('report.method');
    const tabs = screen.root.findAll(node => node.props.accessibilityRole === 'tab' && typeof node.props.onPress === 'function');
    expect(tabs).toHaveLength(2);
    expect(tabs[0].parent).toBe(tabs[1].parent);
    expect(StyleSheet.flatten(tabs[0].parent!.props.style).flexDirection).toBe('row');
    expect(tabs[0].props.accessibilityState.selected).toBe(true);
    await act(async () => { tabs[1].props.onPress(); });
    expect(JSON.stringify(screen.toJSON())).toContain('ResultContent');
    expect(screen.root.findAll(node => node.props.accessibilityRole === 'tab' && typeof node.props.onPress === 'function').find(node => node.props.accessibilityState.selected)?.findByType(Text).props.children).toBe('report.results');
    await act(async () => { info!.props.onPress(); });
    expect(JSON.stringify(screen.toJSON())).not.toContain('report.review');
  } finally { await act(async () => { screen.unmount(); }); }
});


it('shows V2 products returned for the selected concern', async () => {
  const first = { product: { id: 'a' }, optionId: 'a-1', candidateId: 'candidate-a', optionName: 'Option A', priceKRW: 100,
    reasons: [{ goal: 'pores', sources: ['analysis'] }] };
  const second = { ...first, product: { id: 'b' }, optionId: 'b-1', candidateId: 'candidate-b', optionName: 'Option B',
    reasons: [{ goal: 'wrinkles', sources: ['concern'] }] };
  mockResults = { targetConcern: 'pores', matches: [first, second], history: { requestId: 'request', sessionId: 'session' } };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    const cards = () => screen.root.findAll(n => String(n.type) === 'ProductCard');
    expect(cards()).toHaveLength(2);
    expect(cards().map(c => c.props.eyebrow)).toEqual(['Option A', 'Option B']);
    await act(async () => { cards()[1].props.onPress(); });
    const link = mockPush.mock.lastCall?.[0].params.recommendation;
    const context = recommendationContext(link, 'member', 'b');
    expect(context?.item).toMatchObject({ candidateId: 'candidate-b', optionId: 'b-1', rank: 2 });
    expect(context?.feedback.surface).toBe('skin_recommendations');
    expect(apiPost).toHaveBeenCalledWith('/api/recommendations/skin-v2/impressions',
      expect.objectContaining({ candidateId: 'candidate-b', visibilityPolicyVersion: 'direct-interaction-v1' }),
      expect.objectContaining({ expectedUserId: 'member' }));
  } finally {
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});

it('discards the temporary photo when the report is left', async () => {
  const point: [number, number] = [.5, .5];
  const box: [number, number, number, number] = [0, 0, 1, 1];
  useSkinPreviewStore.getState().setPreview({ runId: 'preview', width: 100, height: 100,
    outline: Array(36).fill(point), boxes: Array(6).fill(box), jpeg: '/9j/' });
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
  expect(useSkinPreviewStore.getState().preview).not.toBeNull();
  await act(async () => { screen.unmount(); });
  expect(useSkinPreviewStore.getState().preview).toBeNull();
});

it('shows the empty state when V2 finds no products', async () => {
  mockResults = { targetConcern: 'pores', matches: [] };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    expect(JSON.stringify(screen.toJSON())).toContain('skincare.emptyAi');
    const cards = screen.root.findAll(node => String(node.type) === 'ProductCard');
    expect(cards).toHaveLength(0);
  } finally {
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});
