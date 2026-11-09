import { colorFamily, hexToLab } from '@/lib/colorFamily';
import { geometryFromStyle } from './zoneRecipe';
import type { MakeupState, MakeupZone, Product, Shade, ZoneGeometry } from '@/types';

export type ArChatResult =
  | { kind: 'shade'; zone: MakeupZone; product: Product; shade: Shade }
  | { kind: 'intensity'; zone: MakeupZone; intensity: number }
  | { kind: 'geometry'; zone: MakeupZone; geometry: ZoneGeometry }
  | { kind: 'none' };

type TryOn = { product: Product; shade: Shade };

type StyleRule = { zone: MakeupZone; style: string; zoneRe: RegExp; styleRe: RegExp };

const STYLE_RULES: StyleRule[] = [
  { zone: 'highlighter', style: 'glass_c_zone', zoneRe: /하이라이터|highlighter|ハイライト|高光/, styleRe: /c존|씨존|c-?zone|cゾーン|ｃゾーン|c区/ },
  { zone: 'highlighter', style: 'under_eye_smile', zoneRe: /하이라이터|highlighter|ハイライト|高光|애교/, styleRe: /애교살|under-?eye|卧蚕|卧蠶|目の下/ },
  { zone: 'highlighter', style: 'cupid_bow', zoneRe: /하이라이터|highlighter|ハイライト|高光|큐피드|인중/, styleRe: /큐피드|인중|cupid|人中/ },
  { zone: 'highlighter', style: 'forehead_center', zoneRe: /하이라이터|highlighter|ハイライト|高光/, styleRe: /이마|forehead|額|额头/ },
  { zone: 'highlighter', style: 'nose_tip', zoneRe: /하이라이터|highlighter|ハイライト|高光/, styleRe: /콧대|코끝|nose|鼻/ },
  { zone: 'highlighter', style: 'natural_cheek', zoneRe: /하이라이터|highlighter|ハイライト|高光/, styleRe: /내추럴|광대|cheek|チーク|颧骨/ },
  { zone: 'contour', style: 'jawline', zoneRe: /쉐딩|셰이딩|컨투어|contour|シェーディング|修容/, styleRe: /턱라인|턱선|v라인|브이라인|jaw|下颌|顎/ },
  { zone: 'contour', style: 'nose', zoneRe: /쉐딩|셰이딩|컨투어|contour|シェーディング|修容/, styleRe: /콧대|코 |nose|鼻/ },
  { zone: 'eyeliner', style: 'cat_wing', zoneRe: /아이라인|아이라이너|eyeliner|アイライン|眼线/, styleRe: /캣윙|캣 윙|고양이|cat|猫/ },
  { zone: 'eyeliner', style: 'puppy', zoneRe: /아이라인|아이라이너|eyeliner|アイライン|眼线/, styleRe: /강아지|퍼피|puppy|垂れ/ },
  { zone: 'eyeliner', style: 'smoky', zoneRe: /아이라인|아이라이너|eyeliner|アイライン|眼线/, styleRe: /스모키|smoky|烟熏/ },
  { zone: 'eyeliner', style: 'gyaru', zoneRe: /아이라인|아이라이너|eyeliner|アイライン|眼线/, styleRe: /갸루|gyaru|ギャル/ },
  { zone: 'eyeliner', style: 'under_point', zoneRe: /아이라인|아이라이너|eyeliner|アイライン|眼线/, styleRe: /언더|아래라인|under/ },
  { zone: 'eyeliner', style: 'natural', zoneRe: /아이라인|아이라이너|eyeliner|アイライン|眼线/, styleRe: /내추럴|natural|自然/ },
  { zone: 'blush', style: 'under_eye', zoneRe: /블러셔|블러시|치크|blush|チーク|腮红/, styleRe: /눈밑|눈 밑|under.?eye|目の下/ },
  { zone: 'blush', style: 'side', zoneRe: /블러셔|블러시|치크|blush|チーク|腮红/, styleRe: /귀쪽|사이드|side|耳/ },
  { zone: 'blush', style: 'apple', zoneRe: /블러셔|블러시|치크|blush|チーク|腮红/, styleRe: /광대|애플|apple|颧骨/ },
  { zone: 'eyeshadow', style: 'glitter', zoneRe: /섀도|아이섀|eyeshadow|アイシャドウ|眼影/, styleRe: /글리터|glitter|亮片/ },
  { zone: 'eyeshadow', style: 'shimmer', zoneRe: /섀도|아이섀|eyeshadow|アイシャドウ|眼影/, styleRe: /쉬머|펄|shimmer|パール/ },
  { zone: 'eyeshadow', style: 'glossy', zoneRe: /섀도|아이섀|eyeshadow|アイシャドウ|眼影/, styleRe: /글로시|물광|glossy/ },
  { zone: 'eyeshadow', style: 'matte', zoneRe: /섀도|아이섀|eyeshadow|アイシャドウ|眼影/, styleRe: /매트|matte|雾面/ },
  { zone: 'lip', style: 'overlip', zoneRe: /립|입술|\blips?\b|lipstick|リップ|口红/, styleRe: /오버립|오버라인|overlip|over.?line/ },
  { zone: 'lip', style: 'center_glow', zoneRe: /립|입술|\blips?\b|lipstick|リップ|口红/, styleRe: /중앙|가운데|center/ },
  { zone: 'lip', style: 'full', zoneRe: /립|입술|\blips?\b|lipstick|リップ|口红/, styleRe: /풀립|풀 립|\bfull\b/ },
  { zone: 'mascara', style: 'volume_skinny', zoneRe: /마스카라|mascara|マスカラ|睫毛膏/, styleRe: /스키니|volume skinny/ },
  { zone: 'mascara', style: 'long_curl', zoneRe: /마스카라|mascara|マスカラ|睫毛膏/, styleRe: /컬픽스|컬 픽스|롱컬|컬링|curl/ },
  { zone: 'mascara', style: 'fine', zoneRe: /마스카라|mascara|マスカラ|睫毛膏/, styleRe: /파인|\bfine\b/ },
  { zone: 'mascara', style: 'slim', zoneRe: /마스카라|mascara|マスカラ|睫毛膏/, styleRe: /슬림|메탈|\bslim\b/ },
  { zone: 'mascara', style: 'long', zoneRe: /마스카라|mascara|マスカラ|睫毛膏/, styleRe: /킬래쉬|킬 래쉬|\blong\b/ },
];

