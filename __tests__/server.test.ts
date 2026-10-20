import { RateLimiter, TtlCache } from '@/server/cache';
import { toHttpsShoppingImage } from '@/server/naver';
import { buildTutorialQuery, decodeEntities } from '@/server/youtube';

describe('TtlCache', () => {
  it('de-duplicates concurrent loads and caches the result', async () => {
    const cache = new TtlCache<number>(60_000);
    const load = jest.fn(async () => 42);
    const [a, b] = await Promise.all([cache.getOrLoad('k', load), cache.getOrLoad('k', load)]);
    expect([a, b]).toEqual([42, 42]);
    await cache.getOrLoad('k', load);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('does not cache failures', async () => {
    const cache = new TtlCache<number>(60_000);
    await expect(cache.getOrLoad('k', async () => Promise.reject(new Error('x')))).rejects.toThrow('x');
    await expect(cache.getOrLoad('k', async () => 1)).resolves.toBe(1);
  });
});

describe('RateLimiter', () => {
  it('blocks after the limit within a window', () => {
    const limiter = new RateLimiter(2, 60_000);
    expect(limiter.allow('ip')).toBe(true);
    expect(limiter.allow('ip')).toBe(true);
    expect(limiter.allow('ip')).toBe(false);
    expect(limiter.allow('other')).toBe(true);
  });
});

describe('toHttpsShoppingImage', () => {
  it('rewrites Naver Shopping images to the HTTPS host and rejects other hosts', () => {
    expect(toHttpsShoppingImage('http://shopping.phinf.naver.net/main_1/2.jpg')).toBe(
      'https://shopping-phinf.pstatic.net/main_1/2.jpg'
    );
    expect(toHttpsShoppingImage('https://shopping-phinf.pstatic.net/main_1/2.jpg')).toBe(
      'https://shopping-phinf.pstatic.net/main_1/2.jpg'
    );
    expect(toHttpsShoppingImage('http://shop1.phinf.naver.net/20240101_1/a.jpg')).toBe(
      'https://shop-phinf.pstatic.net/20240101_1/a.jpg'
    );
    expect(toHttpsShoppingImage('https://i.pinimg.com/736x/a.jpg')).toBeNull();
  });
});

describe('youtube helpers', () => {
  it('appends tutorial keywords only when missing', () => {
    expect(buildTutorialQuery('Jisoo')).toBe('Jisoo makeup tutorial');
    expect(buildTutorialQuery('jisoo makeup')).toBe('jisoo makeup');
    expect(buildTutorialQuery('지수 메이크업')).toBe('지수 메이크업');
  });

  it('decodes HTML entities from API titles', () => {
    expect(decodeEntities('Tom &amp; Jerry&#39;s &quot;look&quot;')).toBe('Tom & Jerry\'s "look"');
  });
});
