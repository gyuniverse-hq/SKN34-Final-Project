import { adjustMakeupFromChat } from '@/lib/arChatAdjust';
import type { MakeupState, MakeupZone, Product, ZoneSetting } from '@/types';

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

const paint = (zones: MakeupZone[]): MakeupState => {
  const setting = (): ZoneSetting => ({ hex: '#C08080', texture: 'satin', intensity: 0.5 });
  const makeup = { ...emptyMakeup };
  for (const zone of zones) makeup[zone] = setting();
  return makeup;
};

const allPainted = paint([
  'lip',
  'blush',
  'eyeshadow',
  'eyeliner',
  'highlighter',
  'contour',
  'mascara',
]);

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

  it('does not invent a hex when the painted zone is missing', () => {
    expect(adjustMakeupFromChat('하이라이터 애교살', [lip], emptyMakeup).kind).toBe('none');
  });

  it('ignores a compound style request instead of guessing', () => {
    expect(adjustMakeupFromChat('하이라이터 애교살이랑 쉐딩 턱선', [lip], allPainted).kind).toBe(
      'none'
    );
  });
});

const geometryCases: { text: string; zone: MakeupZone; key: string; value: unknown }[] = [
  { text: '하이라이터 내추럴 광대', zone: 'highlighter', key: 'hlStyle', value: 'natural_cheek' },
  { text: 'highlighter natural cheek', zone: 'highlighter', key: 'hlStyle', value: 'natural_cheek' },
  { text: '하이라이터 물광 C존', zone: 'highlighter', key: 'hlStyle', value: 'glass_c_zone' },
  { text: 'highlighter c-zone glow', zone: 'highlighter', key: 'hlStyle', value: 'glass_c_zone' },
  { text: 'ハイライト Cゾーン', zone: 'highlighter', key: 'hlStyle', value: 'glass_c_zone' },
  { text: '高光C区', zone: 'highlighter', key: 'hlStyle', value: 'glass_c_zone' },
  { text: '하이라이터 콧대', zone: 'highlighter', key: 'hlStyle', value: 'nose_tip' },
  { text: 'highlighter on the nose', zone: 'highlighter', key: 'hlStyle', value: 'nose_tip' },
  { text: '하이라이터 코끝', zone: 'highlighter', key: 'hlStyle', value: 'nose_tip' },
  { text: '애교살 하이라이터', zone: 'highlighter', key: 'hlStyle', value: 'under_eye_smile' },
  { text: 'highlighter under-eye', zone: 'highlighter', key: 'hlStyle', value: 'under_eye_smile' },
  { text: '卧蚕高光', zone: 'highlighter', key: 'hlStyle', value: 'under_eye_smile' },
  { text: '큐피드 활 하이라이터', zone: 'highlighter', key: 'hlStyle', value: 'cupid_bow' },
  { text: 'highlighter cupid bow', zone: 'highlighter', key: 'hlStyle', value: 'cupid_bow' },
  { text: '하이라이터 이마', zone: 'highlighter', key: 'hlStyle', value: 'forehead_center' },
  { text: 'highlighter forehead', zone: 'highlighter', key: 'hlStyle', value: 'forehead_center' },
  { text: '쉐딩 턱라인', zone: 'contour', key: 'contourStyle', value: 'jawline' },
  { text: '쉐딩 턱선', zone: 'contour', key: 'contourStyle', value: 'jawline' },
  { text: '쉐딩 v라인', zone: 'contour', key: 'contourStyle', value: 'jawline' },
  { text: 'contour jawline', zone: 'contour', key: 'contourStyle', value: 'jawline' },
  { text: '修容下颌', zone: 'contour', key: 'contourStyle', value: 'jawline' },
  { text: '쉐딩 콧대', zone: 'contour', key: 'contourStyle', value: 'nose' },
  { text: 'contour the nose', zone: 'contour', key: 'contourStyle', value: 'nose' },
  { text: '아이라인 캣윙', zone: 'eyeliner', key: 'length', value: 0.3 },
  { text: 'eyeliner cat wing', zone: 'eyeliner', key: 'length', value: 0.3 },
  { text: '아이라인 강아지', zone: 'eyeliner', key: 'linerStyle', value: 'puppy' },
  { text: 'eyeliner puppy', zone: 'eyeliner', key: 'linerStyle', value: 'puppy' },
  { text: '아이라인 스모키', zone: 'eyeliner', key: 'linerSoftness', value: 0.8 },
  { text: '아이라인 갸루', zone: 'eyeliner', key: 'length', value: 0.35 },
  { text: '아이라인 언더 포인트', zone: 'eyeliner', key: 'linerLower', value: true },
  { text: '아이라인 내추럴', zone: 'eyeliner', key: 'length', value: 0 },
  { text: '블러셔 광대', zone: 'blush', key: 'blushPlacement', value: 'apple' },
  { text: 'blush apple', zone: 'blush', key: 'blushPlacement', value: 'apple' },
  { text: '블러셔 눈 밑', zone: 'blush', key: 'blushPlacement', value: 'under_eye' },
  { text: '블러셔 귀쪽', zone: 'blush', key: 'blushPlacement', value: 'side' },
  { text: '아이섀도 글리터', zone: 'eyeshadow', key: 'shadowFinish', value: 'glitter' },
  { text: 'eyeshadow shimmer', zone: 'eyeshadow', key: 'shadowFinish', value: 'shimmer' },
  { text: '아이섀도 쉬머', zone: 'eyeshadow', key: 'shadowFinish', value: 'shimmer' },
  { text: '아이섀도 매트', zone: 'eyeshadow', key: 'shadowFinish', value: 'matte' },
  { text: '아이섀도 글로시', zone: 'eyeshadow', key: 'shadowFinish', value: 'glossy' },
  { text: '오버립으로 해줘', zone: 'lip', key: 'overlip', value: 0.03 },
  { text: 'lip overline', zone: 'lip', key: 'overlip', value: 0.03 },
  { text: '풀립으로', zone: 'lip', key: 'overlip', value: 0 },
  { text: '입술 중앙 하이라이트', zone: 'lip', key: 'centerHighlight', value: 0.15 },
  { text: '마스카라 슬림', zone: 'mascara', key: 'length', value: 1.28 },
  { text: '마스카라 파인', zone: 'mascara', key: 'lower', value: false },
  { text: '마스카라 킬래쉬', zone: 'mascara', key: 'length', value: 1.45 },
  { text: '마스카라 컬픽스', zone: 'mascara', key: 'length', value: 1.48 },
  { text: '마스카라 스키니', zone: 'mascara', key: 'thickness', value: 1.3 },
];

