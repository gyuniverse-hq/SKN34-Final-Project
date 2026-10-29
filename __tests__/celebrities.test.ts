import { CELEBRITIES } from '@/constants/celebrities';
import { CELEBRITY_VIDEOS } from '@/lib/celebrityVideos';
import { celebrityHref } from '@/lib/routes';

describe('celebrity collection', () => {
  it('keeps an independent video list and detail route for each requested celebrity', () => {
    expect(CELEBRITIES.map(({ id }) => id)).toEqual([
      'karina', 'wonyoung', 'sullyoon', 'winter', 'jennie', 'haerin', 'wony',
    ]);
    for (const celebrity of CELEBRITIES) {
      expect(celebrityHref(celebrity.id)).toEqual({ pathname: '/celebrities/[id]', params: { id: celebrity.id } });
      expect(Array.isArray(CELEBRITY_VIDEOS[celebrity.id])).toBe(true);
    }
  });
});
