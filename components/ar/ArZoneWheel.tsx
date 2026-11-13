import Ionicons from '@expo/vector-icons/Ionicons';
import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type ComponentRef } from 'react';
import { Animated, BackHandler, Platform, Pressable, StyleSheet, Text, View, useWindowDimensions, type GestureResponderEvent } from 'react-native';
import Svg, { Circle, Line, Path } from 'react-native-svg';
import { theme } from '@/constants/theme';
import type { MakeupZone } from '@/types';
import { arcSnapEasing } from './arcMotion';

const ICONS: Record<MakeupZone, keyof typeof Ionicons.glyphMap> = {
  lip: 'color-palette-outline', blush: 'brush-outline', eyeshadow: 'eye-outline', eyeliner: 'pencil-outline',
  brow: 'remove-outline', foundation: 'water-outline', highlighter: 'sparkles-outline', contour: 'color-wand-outline', mascara: 'eye-outline',
};
interface Props {
  zones: readonly MakeupZone[]; selected: MakeupZone; labels: Partial<Record<MakeupZone, string>>;
  hint: string; openHint?: string; openLabel: string; closeLabel: string;
  onSelect: (zone: MakeupZone) => void; onOpenChange?: (open: boolean) => void;
}
export const zoneWheelRadius = (width: number) => Math.min(220, (width - 24) / 2);

/** Intersect both text-band edges with the sector rays and circular boundaries. */
function labelBounds(radius: number, inner: number, start: number, end: number, top: number, height: number, preferredX: number) {
  let left = -radius;
  let right = radius;
  for (const y of [top, top + height]) {
    const outerX = Math.sqrt(Math.max(0, radius * radius - y * y));
    left = Math.max(left, -outerX);
    right = Math.min(right, outerX);
    if (start > Math.PI + 0.001) left = Math.max(left, y * Math.cos(start) / Math.sin(start));
    if (end < Math.PI * 2 - 0.001) right = Math.min(right, y * Math.cos(end) / Math.sin(end));
    if (Math.abs(y) < inner) {
      const innerX = Math.sqrt(inner * inner - y * y);
      if ((start + end) / 2 < Math.PI * 1.5) right = Math.min(right, -innerX);
      else left = Math.max(left, innerX);
    }
  }
  const width = Math.max(0, Math.min(56, right - left - 6));
  const x = Math.max(left + 3, Math.min(right - width - 3, preferredX - width / 2));
  return { left: x, width };
}