describe('adjustMakeupFromChat geometry utterances', () => {
  it.each(geometryCases)('$text', ({ text, zone, key, value }) => {
    const result = adjustMakeupFromChat(text, [lip], allPainted);
    expect(result.kind).toBe('geometry');
    if (result.kind !== 'geometry') return;
    expect(result.zone).toBe(zone);
    expect(result.geometry[key as keyof typeof result.geometry]).toBe(value);
  });
});

const intensityCases: { text: string; zone: MakeupZone; intensity: number }[] = [
  { text: '하이라이터 연하게', zone: 'highlighter', intensity: 0.32 },
  { text: 'highlighter lighter', zone: 'highlighter', intensity: 0.32 },
  { text: '하이라이터 진하게', zone: 'highlighter', intensity: 0.68 },
  { text: '쉐딩 연하게', zone: 'contour', intensity: 0.32 },
  { text: 'contour stronger', zone: 'contour', intensity: 0.68 },
  { text: '아이라인 진하게', zone: 'eyeliner', intensity: 0.68 },
  { text: '마스카라 연하게', zone: 'mascara', intensity: 0.32 },
];

describe('adjustMakeupFromChat intensity utterances', () => {
  it.each(intensityCases)('$text', ({ text, zone, intensity }) => {
    expect(adjustMakeupFromChat(text, [lip], allPainted)).toEqual({
      kind: 'intensity',
      zone,
      intensity,
    });
  });
});
