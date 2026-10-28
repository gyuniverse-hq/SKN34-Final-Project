import { keepPreviousData, useQuery } from '@tanstack/react-query';
import type {
  CelebLook,
  Product,
  ProductCategory,
  ProductOffers,
  Store,
  YoutubeSearchResult,
} from '@/types';
import { DEV_LOOKS, DEV_TRYON_PRODUCTS, devLookDetail } from '@/lib/devCatalog';
import { apiGet } from './api';

export function useProducts(params: { q?: string; category?: ProductCategory } = {}) {
  const search = new URLSearchParams();
  if (params.q) search.set('q', params.q);
  if (params.category) search.set('category', params.category);
  const qs = search.toString();
  return useQuery({
    queryKey: ['products', params.q ?? '', params.category ?? 'all'],
    queryFn: async () => {
      try {
        return await apiGet<{ products: Product[] }>(`/api/products${qs ? `?${qs}` : ''}`);
      } catch (error) {
        if (!__DEV__) throw error;
        console.warn('[shop] backend unavailable', error);
        return { products: [] };
      }
    },
    select: (d) => d.products,
    placeholderData: keepPreviousData,
  });
}

export function useProductsByIds(ids: string[]) {
  const sorted = [...new Set(ids)].sort();
  return useQuery({
    queryKey: ['products', 'ids', sorted.join(',')],
    queryFn: () =>
      apiGet<{ products: Product[] }>(`/api/products?ids=${encodeURIComponent(sorted.join(','))}`),
    select: (d) => d.products,
    enabled: sorted.length > 0,
    placeholderData: keepPreviousData,
  });
}

export function useProduct(id: string | undefined) {
  return useQuery({
    queryKey: ['product', id],
    queryFn: async () => {
      try {
        return await apiGet<{ product: Product }>(`/api/products/${encodeURIComponent(id!)}`);
      } catch (error) {
        const local = __DEV__ ? DEV_TRYON_PRODUCTS.find((p) => p.id === id) : undefined;
        if (!local) throw error;
        return { product: local };
      }
    },
    select: (d) => d.product,
    enabled: !!id,
  });
}

export function useProductOffers(id: string | undefined) {
  return useQuery({
    queryKey: ['offers', id],
    queryFn: () => apiGet<ProductOffers>(`/api/products/${encodeURIComponent(id!)}/offers`),
    enabled: !!id,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });
}

/** Development: the bundled demo looks stand in when the backend has none or cannot be reached. */
export function useLooks() {
  return useQuery({
    queryKey: ['looks'],
    queryFn: async () => {
      try {
        const res = await apiGet<{ looks: CelebLook[] }>('/api/looks');
        return __DEV__ && res.looks.length === 0 ? { looks: DEV_LOOKS } : res;
      } catch (error) {
        if (!__DEV__) throw error;
        console.warn('[looks] backend unavailable, using demo looks', error);
        return { looks: DEV_LOOKS };
      }
    },
    select: (d) => d.looks,
  });
}

export function useLook(id: string | undefined) {
  return useQuery({
    queryKey: ['look', id],
    queryFn: async () => {
      const demo = __DEV__ ? devLookDetail(id!) : null;
      if (demo) return demo;
      return apiGet<{ look: CelebLook; products: Product[] }>(`/api/looks/${encodeURIComponent(id!)}`);
    },
    enabled: !!id,
  });
}

export function useStores() {
  return useQuery({
    queryKey: ['stores'],
    queryFn: () => apiGet<{ stores: Store[] }>('/api/stores'),
    select: (d) => d.stores,
    staleTime: 60 * 60 * 1000,
  });
}

export function useTutorials(query: string | undefined, max = 6) {
  return useQuery({
    queryKey: ['tutorials', query, max],
    queryFn: () =>
      apiGet<YoutubeSearchResult>(
        `/api/youtube/search?q=${encodeURIComponent(query!)}&max=${max}`
      ),
    enabled: !!query && query.trim().length >= 2,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
}
