import type { Store } from '@/types';

export function mapsUrl(store: Pick<Store, 'lat' | 'lng' | 'name'>): string {
  const query = encodeURIComponent(`${store.lat},${store.lng}`);
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
}
