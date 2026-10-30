import React from 'react';
import { StyleSheet, Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import SkinRecommendationsScreen from '@/app/skin-recommendations';

jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useRouter: () => ({ push: jest.fn(), replace: jest.fn(), canGoBack: () => false }) }));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, language: 'ko' }) }));
jest.mock('@/components/skin/SkinSolution', () => ({ SkinSolution: 'SolutionContent' }));
jest.mock('@/components/skin/SkinReportDetail', () => ({ SkinReportDetail: 'ResultContent' }));
jest.mock('@/components/ui/StateViews', () => ({ LoadingState: 'LoadingState' }));
jest.mock('@/components/skin/SkinSampleProducts', () => ({ SkinSampleProducts: () => null }));
jest.mock('@/hooks/useSkinReport', () => ({ useSkinReport: () => ({
  report: require('@/lib/skinReport').buildSkinReport(require('@/constants/skinCare').SKIN_REPORT_EXAMPLE), example: false, loading: false, loadFailed: false,
  activeConcern: 'dryness', selected: ['dryness'], ingredients: [], samples: [], live: false,
  recommendations: { isFetching: false }, setActive: jest.fn(), findProducts: jest.fn(), toggle: jest.fn(),
}) }));

it('opens report information by default and keeps the sticky tabs in a horizontal inner row', async () => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinRecommendationsScreen />); });
  try {
    const info = screen.root.find(node => node.props.accessibilityState?.expanded === true && typeof node.props.onPress === 'function');
    expect(info).toBeDefined();
    expect(JSON.stringify(screen.toJSON())).toContain('report.review');
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
