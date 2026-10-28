import * as Haptics from 'expo-haptics';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { ProductImage } from '@/components/ui/ProductImage';
import { ShadePicker } from '@/components/ui/ShadePicker';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { canTryOn, pickShade } from '@/lib/catalog';
import { notify } from '@/lib/confirm';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProduct } from '@/lib/queries';
import { arHref, parseId, recommendationsHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { MAX_COMPARE, useCompareStore } from '@/store/compareStore';
export default function ProductDetailScreen() {
  const params = useLocalSearchParams<{ id: string; shade?: string }>();
  const id = parseId(params.id);
  const requestedShadeId = parseId(params.shade);
  const router = useRouter();
  const { t } = useI18n();
  const product = useProduct(id);
  const addToCart = useCartStore((s) => s.add);
  const addToCompare = useCompareStore((s) => s.add);
  const inCompare = useCompareStore((s) => s.items.some((i) => i.productId === id));
  const [pickedShadeId, setShadeId] = useState<string | undefined>(requestedShadeId);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    if (!added) return;
    const timer = setTimeout(() => setAdded(false), 2400);
    return () => clearTimeout(timer);
  }, [added]);

  if (!id) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  if (product.isPending) return <LoadingState />;
  if (product.isError) return <ErrorState error={product.error} onRetry={() => product.refetch()} />;

  const p = product.data;
  const selectedShade = pickShade(p, pickedShadeId);
  const shadeMissing = !!requestedShadeId && pickedShadeId === requestedShadeId && !p.shades.some((s) => s.id === requestedShadeId);
  const tryOn = canTryOn(p);

  const selectShade = (shadeId: string) => {
    setShadeId(shadeId);
    router.setParams({ shade: shadeId });
  };

  const onAdd = () => {
    addToCart({ productId: p.id, shadeId: selectedShade?.id });
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const onCompare = () => {
    if (addToCompare({ productId: p.id, shadeId: selectedShade?.id })) router.push('/compare');
    else notify(t('compare.full', { max: MAX_COMPARE }));
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: p.brand }} />
      <ScrollView contentContainerStyle={styles.content}>
        <ProductImage uri={p.imageUrl} category={p.category} style={styles.hero} recyclingKey={p.id} />
        <View style={styles.body}>
          <Text style={styles.brand}>{p.brand}</Text>
          <Text style={styles.name} accessibilityRole="header">
            {p.name}
          </Text>
          <Text style={styles.nameKo}>{p.nameKo}</Text>
          <View style={styles.priceRow}>
            <Text style={styles.price}>{formatKRW(p.priceKRW)}</Text>
            <Text style={styles.priceLabel}>
              {t('product.referencePrice')} · {t('product.size')} {p.volume}
            </Text>
          </View>

          {p.shades.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>
                {t('product.shades')}
                {selectedShade ? <Text style={styles.sectionValue}>  {selectedShade.name}</Text> : null}
              </Text>
              {shadeMissing ? <Notice tone="warning" body={t('catalog.shadeMissingPicked')} /> : null}
              <ShadePicker shades={p.shades} selectedId={selectedShade?.id} onSelect={(s) => selectShade(s.id)} />
              <Text style={styles.hint}>{t('product.swatchNote')}</Text>
            </View>
          ) : null}

          <View style={styles.inlineActions}>
            {tryOn && selectedShade ? (
              <Button
                label={t('product.similar')}
                icon="color-filter-outline"
                variant="secondary"
                compact
                onPress={() =>
                  router.push(recommendationsHref({ productId: p.id, shadeId: selectedShade.id, zone: p.makeupZone ?? undefined }))
                }
                style={styles.inlineBtn}
              />
            ) : null}
            <Button
              label={inCompare ? t('compare.view') : t('compare.add')}
              icon="git-compare-outline"
              variant="secondary"
              compact
              onPress={onCompare}
              style={styles.inlineBtn}
            />
          </View>

          {p.description ? <Text style={styles.description}>{p.description}</Text> : null}

          {p.keyIngredients.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>{t('product.keyIngredients')}</Text>
              <View style={styles.tags}>
                {p.keyIngredients.map((ing) => (
                  <View key={ing} style={styles.tag}>
                    <Text style={styles.tagText}>{ing}</Text>
                  </View>
                ))}
              </View>
            </View>
          ) : null}

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>{t('compare.texture')}</Text>
            <Text style={styles.hint}>{t(`texture.${p.texture}` as TranslationKey)}</Text>
          </View>

        </View>
      </ScrollView>

      <View style={styles.footer}>
        {tryOn ? (
          <Button
            label={t('product.tryInAr')}
            icon="scan-outline"
            variant="secondary"
            onPress={() => router.push(arHref({ productId: p.id, shadeId: selectedShade?.id }))}
            style={styles.footerBtn}
          />
        ) : null}
        <Button
          label={added ? t('looks.viewCart') : t('product.addToCart')}
          icon={added ? 'checkmark' : 'cart-outline'}
          onPress={added ? () => router.push('/cart') : onAdd}
          accessibilityHint={added ? t('product.added') : undefined}
          style={styles.footerBtn}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { paddingBottom: 24 },
  hero: { width: '100%', aspectRatio: 1, backgroundColor: theme.colors.surfaceAlt },
  body: { padding: theme.spacing.xl, gap: 4 },
  brand: { fontSize: 12, color: theme.colors.accent, fontWeight: '800', letterSpacing: 0.5 },
  name: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  nameKo: { fontSize: theme.font.small, color: theme.colors.inkMuted },
  priceRow: { marginTop: 10, gap: 2 },
  price: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  priceLabel: { fontSize: 12, color: theme.colors.inkFaint },
  section: { marginTop: 22, gap: 8 },
  sectionTitle: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  sectionValue: { fontWeight: '400', color: theme.colors.inkMuted },
  hint: { fontSize: 12, color: theme.colors.inkMuted, lineHeight: 17 },
  inlineActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 16 },
  inlineBtn: { flexGrow: 1, minHeight: theme.hitTarget },
  description: { fontSize: theme.font.body, color: theme.colors.ink, lineHeight: 22, marginTop: 18 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tag: { backgroundColor: theme.colors.roseSoft, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  tagText: { fontSize: 12, color: theme.colors.roseDark, fontWeight: '600' },
  footer: {
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
    backgroundColor: theme.colors.surface,
  },
  footerBtn: { flex: 1 },
});
