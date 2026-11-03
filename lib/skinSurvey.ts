import { SKIN_SURVEY_VERSION, SURVEY_QUESTIONS, SOS_QUESTIONS, surveyChoices, SKIN_SUPPORT_VERSION, SUPPORT_CHOICES, SUPPORT_QUESTIONS } from '@/constants/skinSurvey';
import type { SkinSurveyV2, SkinSurveyV3 } from '@/types/skin';
import { SKIN_CONCERNS } from './routes';

export function isCompleteSkinSurvey(value: unknown): value is SkinSurveyV2 {
  if (!value || typeof value !== 'object') return false;
  const q = value as SkinSurveyV2;
  return q.version === SKIN_SURVEY_VERSION && SURVEY_QUESTIONS.every(key =>
    (surveyChoices(key) as readonly unknown[]).includes(q[key])) && SKIN_CONCERNS.includes(q.priority);
}
export function scoreSos(value: SkinSurveyV2): number {
  if (!isCompleteSkinSurvey(value)) throw new Error('Incomplete skin survey');
  return SOS_QUESTIONS.reduce((total, key) => total + value[key].charCodeAt(0) - 96, 0);
}
export function surveySensitivity(q: SkinSurveyV2 | SkinSurveyV3): 'care' | 'good' | 'unknown' {
  if (q.version === SKIN_SUPPORT_VERSION) {
    return ['unknown', 'notUsed'].includes(q.cosmeticReaction) ? 'unknown'
      : ['repeated', 'avoided'].includes(q.cosmeticReaction) ? 'care' : q.cosmeticReaction === 'once' ? 'unknown' : 'good';
  }
  return q.cosmeticReaction === 'e' ? 'unknown' : ['c', 'd'].includes(q.cosmeticReaction) ? 'care' : 'good';
}

export function isCompleteSupportSurvey(value: unknown): value is SkinSurveyV3 {
  if (!value || typeof value !== 'object') return false;
  const q = value as SkinSurveyV3;
  return q.version === SKIN_SUPPORT_VERSION && SUPPORT_QUESTIONS.every(key =>
    (SUPPORT_CHOICES[key] as readonly unknown[]).includes(q[key])) && SKIN_CONCERNS.includes(q.priority) &&
    Object.keys(q).every(key => key === 'version' || key === 'priority' || (SUPPORT_QUESTIONS as readonly string[]).includes(key));
}
