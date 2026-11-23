import { useState } from 'react';
import { StyleSheet, Text, View, type GestureResponderEvent } from 'react-native';
import { useI18n } from '@/lib/i18n';
import { theme } from '@/constants/theme';

export function IntensityRail({ value, minimum = 0, onChange }: { value?: number; minimum?: number; onChange: (level: number) => void }) {
  const { t } = useI18n();
  const [height, setHeight] = useState(0);
  const update = (level: number) => onChange(Math.max(minimum, Math.min(1, Math.round(level * 20) / 20)));
  const fraction = Math.max(0, ((value ?? minimum) - minimum) / (1 - minimum));
  const travel = Math.max(0, height - 16);
  const move = (e: GestureResponderEvent) => {
    if (travel > 0) update(1 - ((e.nativeEvent.locationY - 8) / travel) * (1 - minimum));
  };
  return <View style={[styles.rail, value === undefined && { opacity: 0.45 }]}>
    <Text style={styles.label}>{t('ar.arc.strong')}</Text>
    <View accessible accessibilityRole="adjustable" accessibilityLabel={t('ar.intensity')}
      accessibilityState={{ disabled: value === undefined }} accessibilityValue={{ min: minimum * 100, max: 100, now: Math.round((value ?? minimum) * 100) }}
      accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
      onAccessibilityAction={({ nativeEvent }) => { if (value !== undefined) update(value + (nativeEvent.actionName === 'increment' ? 0.05 : -0.05)); }}
      onLayout={e => setHeight(Math.max(1, e.nativeEvent.layout.height))}
      onStartShouldSetResponder={() => value !== undefined} onResponderGrant={move} onResponderMove={move} style={styles.hit}>
      <View pointerEvents="none" style={styles.track} />
      <View pointerEvents="none" style={[styles.thumb, { top: (1 - fraction) * travel }]} />
    </View>
    <Text style={styles.label}>{t('ar.arc.light')}</Text>
  </View>;
}
const styles = StyleSheet.create({
  rail: { height: '92%', maxHeight: 324, width: '100%', alignItems: 'center', gap: 4 },
  hit: { width: 44, flex: 1, alignItems: 'center' },
  track: { height: '100%', width: 4, backgroundColor: 'rgba(255,255,255,.75)', borderRadius: 2 },
  thumb: { position: 'absolute', width: 16, height: 16, borderRadius: 8, backgroundColor: theme.colors.rose, borderColor: 'white', borderWidth: 2 },
  label: { color: 'white', fontSize: 11, fontWeight: '600', backgroundColor: theme.colors.overlay, paddingHorizontal: 5, borderRadius: 4 },
});
