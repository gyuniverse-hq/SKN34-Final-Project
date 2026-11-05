import { Pressable, StyleSheet, Text } from 'react-native';
import { theme } from '@/constants/theme';

interface Props {
  label: string;
  selected?: boolean;
  onPress: () => void;
}

export function Chip({ label, selected, onPress }: Props) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      hitSlop={4}
      style={({ pressed }) => [styles.chip, selected && styles.selected, pressed && { opacity: 0.8 }]}>
      <Text style={[styles.text, selected && styles.textSelected]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.colors.card,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  selected: { backgroundColor: theme.colors.ink, borderColor: theme.colors.ink },
  text: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.inkMuted },
  textSelected: { color: theme.colors.white },
});
