import { fuseSupportSkinType } from '@/lib/skinSupportFusion';
import type { SkinProfileV4 } from '@/types/skin';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { SOS_QUESTIONS, surveyChoices } from '@/constants/skinSurvey';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { scoreSos, isCompleteSkinSurvey, surveySensitivity, isCompleteSupportSurvey } from '@/lib/skinSurvey';
import { fuseSkinType } from '@/lib/skinFusion';
import { readSkinProfile, writeSkinProfile } from '@/lib/skinProfile';
import { suggestConcerns } from '@/lib/skinFilters';
import { buildSkinReport } from '@/lib/skinReport';
import { buildSkinRecommendationRequest } from '@/lib/skinRecommendations';
import { STORAGE_KEYS } from '@/lib/storage';
import type { SkinSurveyV2, SkinTypePrediction, SkinProfileV2, SkinSurveyV3, SkinProfileV3 } from '@/types/skin';

const answers: SkinSurveyV2 = { version: 'sos-bstq-1', afterWash: 'a', selfType: 'a', tzoneFrequency: 'a',
  cloggedPores: 'a', tzoneOnset: 'a', washFrequency: 'a', redBumps: 'd', cosmeticReaction: 'e', priority: 'dryness' };
const prediction = (probabilities: [number, number, number]): SkinTypePrediction => ({
  probabilities, label: (['dry', 'balanced', 'oily'] as const)[probabilities.indexOf(Math.max(...probabilities))],
  roiCount: 3, scoreType: 'mean_uncalibrated_softmax',
});
function profile(): SkinProfileV2 {
  const q: SkinSurveyV2 = { ...answers, afterWash: 'd', selfType: 'd', tzoneFrequency: 'd', cloggedPores: 'd', tzoneOnset: 'e', washFrequency: 'e' };
  const { acne: _acne, ...features } = SKIN_REPORT_EXAMPLE.analysis.features;
  return { version: 2, registeredAt: '2026-11-01T00:00:00Z', questionnaire: q,
    analysis: { schema: 'skin-analysis-mobile-v3', skinType: prediction([.5, .05, .45]), features,
      roiMethod: 'opencv_haar_facebox_proportions_v1', validationStatus: 'experimental_unvalidated', preprocessing: 'skin-v3-embedded-enhancement',
      timing: { runId: 'numeric-test', processId: 'test', firstInProcess: false, device: 'test', androidVersion: 'test', build: 'test',
        runtime: 'test', bundleVersion: 'test', alignmentMs: 0, captureMs: 0, imagePreparationMs: 0, validationMs: 0,
        detectionMs: 0, nativeMs: 0, totalMs: 1, memoryPssKb: null,
        models: (['pore', 'pigmentation', 'wrinkle', 'skinType'] as const).map(indicator => ({ indicator, sourceSha256: 'a', sha256: 'b', loadMs: 0, validationMs: 0, preprocessingMs: 0, inferenceMs: 0 })) } },
    fusion: fuseSkinType(prediction([.5, .05, .45]), scoreSos(q)) };
}

it('scores all original response categories and rejects missing or invalid choices', () => {
  expect(scoreSos(answers)).toBe(6);
  expect(scoreSos(profile().questionnaire)).toBe(26);
  for (const key of SOS_QUESTIONS) {
    for (const [i, choice] of surveyChoices(key).entries()) expect(scoreSos({ ...answers, [key]: choice })).toBe(6 + i);
    expect(isCompleteSkinSurvey({ ...answers, [key]: undefined })).toBe(false);
  }
  expect(() => scoreSos({ ...answers, afterWash: 'e' } as unknown as SkinSurveyV2)).toThrow();
  expect(isCompleteSkinSurvey({ ...answers, priority: undefined })).toBe(false);
  expect(isCompleteSkinSurvey({ ...answers, cosmeticReaction: undefined })).toBe(false);
  expect(isCompleteSkinSurvey({ ...answers, redBumps: undefined })).toBe(false);
});

it('limits oily correction to high SOS and a close image judgment', () => {
  const p = prediction([.55, 0, .45]);
  const before = JSON.stringify(p);
  expect(fuseSkinType(p, 19).reason).toBe('low-sos');
  expect(fuseSkinType(p, 20).weight).toBe(.025);
  const result = fuseSkinType(p, 26);
  expect(result).toMatchObject({ type: 'oily', weight: .1, changed: true });
  expect(result.scores!.reduce((a, b) => a + b, 0)).toBeCloseTo(1);
  expect(result.delta!.every(d => Math.abs(d) <= .1)).toBe(true);
  expect(JSON.stringify(p)).toBe(before);
  expect(fuseSkinType(prediction([.551, 0, .449]), 26).reason).toBe('large-gap');
  expect(fuseSkinType(prediction([.7, .2, .1]), 26).type).toBe('dry');
  expect(fuseSkinType(prediction([.2, .3, .5]), 6)).toMatchObject({ type: 'oily', weight: 0 });
  expect(fuseSkinType(undefined, 6)).toMatchObject({ type: 'unknown', scores: null });
  expect(() => fuseSkinType(p, 27)).toThrow();
});

