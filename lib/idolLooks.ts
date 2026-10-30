import type { CelebLook, IdolLook, LookItem, MakeupZone } from '@/types';

const STEP_BY_ZONE: Record<MakeupZone, LookItem['step']> = {
  lip: 'lips',
  blush: 'cheeks',
  eyeshadow: 'eyes',
  eyeliner: 'eyes',
  mascara: 'eyes',
  brow: 'eyes',
  highlighter: 'cheeks',
  contour: 'cheeks',
  foundation: 'base',
};

/** Customer-facing collections show only looks whose video metadata the catalog has verified. */
export function displayableIdolLooks(looks: IdolLook[] | undefined): IdolLook[] {
  return looks?.filter((look) => look.video.analysisStatus === 'metadata_ready') ?? [];
}

export function hasIdolLookArSettings(look: IdolLook): boolean {
  return Boolean(look.arSettings.lip || look.arSettings.blush || look.arSettings.eyeshadow);
}

export function idolLookAsCelebLook(look: IdolLook): CelebLook {
  return {
    id: look.id,
    title: look.displayName,
    inspiration: '',
    description: look.styleDescription,
    thumbnailUrl: look.video.thumbnailUrl,
    tutorialQuery: '',
    items: look.products.flatMap((item) =>
      item.productId && item.shadeId
        ? [{
            productId: item.productId,
            shadeId: item.shadeId,
            step: STEP_BY_ZONE[item.makeupZone],
          }]
        : []
    ),
    makeup: look.arSettings,
    tags: [],
  };
}
