import { adjustMakeupFromChat } from '@/lib/arChatAdjust';
import type { MakeupState, Product } from '@/types';

const emptyMakeup = {} as MakeupState;

const lip: Product = {
  id: 'oy-lip',
  brand: 'Brand',
  name: 'Lip',
  nameKo: '립',
  category: 'lip',
  makeupZone: 'lip',
  texture: 'satin',
  priceKRW: 10000,
  volume: '1',
  shades: [
    { id: 'dark', name: 'dark', hex: '#5A2020' },
    { id: 'light', name: 'light', hex: '#F2C4B8' },
    { id: 'coral', name: 'coral', hex: '#E8836A' },
  ],
  description: '',
  keyIngredients: [],
  tags: [],
  imageUrl: '',
  searchKeyword: 'lip',
};

describe('adjustMakeupFromChat', () => {
  it('picks a lighter catalog lip without inventing a hex', () => {
    const result = adjustMakeupFromChat('립스틱 좀 더 연한 거 없어?', [lip], {
      ...emptyMakeup,
      lip: { hex: '#5A2020', texture: 'satin', intensity: 0.6 },
    });
    expect(result.kind).toBe('shade');
    if (result.kind !== 'shade') return;
    expect(result.shade.hex).not.toBe('#5A2020');
    expect(result.shade.hex).toMatch(/^#[0-9A-F]{6}$/i);
  });

  it('leaves blush intensity adjustments to AR Action', () => {
    const result = adjustMakeupFromChat('블러셔를 조금 더 은은하게 해줘', [lip], {
      ...emptyMakeup,
      blush: { hex: '#E8A0A0', texture: 'sheer', intensity: 0.5 },
    });
    expect(result).toEqual({ kind: 'none' });
  });

  it('applies an existing coral catalog shade', () => {
    const result = adjustMakeupFromChat('코랄 룩 보여줘', [lip], emptyMakeup);
    expect(result.kind).toBe('shade');
    if (result.kind !== 'shade') return;
    expect(result.shade.id).toBe('coral');
  });
});
