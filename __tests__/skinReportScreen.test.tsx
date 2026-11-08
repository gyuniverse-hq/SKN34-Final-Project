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
jest.mock('@/components/skin/SkinReportDetail', () => ({ SkinReportDetail: 'ResultContent' }));
jest.mock('@/components/ui/StateViews', () => ({ LoadingState: 'LoadingState' }));
let mockResults: object | undefined;
jest.mock('@/components/shop/ProductLineCard', () => ({ ProductLineCard: 'ProductCard' }));
jest.mock('@/hooks/useSkinReport', () => ({ useSkinReport: () => ({
  report: require('@/lib/skinReport').buildSkinReport(require('@/constants/skinCare').SKIN_REPORT_EXAMPLE), example: false, loading: false, loadFailed: false,
  activeConcern: 'dryness', primary: 'dryness', selected: [], suggested: ['pores'], ingredients: [], live: Boolean(mockResults),
  recommendations: { isFetching: false, data: mockResults }, setActive: jest.fn(), findProducts: jest.fn(), toggle: jest.fn(),
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


it('shows the top list and independent concern lists with the matching reason and option', async () => {
  const first = { product: { id: 'a' }, optionName: 'Option A', priceKRW: 100,
    reasons: [{ goal: 'dryness', sources: ['primary', 'skinType'] }, { goal: 'pores', sources: ['analysis'] }] };
  const second = { ...first, product: { id: 'b' }, optionName: 'Option B',
    reasons: [{ goal: 'pores', sources: ['analysis'] }] };
  mockResults = { overallTop5: [first], byConcern: { dryness: [first], pores: [second, first] },
    coverage: [{ goal: 'dryness', status: 'ok' }, { goal: 'pores', status: 'ok' },
      { goal: 'sensitivity', status: 'mapping_unavailable' }] };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    const cards = () => screen.root.findAll(n => String(n.type) === 'ProductCard');
    expect(cards().map(c => c.props.note)).toEqual(['skincare.reason.primary\nskincare.reason.analysis']);
    const select = (key: string) => screen.root.find(n => n.props.accessibilityRole === 'button' && n.findAllByType(Text).some(v => v.props.children === key));
    await act(async () => { select('skincare.tab.selected').props.onPress(); });
    expect(cards().map(c => c.props.note)).toEqual(['skincare.reason.primary']);
    await act(async () => { select('skincare.tab.detected').props.onPress(); });
    expect(cards().map(c => c.props.note)).toEqual(['skincare.reason.analysis', 'skincare.reason.analysis']);
    expect(JSON.stringify(screen.toJSON())).not.toContain('report.liveProducts');
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

it('shows six care choices and one combined balance group without duplicate products', async () => {
  const first = { product: { id: 'a' }, optionName: 'Option A', priceKRW: 100,
    reasons: [{ goal: 'dryness', sources: ['primary'] }, { goal: 'oiliness', sources: ['primary'] }] };
  mockResults = { overallTop5: [first], byConcern: { dryness: [first], oiliness: [first] },
    balanceMatches: [first], coverage: [{ goal: 'dryness', status: 'ok' }, { goal: 'oiliness', status: 'ok' }] };
  let screen!: renderer.ReactTestRenderer;
  try {
    await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
    const adjust = screen.root.find(node => node.props.accessibilityRole === 'button' &&
      node.props.accessibilityState?.expanded === false && typeof node.props.onPress === 'function');
    await act(async () => { adjust.props.onPress(); });
    const goals = screen.root.findAll(node => node.props.accessibilityRole === 'radio');
    expect([...new Set(goals.map(node => node.findByType(Text).props.children))]).toEqual([
      'support.priorityChoice.dryness', 'support.priorityChoice.sensitivity',
      'support.priorityChoice.blemish', 'support.priorityChoice.pores',
      'support.priorityChoice.pigmentation', 'support.priorityChoice.wrinkles',
    ]);
    const cards = screen.root.findAll(node => String(node.type) === 'ProductCard');
    expect(cards).toHaveLength(1);
    const selectedTab = screen.root.find(node => node.props.accessibilityRole === 'button' && node.findAllByType(Text).some(v => v.props.children === 'skincare.tab.selected'));
    await act(async () => { selectedTab.props.onPress(); });
    expect(screen.root.findAll(node => String(node.type) === 'ProductCard')[0].props.note).toBe('skincare.reason.primary');
  } finally {
    mockResults = undefined;
    await act(async () => { screen?.unmount(); });
  }
});
