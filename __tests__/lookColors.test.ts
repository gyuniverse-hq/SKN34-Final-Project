import { availableColorFamilies, colorFamilyOf, lookColorFamily } from '@/lib/lookColors';
import type { CelebLook, MakeupState } from '@/types';

function look(id: string, makeup: Partial<MakeupState>): CelebLook {
  return {
    id,
    title: id,
    inspiration: '',
    description: '',
    thumbnailUrl: '',
    tutorialQuery: '',
    items: [],
    makeup: { lip: null, blush: null, eyeshadow: null, ...makeup },
    tags: [],
  };
}

const zone = (hex: string) => ({ hex, intensity: 0.5, texture: 'matte' as const });

describe('look colour families', () => {
  it('classifies catalogue shades into shopper-facing families', () => {
    expect(colorFamilyOf('#E58C7A')).toBe('coral');
    expect(colorFamilyOf('#D9675A')).toBe('coral');
    expect(colorFamilyOf('#B5505E')).toBe('rosy');
    expect(colorFamilyOf('#C9636F')).toBe('rosy');
    expect(colorFamilyOf('#C8102E')).toBe('red');
    expect(colorFamilyOf('#6B4A3A')).toBe('brown');
    expect(colorFamilyOf('#8F6B66')).toBe('mute');
  });

  it('ignores invalid hex values and non-makeup hues', () => {
    expect(colorFamilyOf('rose')).toBeNull();
    expect(colorFamilyOf('#3A7BD5')).toBeNull();
  });

  it('uses the lip colour first, then blush, then eyeshadow', () => {
    expect(lookColorFamily(look('a', { lip: zone('#C8102E'), blush: zone('#E58C7A') }))).toBe('red');
    expect(lookColorFamily(look('b', { blush: zone('#E58C7A'), eyeshadow: zone('#6B4A3A') }))).toBe('coral');
    expect(lookColorFamily(look('c', {}))).toBeNull();
  });

  it('offers only families that have at least one look, in display order', () => {
    const looks = [look('a', { lip: zone('#E58C7A') }), look('b', { lip: zone('#B5505E') }), look('c', {})];
    expect(availableColorFamilies(looks)).toEqual(['rosy', 'coral']);
  });
});
