import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

/** Filter chip with an optional colour dot; omit `swatch` for the "all" chip. */
export const ColorChip = memo(function ColorChip({ label, swatch, selected, onPress }: {
  label: string; swatch?: string; selected: boolean; onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected }}
      hitSlop={4}
      style={({ pressed }) => [styles.chip, selected && styles.selected, pressed && styles.pressed]}>
      {swatch ? <View style={[styles.dot, { backgroundColor: swatch }]} /> : null}
      <Text style={[styles.text, selected && styles.textSelected]}>{label}</Text>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: 36,
    paddingHorizontal: 14,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  selected: { backgroundColor: theme.colors.ink, borderColor: theme.colors.ink },
  dot: { width: 14, height: 14, borderRadius: 7, borderWidth: 1.5, borderColor: theme.colors.white },
  text: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.inkMuted },
  textSelected: { color: theme.colors.white },
  pressed: { opacity: 0.8 },
});
