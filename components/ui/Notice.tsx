import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps, ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

type Tone = 'info' | 'warning' | 'neutral';

const TONES: Record<Tone, { bg: string; fg: string; icon: ComponentProps<typeof Ionicons>['name'] }> = {
  info: { bg: theme.colors.roseSoft, fg: theme.colors.roseDark, icon: 'information-circle-outline' },
  warning: { bg: theme.colors.warningBg, fg: theme.colors.warning, icon: 'alert-circle-outline' },
  neutral: { bg: theme.colors.chip, fg: theme.colors.inkMuted, icon: 'shield-checkmark-outline' },
};

/** Short inline disclosure: AR limits, price freshness, recommendation limits. */
export function Notice({
  tone = 'info',
  icon,
  title,
  body,
  children,
}: {
  tone?: Tone;
  icon?: ComponentProps<typeof Ionicons>['name'];
  title?: string;
  body: string;
  children?: ReactNode;
}) {
  const colors = TONES[tone];
  return (
    <View style={[styles.box, { backgroundColor: colors.bg }]} accessibilityRole={tone === 'warning' ? 'alert' : undefined}>
      <Ionicons name={icon ?? colors.icon} size={18} color={colors.fg} style={styles.icon} />
      <View style={styles.copy}>
        {title ? <Text style={[styles.title, { color: colors.fg }]}>{title}</Text> : null}
        <Text style={[styles.body, { color: colors.fg }]}>{body}</Text>
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { flexDirection: 'row', gap: 10, padding: 12, borderRadius: theme.radius.md },
  icon: { marginTop: 1 },
  copy: { flex: 1, gap: 4 },
  title: { fontSize: theme.font.small, fontWeight: '800' },
  body: { fontSize: 12, lineHeight: 18 },
});
