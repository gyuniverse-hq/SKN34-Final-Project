import { LOOKS } from '@/data/catalog/looks';
import { PRODUCTS } from '@/data/catalog/products';
import { STORES } from '@/data/catalog/stores';
import type { CelebLook, Product, Store } from '@/types';

export async function findAllProducts(): Promise<Product[]> {
  return PRODUCTS;
}

export async function findProductById(id: string): Promise<Product | null> {
  return PRODUCTS.find((p) => p.id === id) ?? null;
}

export async function findAllLooks(): Promise<CelebLook[]> {
  return LOOKS;
}

export async function findLookById(id: string): Promise<CelebLook | null> {
  return LOOKS.find((l) => l.id === id) ?? null;
}

export async function findAllStores(): Promise<Store[]> {
  return STORES;
}
