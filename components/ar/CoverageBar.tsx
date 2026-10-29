import { useRef, useState } from 'react';
import { StyleSheet, Text, View, type GestureResponderEvent } from 'react-native';
import { theme } from '@/constants/theme';

const KNOB = 20;

export interface CoverageBarProps {
  /** 0..1 */
  value: number;
  labels: { title: string; low: string; high: string };
  onChange: (value: number) => void;
}

/** Drag bar for the foundation coverage (how strongly the color is laid on the skin in AR), applied live. */
export function CoverageBar({ value, labels, onChange }: CoverageBarProps) {
  const [trackW, setTrackW] = useState(0);
  const trackWRef = useRef(0);
  const last = useRef(value);
  const move = (e: GestureResponderEvent) => {
    const w = trackWRef.current;
    const v = w <= 0 ? value : Math.round(Math.min(1, Math.max(0, e.nativeEvent.locationX / w)) * 20) / 20;
    if (v === last.current) return;
    last.current = v;
    onChange(v);
  };
  const t = Math.min(1, Math.max(0, value));
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{labels.low}</Text>
      <View
        accessibilityRole="adjustable"
        accessibilityLabel={labels.title}
        accessibilityValue={{ min: 0, max: 100, now: Math.round(t * 100) }}
        style={styles.hit}
        onLayout={(e) => {
          trackWRef.current = e.nativeEvent.layout.width;
          setTrackW(e.nativeEvent.layout.width);
        }}
        onStartShouldSetResponder={() => true}
        onMoveShouldSetResponder={() => true}
        onResponderGrant={move}
        onResponderMove={move}>
        <View style={styles.track} />
        <View pointerEvents="none" style={[styles.fill, { width: t * trackW }]} />
        <View pointerEvents="none" style={[styles.knob, { left: t * Math.max(0, trackW - KNOB) }]} />
      </View>
      <Text style={styles.label}>{labels.high}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16 },
  label: { fontSize: 11, fontWeight: '700', color: theme.colors.inkMuted },
  hit: { flex: 1, height: 28, justifyContent: 'center' },
  track: { height: 6, borderRadius: 3, backgroundColor: theme.colors.border },
  fill: { position: 'absolute', left: 0, height: 6, borderRadius: 3, backgroundColor: theme.colors.ink },
  knob: {
    position: 'absolute',
    top: 4,
    width: KNOB,
    height: KNOB,
    borderRadius: KNOB / 2,
    backgroundColor: theme.colors.white,
    borderWidth: 1,
    borderColor: 'rgba(0,0,0,0.12)',
    ...theme.shadow,
  },
});
