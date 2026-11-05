import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

interface Props {
  icon: ComponentProps<typeof Ionicons>['name'];
  label: string;
  value?: string;
  onPress?: () => void;
  destructive?: boolean;
  selected?: boolean;
}

export function ListRow({ icon, label, value, onPress, destructive, selected }: Props) {
  const color = destructive ? theme.colors.danger : theme.colors.ink;
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : 'text'}
      accessibilityState={selected !== undefined ? { selected } : undefined}
      style={({ pressed }) => [styles.row, pressed && onPress && { backgroundColor: theme.colors.surfaceAlt }]}>
      <Ionicons name={icon} size={20} color={color} />
      <Text style={[styles.label, { color }]}>{label}</Text>
      <View style={styles.right}>
        {value ? <Text style={styles.value}>{value}</Text> : null}
        {selected ? <Ionicons name="checkmark" size={20} color={theme.colors.rose} /> : null}
        {onPress && selected === undefined ? (
          <Ionicons name="chevron-forward" size={18} color={theme.colors.inkFaint} />
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: 14,
    backgroundColor: theme.colors.card,
  },
  label: { flex: 1, fontSize: theme.font.body },
  right: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  value: { fontSize: theme.font.small, color: theme.colors.inkMuted },
});
