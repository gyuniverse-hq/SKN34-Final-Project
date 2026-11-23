import React from 'react';
import { StyleSheet, Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import SkinRecommendationsScreen from '@/app/skin-recommendations';
import { apiPost } from '@/lib/api';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';
import { offerAction } from '@/lib/confirm';

const mockPush = jest.fn();
const mockReplace = jest.fn();
let mockSubscribed = true;
let mockFreeTrial: string | undefined = '1';
jest.mock('@/hooks/useSkinAccess', () => ({ useSkinAccess: () => ({ ready: true, subscribed: mockSubscribed }) }));
jest.mock('@/lib/confirm', () => ({ offerAction: jest.fn() }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useLocalSearchParams: () => ({ freeTrial: mockFreeTrial }), usePreventRemove: () => jest.fn(), useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]), useRouter: () => ({ push: mockPush, replace: mockReplace, canGoBack: () => false }) }));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, language: 'ko' }) }));
jest.mock('@/lib/api', () => ({ apiPost: jest.fn().mockResolvedValue({}) }));
jest.mock('@/components/skin/SkinSolution', () => ({ SkinSolution: 'SolutionContent', SkinRoutine: 'RoutineContent' }));
jest.mock('@/components/skin/SkinReportDetail', () => ({ SkinReportDetail: 'ResultContent', SkinConcernRail: 'ConcernRail' }));
jest.mock('@/components/ui/StateViews', () => ({ LoadingState: 'LoadingState' }));
let mockResults: object | undefined;
let mockOwner: string | undefined;
jest.mock('@/components/shop/ProductLineCard', () => ({ ProductLineCard: 'ProductCard' }));
jest.mock('@/hooks/useSkinReport', () => ({ useSkinReport: () => ({
  report: require('@/lib/skinReport').buildSkinReport(require('@/constants/skinCare').SKIN_REPORT_EXAMPLE), example: false, loading: false, loadFailed: false,
  activeConcern: 'dryness', ingredients: [], live: Boolean(mockResults),
  recommendations: { data: mockResults }, owner: mockOwner, setActive: jest.fn(),
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


it.each([5, 10])('displays %i rule-based products in API order and opens the last product', async limit => {
  const matches = Array.from({ length: limit }, (_, index) => ({
    product: { id: `p-${index + 1}` }, optionId: `o-${index + 1}`, optionName: `Option ${index + 1}`, priceKRW: 100,
    reasons: [{ goal: 'pores', sources: ['analysis'] }],
  }));
  mockResults = { overallTop5: matches.slice(0, 5), ...(limit === 10 ? { overallTop10: matches } : {}) };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    const cards = () => screen.root.findAll(n => String(n.type) === 'ProductCard');
    expect(cards()).toHaveLength(limit);
    expect(cards().map(c => c.props.eyebrow)).toEqual(matches.map(m => m.optionName));
    await act(async () => { cards()[limit - 1].props.onPress(); });
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: '/product/[id]', params: { id: `p-${limit}` } });
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

it('links a tap on rank 10 to a V1 impression and opens the attributed product detail', async () => {
  mockOwner = 'owner';
  const matches = Array.from({ length: 10 }, (_, index) => ({
    product: { id: `p-${index + 1}` }, optionId: `o-${index + 1}`, candidateId: `c-${index + 1}`,
    optionName: 'Option', priceKRW: 100, reasons: [],
  }));
  mockResults = { overallTop10: matches, history: { requestId: 'request', sessionId: 'session' } };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    const cards = screen.root.findAll(n => String(n.type) === 'ProductCard');
    expect(apiPost).not.toHaveBeenCalled();
    await act(async () => { cards[9].props.onPress(); });
    expect(apiPost).toHaveBeenCalledWith('/api/recommendations/skincare/v4/impressions', expect.objectContaining({
      candidateId: 'c-10', displayedPosition: 10, visibilityPolicyVersion: 'direct-interaction-v1',
    }), expect.objectContaining({ expectedUserId: 'owner' }));
    expect(mockPush).toHaveBeenLastCalledWith({
      pathname: '/product/[id]', params: { id: 'p-10', recommendation: expect.any(String) },
    });
  } finally {
    mockOwner = undefined;
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});

it('shows the empty state when the rule-based API finds no products', async () => {
  mockResults = { overallTop10: [], overallTop5: [] };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    expect(JSON.stringify(screen.toJSON())).toContain('skincare.emptyProfileMatches');
    const cards = screen.root.findAll(node => String(node.type) === 'ProductCard');
    expect(cards).toHaveLength(0);
  } finally {
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});

it.each([false, true])('offers membership on exit and respects the choice (subscribe %s)', async subscribe => {
  mockResults = { matches: [] };
  mockSubscribed = false;
  jest.mocked(offerAction).mockImplementationOnce((message, accept, later, onAccept, onLater) =>
    subscribe ? onAccept() : onLater());
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    expect(screen.root.findAll(node => String(node.type) === 'ProductCard')).toHaveLength(0);
    const home = screen.root.findAll(node => node.props.accessibilityLabel === 'tabs.home')[0];
    await act(async () => { home.props.onPress(); });
    expect(offerAction).toHaveBeenCalledWith('skinAccess.reportInvite', 'skinAccess.viewMembership',
      'skinAccess.later', expect.any(Function), expect.any(Function));
    expect(mockReplace).toHaveBeenLastCalledWith(subscribe ? '/membership' : '/(tabs)');
  } finally {
    mockSubscribed = true;
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});

it('leaves a reopened report without repeating the free-analysis subscription invitation', async () => {
  mockFreeTrial = undefined;
  mockSubscribed = false;
  mockResults = { matches: [] };
  jest.mocked(offerAction).mockClear();
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    await act(async () => { screen.root.findAllByProps({ accessibilityLabel: 'tabs.home' })[0].props.onPress(); });
    expect(offerAction).not.toHaveBeenCalled();
    expect(mockReplace).toHaveBeenLastCalledWith('/(tabs)');
  } finally {
    mockFreeTrial = '1';
    mockSubscribed = true;
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});
