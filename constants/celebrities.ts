export const CELEBRITIES = [
  { id: 'karina', nameKey: 'celebrity.karina', group: 'aespa', image: require('@/assets/images/celebrities/karina.jpeg'), credit: null },
  { id: 'wonyoung', nameKey: 'celebrity.wonyoung', group: 'IVE', image: require('@/assets/images/celebrities/wonyoung.jpeg'), credit: null },
  { id: 'sullyoon', nameKey: 'celebrity.sullyoon', group: 'NMIXX', image: require('@/assets/images/celebrities/sullyoon.jpeg'), credit: null },
  { id: 'winter', nameKey: 'celebrity.winter', group: 'aespa', image: require('@/assets/images/celebrities/winter.jpeg'), credit: null },
  { id: 'jennie', nameKey: 'celebrity.jennie', group: 'BLACKPINK', image: require('@/assets/images/celebrities/jennie.jpg'), credit: null },
  { id: 'haerin', nameKey: 'celebrity.haerin', group: 'NewJeans', image: require('@/assets/images/celebrities/haerin.jpeg'), credit: null },
  { id: 'wony', nameKey: 'celebrity.wony', group: '', image: require('@/assets/images/celebrities/wony.jpeg'), credit: null },
] as const;

export type CelebrityId = Celebrity['id'];
export type Celebrity = Omit<(typeof CELEBRITIES)[number], 'credit'> & {
  credit: { file: string; author: string; license: string } | null;
};

export function celebrityImageSource(file: string): string {
  return `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(file.replaceAll(' ', '_'))}`;
}
