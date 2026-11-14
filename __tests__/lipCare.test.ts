import { isLipBaseCare, lipCareFor, lipCareKind, lipCareTint, lipTextureChip } from '@/lib/lipCare';
import { useMakeupStore } from '@/store/makeupStore';
import type { CelebLook, Product } from '@/types';

const named = (name: string) => ({ name, nameKo: name });

describe('lip care (oil / balm) detection', () => {
  it('finds oils and balms by name', () => {
    expect(lipCareKind(named('롬앤 쥬시 플래시 립 오일 (본품/미니)'))).toBe('oil');
    expect(lipCareKind(named('이니스프리 유채꿀 립밤 2종 중 택1 3.5G'))).toBe('balm');
    expect(lipCareKind(named('[NEW/단종부활템] 마몽드 크리미틴트 컬러 밤 7종'))).toBe('balm');
    expect(lipCareKind(named('Dior Lip Glow Oil'))).toBe('oil');
  });

  it('does not treat skincare, ordinary tints, sticks or cheek-and-lip pots as oil / balm', () => {
    expect(lipCareKind(named('토리든 솔리드인 세라마이드 립 에센스 11ml 더블기획/단품'))).toBeNull();
    expect(lipCareKind(named('라네즈 립 슬리핑 마스크 20g'))).toBeNull();
    expect(lipCareKind(named('롬앤 쥬시 래스팅 틴트'))).toBeNull();
    expect(lipCareKind(named('[청담샵템/립앤치크] 에이오유 매트바 4colors'))).toBeNull();
    expect(lipCareKind(named('클리오 에센셜 립치크 탭 4.5g 14종'))).toBeNull();
  });
});

describe('lip skincare is not in the AR lip tab', () => {
  it('flags essences, serums, ampoules and sleeping masks', () => {
    expect(isLipBaseCare(named('토리든 솔리드인 세라마이드 립 에센스 11ml 더블기획/단품'))).toBe(true);
    expect(isLipBaseCare(named('라네즈 립 슬리핑 마스크 20g'))).toBe(true);
    expect(isLipBaseCare(named('차앤박(CNP) 프로폴리스 립세린 15ml 7종'))).toBe(true);
  });

  it('keeps tinted serums and ordinary lip products as colour lips, and leaves oils / balms to the care chip', () => {
    expect(isLipBaseCare(named('[NEW/미니 뉴트럴로즈 증정] 로지킴 PDRN 틴티드 립 앰플 단품/기획 10ml 13colors'))).toBe(false);
    expect(isLipBaseCare(named('롬앤 쥬시 래스팅 틴트'))).toBe(false);
    expect(isLipBaseCare(named('에뛰드 진저슈가 오버나이트 립 마스크 밤'))).toBe(false);
  });
});

describe('lip finish chips', () => {
  it('folds seven finishes into four', () => {
    expect(lipTextureChip('velvet')).toBe('matte');
    expect(lipTextureChip('matte')).toBe('matte');
    expect(lipTextureChip('satin')).toBe('cream');
    expect(lipTextureChip('cream')).toBe('cream');
    expect(lipTextureChip('sheer')).toBe('glossy');
    expect(lipTextureChip('glossy')).toBe('glossy');
    expect(lipTextureChip('shimmer')).toBe('shimmer');
    expect(lipTextureChip(null)).toBeNull();
  });
});

describe('lip care tint', () => {
  it('is 0 for packaging-colour chips (yellow, blue, pale blue, white, grey)', () => {
    expect(lipCareTint({ hex: '#ECDDAE' })).toBe(0);
    expect(lipCareTint({ hex: '#0242B5' })).toBe(0);
    expect(lipCareTint({ hex: '#C5E8F1' })).toBe(0);
    expect(lipCareTint({ hex: '#E1E1E1' })).toBe(0);
  });

  it('is 0 for a placeholder colour and scaled down for a doubtful one', () => {
    expect(lipCareTint({ hex: '#D75C6F', colorSource: 'placeholder' })).toBe(0);
    const sure = lipCareTint({ hex: '#D75C6F', colorConfidence: 0.9 });
    expect(lipCareTint({ hex: '#D75C6F', colorConfidence: 0.35 })).toBeCloseTo(sure * 0.5, 1);
  });

  it('grows with the chroma of a lip-like chip', () => {
    expect(lipCareTint({ hex: '#D75C6F' })).toBeGreaterThan(0.7);
    const pale = lipCareTint({ hex: '#F1C7CF' });
    expect(pale).toBeGreaterThan(0);
    expect(pale).toBeLessThan(0.3);
  });

  it('lipCareFor returns the care field only for an oil / balm', () => {
    expect(lipCareFor(named('이니스프리 유채꿀 립밤'), { hex: '#ECDDAE' })).toEqual({ kind: 'balm', tint: 0 });
    expect(lipCareFor(named('롬앤 쥬시 래스팅 틴트'), { hex: '#D75C6F' })).toBeUndefined();
  });
});

