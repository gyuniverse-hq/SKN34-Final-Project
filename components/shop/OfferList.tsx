import Ionicons from '@expo/vector-icons/Ionicons';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import type { ShoppingOffer } from '@/types';

export type OfferStatus = 'loading' | 'error' | 'unconfigured' | 'empty' | 'ready';

/** Seller search results. Prices are a snapshot from the search provider, not a live quote. */
export function OfferList({
  status,
  offers,
  onOpen,
  onRetry,
}: {
  status: OfferStatus;
  offers: ShoppingOffer[];
  onOpen: (offer: ShoppingOffer) => void;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <View style={styles.wrap}>
      <Text style={styles.title} accessibilityRole="header">
        {t('product.onlinePrices')}
      </Text>
      <Text style={styles.hint}>{t('offers.hint')}</Text>
      {status === 'loading' ? (
        <ActivityIndicator color={theme.colors.rose} style={styles.loading} />
      ) : status === 'error' ? (
        <View style={styles.state}>
          <Text style={styles.stateText}>{t('offers.error')}</Text>
          <Button label={t('common.retry')} variant="secondary" compact onPress={onRetry} />
        </View>
      ) : status === 'unconfigured' ? (
        <Text style={styles.stateText}>{t('offers.unconfigured')}</Text>
      ) : status === 'empty' ? (
        <Text style={styles.stateText}>{t('offers.empty')}</Text>
      ) : (
        offers.map((offer) => (
          <Pressable
            key={offer.link}
            onPress={() => onOpen(offer)}
            accessibilityRole="link"
            accessibilityLabel={`${offer.mallName || t('offers.online')} ${formatKRW(offer.priceKRW)}`}
            accessibilityHint={t('ext.hint')}
            style={({ pressed }) => [styles.offer, pressed && { opacity: 0.85 }]}>
            <View style={styles.offerCopy}>
              <Text style={styles.mall}>{offer.mallName || t('offers.online')}</Text>
              <Text style={styles.offerTitle} numberOfLines={1}>
                {offer.title}
              </Text>
            </View>
            <Text style={styles.price}>{formatKRW(offer.priceKRW)}</Text>
            <Ionicons name="open-outline" size={16} color={theme.colors.inkMuted} />
          </Pressable>
        ))
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  title: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  hint: { fontSize: 12, color: theme.colors.inkMuted, lineHeight: 17 },
  loading: { marginVertical: 8, alignSelf: 'flex-start' },
  state: { gap: 8, alignItems: 'flex-start' },
  stateText: { fontSize: theme.font.small, color: theme.colors.inkMuted, lineHeight: 19 },
  offer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    minHeight: theme.hitTarget,
    padding: 12,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  offerCopy: { flex: 1 },
  mall: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  offerTitle: { fontSize: 12, color: theme.colors.inkMuted },
  price: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
});
