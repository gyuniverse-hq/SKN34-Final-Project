import Ionicons from '@expo/vector-icons/Ionicons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { findOffer, hostnameOf } from '@/lib/externalLink';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { useProduct, useProductOffers } from '@/lib/queries';
import { paramValue, parseId } from '@/lib/routes';

/** "You are leaving VISHUE" confirmation. Opens only a link from this product's own offers. */
export default function ExternalLinkScreen() {
  const params = useLocalSearchParams<{ productId?: string; link?: string }>();
  const productId = parseId(params.productId);
  const router = useRouter();
  const { t } = useI18n();
  const product = useProduct(productId);
  const offers = useProductOffers(productId);
  const [openFailed, setOpenFailed] = useState(false);

  if (!productId) return <EmptyState icon="link-outline" title={t('ext.invalid')} />;
  if (offers.isPending) return <LoadingState />;
  if (offers.isError) return <ErrorState error={offers.error} onRetry={() => offers.refetch()} />;

  const offer = findOffer(offers.data.offers, paramValue(params.link));
  if (!offer) {
    return (
      <EmptyState
        icon="link-outline"
        title={t('ext.invalid')}
        body={t('ext.invalidBody')}
        action={<Button label={t('common.back')} variant="secondary" onPress={() => router.back()} />}
      />
    );
  }

  const open = async () => {
    setOpenFailed(false);
    try {
      await WebBrowser.openBrowserAsync(offer.link);
      router.back();
    } catch {
      setOpenFailed(true);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.icon}>
          <Ionicons name="open-outline" size={28} color={theme.colors.rose} />
        </View>
        <Text style={styles.title} accessibilityRole="header">
          {t('ext.title')}
        </Text>
        <Text style={styles.body}>{t('ext.body')}</Text>

        <View style={styles.card}>
          <Text style={styles.mall}>{offer.mallName || t('offers.online')}</Text>
          <Text style={styles.host}>{hostnameOf(offer.link)}</Text>
          <Text style={styles.offerTitle} numberOfLines={2}>
            {offer.title}
          </Text>
          {product.data ? (
            <Text style={styles.product} numberOfLines={1}>
              {product.data.brand} {product.data.name}
            </Text>
          ) : null}
          <Text style={styles.price}>{formatKRW(offer.priceKRW)}</Text>
          <Text style={styles.priceNote}>{t('ext.priceNote')}</Text>
        </View>

        <Notice tone="neutral" title={t('ext.disclosureTitle')} body={t('ext.disclosure')} />
        {openFailed ? <Notice tone="warning" body={t('ext.openFailed')} /> : null}
      </ScrollView>
      <View style={styles.footer}>
        <Button label={t('ext.continue')} icon="open-outline" onPress={open} />
        <Button label={t('ext.stay')} variant="secondary" onPress={() => router.back()} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.xl, gap: 14 },
  icon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: theme.colors.roseSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  body: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22 },
  card: {
    padding: 16,
    gap: 4,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  mall: { fontSize: theme.font.body, fontWeight: '800', color: theme.colors.ink },
  host: { fontSize: 12, color: theme.colors.inkFaint },
  offerTitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, marginTop: 4 },
  product: { fontSize: 12, color: theme.colors.inkMuted },
  price: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 6 },
  priceNote: { fontSize: 11, color: theme.colors.inkFaint },
  footer: {
    gap: 8,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
