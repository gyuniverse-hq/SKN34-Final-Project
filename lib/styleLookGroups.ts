import type { TranslationKey } from '@/lib/i18n';

const GROUP_LABELS: Record<string, TranslationKey> = {
  '컬러·톤 스타일': 'styleLooks.color',
  '콘셉트·분위기': 'styleLooks.mood',
  '시즌·데일리': 'styleLooks.season',
  '보정·맞춤': 'styleLooks.custom',
  '데일리·활용': 'styleLooks.daily',
  '베이스·피부 표현': 'styleLooks.base',
  '아이 메이크업': 'styleLooks.eye',
};

export function styleLookGroupLabel(group: string, t: (key: TranslationKey) => string): string {
  const key = GROUP_LABELS[group];
  return key ? t(key) : group;
}

const ZONE_LABELS: Record<string, TranslationKey> = {
  '베이스·윤곽': 'styleLooks.zone.base',
  '립': 'styleLooks.zone.lip',
  '입술': 'styleLooks.zone.lip',
  '얼굴': 'celebVideo.zone.face',
  '볼': 'styleLooks.zone.cheek',
  '메이크업 도구': 'styleLooks.zone.tools',
  '모발': 'celebVideo.zone.hair',
  '피부': 'styleLooks.zone.skin',
  '아이섀도': 'styleLooks.zone.shadow',
  '아이라인': 'styleLooks.zone.liner',
  '치크': 'styleLooks.zone.cheek',
  '눈썹': 'styleLooks.zone.brow',
  '속눈썹': 'styleLooks.zone.lash',
  '눈': 'styleLooks.zone.eye',
  '도구·액세서리': 'styleLooks.zone.tools',
  '확인 필요': 'styleLooks.zone.other',
};

export function styleLookZoneLabel(zone: string, t: (key: TranslationKey) => string): string {
  const key = ZONE_LABELS[zone];
  return key ? t(key) : zone;
}

const SOURCE_LABELS: Record<string, TranslationKey> = {
  '제품제공': 'celebVideo.source.provided',
  '직접구매': 'celebVideo.source.purchased',
  '유료광고': 'celebVideo.source.ad',
  '선물': 'celebVideo.source.gift',
};

export function celebrityProductSourceLabel(source: string, t: (key: TranslationKey) => string): string | null {
  const key = SOURCE_LABELS[source];
  return key ? t(key) : null;
}
