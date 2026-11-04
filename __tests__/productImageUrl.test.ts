import { publicProductImageUrl } from '@/lib/productImageUrl';

describe('publicProductImageUrl', () => {
  it('inserts the missing slash in Olive Young thumbnail paths', () => {
    expect(
      publicProductImageUrl(
        'https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails10/0000/0016/A00000016209254ko.jpg'
      )
    ).toBe(
      'https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0016/A00000016209254ko.jpg'
    );
  });

  it('leaves working URLs and empty values unchanged', () => {
    const ok =
      'https://image.oliveyoung.co.kr/cfimages/cf-goods/uploads/images/thumbnails/10/0000/0016/A00000016209254ko.jpg';
    expect(publicProductImageUrl(ok)).toBe(ok);
    expect(publicProductImageUrl('https://shopping-phinf.pstatic.net/a.jpg')).toBe(
      'https://shopping-phinf.pstatic.net/a.jpg'
    );
    expect(publicProductImageUrl('')).toBe('');
    expect(publicProductImageUrl(undefined)).toBe('');
  });
});