function lipSwatches(products: Product[]): TryOn[] {
  return products
    .filter((product) => product.makeupZone === 'lip')
    .flatMap((product) => product.shades.map((shade) => ({ product, shade })));
}

function blushProducts(products: Product[]): Product[] {
  return products.filter((product) => product.makeupZone === 'blush' && product.shades.length > 0);
}

function lightness(hex: string): number {
  return hexToLab(hex).L;
}

function asksLighterLip(text: string): boolean {
  return /연한|연하게|(?<!하이)라이터|얇은|\blight(?:er)?\b|薄い|浅/.test(text) && /립|입술|\blips?\b|lipstick|リップ|口红/.test(text);
}

function asksSofterBlush(text: string): boolean {
  return /블러셔|블러시|치크|blush|チーク|腮红/.test(text) && /은은|부드럽게|소프트|soft|やわらか|柔和/.test(text);
}

function asksCoralLook(text: string): boolean {
  return /코랄|coral|コーラル|珊瑚色/.test(text);
}

function styleHits(text: string): StyleRule[] {
  return STYLE_RULES.filter((rule) => rule.zoneRe.test(text) && rule.styleRe.test(text));
}

function intensityHit(text: string): { zone: MakeupZone; delta: number } | null {
  const down = /연하게|은은|약하게|\blighter\b|\bsofter\b|薄く|淡/.test(text);
  const up = /진하게|강하게|진한|\bheavier\b|\bstronger\b|濃く|浓/.test(text);
  if (down === up) return null;
  const delta = down ? -0.18 : 0.18;
  if (/하이라이터|highlighter|ハイライト|高光/.test(text)) return { zone: 'highlighter', delta };
  if (/쉐딩|셰이딩|컨투어|contour|シェーディング|修容/.test(text)) return { zone: 'contour', delta };
  if (/아이라인|아이라이너|eyeliner|アイライン|眼线/.test(text)) return { zone: 'eyeliner', delta };
  if (/마스카라|mascara|マスカラ|睫毛膏/.test(text)) return { zone: 'mascara', delta };
  return null;
}

