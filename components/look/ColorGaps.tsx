import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

export interface ColorGapOffer {
  key: string;
  text: string;
  price: string;
  onPress: () => void;
}

export interface ColorGapRow {
  key: string;
  /** Zone name, e.g. "Lips" */
  zone: string;
  /** The look's color */
  hex: string;
  status: 'nearest' | 'checking' | 'offers' | 'link' | 'soldout';
  /** Short status chip, e.g. "Closest shade" or "Sold out" */
  badge: string;
  /** Nearest shade: brand, product and shade name */
  headline?: string;
  /** The shade that goes in the set */
  swatch?: string;
  note?: string;
  offers?: ColorGapOffer[];
  action?: { label: string; onPress: () => void };
  onPress?: () => void;
}

/** Colors of a look that nobody in the shop wears: nearest shade with how thick to wear it, sellers, or sold out. */
export function ColorGaps({ title, intro, rows }: { title: string; intro: string; rows: ColorGapRow[] }) {
  if (rows.length === 0) return null;
  return (
    <View>
      <Text style={styles.title} accessibilityRole="header">
        {title}
      </Text>
      <Text style={styles.intro}>{intro}</Text>
      {rows.map((row) => {
        const soldOut = row.status === 'soldout';
        const body = (
          <>
            <View style={styles.head}>
              <View style={[styles.dot, { backgroundColor: row.hex }]} />
              <Text style={styles.zone}>{row.zone}</Text>
              <View style={[styles.badge, soldOut && styles.badgeSold]}>
                <Text style={[styles.badgeText, soldOut && styles.badgeTextSold]}>{row.badge}</Text>
              </View>
            </View>
            {row.headline ? (
              <View style={styles.shadeRow}>
                {row.swatch ? <View style={[styles.dot, { backgroundColor: row.swatch }]} /> : null}
                <Text style={styles.headline} numberOfLines={2}>
                  {row.headline}
                </Text>
              </View>
            ) : null}
            {row.status === 'checking' ? <ActivityIndicator color={theme.colors.rose} style={styles.spinner} /> : null}
            {row.note ? <Text style={[styles.note, soldOut && styles.noteSold]}>{row.note}</Text> : null}
            {row.offers?.map((offer) => (
              <Pressable
                key={offer.key}
                onPress={offer.onPress}
                accessibilityRole="link"
                style={({ pressed }) => [styles.offer, pressed && { opacity: 0.85 }]}>
                <Text style={styles.offerText} numberOfLines={1}>
                  {offer.text}
                </Text>
                <Text style={styles.offerPrice}>{offer.price}</Text>
              </Pressable>
            ))}
            {row.action ? (
              <Pressable
                onPress={row.action.onPress}
                accessibilityRole="link"
                style={({ pressed }) => [styles.action, pressed && { opacity: 0.85 }]}>
                <Text style={styles.actionText}>{row.action.label}</Text>
              </Pressable>
            ) : null}
          </>
        );
        return row.onPress ? (
          <Pressable
            key={row.key}
            onPress={row.onPress}
            accessibilityRole="button"
            style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}>
            {body}
          </Pressable>
        ) : (
          <View key={row.key} style={[styles.card, soldOut && styles.cardSold]} accessibilityState={{ disabled: soldOut }}>
            {body}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 28, marginBottom: 4 },
  intro: { fontSize: theme.font.small, color: theme.colors.inkMuted, lineHeight: 19, marginBottom: 8 },
  card: {
    gap: 6,
    padding: theme.spacing.md,
    marginTop: theme.spacing.sm,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.surface,
  },
  cardSold: { backgroundColor: theme.colors.surfaceAlt, opacity: 0.8 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  dot: { width: 18, height: 18, borderRadius: 9, borderWidth: 1, borderColor: theme.colors.border },
  zone: { flex: 1, fontSize: theme.font.small, fontWeight: '800', color: theme.colors.ink },
  badge: { borderRadius: theme.radius.pill, backgroundColor: theme.colors.roseSoft, paddingHorizontal: 10, paddingVertical: 3 },
  badgeSold: { backgroundColor: theme.colors.danger },
  badgeText: { fontSize: 11, fontWeight: '800', color: theme.colors.roseDark },
  badgeTextSold: { color: theme.colors.white },
  shadeRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  headline: { flex: 1, fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink },
  spinner: { alignSelf: 'flex-start' },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, lineHeight: 19 },
  noteSold: { color: theme.colors.danger },
  offer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
  offerText: { flex: 1, fontSize: theme.font.small, color: theme.colors.ink },
  offerPrice: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  action: {
    alignSelf: 'flex-start',
    borderRadius: theme.radius.pill,
    borderWidth: 1,
    borderColor: theme.colors.rose,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  actionText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.rose },
});
