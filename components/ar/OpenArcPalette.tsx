import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Platform, Pressable, StyleSheet, View, useWindowDimensions, type GestureResponderEvent } from 'react-native';
import type { ColorSwatch } from '@/lib/nearbyColors';
import { ArcFeatherView } from './ArcFeatherView';
import { arcSnapEasing } from './arcMotion';

interface Props {
  items: readonly ColorSwatch[];
  selected?: ColorSwatch;
  label: string;
  hint: string;
  onSelect: (item: ColorSwatch) => void;
}

const ANGLE_STEP = 16;
const WINDOW_RADIUS = 5;
const wrap = (value: number, count: number) => ((value % count) + count) % count;

/** A small window of catalog shades on one rotating drum, clipped to its open upper arc. */
export function OpenArcPalette({ items, selected, label, hint, onSelect }: Props) {
  const { width } = useWindowDimensions();
  const radius = Math.max(160, Math.min(240, width * 0.56));
  const step = radius * ANGLE_STEP * Math.PI / 180;
  const selectedIndex = items.findIndex((item) => item.product.id === selected?.product.id && item.shade.id === selected?.shade.id);
  const [position] = useState(() => new Animated.Value(Math.max(0, selectedIndex)));
  const [center, setCenter] = useState(Math.max(0, selectedIndex));
  const current = useRef(Math.max(0, selectedIndex));
  const animation = useRef<Animated.CompositeAnimation | null>(null);
  const generation = useRef(0);
  const wheelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousItems = useRef(items);
  const drag = useRef({ x: 0, y: 0, start: 0, lastX: 0, lastTime: 0, velocity: 0 });
  const loops = items.length > 7;
  const bound = (value: number) => loops ? value : Math.max(0, Math.min(Math.max(0, items.length - 1), value));

  const stop = useCallback(() => {
    generation.current += 1;
    if (wheelTimer.current) clearTimeout(wheelTimer.current);
    wheelTimer.current = null;
    animation.current?.stop();
    animation.current = null;
  }, []);

  useEffect(() => {
    const listener = position.addListener(({ value }) => {
      current.current = value;
      // Only recycle chips at slot boundaries; animation frames don't rerender the screen.
      setCenter((previous) => Math.round(value) === previous ? previous : Math.round(value));
    });
    return () => { stop(); position.removeListener(listener); };
  }, [position, stop]);

  useEffect(() => {
    const sameCandidates = previousItems.current === items;
    previousItems.current = items;
    if (sameCandidates && selectedIndex >= 0 && items.length && wrap(Math.round(current.current), items.length) === selectedIndex) return;
    stop();
    // Changing filters must never apply the first candidate to the face.
    position.setValue(Math.max(0, selectedIndex));
  }, [items, selectedIndex, position, stop]);

  const snap = (requested: number, apply = true) => {
    stop();
    if (!items.length) return;
    const target = Math.round(bound(requested));
    const token = generation.current;
    const finish = () => {
      const item = items[wrap(target, items.length)];
      if (apply && item && (item.product.id !== selected?.product.id || item.shade.id !== selected?.shade.id)) onSelect(item);
    };
    const distance = Math.abs(target - current.current);
    if (distance < 0.001) { position.setValue(target); finish(); return; }
    animation.current = Animated.timing(position, {
      toValue: target,
      duration: Math.min(620, 380 + distance * 55),
      easing: arcSnapEasing,
      useNativeDriver: Platform.OS !== 'web',
      isInteraction: false,
    });
    animation.current.start(({ finished }) => {
      // A new gesture, filter, mode change or unmount invalidates the pending selection.
      if (finished && token === generation.current) finish();
    });
  };

  const move = (event: GestureResponderEvent) => {
    const { pageX } = event.nativeEvent;
    const now = event.nativeEvent.timestamp;
    const elapsed = now - drag.current.lastTime;
    if (elapsed > 0) drag.current.velocity = (pageX - drag.current.lastX) / elapsed;
    drag.current.lastX = pageX;
    drag.current.lastTime = now;
    position.setValue(bound(drag.current.start - (pageX - drag.current.x) / step));
  };

  const slots = Array.from({ length: WINDOW_RADIUS * 2 + 1 }, (_, i) => center + i - WINDOW_RADIUS)
    .filter((slot) => items.length && (loops || (slot >= 0 && slot < items.length)))
    .map((slot) => {
      const angle = slot * ANGLE_STEP * Math.PI / 180;
      return { slot, item: items[wrap(slot, items.length)],
        placement: { left: radius + Math.sin(angle) * radius, top: radius - Math.cos(angle) * radius } };
    });
  // Include the full 44px chip in the wheel's bounds: native hit testing clips to parents.
  const drumStyle = [styles.drum, {
    width: radius * 2 + 44, height: radius * 2 + 44, left: width / 2 - radius - 22,
    transform: [{ rotate: position.interpolate({ inputRange: [0, 1], outputRange: ['0deg', String(-ANGLE_STEP) + 'deg'] }) }],
  }];
  return (
    <View testID="ar-arc-palette" style={styles.container}
      accessibilityLabel={label} accessibilityHint={hint}
      accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
      onAccessibilityAction={({ nativeEvent }) => {
        if (nativeEvent.actionName === 'increment') snap(Math.round(current.current) + 1);
        else if (nativeEvent.actionName === 'decrement') snap(Math.round(current.current) - 1);
      }}
      onStartShouldSetResponderCapture={(event) => {
        const { pageX: x, pageY: y } = event.nativeEvent;
        drag.current = { x, y, start: current.current, lastX: x, lastTime: event.nativeEvent.timestamp, velocity: 0 };
        // Allow taps on chips. Capture only once the user actually starts turning the drum.
        return false;
      }}
      onMoveShouldSetResponderCapture={(event) => {
        const dx = Math.abs(event.nativeEvent.pageX - drag.current.x);
        return items.length > 1 && dx > 6 && dx > Math.abs(event.nativeEvent.pageY - drag.current.y);
      }}
      onResponderGrant={(event) => { stop(); drag.current.start = current.current; move(event); }}
      onResponderMove={move}
      onResponderRelease={(event) => {
        const velocity = event.nativeEvent.timestamp - drag.current.lastTime < 80 ? drag.current.velocity : 0;
        // A flick can carry at most three extra slots before the long ease-out settles.
        snap(current.current - Math.max(-3, Math.min(3, velocity * 140 / step)));
      }}
      onResponderTerminationRequest={() => true}
      onResponderTerminate={() => snap(drag.current.start, false)}
      {...(Platform.OS === 'web' ? {
        onWheel: (event: { nativeEvent: { deltaX: number; deltaY: number; deltaMode?: number } }) => {
          stop();
          const { deltaX, deltaY, deltaMode } = event.nativeEvent;
          const delta = (Math.abs(deltaX) > Math.abs(deltaY) ? deltaX : deltaY) * (deltaMode === 1 ? 16 : deltaMode === 2 ? width : 1);
          position.setValue(bound(current.current + Math.max(-3, Math.min(3, delta / step))));
          wheelTimer.current = setTimeout(() => snap(current.current), 100);
        },
      } : {})}>
      <View pointerEvents="none" aria-hidden accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        <ArcFeatherView width={width} height={112}>
          <Animated.View testID="ar-arc-drum" style={drumStyle}>
            {slots.map(({ slot, item, placement }) => (
              <View key={slot} style={[styles.hit, placement, item.product.id === selected?.product.id && item.shade.id === selected?.shade.id && styles.selected]}>
                <View style={[styles.swatch, { backgroundColor: item.shade.hex }]} />
              </View>
            ))}
          </Animated.View>
        </ArcFeatherView>
      </View>
      {/* Keep native touch targets outside the SwiftUI/Compose mask bridge. Both layers share one rotation. */}
      <Animated.View testID="ar-arc-touch-drum" pointerEvents="box-none" style={drumStyle}>
        {slots.map(({ slot, item, placement }) => {
          const active = item.product.id === selected?.product.id && item.shade.id === selected?.shade.id;
          const outsideArc = Math.abs(slot - center) > 3;
          return (
            <Pressable key={slot} accessibilityRole="button" accessibilityLabel={item.product.brand + ' ' + item.product.name + ' ' + item.shade.name}
              accessibilityState={{ selected: active }}
              aria-hidden={outsideArc} accessibilityElementsHidden={outsideArc} importantForAccessibility={outsideArc ? 'no-hide-descendants' : 'auto'}
              disabled={outsideArc} onPress={() => snap(slot)}
              style={[styles.hit, placement]} />
          );
        })}
      </Animated.View>
      <View pointerEvents="none" style={styles.marker} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { height: 112, overflow: 'hidden' },
  drum: { position: 'absolute', top: 10 },
  hit: { position: 'absolute', width: 44, height: 44, borderRadius: 22, borderWidth: 1.5, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  selected: { borderColor: '#FFFFFF' },
  swatch: { width: 34, height: 34, borderRadius: 17, borderWidth: 1, borderColor: 'rgba(255,255,255,0.65)' },
  marker: { position: 'absolute', top: 0, alignSelf: 'center', width: 4, height: 4, borderRadius: 2, backgroundColor: '#FFFFFF' },
});