it('keeps the image class on an adjusted tie', () => {
  const p = prediction([37 / 78, 1 - 37 / 78 - 35 / 78, 35 / 78]);
  expect(fuseSkinType(p, 20)).toMatchObject({ type: 'dry', changed: false });
});

it('preserves a v2 snapshot across reload and rejects tampering on both write and read', async () => {
  const p = profile();
  await writeSkinProfile(p);
  expect(await readSkinProfile()).toEqual(p);
  for (const broken of [
    { ...p, fusion: { ...p.fusion, sosTotal: 25 } },
    { ...p, fusion: { ...p.fusion, type: 'balanced' } },
    { ...p, fusion: { ...p.fusion, scores: [.4, .4, .2] } },
    { ...p, fusion: { ...p.fusion, settings: { ...p.fusion.settings, maxWeight: .5 } } },
  ]) {
    await expect(writeSkinProfile(broken as SkinProfileV2)).rejects.toThrow();
    await AsyncStorage.setItem(STORAGE_KEYS.skinProfile, JSON.stringify(broken));
    await expect(readSkinProfile()).rejects.toThrow();
  }
});

it('uses the stored type in report and filters, prioritizes preference without changing its severity', () => {
  const p = profile(), report = buildSkinReport(p);
  expect(report.skinType).toBe(p.fusion.type);
  expect(report.priorities[0]).toMatchObject({ concern: 'dryness', status: 'good' });
  expect(report.concerns).toEqual(suggestConcerns(p));
  expect(report.concerns[0]).toBe('dryness');
  expect(report.concerns).toContain('oiliness');
  expect(report.concerns).not.toContain('blemish');
  expect(report.concerns).not.toContain('sensitivity');
  expect(surveySensitivity({ ...answers, cosmeticReaction: 'c' })).toBe('care');
  expect(surveySensitivity({ ...answers, cosmeticReaction: 'd' })).toBe('care');
  expect(surveySensitivity(answers)).toBe('unknown');
  expect(buildSkinRecommendationRequest(p, ['pores'])).toEqual({ concerns: ['pores'], limit: 8 });
});


const supportAnswers: SkinSurveyV3 = { version: 'skin-support-1', postWashDryness: 'unknown', afternoonTzoneOil: 'unknown',
  cheekState: 'unknown', oilOnset: 'unknown', cosmeticReaction: 'unknown', priority: 'pores' };
