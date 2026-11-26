import type { ComponentRef, RefObject } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import type { CartItem, CartRecommendationCandidate, Product, Shade } from '@/types';

type ViewRef = ComponentRef<typeof View>;

interface Props {
  cards: { candidate: CartRecommendationCandidate; product: Product; shade: Shade }[];
  items: CartItem[];
  clipRef: RefObject<ViewRef | null>;
  setCard: (id: string, node: ViewRef | null) => void;
  onScroll: () => void;
  onOpen: (candidate: CartRecommendationCandidate) => void;
  onAdd: (candidate: CartRecommendationCandidate) => void;
}

export function CartRecommendationShelf({ cards, items, clipRef, setCard, onScroll, onOpen, onAdd }: Props) {
  const { t } = useI18n();
  const { width } = useWindowDimensions();
  if (!cards.length) return null;
  const cardWidth = Math.max(110, Math.min(168, (width - theme.spacing.lg * 2 - 16) / 2.5));
  return (
    <View style={styles.section}>
      <Text style={styles.heading} accessibilityRole="header">{t('cart.recommendations')}</Text>
      <View ref={clipRef} collapsable={false}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}
          onScroll={onScroll} scrollEventThrottle={100}>
          {cards.map(({ candidate, product, shade }) => {
            const added = items.some(item => item.productId === product.id);
            return (
              <View key={candidate.candidateId} collapsable={false} ref={node => setCard(candidate.candidateId, node)}
                style={[styles.card, { width: cardWidth }]}>
                <Pressable onPress={() => onOpen(candidate)} style={styles.details} accessibilityRole="link"
                  accessibilityLabel={`${product.brand} ${product.name} · ${shade.name}`}>
                  <ProductImage uri={product.imageUrl} category={product.category} style={styles.image} compact />
                  <Text style={styles.brand} numberOfLines={1}>{product.brand}</Text>
                  <Text style={styles.name} numberOfLines={2}>{product.name}</Text>
                  <View style={styles.shadeRow}>
                    <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                    <Text style={styles.shade} numberOfLines={1}>{shade.name}</Text>
                  </View>
                  <Text style={styles.price}>{formatKRW(product.priceKRW)}</Text>
                </Pressable>
                <Button compact variant="secondary" label={t(added ? 'cart.recommendationAdded' : 'cart.recommendationAdd')}
                  disabled={added} onPress={() => onAdd(candidate)} />
              </View>
            );
          })}
        </ScrollView>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: theme.spacing.md, gap: 10 },
  heading: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  row: { gap: 8 },
  card: {
    backgroundColor: theme.colors.card, borderRadius: theme.radius.md, borderWidth: 1,
    borderColor: theme.colors.border, padding: 8, gap: 8,
  },
  details: { flex: 1, gap: 3 },
  image: { width: '100%', height: 88, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  brand: { fontSize: 11, fontWeight: '700', color: theme.colors.accent },
  name: { minHeight: 32, fontSize: 12, lineHeight: 16, fontWeight: '600', color: theme.colors.ink },
  shadeRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  swatch: { width: 10, height: 10, borderRadius: 5 },
  shade: { flex: 1, fontSize: 11, color: theme.colors.inkMuted },
  price: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
});
