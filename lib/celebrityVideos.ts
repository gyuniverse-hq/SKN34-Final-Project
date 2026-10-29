import type { CelebrityId } from '@/constants/celebrities';
import type { YoutubeVideo } from '@/types';

/** Add only videos selected for each celebrity. Empty lists mean no videos have been added yet. */
export const CELEBRITY_VIDEOS: Record<CelebrityId, YoutubeVideo[]> = {
  karina: [],
  wonyoung: [],
  sullyoon: [],
  winter: [],
  jennie: [],
  haerin: [],
  wony: [],
};
