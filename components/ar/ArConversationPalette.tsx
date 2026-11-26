import Ionicons from '@expo/vector-icons/Ionicons';
import { useCallback, useEffect, useRef } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { Product, Shade } from '@/types';

const STEPS = [
  { icon: 'mic-outline', text: 'ar.conversation.startMic' },
  { icon: 'chatbubble-outline', text: 'ar.conversation.askProduct' },
  { icon: 'color-palette-outline', text: 'ar.conversation.tryColor' },
] as const;

export function ArConversationGuide() {
  const { t } = useI18n();
  return (
    <View testID="ar-conversation-guide" style={styles.guide}>
      {STEPS.map(({ icon, text }, index) => (
        <View key={text} accessible style={styles.card}>
          <Text style={styles.step}>{t('ar.conversation.step', { number: index + 1 })}</Text>
          <Ionicons name={icon} size={20} color={theme.colors.white} accessible={false} />
          <Text style={styles.instruction}>{t(text)}</Text>
        </View>
      ))}
    </View>
  );
}

const CHIP_SLOT = 54;

export function ArConversationShades({ product, selectedShadeId, onSelect }: {
  product: Product;
  selectedShadeId: string;
  onSelect: (shade: Shade) => void;
}) {
  const { t } = useI18n();
  const list = useRef<FlatList<Shade>>(null);
  const selectedIndex = product.shades.findIndex(shade => shade.id === selectedShadeId);
  const centerSelection = useCallback(() => {
    if (selectedIndex >= 0) {
      list.current?.scrollToIndex({ index: selectedIndex, viewPosition: 0.5, animated: false });
    }
  }, [selectedIndex]);
  useEffect(centerSelection, [centerSelection, product.id]);
  return (
    <FlatList
      ref={list}
      testID="ar-conversation-shades"
      horizontal
      accessibilityRole="radiogroup"
      accessibilityLabel={t('ar.arc.palette')}
      keyboardShouldPersistTaps="handled"
      showsHorizontalScrollIndicator={false}
      data={product.shades}
      extraData={selectedShadeId}
      keyExtractor={shade => shade.id}
      getItemLayout={(_, index) => ({ length: CHIP_SLOT, offset: index * CHIP_SLOT, index })}
      onContentSizeChange={centerSelection}
      style={[styles.palette, { width: CHIP_SLOT * Math.min(5, product.shades.length) }]}
      renderItem={({ item }) => {
        const selected = item.id === selectedShadeId;
        return (
          <Pressable accessibilityRole="radio" accessibilityLabel={item.name}
            accessibilityState={{ checked: selected }} onPress={() => { if (!selected) onSelect(item); }}
            style={styles.chipSlot}>
            <View style={[styles.ring, selected && styles.selectedRing]}>
              <View style={[styles.chip, { backgroundColor: item.hex }]} />
            </View>
          </Pressable>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  guide: { flexDirection: 'row', justifyContent: 'center', alignItems: 'stretch', alignSelf: 'center',
    width: '100%', maxWidth: 400, paddingHorizontal: 12, gap: 6 },
  card: { flex: 1, minWidth: 0, alignItems: 'center', justifyContent: 'center', gap: 5,
    paddingVertical: 9, paddingHorizontal: 5, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.72)', backgroundColor: theme.colors.overlay },
  step: { color: theme.colors.roseSoft, fontSize: 10, fontWeight: '700', letterSpacing: 0.6 },
  instruction: { color: theme.colors.white, fontSize: theme.font.caption, fontWeight: '600',
    lineHeight: 17, textAlign: 'center' },
  palette: { alignSelf: 'center', flexGrow: 0, flexShrink: 0, maxWidth: '100%', height: 48 },
  chipSlot: { width: CHIP_SLOT, height: 48, justifyContent: 'center', alignItems: 'center' },
  ring: { width: 44, height: 44, borderRadius: 22, borderWidth: 1.5, borderColor: 'transparent',
    alignItems: 'center', justifyContent: 'center' },
  selectedRing: { borderColor: theme.colors.white },
  chip: { width: 34, height: 34, borderRadius: 17, borderWidth: 1, borderColor: 'rgba(255,255,255,0.65)' },
});
