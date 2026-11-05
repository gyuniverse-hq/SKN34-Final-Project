import type Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps, ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import type { Product, Shade } from '@/types';

export interface LineAction {
  label: string;
  icon?: ComponentProps<typeof Ionicons>['name'];
  variant?: 'primary' | 'secondary';
  onPress: () => void;
}

interface Props {
  product: Product;
  shade?: Shade;
  /** Step or role label above the name (e.g. "Lips"). */
  eyebrow?: string;
  badges?: { label: string; tone?: BadgeTone }[];
  note?: string;
  onPress?: () => void;
  actions?: LineAction[];
  children?: ReactNode;
}

/** Horizontal product row with optional actions: look items, recommendations, search hits. */
export function ProductLineCard({ product, shade, eyebrow, badges, note, onPress, actions, children }: Props) {
  return (
    <View style={styles.card}>
      <Pressable
        onPress={onPress}
        disabled={!onPress}
        accessibilityRole="button"
        accessibilityLabel={`${product.brand} ${product.name}${shade ? `, ${shade.name}` : ''}, ${formatKRW(product.priceKRW)}`}
        style={({ pressed }) => [styles.main, pressed && onPress ? styles.pressed : null]}>
        <ProductImage uri={product.imageUrl} category={product.category} style={styles.image} recyclingKey={product.id} compact />
        <View style={styles.info}>
          {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
          <Text style={styles.brand} numberOfLines={1}>
            {product.brand}
          </Text>
          <Text style={styles.name} numberOfLines={2}>
            {product.name}
          </Text>
          {shade ? (
            <View style={styles.shadeRow}>
              <View style={[styles.shadeDot, { backgroundColor: shade.hex }]} />
              <Text style={styles.shadeName} numberOfLines={1}>
                {shade.name}
              </Text>
            </View>
          ) : null}
          <Text style={styles.price}>{formatKRW(product.priceKRW)}</Text>
        </View>
      </Pressable>
      {badges?.length ? (
        <View style={styles.badges}>
          {badges.map((b) => (
            <Badge key={b.label} label={b.label} tone={b.tone} />
          ))}
        </View>
      ) : null}
      {note ? <Text style={styles.note}>{note}</Text> : null}
      {children}
      {actions?.length ? (
        <View style={styles.actions}>
          {actions.map((a) => (
            <Button
              key={a.label}
              label={a.label}
              icon={a.icon}
              variant={a.variant ?? 'secondary'}
              compact
              onPress={a.onPress}
              style={styles.action}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 12,
    gap: 10,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  main: { flexDirection: 'row', gap: 12 },
  pressed: { opacity: 0.85 },
  image: { width: 76, height: 76, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  info: { flex: 1, gap: 2 },
  eyebrow: { fontSize: 11, fontWeight: '800', color: theme.colors.accent, textTransform: 'uppercase' },
  brand: { fontSize: 11, fontWeight: '700', color: theme.colors.inkMuted },
  name: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  shadeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  shadeDot: { width: 12, height: 12, borderRadius: 6, borderWidth: 1, borderColor: 'rgba(0,0,0,0.08)' },
  shadeName: { flex: 1, fontSize: 12, color: theme.colors.inkMuted },
  price: { fontSize: theme.font.small, fontWeight: '800', color: theme.colors.ink, marginTop: 2 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  note: { fontSize: 12, lineHeight: 17, color: theme.colors.inkMuted },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  action: { flexGrow: 1, minHeight: theme.hitTarget },
});
