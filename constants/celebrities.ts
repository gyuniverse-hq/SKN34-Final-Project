export const CELEBRITIES = [
  { id: 'karina', nameKey: 'celebrity.karina', group: 'aespa', image: require('@/assets/images/celebrities/karina.jpeg'), credit: null },
  { id: 'wonyoung', nameKey: 'celebrity.wonyoung', group: 'IVE', image: require('@/assets/images/celebrities/wonyoung.jpeg'), credit: null },
  { id: 'sullyoon', nameKey: 'celebrity.sullyoon', group: 'NMIXX', image: require('@/assets/images/celebrities/sullyoon.jpeg'), credit: null },
  { id: 'winter', nameKey: 'celebrity.winter', group: 'aespa', image: require('@/assets/images/celebrities/winter.jpeg'), credit: null },
  { id: 'jennie', nameKey: 'celebrity.jennie', group: 'BLACKPINK', image: require('@/assets/images/celebrities/jennie.jpg'), credit: null },
  { id: 'haerin', nameKey: 'celebrity.haerin', group: 'NewJeans', image: require('@/assets/images/celebrities/haerin.jpeg'), credit: null },
  { id: 'wony', nameKey: 'celebrity.wony', group: 'RESCENE', image: require('@/assets/images/celebrities/wony.jpeg'), credit: null },
] as const;

export type CelebrityId = Celebrity['id'];
export const CELEBRITY_BACKGROUNDS: Record<CelebrityId, string> = {
  karina: '#D4DFD9',
  wonyoung: '#F3CFBD',
  sullyoon: '#E8DCC6',
  winter: '#D6DDEC',
  jennie: '#EACBD1',
  haerin: '#D4E0E5',
  wony: '#E1D7E9',
};

export const CELEBRITY_PORTRAITS: Record<CelebrityId, number> = {
  wonyoung: require('@/assets/images/home/wonyoung.webp'),
  karina: require('@/assets/images/home/karina.webp'),
  sullyoon: require('@/assets/images/home/sullyoon.webp'),
  winter: require('@/assets/images/home/winter.webp'),
  jennie: require('@/assets/images/home/jennie.webp'),
  haerin: require('@/assets/images/home/haerin.webp'),
  wony: require('@/assets/images/home/wony.webp'),
};

export type Celebrity = Omit<(typeof CELEBRITIES)[number], 'credit'> & {
  credit: { file: string; author: string; license: string } | null;
};

export function celebrityImageSource(file: string): string {
  return `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(file.replaceAll(' ', '_'))}`;
}
