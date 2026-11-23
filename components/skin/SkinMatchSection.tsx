import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SkinProductCard } from './SkinProductCard';
import { InlineState } from '@/components/ui/InlineState';
import { homeHeading, homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import type { Product } from '@/types';

/** Home section of products matched to the saved skin result, with a skin analysis shortcut. */
export function SkinMatchSection({
  title,
  actionLabel,
  availability,
  products,
  loading,
  error,
  emptyMessage,
  onAction,
  onRetry,
  onPressProduct,
}: {
  title: string;
  actionLabel?: string;
  availability?: string;
  products: Product[] | undefined;
  loading: boolean;
  error: boolean;
  emptyMessage: string;
  onAction: () => void;
  onRetry: () => void;
  onPressProduct: (product: Product) => void;
}) {
  if (availability && !loading && !error) {
    return (
      <View style={styles.invitation}>
        <View style={styles.symbol}>
          <MaterialCommunityIcons name="face-recognition" size={43} color={theme.colors.roseDark} />
        </View>
        <View style={styles.copy}>
          <Text accessibilityRole="header" style={homeHeading}>{title}</Text>
          <Text style={styles.availability}>{availability}</Text>
          {actionLabel && <Pressable accessibilityRole="button" onPress={onAction} hitSlop={5} style={styles.cta}>
            <Text style={styles.ctaText}>{actionLabel}</Text>
          </Pressable>}
        </View>
      </View>
    );
  }
  return (
    <View style={styles.section}>
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        {actionLabel && <Pressable onPress={onAction} accessibilityRole="button" hitSlop={10} style={styles.action}>
          <Text style={styles.actionText}>{actionLabel} ›</Text>
        </Pressable>}
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
  section: { marginHorizontal: homeLayout.gutter },
  header: { flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 10 },
  title: { ...homeHeading, flex: 1 },
  action: { minHeight: 32, justifyContent: 'center' },
  actionText: { ...homeType(12), color: theme.colors.rose },
  invitation: { flexDirection: 'row', alignItems: 'center', minHeight: 98, marginHorizontal: 10,
    borderRadius: 14, backgroundColor: '#FAEDED', paddingVertical: 10, paddingRight: 12 },
  symbol: { width: '29.5%', minHeight: 62, justifyContent: 'center', alignItems: 'center',
    borderRightColor: '#E4C9CA', borderRightWidth: 1 },
  copy: { flex: 1, marginLeft: '5.5%', alignItems: 'flex-start' },
  availability: { ...homeType(12.5), lineHeight: 18, color: theme.colors.inkMuted, marginTop: 2 },
  cta: { alignItems: 'center', justifyContent: 'center', minHeight: 30, minWidth: 145,
    paddingHorizontal: 15, borderRadius: 18, backgroundColor: theme.colors.roseDark, marginTop: 5 },
  ctaText: { ...homeType(13.5), fontWeight: '700', color: theme.colors.white },
  rail: { gap: 14 },
});
