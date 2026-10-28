import { colorFamily, hexToLab } from '@/lib/colorFamily';

describe('colorFamily', () => {
  it('converts white and black to the ends of CIELAB lightness', () => {
    expect(hexToLab('#FFFFFF').L).toBeCloseTo(100, 0);
    expect(hexToLab('#000000').L).toBeCloseTo(0, 0);
  });

  it.each([
    ['#B3202E', 'red'],
    ['#DD5A59', 'red'],
    ['#E06A4E', 'coral'],
    ['#F08070', 'coral'],
    ['#C25A6E', 'pink'],
    ['#E85A8C', 'pink'],
    ['#7E2A4A', 'berry'],
    ['#8B3A62', 'berry'],
    ['#C08A7A', 'nude'],
    ['#D4A5A0', 'nude'],
    ['#5C2A22', 'brown'],
  ])('%s is %s', (hex, family) => {
    expect(colorFamily(hex)).toBe(family);
  });
});
