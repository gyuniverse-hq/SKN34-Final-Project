import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

export function SectionHeader({
  eyebrow,
  title,
  actionLabel,
  onAction,
}: {
  eyebrow?: string;
  title: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <View style={styles.row}>
      <View style={styles.copy}>
        {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
      </View>
      {actionLabel && onAction ? (
        <Pressable onPress={onAction} accessibilityRole="button" hitSlop={10} style={styles.action}>
          <Text style={styles.actionText}>{actionLabel} ›</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: 12, marginBottom: 12 },
  copy: { flex: 1, gap: 2 },
  eyebrow: { fontSize: 11, fontWeight: '800', letterSpacing: 1.2, color: theme.colors.accent, textTransform: 'uppercase' },
  title: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  action: { minHeight: 32, justifyContent: 'center' },
  actionText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.rose },
});
