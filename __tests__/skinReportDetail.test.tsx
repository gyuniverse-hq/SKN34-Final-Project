import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { SkinReportDetail } from '@/components/skin/SkinReportDetail';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { buildSkinReport } from '@/lib/skinReport';
import type { SkinReportInput } from '@/types/skinReport';
import type { SkinPreview } from '@/types/skin';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
jest.mock('expo-linear-gradient', () => ({ LinearGradient: 'LinearGradient' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@/components/skin/SkinPreviewPhoto', () => ({ SkinPreviewPhoto: 'PreviewPhoto' }));

const input: SkinReportInput = { ...SKIN_REPORT_EXAMPLE, analysis: {
  schema: 'skin-analysis-mobile-v3',
  features: { ...SKIN_REPORT_EXAMPLE.analysis.features, acne: undefined },
  skinType: { label: 'oily', probabilities: [.05, .05, .9], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' },
} };

it('shows the photo first and lets the user switch between skin type and analysis results', async () => {
  const report = buildSkinReport(input);
  const onChange = jest.fn();
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinReportDetail metrics={report.metrics}
    active="pores"
    onChange={onChange} preview={{} as SkinPreview} />); });
  try {
    const rendered = JSON.stringify(screen.toJSON());
    expect(rendered).toContain('report.skinType');
    expect(rendered).not.toContain('report.type.oily');
    expect(rendered).toContain('PreviewPhoto');
    expect(rendered).toContain('concern.pores');
    expect(rendered.indexOf('PreviewPhoto')).toBeLessThan(rendered.indexOf('report.skinType'));
    expect(rendered).not.toContain('report.combined');
    expect(rendered).not.toContain('report.modelNote');
    expect(rendered).not.toContain('report.detailBody');
    const typeTab = screen.root.findAll(node => node.props.accessibilityRole === 'tab')[0];
    await act(async () => { typeTab.props.onPress(); });
    expect(onChange).toHaveBeenCalledWith('dryness');
    await act(async () => { screen.update(<SkinReportDetail metrics={report.metrics} active="dryness" onChange={onChange} preview={{} as SkinPreview} />); });
    expect(JSON.stringify(screen.toJSON())).toContain('report.type.oily');
  } finally { await act(async () => { screen.unmount(); }); }
});

it('shows only image-backed items, uses the 40/60 skin type, and removes regional controls', async () => {
  const report = buildSkinReport(input);
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinReportDetail metrics={report.metrics} active="dryness" onChange={jest.fn()} preview={null} />); });
  try {
    const tabs = screen.root.findAll(node => node.props.accessibilityRole === 'tab' && typeof node.props.onPress === 'function');
    expect(tabs.map(tab => tab.findByType(Text).props.children)).toEqual(['report.skinType', 'concern.pigmentation', 'concern.wrinkles', 'concern.pores']);
    const rendered = JSON.stringify(screen.toJSON());
    expect(rendered).toContain('report.type.oily');
    expect(rendered).not.toContain('report.modelNote');
    expect(rendered).not.toContain('report.regions');
    expect(rendered).not.toContain('report.maxGrade');
    expect(rendered).not.toContain('skin.answer');
    expect(rendered).not.toContain('report.good');
    expect(rendered).not.toContain('report.detailBody');
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
    expect(JSON.stringify(screen.toJSON())).toContain('report.good');
    await act(async () => { tabs[2].props.onPress(); });
    expect(onChange).toHaveBeenCalledWith('pores');
  } finally { await act(async () => { screen.unmount(); }); }
});

it('excludes inferred oiliness and unavailable model results from detail tabs', async () => {
  const report = buildSkinReport({ version: 3, registeredAt: input.registeredAt,
    analysis: input.analysis, questionnaire: { version: 'skin-support-1', postWashDryness: 'unknown',
      afternoonTzoneOil: 'marked', cheekState: 'oily', oilOnset: 'within1h',
      cosmeticReaction: 'repeated', priority: 'sensitivity' } });
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinReportDetail metrics={report.metrics} active="oiliness" onChange={jest.fn()} preview={null} />); });
  try {
    const tabs = screen.root.findAll(node => node.props.accessibilityRole === 'tab' && typeof node.props.onPress === 'function');
    expect(tabs.map(tab => tab.findByType(Text).props.children)).toEqual(['report.skinType', 'concern.pigmentation', 'concern.wrinkles', 'concern.pores']);
  } finally { await act(async () => { screen.unmount(); }); }
});

it.each([[0, 'good'], [.75, 'care'], [1, 'care']] as const)(
  'places the dot at score %s on the full gradient without a visible numeric label', async (score, status) => {
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinReportDetail active="pores" onChange={jest.fn()} preview={null}
    metrics={[{ concern: 'pores', source: 'analysis', status, value: Number(score >= .5), maximum: 1, modelScore: score,
      regions: [{ region: 'leftCheek', value: Number(score >= .5) }] }]} />); });
  try {
    const gradient = screen.root.find(node => String(node.type) === 'LinearGradient');
    expect(gradient.props.start.x).toBe(0);
    expect(gradient.props.end.x).toBe(1);
    const views = screen.root.findAllByType(View).map(node => StyleSheet.flatten(node.props.style));
    expect(views).toContainEqual(expect.objectContaining({ left: `${score * 100}%` }));
    const texts = screen.root.findAllByType(Text).map(node => node.props.children);
    expect(texts.indexOf(`report.${status}`)).toBeLessThan(texts.indexOf(`report.${status}Body`));
    expect(texts.join(' ')).not.toMatch(/report\.modelScore|\d+\.\d+\s*\/\s*1/);
  } finally { await act(async () => { screen.unmount(); }); }
});

it.each([[0, 'good'], [1, 'good'], [2, 'good'], [3, 'good'], [4, 'care'], [5, 'care'], [6, 'care']] as const)(
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
      expect(texts).not.toContain('report.modelScore');
      expect(screen.root.findAll(node => String(node.type) === 'LinearGradient')).toHaveLength(0);
    } finally { await act(async () => { screen.unmount(); }); }
  }
);
