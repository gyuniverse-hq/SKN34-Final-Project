import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ProductImage } from '@/components/ui/ProductImage';
import { homeLayout, homeType } from '@/constants/homeLayout';
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
    width: '50%',
    paddingHorizontal: homeLayout.productGap / 2,
    paddingBottom: 18,
  },
  image: { width: '100%', aspectRatio: 1, borderRadius: 10, backgroundColor: theme.colors.cream },
  body: { paddingTop: 8, paddingHorizontal: 2, gap: 2 },
  brand: { ...homeType(11), color: theme.colors.roseDark, fontWeight: '500' },
  name: { ...homeType(14), lineHeight: 19, color: theme.colors.ink },
  price: { ...homeType(15), fontWeight: '600', color: theme.colors.ink, marginTop: 2 },
  shades: { flexDirection: 'row', alignItems: 'center', gap: 3, marginTop: 4 },
  dot: { width: 10, height: 10, borderRadius: 5, borderWidth: StyleSheet.hairlineWidth, borderColor: 'rgba(0,0,0,0.12)' },
  shadeLabel: { ...homeType(11), flexShrink: 1, color: theme.colors.inkMuted, marginLeft: 2 },
});
