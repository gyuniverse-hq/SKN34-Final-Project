import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { theme } from '@/constants/theme';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

interface Props {
  label: string;
  onPress: () => void;
  variant?: Variant;
  icon?: ComponentProps<typeof Ionicons>['name'];
  disabled?: boolean;
  loading?: boolean;
  compact?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityHint?: string;
}

const FOREGROUND: Record<Variant, string> = {
  primary: theme.colors.white,
  secondary: theme.colors.ink,
  ghost: theme.colors.rose,
  danger: theme.colors.white,
};

export function Button({
  label,
  onPress,
  variant = 'primary',
  icon,
  disabled,
  loading,
  compact,
  style,
  accessibilityHint,
}: Props) {
  const color = FOREGROUND[variant];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={accessibilityHint}
      accessibilityState={{ disabled: !!(disabled || loading), busy: !!loading }}
      style={({ pressed }) => [
        styles.base,
        compact && styles.compact,
        styles[variant],
        (disabled || loading) && styles.disabled,
        pressed && styles.pressed,
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={color} />
      ) : (
        <View style={styles.row}>
          {icon ? <Ionicons name={icon} size={compact ? 16 : 18} color={color} /> : null}
          <Text style={[styles.label, compact && styles.labelCompact, { color }]} numberOfLines={1}>
            {label}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 50,
    paddingHorizontal: 18,
    borderRadius: theme.radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  compact: { minHeight: 38, paddingHorizontal: 14 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  primary: { backgroundColor: theme.colors.rose },
  secondary: { backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border },
  ghost: { backgroundColor: 'transparent' },
  danger: { backgroundColor: theme.colors.danger },
  disabled: { opacity: 0.45 },
  pressed: { opacity: 0.8 },
  label: { fontSize: theme.font.body, fontWeight: '600' },
  labelCompact: { fontSize: theme.font.small },
});
