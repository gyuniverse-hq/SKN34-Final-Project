import * as Haptics from 'expo-haptics';
import * as WebBrowser from 'expo-web-browser';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { ProductImage } from '@/components/ui/ProductImage';
import { ShadePicker } from '@/components/ui/ShadePicker';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { HomeChatButton } from '@/components/chat/HomeChatButton';
import { canTryOn, pickShade } from '@/lib/catalog';
import { isSafeExternalUrl } from '@/lib/externalLink';
import { notify } from '@/lib/confirm';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProduct, useProductOption, useProductVideos } from '@/lib/queries';
import { arHref, chatHref, parseId, productVideoHref, recommendationsHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { useRecommendationProductFeedback } from '@/hooks/useRecommendationProductFeedback';
import { MAX_COMPARE, useCompareStore } from '@/store/compareStore';
export default function ProductDetailScreen() {
  const params = useLocalSearchParams<{ id: string; shade?: string; recommendation?: string; requireShade?: string; optionId?: string }>();
  const id = parseId(params.id);
  const optionId = parseId(params.optionId);
  const sale = useProductOption(id, optionId);
  const requestedShadeId = parseId(params.shade);
  const router = useRouter();
  const { t } = useI18n();
  const product = useProduct(id);
  const feedback = useRecommendationProductFeedback(parseId(params.recommendation), id, product.isSuccess);
  const productVideos = useProductVideos(id);
  const addToCart = useCartStore((s) => s.add);
  const addToCompare = useCompareStore((s) => s.add);
  const inCompare = useCompareStore((s) => s.items.some((i) => i.productId === id));
  const [selection, setSelection] = useState({ productId: id, shadeId: requestedShadeId });
  // An unchanged route shade can be retained from the previous product.
  const pickedShadeId = selection.productId === id
    ? selection.shadeId
    : requestedShadeId === selection.shadeId ? undefined : requestedShadeId;
  const selectionKey = JSON.stringify([id, optionId, pickedShadeId]);
  const [addedKey, setAddedKey] = useState<string>();
  const added = addedKey === selectionKey;

  useEffect(() => {
    if (!added) return;
    const timer = setTimeout(() => setAddedKey(undefined), 2400);
    return () => clearTimeout(timer);
  }, [added]);

  if (params.optionId !== undefined && !optionId) return <EmptyState icon="search-outline" title={t('sale.unavailable')} />;
  if (!id) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  if (product.isPending) return <LoadingState />;
  if (product.isError) return <ErrorState error={product.error} onRetry={() => product.refetch()} />;

  if (optionId && sale.isPending) return <LoadingState />;
  if (optionId && (sale.isError || sale.data?.productId !== id || sale.data?.optionId !== optionId))
    return <EmptyState icon="search-outline" title={t('sale.unavailable')} />;
  const option = optionId ? sale.data : undefined;
  const p = product.data;
  const selectedShade = optionId ? p.shades.find(s => s.id === option?.arShadeId) : params.requireShade === '1' ? p.shades.find((shade) => shade.id === pickedShadeId) : pickShade(p, pickedShadeId);
  const arShade = optionId ? selectedShade : p.shades.find((shade) => shade.id === pickedShadeId);
  const shadeMissing = !!requestedShadeId && pickedShadeId === requestedShadeId && !p.shades.some((s) => s.id === requestedShadeId);
  const tryOn = canTryOn(p) && (!optionId || !!arShade);

  const selectShade = (shadeId: string) => {
    setSelection({ productId: id, shadeId });
    router.setParams({ shade: shadeId });
  };

  const onAdd = () => {
    if (!optionId && params.requireShade === '1' && p.shades.length && !selectedShade) { notify(t('chat.ingredient.selection')); return; }
    const quantity = () => useCartStore.getState().items.find(i => i.productId === p.id && (optionId ? i.optionId === optionId : !i.optionId && i.shadeId === selectedShade?.id))?.quantity ?? 0;
    const before = quantity();
    const cart = feedback.prepareCartAdd();
    addToCart({ productId: p.id, shadeId: selectedShade?.id, ...(optionId ? { optionId } : {}),
      ...(cart?.source ? { skincareCartSources: [cart.source] } : {}),
    });
    if (quantity() > before) cart?.record();
    setAddedKey(selectionKey);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const onCompare = () => {
    if (!optionId && params.requireShade === '1' && p.shades.length && !selectedShade) { notify(t('chat.ingredient.selection')); return; }
    if (addToCompare({ productId: p.id, shadeId: selectedShade?.id })) router.push('/compare');
    else notify(t('compare.full', { max: MAX_COMPARE }));
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: p.brand }} />
      <View style={styles.scrollArea}>
        <ScrollView contentContainerStyle={styles.content}>
          <ProductImage uri={optionId ? option?.image?.url ?? '' : p.imageUrl} category={p.category} style={styles.hero} recyclingKey={optionId ?? p.id} />
          <View style={styles.body}>
            {feedback.failed ? <Notice tone="warning" body={t('skincare.feedbackFailed')} /> : null}
            <Text style={styles.brand}>{p.brand}</Text>
            <Text style={styles.name} accessibilityRole="header">
              {p.name}
            </Text>
            <Text style={styles.nameKo}>{p.nameKo}</Text>
            {option ? <>
              <Text style={styles.sectionTitle}>{option.name}</Text>
              <Text style={styles.hint}>{t(option.image ? `sale.image.${option.image.kind}` : 'sale.image.missing')}</Text>
              <Text style={styles.hint}>{t('sale.checkoutBlocked')}</Text>
              {option.observedAt ? <Text style={styles.hint}>{t('sale.observedAt', { date: option.observedAt })}</Text> : null}
            </> : null}
            <View style={styles.priceRow}>
              <Text style={styles.price}>{optionId ? option?.priceKRW != null ? formatKRW(option.priceKRW) : t('sale.priceUnknown') : formatKRW(p.priceKRW)}</Text>
              <Text style={styles.priceLabel}>
                {t('product.referencePrice')} · {t('product.size')} {p.volume}
              </Text>
            </View>

            {!optionId && p.shades.length > 0 ? (
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
                disabled={!!optionId}
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

            {p.texture ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>{t('compare.texture')}</Text>
                <Text style={styles.hint}>{t(`texture.${p.texture}` as TranslationKey)}</Text>
              </View>
            ) : null}

            {productVideos.data?.length ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>{t('product.videosTitle')}</Text>
                {productVideos.data.map((video) => (
                  <Pressable key={`${video.source}-${video.id}-${video.shadeId ?? ''}`}
                    accessibilityRole="link" style={styles.videoLink}
                    onPress={() => router.push(productVideoHref(video.source, video.id))}>
                    <Text style={styles.videoTitle}>{video.title}</Text>
                    {video.channelName ? <Text style={styles.hint}>{video.channelName}</Text> : null}
                  </Pressable>
                ))}
              </View>
            ) : null}

          </View>
        </ScrollView>
        <HomeChatButton label={t('home.chatFab')} hint={t('home.chatFabHint')}
          onPress={() => router.push(chatHref({ productId: p.id, shadeId: arShade?.id }))} />
      </View>

      <View style={styles.footer}>
        {tryOn ? (
          <Button
            label={t('product.tryInAr')}
            icon="scan-outline"
            variant="secondary"
            onPress={() => {
              if (!arShade) { notify(t('chat.selectShade')); return; }
              router.push(arHref({ productId: p.id, shadeId: arShade.id }));
            }}
            style={styles.footerBtn}
          />
        ) : null}
        {p.sourceUrl && isSafeExternalUrl(p.sourceUrl) ? (
          <Button
            label={t('ar.openStore')}
            icon="open-outline"
            variant="secondary"
            onPress={() => { void WebBrowser.openBrowserAsync(p.sourceUrl!); }}
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
  scrollArea: { flex: 1 },
  content: { paddingBottom: 94 },
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
  videoLink: { minHeight: theme.hitTarget, justifyContent: 'center', paddingVertical: 8 },
  videoTitle: { color: theme.colors.rose, fontWeight: '700' },
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
