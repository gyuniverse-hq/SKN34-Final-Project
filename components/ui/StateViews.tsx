import Ionicons from '@expo/vector-icons/Ionicons';
import type { ComponentProps, ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { ApiError } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { Button } from './Button';
import { Mascot } from './Mascot';

export function LoadingState() {
  return (
    <View style={styles.center} accessibilityRole="progressbar">
      <Mascot size={72} bounce decorative />
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  const isNotFound = error instanceof ApiError && error.status === 404;
  const isNetwork = error instanceof ApiError && error.status === 0;
  return (
    <View style={styles.center}>
      <Ionicons
        name={isNotFound ? 'search-outline' : 'cloud-offline-outline'}
        size={40}
        color={theme.colors.inkFaint}
      />
      <Text style={styles.title}>{isNotFound ? t('common.notFound') : t('common.errorTitle')}</Text>
      {isNetwork ? <Text style={styles.body}>{t('common.networkError')}</Text> : null}
      {onRetry && !isNotFound ? (
        <Button label={t('common.retry')} onPress={onRetry} variant="secondary" compact style={styles.action} />
      ) : null}
    </View>
  );
}

export function EmptyState({
  icon,
  illustration,
  title,
  body,
  action,
}: {
  icon?: ComponentProps<typeof Ionicons>['name'];
  /** Shown instead of the icon. */
  illustration?: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <View style={styles.center}>
      {illustration ?? (icon ? <Ionicons name={icon} size={44} color={theme.colors.inkFaint} /> : null)}
      <Text style={styles.title}>{title}</Text>
      {body ? <Text style={styles.body}>{body}</Text> : null}
      {action ? <View style={styles.action}>{action}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: theme.spacing.xxl,
    gap: theme.spacing.sm,
    minHeight: 240,
  },
  title: { fontSize: theme.font.title, fontWeight: '700', color: theme.colors.ink, textAlign: 'center' },
  body: { fontSize: theme.font.small, color: theme.colors.inkMuted, textAlign: 'center', lineHeight: 19 },
  action: { marginTop: theme.spacing.md },
});
