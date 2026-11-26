import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { homeHeading } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';

export function MenuSection({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <View style={styles.section}>
      {title && <Text accessibilityRole="header" style={styles.title}>{title}</Text>}
      <View style={styles.card}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginBottom: 22 },
  title: { ...homeHeading, marginBottom: 8 },
  card: { borderRadius: theme.radius.md, overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border, backgroundColor: theme.colors.border, gap: StyleSheet.hairlineWidth },
});
