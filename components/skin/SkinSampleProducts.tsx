import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { formatKRW } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import type { SkinConcern } from '@/types';
import type { SkinSampleProduct } from '@/types/skinReport';

export function SkinSampleProducts({ matches }: { matches: { product: SkinSampleProduct; matchedConcerns: SkinConcern[] }[] }) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<SkinSampleProduct | null>(null);
  return <>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.rail}>
      {matches.map(({ product, matchedConcerns }) => <Pressable key={product.id} accessibilityRole="button" onPress={() => setSelected(product)} style={styles.card}>
        <View style={styles.art}><Ionicons name={product.name === 'cleanser' ? 'water-outline' : product.name === 'sun' ? 'sunny-outline' : 'flask-outline'} size={44} color={theme.colors.accent} />
          <Text style={styles.artLabel}>{t('report.sampleProducts')}</Text></View>
        <Text style={styles.brand}>{t('report.sampleBrand')}</Text>
        <Text style={styles.name}>{t(`report.sampleProduct.${product.name}`)}</Text>
        <Text style={styles.price}>{formatKRW(product.priceKRW)}</Text>
        <View style={styles.badges}>{matchedConcerns.map((c) => <Text key={c} style={styles.badge}>{t(`concern.${c}` as TranslationKey)}</Text>)}</View>
      </Pressable>)}
    </ScrollView>
    <Modal visible={selected !== null} transparent animationType="fade" onRequestClose={() => setSelected(null)}>
      <View style={styles.overlay}>
        <View style={styles.dialog} accessibilityViewIsModal>
          <Text style={styles.brand}>{t('report.sampleDetail')}</Text>
          {selected ? <>
            <Text style={styles.dialogTitle}>{t(`report.sampleProduct.${selected.name}`)}</Text>
            <Text style={styles.price}>{formatKRW(selected.priceKRW)}</Text>
            <Text style={styles.copy}>{t('report.sampleProductsBody')}</Text>
            <Text style={styles.copy}>{selected.ingredients.map((id) => t(`report.ingredient.${id}`)).join(' · ')}</Text>
          </> : null}
          <Button label={t('report.close')} onPress={() => setSelected(null)} />
        </View>
      </View>
    </Modal>
  </>;
}

const styles = StyleSheet.create({
  rail: { gap: 14, paddingVertical: 4 }, card: { width: 176, gap: 8 },
  art: { height: 160, alignItems: 'center', justifyContent: 'center', gap: 18, borderRadius: 14, backgroundColor: theme.colors.roseSoft },
  artLabel: { fontSize: 10, letterSpacing: 1, color: theme.colors.rose }, brand: { color: theme.colors.accent, fontSize: 10, fontWeight: '700', letterSpacing: 0.5 },
  name: { fontSize: 14, fontWeight: '700', lineHeight: 22, color: theme.colors.ink }, price: { color: theme.colors.ink, fontSize: 15, fontWeight: '700' },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 5 }, badge: { fontSize: 10, paddingVertical: 4, paddingHorizontal: 7, color: theme.colors.rose, backgroundColor: theme.colors.chip, borderRadius: 5 },
  overlay: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: theme.colors.overlay, padding: 24 },
  dialog: { width: '100%', maxWidth: 400, borderRadius: 20, backgroundColor: theme.colors.surface, padding: 24, gap: 18 },
  dialogTitle: { fontSize: 24, lineHeight: 33, fontWeight: '800', color: theme.colors.ink }, copy: { fontSize: 14, lineHeight: 23, color: theme.colors.inkMuted },
});
