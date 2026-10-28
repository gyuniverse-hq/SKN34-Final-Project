import Ionicons from '@expo/vector-icons/Ionicons';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { Button } from './Button';

/** Section-sized loading / empty / error state for lists inside a scrolling screen. */
export function InlineState({
  status,
  message,
  onRetry,
}: {
  status: 'loading' | 'empty' | 'error';
  message?: string;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  if (status === 'loading') {
    return (
      <View style={styles.box} accessibilityRole="progressbar" accessibilityLabel={t('common.loading')}>
        <ActivityIndicator color={theme.colors.rose} />
      </View>
    );
  }
  return (
    <View style={styles.box}>
      <Ionicons
        name={status === 'error' ? 'cloud-offline-outline' : 'file-tray-outline'}
        size={22}
        color={theme.colors.inkFaint}
      />
      <Text style={styles.text}>{message ?? (status === 'error' ? t('common.errorTitle') : t('common.empty'))}</Text>
      {status === 'error' && onRetry ? (
        <Button label={t('common.retry')} variant="secondary" compact onPress={onRetry} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 20,
    paddingHorizontal: 16,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
  },
  text: { fontSize: theme.font.small, color: theme.colors.inkMuted, textAlign: 'center', lineHeight: 19 },
});
