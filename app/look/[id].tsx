import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { VideoCard } from '@/components/celeb/VideoCard';
import { ColorGaps, type ColorGapRow } from '@/components/look/ColorGaps';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useLookColorGaps } from '@/hooks/useLookColorGaps';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useLook, useTutorials } from '@/lib/queries';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';
import type { CelebLook, Product } from '@/types';

export default function LookDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const query = useLook(id);

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  return <LookDetail look={query.data.look} products={query.data.products} />;
}

function LookDetail({ look, products }: { look: CelebLook; products: Product[] }) {
  const router = useRouter();
  const { t } = useI18n();
  const tutorials = useTutorials(look.tutorialQuery, 4);
  const applyLook = useMakeupStore((s) => s.applyLook);
  const addMany = useCartStore((s) => s.addMany);
  const [added, setAdded] = useState(false);

  const lines = useMemo(
    () =>
      look.items
        .map((item) => {
          const product = products.find((p) => p.id === item.productId);
          if (!product) return null;
          const shade = product.shades.find((s) => s.id === item.shadeId);
          return { item, product, shade };
        })
        .filter((l): l is NonNullable<typeof l> => !!l),
    [look.items, products]
  );
  // A line whose shade is gone from the shop is a missing color, not something to put in the cart.
  const sellable = useMemo(() => lines.filter((l) => !(l.item.shadeId && !l.shade)), [lines]);
  const gaps = useLookColorGaps(look.makeup, sellable);
  // Only the nearest shade of a missing color can be bought here; sellers and sold-out colors cannot.
  const substitutes = gaps.flatMap((g) => (g.kind === 'nearest' ? [g.nearest] : []));
  const total =
    sellable.reduce((sum, l) => sum + l.product.priceKRW, 0) +
    substitutes.reduce((sum, n) => sum + n.product.priceKRW, 0);

  const onLookToCart = () => {
    addMany([
      ...sellable.map((l) => ({ productId: l.product.id, shadeId: l.shade?.id, addedFromLookId: look.id })),
      ...substitutes.map((n) => ({ productId: n.product.id, shadeId: n.shade.id, addedFromLookId: look.id })),
    ]);
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const gapRows: ColorGapRow[] = gaps.map((g) => {
    const base = { key: g.zone, zone: t(`ar.zone.${g.zone}` as TranslationKey), hex: g.hex };
    if (g.kind === 'nearest') {
      const { product, shade } = g.nearest;
      const note =
        g.amount === null
          ? t('looks.color.asIs')
          : g.amount.dir === 'thicker'
            ? t('looks.color.thicker', { n: g.amount.layers })
            : t('looks.color.thinner');
      return {
        ...base,
        status: 'nearest',
        badge: t('looks.color.nearest'),
        headline: `${product.brand} ${product.name} · ${shade.name}`,
        swatch: shade.hex,
        note,
        onPress: () => router.push({ pathname: '/product/[id]', params: { id: product.id, shade: shade.id } }),
      };
    }
    if (g.kind === 'checking') {
      return { ...base, status: 'checking', badge: t('looks.color.checking'), note: t('looks.color.notInCart') };
    }
    if (g.kind === 'soldout') {
      return { ...base, status: 'soldout', badge: t('looks.color.soldOut'), note: t('looks.color.soldOutHint') };
    }
    const open = (url: string) => () => {
      WebBrowser.openBrowserAsync(url).catch(() => {});
    };
    if (g.kind === 'offers') {
      return {
        ...base,
        status: 'offers',
        badge: t('looks.color.offers'),
        note: t('looks.color.notInCart'),
        offers: g.offers.map((o) => ({
          key: o.link,
          text: `${o.mallName} · ${o.title}`,
          price: formatKRW(o.priceKRW),
          onPress: open(o.link),
        })),
        action: { label: t('looks.color.findOnNaver'), onPress: open(g.url) },
      };
    }
    return {
      ...base,
      status: 'link',
      badge: t('looks.color.offers'),
      note: t('looks.color.notInCart'),
      action: { label: t('looks.color.findOnNaver'), onPress: open(g.url) },
    };
  });

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: look.title }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Image source={{ uri: look.thumbnailUrl }} style={styles.hero} contentFit="cover" transition={150} />
        <View style={styles.body}>
          <Text style={styles.inspiration}>{look.inspiration}</Text>
          <Text style={styles.title} accessibilityRole="header">
            {look.title}
          </Text>
          <Text style={styles.description}>{look.description}</Text>

          <Text style={styles.sectionTitle}>{t('looks.productsInLook')}</Text>
          {lines.map(({ item, product, shade }) => (
            <Pressable
              key={`${product.id}-${item.shadeId ?? ''}`}
              onPress={() =>
                router.push({ pathname: '/product/[id]', params: { id: product.id, shade: shade?.id ?? '' } })
              }
              accessibilityRole="button"
              style={({ pressed }) => [styles.line, pressed && { opacity: 0.85 }]}>
              <Image source={{ uri: product.imageUrl }} style={styles.lineImage} contentFit="cover" />
              <View style={{ flex: 1 }}>
                <Text style={styles.step}>{t(`looks.step.${item.step}` as TranslationKey)}</Text>
                <Text style={styles.lineName} numberOfLines={1}>
                  {product.brand} {product.name}
                </Text>
                {shade ? (
                  <View style={styles.shadeRow}>
                    <View style={[styles.shadeDot, { backgroundColor: shade.hex }]} />
                    <Text style={styles.shadeName}>{shade.name}</Text>
                  </View>
                ) : null}
              </View>
              <Text style={styles.linePrice}>{formatKRW(product.priceKRW)}</Text>
            </Pressable>
          ))}
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>{t('looks.setTotal')}</Text>
            <Text style={styles.totalValue}>{formatKRW(total)}</Text>
          </View>

          <ColorGaps title={t('looks.color.title')} intro={t('looks.color.intro')} rows={gapRows} />

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
            router.push('/ar');
          }}
        />
        <Button
          label={added ? t('looks.addedToCart') : t('looks.lookToCart')}
          icon={added ? 'checkmark' : 'cart-outline'}
          onPress={added ? () => router.push('/cart') : onLookToCart}
          accessibilityHint={added ? t('looks.viewCart') : undefined}
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
  inspiration: { fontSize: 12, fontWeight: '700', color: theme.colors.rose },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink, marginTop: 4 },
  description: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22, marginTop: 8 },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 28, marginBottom: 8 },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: theme.colors.border,
  },
  lineImage: { width: 52, height: 52, borderRadius: theme.radius.sm, backgroundColor: theme.colors.surfaceAlt },
  step: { fontSize: 11, fontWeight: '700', color: theme.colors.rose, textTransform: 'uppercase' },
  lineName: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink },
  shadeRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  shadeDot: { width: 10, height: 10, borderRadius: 5 },
  shadeName: { fontSize: 12, color: theme.colors.inkMuted },
  linePrice: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
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