/** Tap to choose, or hold the hub and slide through the annular sectors. */
export function ArZoneWheel({ zones, selected, labels, hint, openHint, openLabel, closeLabel, onSelect, onOpenChange }: Props) {
  const { width } = useWindowDimensions();
  const radius = zoneWheelRadius(width);
  const inner = radius * 0.36;
  const iconRadius = radius * 0.88;
  const fontSize = width < 360 ? 9 : 10;
  const lineHeight = fontSize + 2;
  const textHeight = lineHeight * 2;
  const [open, setOpen] = useState(false);
  const [visible, setVisible] = useState(false);
  const [hover, setHover] = useState<MakeupZone | null>(null);
  const [reveal] = useState(() => new Animated.Value(0));
  const animation = useRef<Animated.CompositeAnimation | null>(null);
  const hub = useRef<ComponentRef<typeof View>>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const held = useRef(false);
  const origin = useRef({ x: 0, y: 0 });
  const clearTimer = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; };

  const changeOpen = useCallback((next: boolean) => {
    animation.current?.stop();
    setOpen(next);
    if (next) setVisible(true);
    else setHover(null);
    animation.current = Animated.timing(reveal, {
      toValue: next ? 1 : 0, duration: next ? 280 : 200, easing: arcSnapEasing,
      useNativeDriver: Platform.OS !== 'web',
    });
    animation.current.start(({ finished }) => {
      if (finished && !next) setVisible(false);
    });
  }, [reveal, setHover, setOpen, setVisible]);

  useLayoutEffect(() => {
    onOpenChange?.(visible);
    return () => onOpenChange?.(false);
  }, [visible, onOpenChange]);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    animation.current?.stop();
  }, []);
  useEffect(() => {
    if (!visible) return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => { changeOpen(false); return true; });
    return () => sub.remove();
  }, [visible, changeOpen]);

  const targetAt = (event: GestureResponderEvent) => {
    const dx = event.nativeEvent.pageX - origin.current.x;
    const dy = event.nativeEvent.pageY - origin.current.y;
    const distance = Math.hypot(dx, dy);
    // The inner opening is a cancel zone; the entire wedge is selectable, not just its icon.
    if (dy > 0 || distance < inner || distance > radius + 12 || !zones.length) return null;
    const index = Math.min(zones.length - 1, Math.floor(Math.atan2(-dy, -dx) / Math.PI * zones.length));
    return zones[index] ?? null;
  };
  const choose = (zone: MakeupZone) => { onSelect(zone); changeOpen(false); };
  const sectors = zones.map((zone, i) => {
    const start = Math.PI + Math.PI * i / zones.length;
    const end = Math.PI + Math.PI * (i + 1) / zones.length;
    const angle = (start + end) / 2;
    const point = (r: number, a: number) => [width / 2 + Math.cos(a) * r, radius + 1 + Math.sin(a) * r].join(' ');
    const iconX = Math.cos(angle) * iconRadius;
    const iconY = Math.min(Math.sin(angle) * iconRadius, -textHeight - 20);
    const textTop = iconY + 12;
    const textBox = labelBounds(radius, inner, start, end, textTop, textHeight, iconX);
    return {
      zone, angle,
      path: 'M ' + point(radius, start) + ' A ' + radius + ' ' + radius + ' 0 0 1 ' + point(radius, end)
        + ' L ' + point(inner, end) + ' A ' + inner + ' ' + inner + ' 0 0 0 ' + point(inner, start) + ' Z',
      iconX: width / 2 + iconX,
      iconY: radius + 1 + iconY,
      textLeft: width / 2 + textBox.left,
      textTop: radius + 1 + textTop,
      textWidth: textBox.width,
    };
  });
  const hovered = sectors.find((sector) => sector.zone === hover);
  return (
    <View pointerEvents="box-none" style={[styles.container, { height: visible ? radius + 88 : 88 }]}>
      {visible ? (
        <View testID="ar-zone-fan" pointerEvents={open ? 'box-none' : 'none'} style={StyleSheet.absoluteFill} accessibilityViewIsModal
          onStartShouldSetResponderCapture={(event) => !!targetAt(event)}
          onResponderGrant={(event) => setHover(targetAt(event))}
          onResponderMove={(event) => setHover(targetAt(event))}
          onResponderRelease={(event) => { const target = targetAt(event); if (target) choose(target); else changeOpen(false); }}
          onResponderTerminate={() => setHover(null)}>
          <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel={closeLabel} onPress={() => changeOpen(false)} />
          <Animated.View style={[styles.fan, {
            width, height: radius + 2, opacity: reveal,
            transform: [{ translateY: (radius + 2) / 2 }, { scale: reveal.interpolate({ inputRange: [0, 1], outputRange: [0.88, 1] }) }, { translateY: -(radius + 2) / 2 }],
          }]}>
            <Svg width={width} height={radius + 2} pointerEvents="none" accessible={false}>
              {sectors.map(({ zone, path }) => (
                <Path key={zone} d={path} fill={(hover ?? selected) === zone ? 'rgba(151,61,93,0.72)' : 'rgba(37,30,33,0.52)'}
                  stroke="rgba(255,255,255,0.7)" strokeWidth={0.8} strokeLinejoin="round" />
              ))}
              {hovered ? <>
                <Line x1={width / 2} y1={radius + 1} x2={width / 2 + Math.cos(hovered.angle) * (inner + 22)} y2={radius + 1 + Math.sin(hovered.angle) * (inner + 22)} stroke="white" strokeWidth={1.5} />
                <Circle cx={width / 2 + Math.cos(hovered.angle) * (inner + 22)} cy={radius + 1 + Math.sin(hovered.angle) * (inner + 22)} r={4} fill="white" />
              </> : null}
            </Svg>
            {sectors.map(({ zone, iconX, iconY, textLeft, textTop, textWidth }) => (
              <Fragment key={zone}>
                <View pointerEvents="none" style={[styles.sectorIcon, { left: iconX - 12, top: iconY - 12 }]}>
                  <Ionicons name={ICONS[zone]} size={21} color="#FFFFFF" />
                </View>
                <Pressable accessibilityRole="button" accessibilityLabel={labels[zone]}
                  accessibilityState={{ selected: selected === zone }} onPress={() => choose(zone)}
                  style={[styles.sectorLabel, { width: textWidth, height: textHeight, left: textLeft, top: textTop }]}>
                  <Text style={[styles.zoneLabel, { fontSize, lineHeight }]} numberOfLines={2}>{labels[zone]}</Text>
                </Pressable>
              </Fragment>
            ))}
          </Animated.View>
        </View>
      ) : null}
      <View ref={hub} accessible focusable accessibilityRole="button" accessibilityLabel={openLabel} accessibilityHint={hint}
        accessibilityState={{ expanded: open }} accessibilityActions={[{ name: 'activate', label: openLabel }]}
        onAccessibilityAction={() => changeOpen(!open)}
        onStartShouldSetResponder={() => true}
        onResponderGrant={(event) => {
          origin.current = { x: event.nativeEvent.pageX, y: event.nativeEvent.pageY };
          hub.current?.measureInWindow((x, y, w, h) => { if (w && h) origin.current = { x: x + w / 2, y: y + h / 2 }; });
          held.current = open;
          clearTimer();
          if (!open) timer.current = setTimeout(() => { held.current = true; changeOpen(true); }, 350);
        }}
        onResponderMove={(event) => { if (held.current) setHover(targetAt(event)); }}
        onResponderRelease={(event) => {
          clearTimer();
          const target = held.current ? targetAt(event) : null;
          if (target) choose(target);
          else if (!held.current) changeOpen(!open);
          else changeOpen(false);
        }}
        onResponderTerminationRequest={() => false}
        onResponderTerminate={() => { clearTimer(); held.current = false; changeOpen(false); }}
        style={[styles.hub, { marginTop: visible ? radius : 0 }]}>
        <Ionicons name={ICONS[selected]} size={22} color="#FFFFFF" />
        <Text style={styles.hubLabel}>{labels[selected]}</Text>
      </View>
      <Text style={styles.hint}>{open ? openHint ?? hint : hint}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { width: '100%', alignItems: 'center', justifyContent: 'flex-start', zIndex: 5 },
  fan: { position: 'absolute', top: 31 },
  sectorIcon: { position: 'absolute', width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  sectorLabel: { position: 'absolute', overflow: 'hidden', justifyContent: 'center' },
  hub: { width: 64, height: 64, borderRadius: 32, borderWidth: 1.5, borderColor: '#FFFFFF', backgroundColor: theme.colors.rose, alignItems: 'center', justifyContent: 'center', gap: 2 },
  zoneLabel: { color: '#FFFFFF', fontWeight: '500', textAlign: 'center' },
  hubLabel: { color: '#FFFFFF', fontSize: 10, fontWeight: '600' },
  hint: { marginTop: 6, fontSize: 10, color: 'rgba(255,255,255,0.8)' },
});
