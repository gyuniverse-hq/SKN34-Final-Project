import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import type { Product } from '@/types';

interface Props {
  product: Product;
  shadeLabel: string;
  onPress: () => void;
}

export const ProductCard = memo(function ProductCard({ product, shadeLabel, onPress }: Props) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${product.brand} ${product.name}, ${formatKRW(product.priceKRW)}`}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.9 }]}>
      <ProductImage uri={product.imageUrl} category={product.category} style={styles.image} recyclingKey={product.id} />
      <View style={styles.body}>
        <Text style={styles.brand} numberOfLines={1}>
          {product.brand}
        </Text>
        <Text style={styles.name} numberOfLines={2}>
          {product.name}
        </Text>
        <Text style={styles.price}>{formatKRW(product.priceKRW)}</Text>
        {product.shades.length > 1 ? (
          <View style={styles.shades}>
            {product.shades.slice(0, 5).map((s) => (
              <View key={s.id} style={[styles.dot, { backgroundColor: s.hex }]} />
            ))}
            <Text style={styles.shadeLabel}>{shadeLabel}</Text>
          </View>
        ) : null}
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: {
    flex: 1,
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    overflow: 'hidden',
    margin: 6,
  },
  image: { width: '100%', aspectRatio: 1, backgroundColor: theme.colors.surfaceAlt },
  body: { padding: 12, gap: 3 },
  brand: { fontSize: 11, color: theme.colors.accent, fontWeight: '700' },
  name: { fontSize: 14, fontWeight: '600', color: theme.colors.ink, minHeight: 36 },
  price: { fontSize: 15, fontWeight: '800', color: theme.colors.ink, marginTop: 2 },
  shades: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 6 },
  dot: { width: 12, height: 12, borderRadius: 6, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  shadeLabel: { fontSize: 11, color: theme.colors.inkMuted, marginLeft: 2 },
});
