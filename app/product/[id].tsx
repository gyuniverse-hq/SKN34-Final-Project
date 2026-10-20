import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { ShadePicker } from '@/components/ui/ShadePicker';
import { ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { useProduct, useProductOffers } from '@/lib/queries';
import { useCartStore } from '@/store/cartStore';
import { useMakeupStore } from '@/store/makeupStore';

export default function ProductDetailScreen() {
  const { id, shade } = useLocalSearchParams<{ id: string; shade?: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const product = useProduct(id);
  const offers = useProductOffers(id);
  const addToCart = useCartStore((s) => s.add);
  const applyShade = useMakeupStore((s) => s.applyShade);
  const [pickedShadeId, setShadeId] = useState<string | undefined>(shade || undefined);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    if (!added) return;
    const timer = setTimeout(() => setAdded(false), 1800);
    return () => clearTimeout(timer);
  }, [added]);

  if (product.isPending) return <LoadingState />;
  if (product.isError) return <ErrorState error={product.error} onRetry={() => product.refetch()} />;

  const p = product.data;
  const selectedShade = p.shades.find((s) => s.id === pickedShadeId) ?? p.shades[0];
  const shadeId = selectedShade?.id;
  const zone = p.makeupZone;

  const onAdd = () => {
    addToCart({ productId: p.id, shadeId: selectedShade?.id });
    setAdded(true);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
  };

  const onTryOn = () => {
    if (selectedShade) applyShade(p, selectedShade);
    router.push('/ar');
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: p.brand }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Image source={{ uri: p.imageUrl }} style={styles.hero} contentFit="cover" transition={150} />
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
              <ShadePicker shades={p.shades} selectedId={shadeId} onSelect={(s) => setShadeId(s.id)} />
            </View>
          ) : null}

          <Text style={styles.description}>{p.description}</Text>

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

          {offers.data?.configured && offers.data.offers.length > 0 ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>{t('product.onlinePrices')}</Text>
              <Text style={styles.hint}>{t('product.onlinePricesHint')}</Text>
              {offers.data.offers.slice(0, 3).map((offer) => (
                <Pressable
                  key={offer.link}
                  onPress={() => WebBrowser.openBrowserAsync(offer.link)}
                  accessibilityRole="link"
                  accessibilityLabel={`${offer.mallName} ${formatKRW(offer.priceKRW)}`}
                  style={({ pressed }) => [styles.offer, pressed && { opacity: 0.85 }]}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.offerMall}>{offer.mallName || 'Online'}</Text>
                    <Text style={styles.offerTitle} numberOfLines={1}>
                      {offer.title}
                    </Text>
                  </View>
                  <Text style={styles.offerPrice}>{formatKRW(offer.priceKRW)}</Text>
                  <Ionicons name="open-outline" size={16} color={theme.colors.inkMuted} />
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      </ScrollView>

      <Button
        label={t('product.buyOfficial')}
        icon="bag-handle-outline"
        variant="ghost"
        compact
        onPress={() => {}}
        style={styles.officialBtn}
      />
      <View style={styles.footer}>
        {zone ? (
          <Button label={t('product.tryInAr')} icon="scan-outline" variant="secondary" onPress={onTryOn} style={styles.footerBtn} />
        ) : null}
        <Button
          label={added ? t('product.added') : t('product.addToCart')}
          icon={added ? 'checkmark' : 'cart-outline'}
          onPress={onAdd}
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
  brand: { fontSize: 12, color: theme.colors.inkMuted, textTransform: 'uppercase', letterSpacing: 1 },
  name: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  nameKo: { fontSize: theme.font.small, color: theme.colors.inkMuted },
  priceRow: { marginTop: 10, gap: 2 },
  price: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  priceLabel: { fontSize: 12, color: theme.colors.inkFaint },
  section: { marginTop: 22, gap: 8 },
  sectionTitle: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
  sectionValue: { fontWeight: '400', color: theme.colors.inkMuted },
  description: { fontSize: theme.font.body, color: theme.colors.ink, lineHeight: 22, marginTop: 18 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tag: { backgroundColor: theme.colors.roseSoft, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill },
  tagText: { fontSize: 12, color: theme.colors.roseDark, fontWeight: '600' },
  hint: { fontSize: 12, color: theme.colors.inkMuted },
  offer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    padding: 12,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  offerMall: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  offerTitle: { fontSize: 12, color: theme.colors.inkMuted },
  offerPrice: { fontSize: theme.font.body, fontWeight: '700', color: theme.colors.ink },
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
  officialBtn: { alignSelf: 'center' },
});
