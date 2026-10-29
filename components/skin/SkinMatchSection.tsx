import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SkinProductCard } from './SkinProductCard';
import { InlineState } from '@/components/ui/InlineState';
import { theme } from '@/constants/theme';
import type { Product } from '@/types';

/** Home section of products matched to the saved skin result, with a skin analysis shortcut. */
export function SkinMatchSection({
  title,
  actionLabel,
  products,
  loading,
  error,
  emptyMessage,
  onAction,
  onRetry,
  onPressProduct,
}: {
  title: string;
  actionLabel: string;
  products: Product[] | undefined;
  loading: boolean;
  error: boolean;
  emptyMessage: string;
  onAction: () => void;
  onRetry: () => void;
  onPressProduct: (product: Product) => void;
}) {
  return (
    <View style={styles.section}>
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        <Pressable onPress={onAction} accessibilityRole="button" hitSlop={10} style={styles.action}>
          <Text style={styles.actionText}>{actionLabel} ›</Text>
        </Pressable>
      </View>
      {loading ? (
        <InlineState status="loading" />
      ) : error ? (
        <InlineState status="error" onRetry={onRetry} />
      ) : !products?.length ? (
        <InlineState status="empty" message={emptyMessage} />
      ) : (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
          {products.map((product) => (
            <SkinProductCard key={product.id} product={product} onPress={() => onPressProduct(product)} />
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 32 },
  header: { flexDirection: 'row', alignItems: 'flex-end', gap: 12, marginBottom: 16 },
  title: { flex: 1, fontSize: theme.font.title, lineHeight: 24, fontWeight: '800', color: theme.colors.ink },
  action: { minHeight: 32, justifyContent: 'center' },
  actionText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.rose },
  rail: { gap: 14 },
});
