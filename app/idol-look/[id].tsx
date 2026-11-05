import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { ProductLineCard, type LineAction } from '@/components/shop/ProductLineCard';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { ProductImage } from '@/components/ui/ProductImage';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { canTryOn, resolveShade } from '@/lib/catalog';
import { isSafeExternalUrl } from '@/lib/externalLink';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { hasIdolLookArSettings, idolLookAsCelebLook } from '@/lib/idolLooks';
import { idolLookMapping, lookProductStatus } from '@/lib/lookStatus';
import { useIdolLook } from '@/lib/queries';
import { arHref, parseId, productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';

export default function IdolLookDetailScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const id = parseId(params.id);
  const router = useRouter();
  const { t } = useI18n();
  const query = useIdolLook(id);
  const applyLook = useMakeupStore((s) => s.applyLook);
  const add = useCartStore((s) => s.add);
  const [showPlayer, setShowPlayer] = useState(false);
  const [playerFailed, setPlayerFailed] = useState(false);
  const [addedLine, setAddedLine] = useState<string | null>(null);

  if (!id) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  const { look, products } = query.data;
  const hasArSettings = hasIdolLookArSettings(look);
  const mapping = idolLookMapping(look);
  const watch = () => {
    setPlayerFailed(false);
    setShowPlayer(true);
  };
  const openYoutube = () => {
    if (isSafeExternalUrl(look.video.youtubeUrl)) WebBrowser.openBrowserAsync(look.video.youtubeUrl);
  };
  const embedUrl = `https://www.youtube.com/embed/${encodeURIComponent(look.video.videoId)}?playsinline=1&start=${look.video.startSeconds}`;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: look.displayName }} />
      <ScrollView contentContainerStyle={styles.content}>
        {showPlayer && !playerFailed ? (
          <View style={styles.player}>
            <WebView
              source={{ uri: embedUrl }}
              allowsInlineMediaPlayback
              mediaPlaybackRequiresUserAction={false}
              onError={() => setPlayerFailed(true)}
            />
          </View>
        ) : (
          <ProductImage uri={look.video.thumbnailUrl} style={styles.hero} />
        )}
        <View style={styles.body}>
          <Text style={styles.eyebrow}>{t('home.idolEyebrow')}</Text>
          <Text accessibilityRole="header" style={styles.title}>
            {look.displayName}
          </Text>
          <View style={styles.sourceRow}>
            <Text style={styles.channel} numberOfLines={1}>
              YouTube{look.video.channelName ? ` · ${look.video.channelName}` : ''}
            </Text>
            <Pressable onPress={openYoutube} accessibilityRole="link" hitSlop={8}>
              <Text style={styles.link}>{t('idol.openYoutube')} ↗</Text>
            </Pressable>
          </View>
          {look.video.analysisStatus === 'metadata_unavailable' ? <Notice tone="warning" body={t('idol.videoUnavailable')} /> : null}
          <View style={styles.actions}>
            <Button label={t('idol.video')} icon="logo-youtube" onPress={watch} style={styles.actionBtn} />
            <Button
              label={t('idol.tryAr')}
              icon="scan-outline"
              variant="secondary"
              disabled={!hasArSettings}
              onPress={() => {
                applyLook(idolLookAsCelebLook(look), products);
                router.push(arHref({ compare: true }));
              }}
              style={styles.actionBtn}
            />
          </View>
          {playerFailed ? <Button label={t('idol.openYoutube')} variant="secondary" icon="open-outline" onPress={openYoutube} /> : null}
          {!hasArSettings ? <Text style={styles.note}>{t('idol.noArSettings')}</Text> : null}

          <Text style={styles.heading}>{t('idol.style')}</Text>
          <Text style={styles.description}>{look.styleDescription}</Text>

          <View style={styles.headingRow}>
            <Text style={[styles.heading, styles.headingInRow]}>{t('idol.products')}</Text>
            <Badge label={t(mapping.key, { count: mapping.count })} tone={mapping.tone} />
          </View>
          <Notice tone="neutral" body={t('idol.productsNotice')} />
          <View style={styles.list}>
            {look.products.length === 0 ? <Text style={styles.description}>{t('idol.noProducts')}</Text> : null}
            {look.products.map((entry) => {
              const product = products.find((item) => item.id === entry.productId);
              const status = lookProductStatus(entry.status);
              const zoneLabel = t(`ar.zone.${entry.makeupZone}` as TranslationKey);
              if (!product) {
                return (
                  <View key={entry.id} style={styles.pending}>
                    <Text style={styles.pendingZone}>{zoneLabel}</Text>
                    <Badge label={t(status.key)} tone={status.tone} />
                    <Text style={styles.note}>{t('catalog.productUnavailable')}</Text>
                  </View>
                );
              }
              const { shade } = resolveShade(product, entry.shadeId ?? undefined);
              const key = `${product.id}::${shade?.id ?? ''}`;
              const actions: LineAction[] = [];
              if (canTryOn(product)) {
                actions.push({
                  label: t('rec.tryThis'),
                  icon: 'scan-outline',
                  onPress: () => router.push(arHref({ productId: product.id, shadeId: shade?.id })),
                });
              }
              actions.push({
                label: addedLine === key ? t('product.added') : t('product.addToCart'),
                icon: addedLine === key ? 'checkmark' : 'cart-outline',
                variant: 'primary',
                onPress: () => {
                  add({ productId: product.id, shadeId: shade?.id, addedFromLookId: look.id });
                  setAddedLine(key);
                },
              });
              return (
                <ProductLineCard
                  key={entry.id}
                  product={product}
                  shade={shade}
                  eyebrow={zoneLabel}
                  badges={[{ label: t(status.key), tone: status.tone }]}
                  note={entry.recommendationReason ?? undefined}
                  onPress={() => router.push(productHref(product.id, shade?.id))}
                  actions={actions}>
                  {entry.sourceUrl && isSafeExternalUrl(entry.sourceUrl) ? (
                    <Pressable
                      onPress={() => WebBrowser.openBrowserAsync(entry.sourceUrl!)}
                      accessibilityRole="link"
                      hitSlop={8}>
                      <Text style={styles.link}>{t('idol.evidence')} ↗</Text>
                    </Pressable>
                  ) : null}
                </ProductLineCard>
              );
            })}
          </View>
          <Text style={styles.disclaimer}>{t('looks.disclaimer')}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { paddingBottom: 24 },
  hero: { width: '100%', aspectRatio: 16 / 9, backgroundColor: theme.colors.surfaceAlt },
  player: { width: '100%', aspectRatio: 16 / 9, backgroundColor: theme.colors.black, overflow: 'hidden' },
  body: { padding: theme.spacing.lg, gap: 8 },
  eyebrow: { fontSize: 11, fontWeight: '800', letterSpacing: 1.2, color: theme.colors.accent },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  sourceRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  channel: { flex: 1, color: theme.colors.inkMuted, fontSize: theme.font.small, fontWeight: '600' },
  link: { color: theme.colors.rose, fontSize: theme.font.small, fontWeight: '800' },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  actionBtn: { flexGrow: 1 },
  headingRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 16 },
  heading: { marginTop: 16, fontSize: theme.font.title, color: theme.colors.ink, fontWeight: '800' },
  headingInRow: { flex: 1, marginTop: 0 },
  description: { color: theme.colors.inkMuted, fontSize: theme.font.body, lineHeight: 21 },
  list: { gap: 10, marginTop: 4 },
  pending: { gap: 6, padding: 12, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card },
  pendingZone: { fontSize: 11, fontWeight: '800', color: theme.colors.accent, textTransform: 'uppercase' },
  note: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 17 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 20, lineHeight: 16 },
});
