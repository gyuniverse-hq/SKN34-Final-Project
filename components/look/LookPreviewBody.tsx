import { useRef, useState, type ComponentRef } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { ProductCard } from '@/components/ui/ProductCard';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import type { TranslationKey } from '@/lib/i18n';
import type { LookPreviewZone } from '@/lib/lookPreview';
import type { MakeupZone } from '@/types';
import { LookColorMap } from './LookColorMap';

type Props = {
  zones: LookPreviewZone[];
  title: string;
  addedNotice: boolean;
  onStart: () => void;
  onProduct: (productId: string, shadeId: string) => void;
  onAdd: (productId: string, shadeId: string) => void;
  onOpenCart: () => void;
  t: (key: TranslationKey) => string;
};

export function LookPreviewBody({
  zones,
  title,
  addedNotice,
  onStart,
  onProduct,
  onAdd,
  onOpenCart,
  t,
}: Props) {
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const listY = useRef(0);
  const zoneY = useRef<Partial<Record<MakeupZone, number>>>({});
  const [activeZone, setActiveZone] = useState<MakeupZone | null>(null);

  const jumpToZone = (zone: MakeupZone) => {
    setActiveZone(zone);
    const offset = zoneY.current[zone];
    if (offset == null) return;
    scroll.current?.scrollTo({ y: Math.max(0, listY.current + offset - 12), animated: true });
  };

  return (
    <View style={styles.screen}>
      <ScrollView ref={scroll} contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        <Text style={styles.blurb}>{t(zones.length ? 'lookPreview.intro' : 'lookPreview.empty')}</Text>
        {zones.length ? (
          <>
            <LookColorMap
              zones={zones}
              caption={t('lookPreview.mapCaption')}
              onZonePress={jumpToZone}
            />
            <View
              style={styles.list}
              onLayout={(event) => {
                listY.current = event.nativeEvent.layout.y;
              }}>
              {zones.map((zone) => {
                const products = [zone.product, zone.secondaryProduct].filter((item) => !!item);
                return (
                  <View
                    key={zone.zone}
                    style={[styles.zone, activeZone === zone.zone && styles.zoneActive]}
                    accessibilityLabel={`${zone.index}. ${t(zone.labelKey)}`}
                    onLayout={(event) => {
                      zoneY.current[zone.zone] = event.nativeEvent.layout.y;
                    }}>
                    <View style={styles.zoneHeader}>
                      <View style={styles.badge}>
                        <Text style={styles.index}>{zone.index}</Text>
                      </View>
                      <View style={styles.zoneCopy}>
                        <Text style={styles.zoneName} accessibilityRole="header">
                          {t(zone.labelKey)}
                        </Text>
                        <Text style={styles.hint}>{t(zone.hintKey)}</Text>
                      </View>
                      <View style={styles.arColors} accessibilityLabel={t('lookPreview.arColor')}>
                        <Text style={styles.colorCaption}>{t('lookPreview.arColor')}</Text>
                        <View style={styles.swatchRow}>
                          <View style={[styles.swatch, { backgroundColor: zone.hex }]} />
                          {zone.hexTo ? (
                            <View style={[styles.swatch, { backgroundColor: zone.hexTo }]} />
                          ) : null}
                        </View>
                      </View>
                    </View>
                    {products.length ? (
                      products.map(({ product, shade }, index) => (
                        <View
                          key={`${product.id}:${shade.id}`}
                          style={[styles.product, index > 0 && styles.productDivider]}>
                          <Text style={styles.colorCaption}>{t('lookPreview.productShade')}</Text>
                          <ProductCard
                            product={product}
                            selectedShade={shade}
                            shadeLabel={shade.name}
                            onPress={() => onProduct(product.id, shade.id)}
                          />
                          <Button
                            label={t('lookPreview.addToCart')}
                            accessibilityHint={`${product.name}, ${shade.name}`}
                            variant="secondary"
                            compact
                            style={styles.add}
                            onPress={() => onAdd(product.id, shade.id)}
                          />
                        </View>
                      ))
                    ) : (
                      <Text style={styles.hint}>{t('lookPreview.lookColor')}</Text>
                    )}
                  </View>
                );
              })}
            </View>
          </>
        ) : null}
      </ScrollView>
      <View style={styles.footer}>
        {addedNotice ? (
          <View style={styles.banner} accessibilityLiveRegion="polite">
            <Text style={styles.bannerText}>{t('product.added')}</Text>
            <Pressable
              accessibilityRole="link"
              accessibilityLabel={t('looks.viewCart')}
              onPress={onOpenCart}
              hitSlop={8}>
              <Text style={styles.bannerLink}>{t('looks.viewCart')}</Text>
            </Pressable>
          </View>
        ) : null}
        <Button
          label={t('lookPreview.start')}
          onPress={onStart}
          disabled={!zones.length}
          style={styles.start}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { alignSelf: 'center', width: '100%', maxWidth: 560, padding: theme.spacing.lg, gap: theme.spacing.md },
  title: { color: theme.colors.ink, fontSize: theme.font.h2, fontFamily: theme.fontFamily.display, lineHeight: 30 },
  blurb: { marginTop: -4, color: theme.colors.inkMuted, fontSize: theme.font.body, lineHeight: 22 },
  list: { gap: theme.spacing.sm },
  zone: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.md,
    padding: theme.spacing.md,
    gap: theme.spacing.md,
    backgroundColor: theme.colors.card,
  },
  zoneActive: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  zoneHeader: { flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm },
  badge: {
    minWidth: 26,
    height: 26,
    borderRadius: 13,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.colors.ink,
  },
  index: { color: theme.colors.white, fontSize: 13, fontWeight: '700' },
  zoneCopy: { flex: 1, gap: 2, minWidth: 0 },
  zoneName: { color: theme.colors.ink, fontSize: theme.font.body, fontFamily: theme.fontFamily.display },
  hint: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  arColors: { alignItems: 'flex-end', gap: 4 },
  colorCaption: {
    color: theme.colors.inkFaint,
    fontSize: 10,
    fontFamily: theme.fontFamily.regular,
  },
  swatchRow: { flexDirection: 'row', gap: 4 },
  swatch: { width: 19, height: 19, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 10 },
  product: { gap: theme.spacing.sm },
  productDivider: {
    paddingTop: theme.spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
  add: { alignSelf: 'flex-end', minHeight: theme.hitTarget },
  footer: {
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: theme.colors.border,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.sm,
    paddingBottom: theme.spacing.sm,
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.surface,
  },
  banner: {
    width: '100%',
    maxWidth: 520,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: theme.spacing.sm,
    backgroundColor: theme.colors.roseSoft,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.sm,
  },
  bannerText: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small, fontFamily: theme.fontFamily.regular },
  bannerLink: { color: theme.colors.rose, fontSize: theme.font.small, fontFamily: theme.fontFamily.display },
  start: { width: '100%', maxWidth: 520 },
});
