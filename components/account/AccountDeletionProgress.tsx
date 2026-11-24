import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

interface Props {
  complete: boolean;
  busy: boolean;
  signedIn: boolean;
  issue?: 'unconfirmed' | 'sessionEnded' | 'cleanupFailed' | 'signOutFailed';
  onCheck: () => void;
  onLeave: () => void;
}

export function AccountDeletionProgress({ complete, busy, signedIn, issue, onCheck, onLeave }: Props) {
  const { t } = useI18n();
  const showCheck = complete ? issue === 'cleanupFailed' : signedIn && issue !== 'sessionEnded';

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.panel}>
          <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.title}>
            {t(complete ? 'account.deleteDone' : 'account.deletePendingTitle')}
          </Text>
          {!complete && issue !== 'sessionEnded' && (
            <Text style={styles.body}>{t('account.deletePendingBody')}</Text>
          )}
          {issue && (
            <Text accessibilityLiveRegion="polite" style={styles.body}>
              {t(issue === 'unconfirmed' ? 'account.deleteStatusUnavailable'
                : issue === 'sessionEnded' ? 'account.deleteSessionEnded'
                  : issue === 'cleanupFailed' ? 'account.deleteCleanupFailed'
                    : 'account.deleteSignOutFailed')}
            </Text>
          )}
          {showCheck && (
            <Button multiline label={t(complete ? 'common.retry' : 'account.deleteCheck')}
              loading={busy} onPress={onCheck} />
          )}
          <Button multiline variant={showCheck ? 'secondary' : 'primary'}
            label={t(signedIn ? 'account.deleteLeave' : 'account.deleteClose')}
            disabled={busy || issue === 'cleanupFailed'} onPress={onLeave} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { flexGrow: 1, justifyContent: 'center', padding: homeLayout.gutter },
  panel: {
    width: '100%', maxWidth: 420, alignSelf: 'center', gap: theme.spacing.md,
    padding: theme.spacing.xl, borderRadius: theme.radius.lg, backgroundColor: theme.colors.card,
  },
  title: { ...homeType(22), fontWeight: '700', color: theme.colors.ink },
  body: { ...homeType(14), lineHeight: 22, color: theme.colors.inkMuted },
});
