import type { CartLine } from "./api";

const KEY = "vishue-web-cart";

export function loadCart(): CartLine[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as CartLine[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveCart(lines: CartLine[]) {
  localStorage.setItem(KEY, JSON.stringify(lines));
}

export function cartTotal(lines: CartLine[]) {
  return lines.reduce((sum, line) => sum + line.unitPriceKRW * line.quantity, 0);
}
