import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { VideoCard } from '@/components/celeb/VideoCard';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useLook, useTutorials } from '@/lib/queries';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';

export default function LookDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const query = useLook(id);
  const tutorials = useTutorials(query.data?.look.tutorialQuery, 4);
  const applyLook = useMakeupStore((s) => s.applyLook);
  const addMany = useCartStore((s) => s.addMany);
  const [added, setAdded] = useState(false);

  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  const { look, products } = query.data;
  const lines = look.items
    .map((item) => {
      const product = products.find((p) => p.id === item.productId);
      if (!product) return null;
      const shade = product.shades.find((s) => s.id === item.shadeId);
      return { item, product, shade };
    })
    .filter((l): l is NonNullable<typeof l> => !!l);
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
