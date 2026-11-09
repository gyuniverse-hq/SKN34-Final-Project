import React from 'react';
import { StyleSheet, Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import SkinRecommendationsScreen from '@/app/skin-recommendations';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';

jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]), useRouter: () => ({ push: jest.fn(), replace: jest.fn(), canGoBack: () => false }) }));
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
  recommendations: { isFetching: false, data: mockResults }, setActive: jest.fn(),
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


it('keeps AI recommendations visible while browsing all six concerns', async () => {
  const first = { product: { id: 'a' }, optionName: 'Option A', priceKRW: 100,
    reasons: [{ goal: 'pores', sources: ['analysis'] }] };
  const second = { ...first, product: { id: 'b' }, optionName: 'Option B',
    reasons: [{ goal: 'wrinkles', sources: ['concern'] }] };
  mockResults = { overallTop5: [first], byConcern: { pores: [first], wrinkles: [second] },
    coverage: [{ goal: 'pores', status: 'ok' }, { goal: 'wrinkles', status: 'ok' }] };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    const cards = () => screen.root.findAll(n => String(n.type) === 'ProductCard');
    const rail = () => screen.root.find(node => String(node.type) === 'ConcernRail');
    expect(rail().props.concerns).toEqual(['dryness', 'sensitivity', 'blemish', 'pores', 'pigmentation', 'wrinkles']);
    expect(cards().map(c => c.props.note)).toEqual(['skincare.reason.analysis']);
    await act(async () => { rail().props.onChange('wrinkles'); });
    expect(cards().map(c => c.props.note)).toEqual(['skincare.reason.analysis', 'skincare.reason.concern']);
    expect(cards().map(c => c.props.eyebrow)).toEqual(['Option A', 'Option B']);
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

it('still shows the combined balance list when the profile has no AI recommendations', async () => {
  const first = { product: { id: 'a' }, optionName: 'Option A', priceKRW: 100,
    reasons: [{ goal: 'dryness', sources: ['concern'] }, { goal: 'oiliness', sources: ['concern'] }] };
  mockResults = { overallTop5: [], byConcern: { dryness: [first], oiliness: [first] },
    balanceMatches: [first], coverage: [{ goal: 'dryness', status: 'ok' }, { goal: 'oiliness', status: 'ok' }] };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    expect(JSON.stringify(screen.toJSON())).toContain('skincare.emptyAi');
    const cards = screen.root.findAll(node => String(node.type) === 'ProductCard');
    expect(cards).toHaveLength(1);
    expect(cards[0].props.note).toBe('skincare.reason.concern');
  } finally {
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});
