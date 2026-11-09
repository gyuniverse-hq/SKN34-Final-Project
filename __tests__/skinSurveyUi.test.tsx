import { fuseSupportSkinType } from '@/lib/skinSupportFusion';
import { SkinSupportSummary } from '@/components/skin/SkinSupportSummary';
import React, { useState } from 'react';
import renderer, { act } from 'react-test-renderer';
import { SkinSurvey } from '@/components/skin/SkinSurvey';
import { SkinSurveySummary } from '@/components/skin/SkinSurveySummary';
import { Button } from '@/components/ui/Button';
import { isCompleteSupportSurvey } from '@/lib/skinSurvey';
import { fuseSkinType } from '@/lib/skinFusion';
import type { SkinSurveyV2, SkinSurveyV3, SkinTypePrediction } from '@/types/skin';

jest.mock('react-native', () => ({
  View: 'View', Text: 'Text', ScrollView: 'ScrollView', Pressable: 'Pressable',
  StyleSheet: { create: (styles: unknown) => styles },
  Platform: { select: (values: { default: unknown }) => values.default },
}));
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');
// Isolate survey state transitions from native pressable rendering overhead.
jest.mock('@/components/ui/Chip', () => ({ Chip: 'Chip' }));
jest.mock('@/components/ui/Button', () => ({ Button: 'Button' }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
const answers: SkinSurveyV2 = { version: 'sos-bstq-1', afterWash: 'a', selfType: 'a', tzoneFrequency: 'a',
  cloggedPores: 'a', tzoneOnset: 'a', washFrequency: 'a', redBumps: 'a', cosmeticReaction: 'e', priority: 'pores' };
it('finishes after five answers without asking for a care goal', async () => {
  const finish = jest.fn();
  function Harness() {
    const [q, setQ] = useState<Partial<SkinSurveyV3>>({ version: 'skin-support-1' });
    return <SkinSurvey answers={q} onChange={setQ} onFinish={finish} complete={isCompleteSupportSurvey(q)} saving={false} error={false} />;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Harness />); });
  try {
    const button = (label: string) => screen.root.findAllByType(Button).find(node => node.props.label === label)!;
    const radio = (label: string) => screen.root.findAll(node => node.props.accessibilityRole === 'radio' && node.props.accessibilityLabel === label)[0];
    expect(button('support.next').props.disabled).toBe(true);
    for (const key of ['postWashDryness', 'afternoonTzoneOil', 'cheekState', 'oilOnset']) {
      await act(async () => { radio(`support.${key}.unknown`).props.onPress(); });
      await act(async () => { button('support.next').props.onPress(); });
    }
    expect(button('skin.viewResult').props.disabled).toBe(true);
    expect(radio('support.cosmeticReaction.avoided')).toBeUndefined();
    expect(radio('support.cosmeticReaction.notUsed')).toBeUndefined();
    await act(async () => { radio('support.cosmeticReaction.unknown').props.onPress(); });
    expect(button('skin.viewResult').props.disabled).toBe(false);
    await act(async () => { button('skin.viewResult').props.onPress(); });
    expect(finish).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(screen.toJSON())).not.toContain('support.priority');
  } finally { await act(async () => screen.unmount()); }
});

it('keeps score comparison collapsed while showing image and survey provenance', async () => {
  const raw: SkinTypePrediction = { label: 'dry', probabilities: [.5, .05, .45], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinSurveySummary assessment={{ raw, questionnaire: answers, fusion: fuseSkinType(raw, 26) }} />); });
  try {
    expect(JSON.stringify(screen.toJSON())).toContain('survey.basis');
    expect(JSON.stringify(screen.toJSON())).not.toContain('survey.scoreNotice');
    const button = screen.root.findAll(node => node.props.accessibilityRole === 'button' && node.props.accessibilityState?.expanded === false && typeof node.props.onPress === 'function')[0];
    await act(async () => button.props.onPress());
    expect(JSON.stringify(screen.toJSON())).toContain('survey.scoreNotice');
  } finally { await act(async () => screen.unmount()); }
});


it('shows support responses and only raw model scores without SOS or adjustment comparison', async () => {
  const q: SkinSurveyV3 = { version: 'skin-support-1', postWashDryness: 'unknown', afternoonTzoneOil: 'marked',
    cheekState: 'variable', oilOnset: 'notNoticed', cosmeticReaction: 'notUsed', priority: 'pores' };
  const raw: SkinTypePrediction = { label: 'dry', probabilities: [.5, .05, .45], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinSupportSummary assessment={{ questionnaire: q, raw }} />); });
  try {
    const initial = JSON.stringify(screen.toJSON());
    expect(initial).toContain('support.postWashDryness.unknown');
    expect(initial).toContain('support.oilOnset.notNoticed');
    expect(initial).toContain('support.cosmeticReaction.notUsed');
    expect(initial).not.toContain('survey.');
    expect(initial).not.toContain('support.scoreNotice');
    const button = screen.root.findAll(node => node.props.accessibilityRole === 'button' && node.props.accessibilityState?.expanded === false && typeof node.props.onPress === 'function')[0];
    await act(async () => button.props.onPress());
    expect(JSON.stringify(screen.toJSON())).toContain('support.scoreNotice');
    expect(JSON.stringify(screen.toJSON())).not.toContain('survey.');
  } finally { await act(async () => screen.unmount()); }
});


it('shows v4 adjustment reasons and raw/final comparison without the old no-correction notice', async () => {
  const q: SkinSurveyV3 = { version: 'skin-support-1', postWashDryness: 'none', afternoonTzoneOil: 'marked',
    cheekState: 'oily', oilOnset: 'within1h', cosmeticReaction: 'unknown', priority: 'pores' };
  const raw: SkinTypePrediction = { label: 'balanced', probabilities: [.1, .47, .43], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinSupportSummary assessment={{ questionnaire: q, raw, fusion: fuseSupportSkinType(raw, q) }} />); });
  try {
    expect(JSON.stringify(screen.toJSON())).toContain('support.fusionReason');
    const button = screen.root.findAll(node => node.props.accessibilityRole === 'button' && node.props.accessibilityState?.expanded === false && typeof node.props.onPress === 'function')[0];
    await act(async () => button.props.onPress());
    expect(JSON.stringify(screen.toJSON())).toContain('support.fusionScore');
    expect(JSON.stringify(screen.toJSON())).not.toContain('support.scoreNotice');
  } finally { await act(async () => screen.unmount()); }
});
