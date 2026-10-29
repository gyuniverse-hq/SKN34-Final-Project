import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { careTagsOf, type CareTag } from '@/lib/skinFilters';
import type { Product } from '@/types';

const MAX_TAGS = 2;

const TAG_COLORS: Record<CareTag, { bg: string; fg: string }> = {
  hydrating: { bg: '#DDF2FB', fg: '#1E6B8A' },
  soothing: { bg: '#E3F5D8', fg: '#45762A' },
  'oil-control': { bg: '#DCF3EA', fg: '#2D7559' },
  'blemish-care': { bg: '#FDE7E2', fg: '#A3442E' },
  'pore-care': { bg: '#ECE8FB', fg: '#58489A' },
  brightening: { bg: '#FFF1D6', fg: '#956100' },
  firming: { bg: theme.colors.roseSoft, fg: theme.colors.roseDark },
};

export const SkinProductCard = memo(function SkinProductCard({ product, onPress }: { product: Product; onPress: () => void }) {
  const { t } = useI18n();
  const tags = careTagsOf(product.tags).slice(0, MAX_TAGS);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={[product.brand, product.name, ...tags.map((tag) => t(`careTag.${tag}` as TranslationKey))].join(', ')}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}>
      <ProductImage uri={product.imageUrl} category={product.category} style={styles.image} recyclingKey={product.id} />
      <Text style={styles.brand} numberOfLines={1}>
        {product.brand}
      </Text>
      <Text style={styles.name} numberOfLines={1}>
        {product.name}
      </Text>
      {tags.length > 0 ? (
        <View style={styles.tags}>
          {tags.map((tag) => (
            <View key={tag} style={[styles.tag, { backgroundColor: TAG_COLORS[tag].bg }]}>
              <Text style={[styles.tagText, { color: TAG_COLORS[tag].fg }]}>{t(`careTag.${tag}` as TranslationKey)}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: { width: 148 },
  image: { width: '100%', aspectRatio: 1, borderRadius: theme.radius.md, backgroundColor: theme.colors.card },
  brand: { marginTop: 10, fontSize: 12, color: theme.colors.inkFaint },
  name: { marginTop: 2, fontSize: 14, fontWeight: '600', color: theme.colors.ink },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 },
  tag: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.sm },
  tagText: { fontSize: 11, fontWeight: '700' },
});