describe('lip care layer in the store', () => {
  const colour = (id: string, hex: string) =>
    ({ id, name: `${id} 틴트`, nameKo: `${id} 틴트`, makeupZone: 'lip', texture: 'matte', shades: [{ id: 's', name: 's', hex }] }) as unknown as Product;
  const care = (id: string, name: string, hex: string) =>
    ({ id, name, nameKo: name, makeupZone: 'lip', texture: 'glossy', shades: [{ id: 's', name: 's', hex }] }) as unknown as Product;
  const red = colour('red', '#B3202E');
  const coral = colour('coral', '#E4614F');
  const oil = care('oil', '롬앤 립 오일', '#C5E8F1');
  const balm = care('balm', '이니스프리 립밤', '#F1C7CF');
  const store = () => useMakeupStore.getState();
  const apply = (p: Product) => store().applyShade(p, p.shades[0]);

  beforeEach(() => store().reset());

  it('puts the oil over the colour lip without touching the colour', () => {
    apply(red);
    apply(oil);
    expect(store().makeup.lip?.hex).toBe('#B3202E');
    expect(store().makeup.lipCare?.care).toEqual({ kind: 'oil', tint: 0 });
    expect(store().selections.lip?.productId).toBe('red');
    expect(store().careSelection?.productId).toBe('oil');
  });

  it('keeps one care product at a time: a balm replaces the oil', () => {
    apply(red);
    apply(oil);
    apply(balm);
    expect(store().makeup.lipCare?.care?.kind).toBe('balm');
    expect(store().careSelection?.productId).toBe('balm');
  });

  it('replaces the colour lip with another colour (no mixing) and keeps the care layer', () => {
    apply(red);
    apply(oil);
    apply(coral);
    expect(store().makeup.lip?.hex).toBe('#E4614F');
    expect(store().selections.lip?.productId).toBe('coral');
    expect(store().makeup.lipCare?.care?.kind).toBe('oil');
  });

  it('takes the colour off alone, and the care layer off alone', () => {
    apply(red);
    apply(oil);
    store().clearZone('lip');
    expect(store().makeup.lip).toBeNull();
    expect(store().selections.lip).toBeUndefined();
    expect(store().makeup.lipCare).not.toBeNull();
    store().clearLipCare();
    expect(store().makeup.lipCare).toBeNull();
    expect(store().careSelection).toBeNull();
  });

  it('allows a care product on the bare lip', () => {
    apply(balm);
    expect(store().makeup.lip).toBeNull();
    expect(store().makeup.lipCare?.care?.kind).toBe('balm');
  });

  it('reset clears the care layer', () => {
    apply(oil);
    store().reset();
    expect(store().makeup.lipCare ?? null).toBeNull();
    expect(store().careSelection).toBeNull();
  });

  it('turns a look lip made of a care product into the care layer', () => {
    const look = {
      id: 'l', title: 'L', items: [{ productId: 'balm', shadeId: 's', step: 'lips' }],
      makeup: { lip: { hex: '#F1C7CF', intensity: 0.7, texture: 'glossy' } },
    } as unknown as CelebLook;
    store().applyLook(look, [balm]);
    expect(store().makeup.lip).toBeNull();
    expect(store().makeup.lipCare?.care?.kind).toBe('balm');
    expect(store().careSelection?.productId).toBe('balm');
    expect(store().selections.lip).toBeUndefined();
  });
});
