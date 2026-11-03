/** Original item order and response categories; translations are not separately validated. */
export const SKIN_SURVEY_VERSION = 'sos-bstq-1' as const;
export const SKIN_SURVEY_SOURCES = {
  sos: { url: 'https://file.scirp.org/pdf/JCDSA_2014032011095563.pdf', table: 2, year: 2014,
    authors: 'Baumann LS, Penfield RD, Clarke JL, Duque DK', translationVersion: '1', translationValidated: false },
  bstq: { url: 'https://doi.org/10.5021/ad.2017.29.5.586', appendix: 1, part: 2, items: [1, 18],
    translationVersion: '1', translationValidated: false },
} as const;
export const SOS_QUESTIONS = ['afterWash', 'selfType', 'tzoneFrequency', 'cloggedPores', 'tzoneOnset', 'washFrequency'] as const;
export const SURVEY_QUESTIONS = [...SOS_QUESTIONS, 'redBumps', 'cosmeticReaction'] as const;
export const FOUR_CHOICES = ['a', 'b', 'c', 'd'] as const;
export const FIVE_CHOICES = [...FOUR_CHOICES, 'e'] as const;
export function surveyChoices(key: typeof SURVEY_QUESTIONS[number]) {
  return key === 'tzoneOnset' || key === 'washFrequency' || key === 'cosmeticReaction' ? FIVE_CHOICES : FOUR_CHOICES;
}

/** Custom support survey: concepts only, not SOS/BSTQ scoring or a validated abbreviated instrument. */
export const SKIN_SUPPORT_VERSION = 'skin-support-1' as const;
export const SKIN_SUPPORT_SOURCES = {
  sos: SKIN_SURVEY_SOURCES.sos.url,
  bstq: SKIN_SURVEY_SOURCES.bstq.url,
  koreanItemSelection: 'https://doi.org/10.1111/jocd.15820',
  uxReference: 'https://www.amoremall.com/kr/ko/display/event_detail?planDisplaySn=10347',
  validated: false,
} as const;
export const SUPPORT_CHOICES = {
  postWashDryness: ['none', 'mild', 'marked', 'unknown'],
  afternoonTzoneOil: ['none', 'slight', 'marked', 'unknown'],
  cheekState: ['dry', 'comfortable', 'oily', 'variable', 'unknown'],
  oilOnset: ['within1h', 'after1to3h', 'after3h', 'notNoticed', 'unknown'],
  cosmeticReaction: ['none', 'once', 'repeated', 'avoided', 'notUsed', 'unknown'],
} as const;
export const SUPPORT_QUESTIONS = ['postWashDryness', 'afternoonTzoneOil', 'cheekState', 'oilOnset', 'cosmeticReaction'] as const;
// Keep legacy answers readable; new entries use the narrower set shown in the survey.
export const SUPPORT_REACTION_CHOICES = ['none', 'once', 'repeated', 'unknown'] as const;
// Care-goal labels map onto the existing concern codes used by recommendations.
export const SUPPORT_PRIORITY_CONCERNS = ['dryness', 'sensitivity', 'pigmentation', 'wrinkles', 'pores'] as const;
