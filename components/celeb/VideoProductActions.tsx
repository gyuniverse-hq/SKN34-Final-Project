import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { canTryOn } from '@/lib/catalog';
import { useI18n } from '@/lib/i18n';
import { lookMatchType } from '@/lib/lookProductMatch';
import { parseId } from '@/lib/routes';
import { isArPaintZone } from '@/store/makeupStore';
import type { Product, VideoProductMapping } from '@/types';

interface Props {
  mapping: VideoProductMapping;
  product?: Product;
  onProduct: (productId: string, shadeId?: string) => void;
  onTryOn: (productId: string, shadeId: string) => void;
}

export function VideoProductActions({ mapping, product, onProduct, onTryOn }: Props) {
  const { t } = useI18n();
  const productId = parseId(mapping.catalogProductId);
  if (!productId || !product || product.id !== productId) return null;
  const shadeId = parseId(mapping.catalogShadeId);
  const shade = product.shades.find((item) => item.id === shadeId);
  const validShade = shade && shade.measureMethod !== 'placeholder' && shade.colorSource !== 'placeholder' ? shade : undefined;
  if (mapping.mappingVerified === true) {
    const tryOn = validShade && canTryOn(product) && product.makeupZone && isArPaintZone(product.makeupZone);
    return (
      <View style={styles.actions}>
        <Text style={styles.verified}>{t('videoAr.verifiedProduct')}</Text>
        <Pressable accessibilityRole="button" onPress={() => onProduct(productId, validShade?.id)} style={styles.link}>
          <Text style={styles.linkText}>{t('styleLooks.openProduct')}</Text>
        </Pressable>
        {tryOn && validShade ? <Pressable accessibilityRole="button" onPress={() => onTryOn(productId, validShade.id)} style={styles.link}>
          <Text style={styles.linkText}>{t('styleLooks.tryAr')}</Text>
        </Pressable> : null}
      </View>
    );
  }
  if (lookMatchType(mapping, product, validShade) === 'UNVERIFIED' && validShade) {
    return (
      <View style={styles.actions}>
        <Text style={styles.verified}>{t('videoAr.similarProduct')}</Text>
      </View>
    );
  }
  return null;
}

const styles = StyleSheet.create({
  actions: { marginTop: 8, gap: 6 },
  verified: { color: theme.colors.success, fontWeight: '700', fontSize: 12 },
  link: { minHeight: 44, justifyContent: 'center' },
  linkText: { color: theme.colors.rose, fontWeight: '700' },
});
