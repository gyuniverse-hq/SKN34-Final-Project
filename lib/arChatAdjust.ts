import { colorFamily, hexToLab } from '@/lib/colorFamily';
import type { MakeupState, MakeupZone, Product, Shade } from '@/types';

export type ArChatResult =
  | { kind: 'shade'; zone: MakeupZone; product: Product; shade: Shade }
  | { kind: 'intensity'; zone: MakeupZone; intensity: number }
  | { kind: 'none' };

type TryOn = { product: Product; shade: Shade };

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
  return /연한|연하게|라이터|얇은|light(er)?|薄い|浅/.test(text) && /립|립스틱|lipstick|リップ|口红/.test(text);
}

function asksSofterBlush(text: string): boolean {
  return /블러셔|블러시|치크|blush|チーク|腮红/.test(text) && /은은|부드럽게|소프트|soft|やわらか|柔和/.test(text);
}

function asksCoralLook(text: string): boolean {
  return /코랄|coral|コーラル|珊瑚色/.test(text);
}

/** Map a chat request onto catalog shades already on the device. Never invents a hex. */
export function adjustMakeupFromChat(
  text: string,
  products: Product[],
  makeup: MakeupState
): ArChatResult {
  const query = text.trim().toLowerCase();
  if (!query) return { kind: 'none' };

  if (asksSofterBlush(query)) {
    if (!makeup.blush) return { kind: 'none' };
    return { kind: 'intensity', zone: 'blush', intensity: Math.max(0.12, makeup.blush.intensity - 0.18) };
  }

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

  return { kind: 'none' };
}