function supportProfile(): SkinProfileV3 {
  return { version: 3, registeredAt: '2026-11-01T00:00:00Z', analysis: profile().analysis, questionnaire: { ...supportAnswers } };
}
it('accepts explicit unknowns but rejects missing, legacy and invalid support responses', () => {
  expect(isCompleteSupportSurvey(supportAnswers)).toBe(true);
  for (const key of Object.keys(supportAnswers)) {
    expect(isCompleteSupportSurvey({ ...supportAnswers, [key]: undefined })).toBe(false);
    expect(isCompleteSupportSurvey({ ...supportAnswers, [key]: 'invalid' })).toBe(false);
  }
  expect(isCompleteSupportSurvey({ ...supportAnswers, oilOnset: 'notNoticed', cheekState: 'variable', cosmeticReaction: 'notUsed' })).toBe(true);
  expect(isCompleteSupportSurvey({ ...supportAnswers, afterWash: 'a' })).toBe(false);
  expect(() => scoreSos(supportAnswers as unknown as SkinSurveyV2)).toThrow();
});
it('keeps onset categories and afternoon oil independent without manufacturing scores', async () => {
  for (const oilOnset of ['within1h', 'after1to3h', 'after3h', 'notNoticed', 'unknown'] as const) {
    const p = supportProfile();
    p.questionnaire = { ...supportAnswers, afternoonTzoneOil: 'marked', oilOnset };
    await writeSkinProfile(p);
    expect(await readSkinProfile()).toEqual(p);
    expect(buildSkinReport(p).skinType).toBe(p.analysis.skinType!.label);
    expect(buildSkinReport(p).assessment).toBeUndefined();
    expect(buildSkinReport(p).supportAssessment?.questionnaire.oilOnset).toBe(oilOnset);
    expect(p).not.toHaveProperty('fusion');
  }
});
it('does not infer type or care flags from the four support answers', () => {
  const p = supportProfile();
  p.questionnaire = { ...supportAnswers, postWashDryness: 'marked', afternoonTzoneOil: 'marked', cheekState: 'dry', oilOnset: 'within1h' };
  const raw = JSON.stringify(p.analysis);
  const report = buildSkinReport(p);
  expect(report.skinType).toBe('dry'); // v2 SOS policy would switch this image to oily.
  expect(report.concerns).toEqual(suggestConcerns(p));
  expect(report.concerns).not.toContain('oiliness');
  expect(report.priorities[0].concern).toBe('pores');
  expect(JSON.stringify(p.analysis)).toBe(raw);
  const noModel = supportProfile();
  noModel.analysis = { ...noModel.analysis, skinType: undefined };
  expect(buildSkinReport(noModel).skinType).toBe('unknown');
});
it('uses only repeated or avoided reactions to propose sensitivity for v3', () => {
  for (const reaction of ['none', 'once', 'repeated', 'avoided', 'notUsed', 'unknown'] as const) {
    const p = supportProfile(); p.questionnaire.cosmeticReaction = reaction;
    expect(suggestConcerns(p).includes('sensitivity')).toBe(['repeated', 'avoided'].includes(reaction));
    expect(buildSkinReport(p).concerns).toEqual(suggestConcerns(p));
    expect(buildSkinRecommendationRequest(p, ['wrinkles'])).toEqual({ concerns: ['wrinkles'], limit: 8 });
  }
});
it('rejects a v3 payload with invented fusion data on read and write', async () => {
  const bad = { ...supportProfile(), fusion: profile().fusion };
  await expect(writeSkinProfile(bad)).rejects.toThrow();
  await AsyncStorage.setItem(STORAGE_KEYS.skinProfile, JSON.stringify(bad));
  await expect(readSkinProfile()).rejects.toThrow();
});


it('stores and reloads a separate v4 fusion snapshot used consistently by report and filters', async () => {
  const old = supportProfile();
  const questionnaire: SkinSurveyV3 = { ...old.questionnaire, postWashDryness: 'none', afternoonTzoneOil: 'marked', cheekState: 'oily', oilOnset: 'within1h' };
  const p: SkinProfileV4 = { ...old, version: 4, questionnaire, fusion: fuseSupportSkinType(old.analysis.skinType, questionnaire) };
  await writeSkinProfile(p);
  expect(await readSkinProfile()).toEqual(p);
  expect(p.analysis.skinType!.label).toBe('dry');
  expect(buildSkinReport(p).skinType).toBe('oily');
  expect(buildSkinReport(p).concerns).toEqual(suggestConcerns(p));
  expect(suggestConcerns(p)).toContain('oiliness');
  expect(buildSkinRecommendationRequest(p, ['pores'])).toEqual({ concerns: ['pores'], limit: 8 });
  for (const fusion of [
    { ...p.fusion, scores: [.2, .3, .5] }, { ...p.fusion, reason: 'neutral' },
    { ...p.fusion, applied: false }, { ...p.fusion, signals: { dry: 0, oily: .5 } },
    { ...p.fusion, settings: { ...p.fusion.settings, maxAdjustment: .09 } },
  ]) {
    const bad = { ...p, fusion } as SkinProfileV4;
    await expect(writeSkinProfile(bad)).rejects.toThrow();
    await AsyncStorage.setItem(STORAGE_KEYS.skinProfile, JSON.stringify(bad));
    await expect(readSkinProfile()).rejects.toThrow();
  }
});


it('replays recorded v4 settings instead of reapplying current default values', async () => {
  const old = supportProfile();
  const q: SkinSurveyV3 = { ...old.questionnaire, postWashDryness: 'none', afternoonTzoneOil: 'marked', cheekState: 'oily', oilOnset: 'within1h' };
  const fusion = fuseSupportSkinType(old.analysis.skinType, q);
  const tuned = fuseSupportSkinType(old.analysis.skinType, q, { ...fusion.settings, maxAdjustment: .05 });
  const p: SkinProfileV4 = { ...old, version: 4, questionnaire: q, fusion: tuned };
  await writeSkinProfile(p);
  expect(await readSkinProfile()).toEqual(p);
  expect(buildSkinReport(p).skinType).toBe(tuned.type);
});
