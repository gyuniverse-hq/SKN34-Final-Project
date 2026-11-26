import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';

interface Props {
  icon: ComponentProps<typeof Ionicons>['name'];
  label: string;
  value?: string;
  onPress?: () => void;
  destructive?: boolean;
  selected?: boolean;
  prominent?: boolean;
}

export function ListRow({ icon, label, value, onPress, destructive, selected, prominent }: Props) {
  const color = destructive ? theme.colors.danger : theme.colors.ink;
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : 'text'}
      accessibilityState={selected !== undefined ? { selected } : undefined}
      style={({ pressed }) => [styles.row, prominent && styles.profile, pressed && onPress && { backgroundColor: theme.colors.surfaceAlt }]}>
      <Ionicons name={icon} size={prominent ? 28 : 19} color={destructive ? color : theme.colors.roseDark} />
      <Text style={[styles.label, { color }, prominent && styles.profileLabel]}>{label}</Text>
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
    minHeight: 48,
    paddingVertical: 10,
    backgroundColor: theme.colors.card,
  },
  profile: { minHeight: 64, backgroundColor: homeLayout.blush },
  profileLabel: { ...homeType(16), fontWeight: '600', color: theme.colors.roseDark },
  label: { flex: 1, ...homeType(14) },
  right: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  value: { ...homeType(13), color: theme.colors.inkMuted },
});
