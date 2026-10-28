import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

export type BadgeTone = 'brand' | 'neutral' | 'success' | 'warning';

const TONES: Record<BadgeTone, { bg: string; fg: string }> = {
  brand: { bg: theme.colors.roseSoft, fg: theme.colors.roseDark },
  neutral: { bg: theme.colors.chip, fg: theme.colors.inkMuted },
  success: { bg: '#E7F3EE', fg: theme.colors.success },
  warning: { bg: theme.colors.warningBg, fg: theme.colors.warning },
};

export function Badge({
  label,
  tone = 'neutral',
  icon,
}: {
  label: string;
  tone?: BadgeTone;
  icon?: ComponentProps<typeof Ionicons>['name'];
}) {
  const colors = TONES[tone];
  return (
    <View style={[styles.badge, { backgroundColor: colors.bg }]}>
      {icon ? <Ionicons name={icon} size={12} color={colors.fg} /> : null}
      <Text style={[styles.text, { color: colors.fg }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: theme.radius.pill,
  },
  text: { fontSize: 11, fontWeight: '700', flexShrink: 1 },
});
