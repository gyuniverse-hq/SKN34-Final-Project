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
it('requires six answers and accepts explicit unknown choices', async () => {
  function Harness() {
    const [q, setQ] = useState<Partial<SkinSurveyV3>>({ version: 'skin-support-1' });
    return <SkinSurvey answers={q} onChange={setQ} onFinish={jest.fn()} complete={isCompleteSupportSurvey(q)} saving={false} error={false} />;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Harness />); });
  try {
    expect(screen.root.findAllByType(Button).find(button => button.props.label === 'support.next')!.props.disabled).toBe(true);
    for (const key of ['postWashDryness', 'afternoonTzoneOil', 'cheekState', 'oilOnset', 'cosmeticReaction']) {
      if (key === 'cosmeticReaction') { const labels = screen.root.findAll(node => node.props.accessibilityRole === 'radio').map(node => node.props.accessibilityLabel); expect(labels).not.toContain('support.cosmeticReaction.avoided'); expect(labels).not.toContain('support.cosmeticReaction.notUsed'); expect(labels).toContain('support.cosmeticReaction.unknown'); }
      await act(async () => { screen.root.findAll(node => node.props.accessibilityRole === 'radio' && node.props.accessibilityLabel === `support.${key}.unknown`)[0].props.onPress(); });
      await act(async () => { screen.root.findAllByType(Button).find(button => button.props.label === 'support.next')!.props.onPress(); });
    }
    expect(screen.root.findAll(node => node.props.accessibilityRole === 'radio').map(node => node.props.accessibilityLabel))
      .toEqual(['support.priorityChoice.dryness', 'support.priorityChoice.sensitivity', 'support.priorityChoice.blemish', 'support.priorityChoice.pores', 'support.priorityChoice.pigmentation', 'support.priorityChoice.wrinkles']);
    expect(screen.root.findAllByType(Button).find(button => button.props.label === 'skin.viewResult')!.props.disabled).toBe(true);
    await act(async () => { screen.root.findAll(node => node.props.accessibilityRole === 'radio' && node.props.accessibilityLabel === 'support.priorityChoice.pores')[0].props.onPress(); });
    expect(screen.root.findAllByType(Button).find(button => button.props.label === 'skin.viewResult')!.props.disabled).toBe(false);
    await act(async () => { screen.root.findAllByType(Button).find(button => button.props.label === 'support.previous')!.props.onPress(); });
    expect(screen.root.findAll(node => node.props.accessibilityRole === 'radio' && node.props.accessibilityLabel === 'support.cosmeticReaction.unknown')[0].props.accessibilityState.checked).toBe(true);
  } finally { await act(async () => screen.unmount()); }
});
it('shows a previously saved oiliness priority as the balance selection', async () => {
  const q: SkinSurveyV3 = { version: 'skin-support-1', postWashDryness: 'unknown',
    afternoonTzoneOil: 'unknown', cheekState: 'unknown', oilOnset: 'unknown',
    cosmeticReaction: 'unknown', priority: 'oiliness' };
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<SkinSurvey answers={q} onChange={jest.fn()}
    onFinish={jest.fn()} complete saving={false} error={false} />); });
  try {
    for (let i = 0; i < 5; i++) {
      await act(async () => { screen.root.findAllByType(Button).find(button => button.props.label === 'support.next')!.props.onPress(); });
    }
    const balance = screen.root.find(node => node.props.accessibilityRole === 'radio' &&
      node.props.accessibilityLabel === 'support.priorityChoice.dryness');
    expect(balance.props.accessibilityState.checked).toBe(true);
    expect(isCompleteSupportSurvey(q)).toBe(true);
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
