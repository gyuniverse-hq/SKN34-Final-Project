/** Prices of 0 mean "not checked yet" (imported products without a price) and render as a dash. */
export function formatKRW(amount: number): string {
  if (!amount) return '—';
  return `₩${Math.round(amount).toLocaleString('en-US')}`;
}

export function formatDate(iso: string, locale: string): string {
  try {
    return new Date(iso).toLocaleString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function createId(prefix = ''): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `${prefix}${Date.now().toString(36)}${random}`.toUpperCase();
}
