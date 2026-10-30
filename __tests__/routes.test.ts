import {
  arHref,
  externalLinkHref,
  loginHref,
  paramValue,
  parseCategory,
  parseConcerns,
  parseFlag,
  parseId,
  parseIntensity,
  parseLoginReturnTo,
  parseSearchSource,
  parseZone,
  productHref,
  recommendationsHref,
  searchHref,
  signupHref,
} from '@/lib/routes';

describe('route param parsing', () => {
  it('takes the first trimmed value of repeated params', () => {
    expect(paramValue(['a', 'b'])).toBe('a');
    expect(paramValue('  x ')).toBe('x');
    expect(paramValue('   ')).toBeUndefined();
    expect(paramValue(undefined)).toBeUndefined();
  });

  it('accepts catalog-style ids only', () => {
    expect(parseId('romand-juicy-tint')).toBe('romand-juicy-tint');
    expect(parseId('LOOK-001')).toBe('LOOK-001');
    expect(parseId('06')).toBe('06');
    expect(parseId('../etc')).toBeUndefined();
    expect(parseId('a b')).toBeUndefined();
    expect(parseId('x'.repeat(65))).toBeUndefined();
  });

  it('rejects unknown zones, categories and sources', () => {
    expect(parseZone('blush')).toBe('blush');
    expect(parseZone('cheek')).toBeUndefined();
    expect(parseCategory('suncare')).toBe('suncare');
    expect(parseCategory('perfume')).toBeUndefined();
    expect(parseSearchSource('skin')).toBe('skin');
    expect(parseSearchSource('ads')).toBeUndefined();
  });

  it('keeps known concerns in canonical order without duplicates', () => {
    expect(parseConcerns('pores,dryness,cancer,pores')).toEqual(['dryness', 'pores']);
    expect(parseConcerns(undefined)).toEqual([]);
  });

  it('bounds AR intensity to 0..1', () => {
    expect(parseIntensity('0.65')).toBe(0.65);
    expect(parseIntensity('1.5')).toBeUndefined();
    expect(parseIntensity('abc')).toBeUndefined();
    expect(parseFlag('1')).toBe(true);
    expect(parseFlag('true')).toBe(false);
  });

  it('only allows checkout as a post-login destination', () => {
    expect(parseLoginReturnTo('checkout')).toBe('checkout');
    expect(parseLoginReturnTo('/my')).toBeUndefined();
  });
});

describe('route builders pass ids, never names', () => {
  it('product detail keeps the exact shade', () => {
    expect(productHref('p1', '02')).toEqual({ pathname: '/product/[id]', params: { id: 'p1', shade: '02' } });
    expect(productHref('p1')).toEqual({ pathname: '/product/[id]', params: { id: 'p1' } });
  });

  it('AR carries product + shade, and drops a shade without a product', () => {
    expect(arHref({ productId: 'p1', shadeId: '02' })).toEqual({ pathname: '/ar', params: { productId: 'p1', shadeId: '02' } });
    expect(arHref({ shadeId: '02', compare: true })).toEqual({ pathname: '/ar', params: { compare: '1' } });
  });

  it('recommendations carry product, shade, zone and intensity', () => {
    expect(recommendationsHref({ productId: 'p1', shadeId: '02', zone: 'lip', intensity: 0.6 })).toEqual({
      pathname: '/recommendations',
      params: { productId: 'p1', shadeId: '02', zone: 'lip', intensity: '0.60' },
    });
  });

  it('search round-trips concerns through the parser', () => {
    const href = searchHref({ q: ' tint ', concerns: ['pores', 'dryness'], source: 'skin' }) as {
      params: Record<string, string>;
    };
    expect(href.params).toEqual({ q: 'tint', concerns: 'dryness,pores', source: 'skin' });
    expect(parseConcerns(href.params.concerns)).toEqual(['dryness', 'pores']);
    expect((searchHref() as { params: object }).params).toEqual({});
  });

  it('external link screen receives the product and its offer link', () => {
    expect(externalLinkHref('p1', 'https://shop.example/x')).toEqual({
      pathname: '/external-link',
      params: { productId: 'p1', link: 'https://shop.example/x' },
    });
  });

  it('login return links are limited to the checkout flow', () => {
    expect(loginHref('checkout')).toEqual({ pathname: '/login', params: { returnTo: 'checkout' } });
  });

  it('sign-up links keep the return target and open the code step only with an email', () => {
    expect(signupHref()).toEqual({ pathname: '/signup', params: {} });
    expect(signupHref({ returnTo: 'checkout' })).toEqual({ pathname: '/signup', params: { returnTo: 'checkout' } });
    expect(signupHref({ returnTo: 'checkout', verifyEmail: 'a@b.co' })).toEqual({
      pathname: '/signup',
      params: { returnTo: 'checkout', email: 'a@b.co', verify: '1' },
    });
  });
});