function painted(makeup: MakeupState, zone: MakeupZone): boolean {
  return !!makeup[zone];
}

/** Closed-set style/intensity/shade phrases that the AR screen may run locally. */
export function isClosedLocalArChat(text: string): boolean {
  const query = text.trim().toLowerCase();
  if (!query || /하지\s*마|don't|do not|말고/.test(query)) return false;
  const styles = styleHits(query);
  const intensity = intensityHit(query);
  const intents = [
    asksSofterBlush(query),
    asksLighterLip(query),
    asksCoralLook(query),
    styles.length === 1 && !intensity,
    styles.length === 0 && !!intensity,
  ].filter(Boolean);
  return intents.length === 1;
}

/** Map a chat request onto catalog shades or geometry already on the device. Never invents a hex. */
export function adjustMakeupFromChat(
  text: string,
  products: Product[],
  makeup: MakeupState
): ArChatResult {
  const query = text.trim().toLowerCase();
  if (!query) return { kind: 'none' };

  const lips = lipSwatches(products);
  if (asksLighterLip(query)) {
    if (lips.length === 0) return { kind: 'none' };
    const current = makeup.lip ? lightness(makeup.lip.hex) : 45;
    const lighter = lips
      .filter((item) => lightness(item.shade.hex) >= current + 3)
      .sort((a, b) => lightness(a.shade.hex) - lightness(b.shade.hex));
    const pick = lighter[0] ?? [...lips].sort((a, b) => lightness(b.shade.hex) - lightness(a.shade.hex))[0];
    return pick ? { kind: 'shade', zone: 'lip', product: pick.product, shade: pick.shade } : { kind: 'none' };
  }

  if (asksCoralLook(query)) {
    const coralLip = lips.find((item) => colorFamily(item.shade.hex) === 'coral');
    if (coralLip) return { kind: 'shade', zone: 'lip', product: coralLip.product, shade: coralLip.shade };
    const coralBlush = blushProducts(products).find((product) =>
      product.shades.some((shade) => colorFamily(shade.hex) === 'coral')
    );
    if (coralBlush) {
      const shade = coralBlush.shades.find((item) => colorFamily(item.hex) === 'coral') ?? coralBlush.shades[0];
      return { kind: 'shade', zone: 'blush', product: coralBlush, shade };
    }
  }

  const styles = styleHits(query);
  const intensity = intensityHit(query);
  if (styles.length > 1) return { kind: 'none' };
  if (styles.length === 1 && intensity) return { kind: 'none' };

  if (styles.length === 1) {
    const hit = styles[0];
    if (!painted(makeup, hit.zone)) return { kind: 'none' };
    const geometry = geometryFromStyle(hit.zone, hit.style);
    return geometry ? { kind: 'geometry', zone: hit.zone, geometry } : { kind: 'none' };
  }

  if (intensity) {
    const current = makeup[intensity.zone];
    if (!current) return { kind: 'none' };
    return {
      kind: 'intensity',
      zone: intensity.zone,
      intensity: Math.min(1, Math.max(0.12, Math.round((current.intensity + intensity.delta) * 100) / 100)),
    };
  }

  return { kind: 'none' };
}
