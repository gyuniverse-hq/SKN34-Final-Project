import * as Haptics from 'expo-haptics';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { VideoCard } from '@/components/celeb/VideoCard';
import { ProductLineCard } from '@/components/shop/ProductLineCard';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { ProductImage } from '@/components/ui/ProductImage';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { canTryOn, resolveShade } from '@/lib/catalog';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useLook, useTutorials } from '@/lib/queries';
import { arHref, parseId, productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';

export default function LookDetailScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const id = parseId(params.id);
  const router = useRouter();
  const { t } = useI18n();
  const query = useLook(id);
  const tutorials = useTutorials(query.data?.look.tutorialQuery, 4);
  const applyLook = useMakeupStore((s) => s.applyLook);
  const add = useCartStore((s) => s.add);
  const addMany = useCartStore((s) => s.addMany);
  const [added, setAdded] = useState(false);
  const [addedLine, setAddedLine] = useState<string | null>(null);

  if (!id) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  const { look, products } = query.data;
  const lines = look.items.flatMap((item) => {
    const product = products.find((p) => p.id === item.productId);
    const { availability, shade } = resolveShade(product, item.shadeId);
    return product && availability === 'available' ? [{ item, product, shade }] : [];
  });
  const missingCount = look.items.length - lines.length;
  const total = lines.reduce((sum, l) => sum + l.product.priceKRW, 0);

  const onLookToCart = () => {
    addMany(lines.map((l) => ({ productId: l.product.id, shadeId: l.shade?.id, addedFromLookId: look.id })));
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: look.title }} />
      <ScrollView contentContainerStyle={styles.content}>
        <ProductImage uri={look.thumbnailUrl} style={styles.hero} />
        <View style={styles.body}>
          {look.inspiration ? <Text style={styles.inspiration}>{look.inspiration}</Text> : null}
          <Text style={styles.title} accessibilityRole="header">
            {look.title}
          </Text>
          {look.description ? <Text style={styles.description}>{look.description}</Text> : null}
          <View style={styles.badges}>
            <Badge label={t('badge.vishuePick')} tone="brand" icon="sparkles-outline" />
            {[look.makeup.lip, look.makeup.blush, look.makeup.eyeshadow].some(Boolean) ? (
              <Badge label={t('looks.arReady')} tone="neutral" icon="scan-outline" />
            ) : null}
          </View>
          <View style={styles.gap} />
          <Notice tone="neutral" body={t('looks.pickNotice')} />

          <Text style={styles.sectionTitle} accessibilityRole="header">
            {t('looks.productsInLook')}
          </Text>
          {lines.length === 0 ? <Text style={styles.note}>{t('looks.noProducts')}</Text> : null}
          <View style={styles.list}>
            {lines.map(({ item, product, shade }) => {
              const key = `${product.id}::${shade?.id ?? ''}`;
              const actions = [
                ...(canTryOn(product)
                  ? [{ label: t('rec.tryThis'), icon: 'scan-outline' as const, onPress: () => router.push(arHref({ productId: product.id, shadeId: shade?.id })) }]
                  : []),
                {
                  label: addedLine === key ? t('product.added') : t('product.addToCart'),
                  icon: addedLine === key ? ('checkmark' as const) : ('cart-outline' as const),
                  variant: 'primary' as const,
                  onPress: () => {
                    add({ productId: product.id, shadeId: shade?.id, addedFromLookId: look.id });
                    setAddedLine(key);
                  },
                },
              ];
              return (
                <ProductLineCard
                  key={`${item.step}-${key}`}
                  product={product}
                  shade={shade}
                  eyebrow={t(`looks.step.${item.step}` as TranslationKey)}
                  onPress={() => router.push(productHref(product.id, shade?.id))}
                  actions={actions}
                />
              );
            })}
          </View>
          {missingCount > 0 ? <Text style={styles.note}>{t('looks.missingProducts', { count: missingCount })}</Text> : null}
          {lines.length > 0 ? (
            <View style={styles.totalRow}>
              <Text style={styles.totalLabel}>{t('looks.setTotal')}</Text>
              <Text style={styles.totalValue}>{formatKRW(total)}</Text>
            </View>
          ) : null}

          {tutorials.data?.configured !== false ? (
            <>
              <Text style={styles.sectionTitle}>{t('looks.tutorials')}</Text>
              {tutorials.isPending && tutorials.fetchStatus !== 'idle' ? (
                <ActivityIndicator color={theme.colors.rose} style={{ marginVertical: 12 }} />
              ) : tutorials.isError ? (
                <Text style={styles.note}>{t('looks.tutorialsUnavailable')}</Text>
              ) : tutorials.data?.videos.length === 0 ? (
                <Text style={styles.note}>{t('looks.noTutorials')}</Text>
              ) : (
                tutorials.data?.videos.map((video) => <VideoCard key={video.videoId} video={video} />)
              )}
            </>
          ) : null}
          <Text style={styles.disclaimer}>{t('looks.disclaimer')}</Text>
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Button
          label={t('looks.applyInAr')}
          icon="scan-outline"
          variant="secondary"
          onPress={() => {
            applyLook(look, products);
            router.push(arHref({ compare: true }));
          }}
        />
        <Button
          label={added ? t('looks.viewCart') : t('looks.lookToCart')}
          icon={added ? 'checkmark' : 'cart-outline'}
          disabled={lines.length === 0}
          onPress={added ? () => router.push('/cart') : onLookToCart}
          accessibilityHint={added ? t('looks.addedToCart') : undefined}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { paddingBottom: 24 },
  hero: { width: '100%', height: 280, backgroundColor: theme.colors.surfaceAlt },
  body: { padding: theme.spacing.xl },
  inspiration: { fontSize: 12, fontWeight: '700', color: theme.colors.accent },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink, marginTop: 4 },
  description: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22, marginTop: 8 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12 },
  gap: { height: 12 },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 28, marginBottom: 10 },
  list: { gap: 10 },
  totalRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 14 },
  totalLabel: { fontSize: theme.font.body, color: theme.colors.inkMuted },
  totalValue: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 8 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 20, lineHeight: 16 },
  footer: {
    gap: 8,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
    backgroundColor: theme.colors.surface,
  },
});
