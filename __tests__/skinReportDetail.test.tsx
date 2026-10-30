import React from 'react';
import { Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { SkinReportDetail } from '@/components/skin/SkinReportDetail';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { buildSkinReport } from '@/lib/skinReport';
import type { SkinReportInput } from '@/types/skinReport';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/components/skin/SkinPreviewPhoto', () => ({ SkinPreviewPhoto: 'PreviewPhoto' }));

const input: SkinReportInput = { ...SKIN_REPORT_EXAMPLE, analysis: {
  schema: 'skin-analysis-mobile-v3',
  features: { ...SKIN_REPORT_EXAMPLE.analysis.features, acne: undefined },
  skinType: { label: 'oily', probabilities: [.05, .05, .9], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' },
} };

it('shows only image-backed items, uses the 40/60 skin type, and removes regional controls', async () => {
  const report = buildSkinReport(input);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinReportDetail metrics={report.metrics} active="dryness" onChange={jest.fn()} preview={null} />); });
  try {
    const tabs = screen.root.findAll(node => node.props.accessibilityRole === 'tab' && typeof node.props.onPress === 'function');
    expect(tabs.map(tab => tab.findByType(Text).props.children)).toEqual(['report.skinType', 'concern.pigmentation', 'concern.wrinkles', 'concern.pores']);
    const rendered = JSON.stringify(screen.toJSON());
    expect(rendered).toContain('report.type.oily');
    expect(rendered).toContain('report.typeBasisCombined');
    expect(rendered).not.toContain('report.regions');
    expect(rendered).not.toContain('report.maxGrade');
    expect(rendered).not.toContain('skin.answer');
    expect(rendered).not.toContain('report.good');
  } finally { await act(async () => { screen.unmount(); }); }
});

it('selects an image result when a hidden survey item is active and leaves legacy surveys hidden', async () => {
  const report = buildSkinReport(SKIN_REPORT_EXAMPLE);
  let screen!: renderer.ReactTestRenderer;
  const onChange = jest.fn();
  await act(async () => { screen = renderer.create(<SkinReportDetail metrics={report.metrics} active="oiliness" onChange={onChange} preview={null} />); });
  try {
    const tabs = screen.root.findAll(node => node.props.accessibilityRole === 'tab' && typeof node.props.onPress === 'function');
    expect(tabs.map(tab => tab.findByType(Text).props.children)).toEqual(['concern.pigmentation', 'concern.wrinkles', 'concern.pores', 'concern.blemish']);
    expect(tabs[0].props.accessibilityState.selected).toBe(true);
    expect(JSON.stringify(screen.toJSON())).toContain('report.fair');
    await act(async () => { tabs[2].props.onPress(); });
    expect(onChange).toHaveBeenCalledWith('pores');
  } finally { await act(async () => { screen.unmount(); }); }
});

it.each([[0, 'good'], [1, 'good'], [2, 'fair'], [3, 'fair'], [4, 'care'], [5, 'care'], [6, 'care']] as const)(
  'shows only the %s status without a numeric grade', async (grade, status) => {
    const report = buildSkinReport({ ...input, analysis: { ...input.analysis, features: {
      ...input.analysis.features, wrinkle_grade_forehead: grade, wrinkle_grade_glabella: 0,
      wrinkle_grade_eye_image_left: 0, wrinkle_grade_eye_image_right: 0,
    } } });
    let screen!: renderer.ReactTestRenderer;
    await act(async () => { screen = renderer.create(<SkinReportDetail metrics={report.metrics} active="wrinkles" onChange={jest.fn()} preview={null} />); });
    try {
      const texts = screen.root.findAllByType(Text).map(node => node.props.children);
      expect(texts.filter(text => text === `report.${status}`)).toHaveLength(1);
      expect(JSON.stringify(texts)).not.toContain('skin.grade');
      expect(JSON.stringify(texts)).not.toContain('report.maxGrade');
    } finally { await act(async () => { screen.unmount(); }); }
  }
);
