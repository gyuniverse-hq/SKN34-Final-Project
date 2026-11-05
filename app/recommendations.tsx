import * as Haptics from 'expo-haptics';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ProductLineCard } from '@/components/shop/ProductLineCard';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { Notice } from '@/components/ui/Notice';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useSimilarRecommendations } from '@/hooks/useSimilarRecommendations';
import { ApiError } from '@/lib/api';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProduct } from '@/lib/queries';
import { arHref, parseId, parseIntensity, parseZone, productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';

/** `/recommendations?productId&shadeId&zone&intensity`: similar shades for the AR selection. */
export default function RecommendationsScreen() {
  const params = useLocalSearchParams<{ productId?: string; shadeId?: string; zone?: string; intensity?: string }>();
  const productId = parseId(params.productId);
  const shadeId = parseId(params.shadeId);
  const zone = parseZone(params.zone);
  const intensity = parseIntensity(params.intensity);
  const router = useRouter();
  const { t } = useI18n();
  const source = useProduct(productId);
  const { query, items } = useSimilarRecommendations(productId, shadeId);
  const addToCart = useCartStore((s) => s.add);
  const [addedKey, setAddedKey] = useState<string | null>(null);

  if (!productId || !shadeId) {
    return (
      <EmptyState
        icon="color-filter-outline"
        title={t('rec.noSource')}
        body={t('rec.noSourceBody')}
        action={<Button label={t('home.ar')} onPress={() => router.replace('/ar')} />}
      />
    );
  }

  const sourceShade = source.data?.shades.find((s) => s.id === shadeId);
  const errorCode = query.error instanceof ApiError ? query.error.code : undefined;

  let list;
  if (query.isPending) list = <LoadingState />;
  else if (errorCode === 'shade_not_found' || errorCode === 'not_found') {
    list = <InlineState status="empty" message={t(errorCode === 'not_found' ? 'catalog.productUnavailable' : 'catalog.shadeUnavailable')} />;
  } else if (errorCode === 'not_try_on') list = <InlineState status="empty" message={t('ar.notTryOn')} />;
  else if (query.isError) list = <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  else if (items.length === 0) list = <InlineState status="empty" message={t('rec.empty')} />;
  else {
    list = items.map(({ product, shade, deltaE, reasons }) => {
      const key = `${product.id}::${shade.id}`;
      return (
        <ProductLineCard
          key={key}
          product={product}
          shade={shade}
          badges={reasons.map((r) => ({ label: t(`rec.reason.${r}` as TranslationKey), tone: r === 'close_color' ? 'brand' : 'neutral' }))}
          note={t('rec.deltaE', { value: deltaE.toFixed(1) })}
          onPress={() => router.push(productHref(product.id, shade.id))}
          actions={[
            { label: t('rec.tryThis'), icon: 'scan-outline', onPress: () => router.push(arHref({ productId: product.id, shadeId: shade.id })) },
            {
              label: addedKey === key ? t('product.added') : t('product.addToCart'),
              icon: addedKey === key ? 'checkmark' : 'cart-outline',
              variant: 'primary',
              onPress: () => {
                addToCart({ productId: product.id, shadeId: shade.id });
                setAddedKey(key);
                Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
              },
            },
          ]}
        />
      );
    });
  }

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t('rec.title') }} />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.sourceCard}>
          <View style={[styles.sourceSwatch, { backgroundColor: sourceShade?.hex ?? query.data?.source.hex ?? theme.colors.border }]} />
          <View style={styles.sourceCopy}>
            <Text style={styles.sourceLabel}>{t('rec.basedOn')}</Text>
            <Text style={styles.sourceName} numberOfLines={2}>
              {source.data ? `${source.data.brand} ${source.data.name}` : '—'}
            </Text>
            <Text style={styles.sourceMeta}>
              {[
                sourceShade?.name,
                zone ? t(`ar.zone.${zone}` as TranslationKey) : undefined,
                intensity !== undefined ? t('rec.intensity', { value: Math.round(intensity * 100) }) : undefined,
              ]
                .filter(Boolean)
                .join(' · ')}
            </Text>
          </View>
        </View>

        <Text style={styles.sectionTitle} accessibilityRole="header">
          {t('rec.listTitle')}
        </Text>
        <View style={styles.list}>{list}</View>

        <Text style={styles.sectionTitle} accessibilityRole="header">
          {t('rec.whyTitle')}
        </Text>
        <Notice tone="neutral" title={t('rec.whyHow')} body={t('rec.whyHowBody')} />
        <View style={styles.gap} />
        <Notice tone="warning" title={t('rec.limitsTitle')} body={t('rec.limitsBody')} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  sourceCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    padding: 14,
    borderRadius: theme.radius.lg,
    backgroundColor: theme.colors.roseSoft,
  },
  sourceSwatch: { width: 52, height: 52, borderRadius: 26, borderWidth: 3, borderColor: theme.colors.white },
  sourceCopy: { flex: 1, gap: 2 },
  sourceLabel: { fontSize: 11, fontWeight: '800', color: theme.colors.accent },
  sourceName: { fontSize: theme.font.body, fontWeight: '800', color: theme.colors.ink },
  sourceMeta: { fontSize: 12, color: theme.colors.inkMuted },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 24, marginBottom: 10 },
  list: { gap: 10 },
  gap: { height: 8 },
});
