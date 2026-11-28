import {
  arHref,
  checkoutHref,
  lookPreviewHref,
  externalLinkHref,
  loginHref,
  paramValue,
  parseCategory,
  parseConcerns,
  parseCheckoutSelection,
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

test('direct checkout keeps both catalog IDs across auth routes', () => {
  const selection = { productId: 'p1', shadeId: '02' };
  expect(parseCheckoutSelection(selection)).toEqual(selection);
  expect(parseCheckoutSelection({ productId: 'p1', shadeId: 'invalid/shade' })).toBeUndefined();
  expect(checkoutHref(selection)).toEqual({ pathname: '/checkout', params: selection });
  expect(loginHref('checkout', selection)).toEqual({ pathname: '/login', params: { returnTo: 'checkout', ...selection } });
  expect(signupHref({ returnTo: 'checkout', selection })).toEqual({ pathname: '/signup', params: { returnTo: 'checkout', ...selection } });
});

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

  it('accepts known post-login destinations', () => {
    expect(parseLoginReturnTo('checkout')).toBe('checkout');
    expect(parseLoginReturnTo('membership')).toBe('membership');
    expect(parseLoginReturnTo('rewards')).toBe('rewards');
    expect(parseLoginReturnTo('/my')).toBeUndefined();
  });
});

describe('route builders pass ids, never names', () => {
  it('product detail keeps the exact shade', () => {
    expect(productHref('p1', '02')).toEqual({ pathname: '/product/[id]', params: { id: 'p1', shade: '02' } });
    expect(productHref('p1')).toEqual({ pathname: '/product/[id]', params: { id: 'p1' } });
    expect(productHref('p1', undefined, undefined, true)).toEqual({ pathname: '/product/[id]', params: { id: 'p1', requireShade: '1' } });
  });

  it('AR carries product + shade, and drops a shade without a product', () => {
    expect(arHref({ productId: 'p1', shadeId: '02' })).toEqual({ pathname: '/ar', params: { productId: 'p1', shadeId: '02' } });
    expect(arHref({ shadeId: '02', compare: true })).toEqual({ pathname: '/ar', params: { compare: '1' } });
  });

  it('look preview carries look id and optional title before video AR', () => {
    expect(lookPreviewHref({ lookId: 'style-ZAozXs-ZZik', title: 'Strawberry' })).toEqual({
      pathname: '/look-preview',
      params: { id: 'style-ZAozXs-ZZik', title: 'Strawberry' },
    });
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

  it('login links retain the requested destination', () => {
    expect(loginHref('rewards')).toEqual({ pathname: '/login', params: { returnTo: 'rewards' } });
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


it('carries sale option independently of shade in product links', () => {
  expect(productHref('p', undefined, undefined, true, 'sale-02')).toEqual({
    pathname: '/product/[id]', params: { id: 'p', requireShade: '1', optionId: 'sale-02' },
  });
});
