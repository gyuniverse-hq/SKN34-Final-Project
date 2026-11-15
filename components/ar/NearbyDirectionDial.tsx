import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import { Animated, Modal, Platform, Pressable, StyleSheet, Text, View, useWindowDimensions, type GestureResponderEvent } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { arcSnapEasing } from './arcMotion';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { NEARBY_DIRECTIONS, type NearbyDirection } from '@/lib/nearbyColors';

const STEP = 44;
const HEIGHT = STEP * 5;
const clamp = (value: number) => Math.max(0, Math.min(NEARBY_DIRECTIONS.length - 1, value));

interface Props {
  direction: NearbyDirection;
  counts: Record<NearbyDirection, number>;
  onDirection: (direction: NearbyDirection) => void;
}

/** A discrete radio scale. Only the settled needle position changes candidates. */
export function NearbyDirectionDial({ direction, counts, onDirection }: Props) {
  const { t } = useI18n();
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const trigger = useRef<ComponentRef<typeof View>>(null);
  const [position, setPosition] = useState<{ top: number; right: number; width: number; height: number; direction: NearbyDirection } | null>(null);
  const visible = position !== null && position.width === width && position.height === height && position.direction === direction;
  // Discard old geometry, including if the window later returns to the same size.
  if (position && !visible) setPosition(null);
  const [preview, setPreview] = useState(0);
  const [notice, setNotice] = useState<NearbyDirection | null>(null);
  const [offset] = useState(() => new Animated.Value(0));
  const [reveal] = useState(() => new Animated.Value(0));
  const [noticeOpacity] = useState(() => new Animated.Value(0));
  const animation = useRef<Animated.CompositeAnimation | null>(null);
  const noticeAnimation = useRef<Animated.CompositeAnimation | null>(null);
  const drag = useRef({ x: 0, y: 0, index: 0 });
  const pending = useRef(false);
  const mounted = useRef(true);
  const open = useRef(false);
  const nativeDriver = Platform.OS !== 'web';

  const cancel = () => {
    open.current = false;
    animation.current?.stop();
    pending.current = false;
    setPosition(null);
  };

  useEffect(() => {
    // Rotation, resize and external direction changes must not commit a stale gesture.
    open.current = false;
    animation.current?.stop();
    pending.current = false;
  }, [direction, width, height]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      open.current = false;
      animation.current?.stop();
      noticeAnimation.current?.stop();
      reveal.stopAnimation();
    };
  }, [reveal]);

  const show = () => {
    noticeAnimation.current?.stop();
    setNotice(null);
    trigger.current?.measureInWindow((x, y, w, h) => {
      if (!mounted.current) return;
      const index = NEARBY_DIRECTIONS.indexOf(direction);
      offset.setValue(index * STEP);
      setPreview(index);
      open.current = true;
      setPosition({
        width, height, direction,
        top: Math.max(insets.top + 8, Math.min(height - insets.bottom - HEIGHT - 8, y + h / 2 - HEIGHT / 2)),
        right: Math.max(insets.right, width - x - w),
      });
      reveal.setValue(0);
      Animated.timing(reveal, { toValue: 1, duration: 240, easing: arcSnapEasing, useNativeDriver: nativeDriver }).start();
    });
  };

  const choose = (index: number) => {
    if (!open.current || pending.current) return;
    pending.current = true;
    const snapped = Math.round(clamp(index));
    setPreview(snapped);
    animation.current = Animated.timing(offset, { toValue: snapped * STEP, duration: 240, easing: arcSnapEasing, useNativeDriver: nativeDriver });
    animation.current.start(({ finished }) => {
      if (!finished || !mounted.current || !open.current) return;
      const selected = NEARBY_DIRECTIONS[snapped];
      open.current = false;
      pending.current = false;
      setPosition(null);
      onDirection(selected);
      setNotice(selected);
      noticeOpacity.setValue(1);
      noticeAnimation.current = Animated.sequence([
        Animated.delay(1200),
        Animated.timing(noticeOpacity, { toValue: 0, duration: 400, easing: arcSnapEasing, useNativeDriver: nativeDriver }),
      ]);
      noticeAnimation.current.start(({ finished: hidden }) => { if (hidden && mounted.current) setNotice(null); });
    });
  };

  const dragIndex = (event: GestureResponderEvent) => clamp(drag.current.index + (event.nativeEvent.pageY - drag.current.y) / STEP);
  const move = (event: GestureResponderEvent) => {
    if (pending.current) return;
    const next = dragIndex(event);
    offset.setValue(next * STEP);
    setPreview(Math.round(next));
  };

  return (
    <View pointerEvents="box-none" style={styles.container}>
      {notice ? <Animated.View pointerEvents="none" style={[styles.notice, { opacity: noticeOpacity }]}>
        <Text style={styles.noticeText} accessibilityLiveRegion="polite">{t(`ar.explore.${notice}`)}</Text>
      </Animated.View> : null}
      <View ref={trigger} testID="ar-direction-anchor" collapsable={false}>
        <Pressable accessibilityRole="button" accessibilityLabel={t('ar.arc.direction')}
          accessibilityValue={{ text: t(`ar.explore.${direction}`) }} accessibilityState={{ expanded: visible }}
          onPress={show} style={[styles.trigger, visible && { opacity: 0 }]}>
          <Ionicons name="caret-back" size={17} color="rgba(255,255,255,0.7)" />
        </Pressable>
      </View>
      {visible ? (
        <Modal transparent animationType="none" statusBarTranslucent onRequestClose={cancel}>
          <View style={styles.overlay}>
            <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel={t('common.cancel')} onPress={cancel} />
            <Animated.View style={[styles.panel, { top: position.top, right: position.right, opacity: reveal, transform: [{ translateX: reveal.interpolate({ inputRange: [0, 1], outputRange: [18, 0] }) }] }]}
              accessibilityViewIsModal>
              <View testID="ar-direction-scale" style={styles.scale}
                onStartShouldSetResponderCapture={(event) => {
                  drag.current = { x: event.nativeEvent.pageX, y: event.nativeEvent.pageY, index: preview };
                  return false;
                }}
                onMoveShouldSetResponderCapture={(event) => !pending.current && Math.abs(event.nativeEvent.pageY - drag.current.y) > 6
                  && Math.abs(event.nativeEvent.pageY - drag.current.y) > Math.abs(event.nativeEvent.pageX - drag.current.x)}
                onResponderGrant={move} onResponderMove={move}
                onResponderRelease={(event) => choose(dragIndex(event))}
                onResponderTerminationRequest={() => true} onResponderTerminate={cancel}>
                <Animated.View pointerEvents="none" style={[styles.selection, { transform: [{ translateY: offset }] }]} />
                {NEARBY_DIRECTIONS.map((item, index) => (
                    <Pressable key={item} accessibilityRole="button" accessibilityLabel={`${t(`ar.explore.${item}`)} · ${counts[item]}`}
                      accessibilityState={{ selected: preview === index }} onPress={() => choose(index)}
                      style={[styles.option, { opacity: preview === index ? 1 : 0.72 }]}>
                      <Text style={styles.label} numberOfLines={1}>{t(`ar.explore.${item}`)}</Text>
                      <Text style={styles.count}>{counts[item]}</Text>
                      <View style={[styles.tick, preview === index && styles.tickSelected]} />
                    </Pressable>
                ))}
              </View>
              <Animated.View style={{ transform: [{ translateY: offset }] }}>
                <Pressable accessibilityRole="button" accessibilityLabel={t('common.cancel')} onPress={cancel} style={styles.needle}>
                  <Ionicons name="caret-back" size={17} color="#FFFFFF" />
                </Pressable>
              </Animated.View>
            </Animated.View>
          </View>
        </Modal>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { position: 'absolute', top: 74, right: 0, alignItems: 'flex-end' },
  trigger: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  overlay: { flex: 1 },
  panel: { position: 'absolute', flexDirection: 'row', width: 234, height: HEIGHT },
  scale: { flex: 1, height: HEIGHT, overflow: 'hidden', borderRadius: 22, backgroundColor: 'rgba(36,25,31,0.94)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.25)' },
  selection: { position: 'absolute', top: 0, left: 6, right: 6, height: STEP, borderRadius: 14, backgroundColor: theme.colors.rose },
  option: { height: STEP, flexDirection: 'row', gap: 9, alignItems: 'center', paddingLeft: 14, paddingRight: 8 },
  label: { flex: 1, color: '#FFFFFF', fontSize: 12, fontWeight: '600' },
  count: { color: '#FFFFFF', fontSize: 10, fontVariant: ['tabular-nums'] },
  tick: { width: 8, height: 1, backgroundColor: '#FFFFFF' },
  tickSelected: { width: 13, height: 2 },
  needle: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  notice: { position: 'absolute', right: 40, top: 7, width: 132, alignItems: 'center', paddingHorizontal: 10, paddingVertical: 8, borderRadius: 16, backgroundColor: 'rgba(36,25,31,0.7)' },
  noticeText: { color: '#FFFFFF', fontSize: 11 },
});
