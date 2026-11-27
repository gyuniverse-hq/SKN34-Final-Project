import Ionicons from '@expo/vector-icons/Ionicons';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Platform, Pressable, StyleSheet, Text, View, useWindowDimensions, type FlatList } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { ColorSwatch } from '@/lib/nearbyColors';
import { ArcFeatherView } from './ArcFeatherView';

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
const PALETTE_HEIGHT = 48;
const RING_SIZE = 44;
const PALETTE_WIDTH = CHIP_SLOT * 5;
const EDGE_FEATHER = 20;
const VISIBLE_RADIUS = 4;
const useNativeDriver = Platform.OS !== 'web';
const swatchKey = ({ product, shade }: ColorSwatch) => JSON.stringify([product.id, shade.id]);

export function ArConversationShades({ items, selected, onSelect, itemLabel, selectOnSwipe = false }: {
  items: readonly ColorSwatch[];
  selected?: ColorSwatch | null;
  onSelect: (item: ColorSwatch) => void;
  itemLabel?: (item: ColorSwatch, index: number) => string;
  selectOnSwipe?: boolean;
}) {
  const { t } = useI18n();
  const { width: windowWidth } = useWindowDimensions();
  const [reduceMotion, setReduceMotion] = useState(false);
  const list = useRef<FlatList<ColorSwatch>>(null);
  const isUserScroll = useRef(false);
  const selectedIndex = items.findIndex(({ product, shade }) => product.id === selected?.product.id && shade.id === selected?.shade.id);
  const targetIndex = Math.max(0, selectedIndex);
  const width = Math.min(windowWidth, PALETTE_WIDTH);
  const sidePadding = Math.max(0, (width - CHIP_SLOT) / 2);
  const trackWidth = items.length * CHIP_SLOT + sidePadding * 2;
  const [scrollOffset] = useState(() => new Animated.Value(targetIndex * CHIP_SLOT));
  const [visibleCenter, setVisibleCenter] = useState(targetIndex);
  const trackOffset = useMemo(() => Animated.multiply(scrollOffset, -1), [scrollOffset]);
  const onScroll = useMemo(() => Animated.event([{ nativeEvent: { contentOffset: { x: scrollOffset } } }], {
    useNativeDriver,
  }), [scrollOffset]);
  const previousSelection = useRef<{ index: number; width: number } | null>(null);
  useEffect(() => {
    let active = true;
    let changed = false;
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', enabled => {
      changed = true;
      setReduceMotion(enabled);
    });
    void AccessibilityInfo.isReduceMotionEnabled().then(enabled => {
      if (active && !changed) setReduceMotion(enabled);
    }).catch(() => {});
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);
  useEffect(() => {
    const listener = scrollOffset.addListener(({ value }) => setVisibleCenter(Math.round(value / CHIP_SLOT)));
    return () => scrollOffset.removeListener(listener);
  }, [scrollOffset]);
  const centerSelection = useCallback((animated: boolean) => {
    const offset = targetIndex * CHIP_SLOT;
    isUserScroll.current = false;
    if (!animated) scrollOffset.setValue(offset);
    list.current?.scrollToOffset({ offset, animated });
  }, [scrollOffset, targetIndex]);
  useLayoutEffect(() => {
    const previous = previousSelection.current;
    previousSelection.current = { index: selectedIndex, width };
    const animate = !reduceMotion && previous?.width === width &&
      previous.index >= 0 && selectedIndex >= 0 && previous.index !== selectedIndex;
    centerSelection(animate);
  }, [centerSelection, reduceMotion, selectedIndex, width]);
  const selectAtOffset = (offset: number) => {
    if (!isUserScroll.current) return;
    isUserScroll.current = false;
    const index = Math.max(0, Math.min(items.length - 1, Math.round(offset / CHIP_SLOT)));
    if (items[index] && index !== selectedIndex) onSelect(items[index]);
  };
  const start = Math.max(0, Math.min(items.length - 1, visibleCenter) - VISIBLE_RADIUS);
  const end = Math.max(start, visibleCenter + VISIBLE_RADIUS + 1);
  return (
    <View testID="ar-conversation-shade-strip" style={[styles.palette, { width }]}>
      <View pointerEvents="none" aria-hidden accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        <ArcFeatherView width={width} height={PALETTE_HEIGHT} feather={Math.min(EDGE_FEATHER, width / 2)} fadeBottom={false}>
          <Animated.View testID="ar-conversation-shade-track"
            style={[styles.track, { width: trackWidth, transform: [{ translateX: trackOffset }] }]}>
            {items.slice(start, end).map((item, index) => (
              <View key={swatchKey(item)} style={[styles.chipSlot, styles.trackSlot, { left: sidePadding + (start + index) * CHIP_SLOT }]}>
                <View style={[styles.ring, start + index === selectedIndex && styles.selectedRing]}>
                  <View style={[styles.chip, { backgroundColor: item.shade.hex }]} />
                </View>
              </View>
            ))}
          </Animated.View>
        </ArcFeatherView>
      </View>
      {/* The mask draws the chips. This scroll view handles touch and accessibility on the same slots. */}
      <Animated.FlatList
        ref={list}
        testID="ar-conversation-shades"
        horizontal
        accessibilityRole="radiogroup"
        accessibilityLabel={t('ar.arc.palette')}
        accessibilityHint={t('ar.arc.swipe')}
        keyboardShouldPersistTaps="handled"
        showsHorizontalScrollIndicator={false}
        persistentScrollbar={false}
        bounces={false}
        overScrollMode="never"
        automaticallyAdjustContentInsets={false}
        style={StyleSheet.absoluteFill}
        contentContainerStyle={{ paddingHorizontal: sidePadding }}
        data={items}
        extraData={selectedIndex}
        keyExtractor={swatchKey}
        getItemLayout={(_, index) => ({ length: CHIP_SLOT, offset: sidePadding + index * CHIP_SLOT, index })}
        onScroll={onScroll}
        scrollEventThrottle={16}
        snapToInterval={selectOnSwipe ? CHIP_SLOT : undefined}
        decelerationRate={selectOnSwipe ? 'fast' : 'normal'}
        onScrollBeginDrag={selectOnSwipe ? () => { isUserScroll.current = true; } : undefined}
        onScrollEndDrag={selectOnSwipe ? ({ nativeEvent }) => {
          if (!nativeEvent.velocity?.x) selectAtOffset(nativeEvent.contentOffset.x);
        } : undefined}
        onMomentumScrollEnd={selectOnSwipe ? ({ nativeEvent }) => selectAtOffset(nativeEvent.contentOffset.x) : undefined}
        onContentSizeChange={() => centerSelection(false)}
        renderItem={({ item, index }) => (
          <Pressable accessibilityRole="radio" accessibilityLabel={itemLabel?.(item, index) ?? item.shade.name}
            accessibilityState={{ checked: index === selectedIndex }}
            onPress={() => { isUserScroll.current = false; onSelect(item); }} style={styles.chipSlot} />
        )}
      />
    </View>
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
  palette: { alignSelf: 'center', flexGrow: 0, flexShrink: 0, maxWidth: '100%', height: PALETTE_HEIGHT, overflow: 'hidden' },
  track: { position: 'absolute', left: 0, top: 0, height: PALETTE_HEIGHT },
  chipSlot: { width: CHIP_SLOT, height: PALETTE_HEIGHT, justifyContent: 'center', alignItems: 'center' },
  trackSlot: { position: 'absolute' },
  ring: { width: RING_SIZE, height: RING_SIZE, borderRadius: RING_SIZE / 2, borderWidth: 1.5, borderColor: 'transparent',
    alignItems: 'center', justifyContent: 'center' },
  selectedRing: { borderColor: theme.colors.white },
  chip: { width: 34, height: 34, borderRadius: 17, borderWidth: 1, borderColor: 'rgba(255,255,255,0.65)' },
});
