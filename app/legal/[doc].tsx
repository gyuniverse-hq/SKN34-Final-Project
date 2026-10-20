import { Stack, useLocalSearchParams } from 'expo-router';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { PRIVACY_POLICY, TERMS_OF_USE } from '@/constants/legal';
import { useI18n } from '@/lib/i18n';

export default function LegalScreen() {
  const { doc } = useLocalSearchParams<{ doc: string }>();
  const { t } = useI18n();
  const content = doc === 'privacy' ? PRIVACY_POLICY : doc === 'terms' ? TERMS_OF_USE : null;
  if (!content) return <EmptyState icon="document-outline" title={t('common.notFound')} />;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: doc === 'privacy' ? t('my.privacy') : t('my.terms') }} />
      <Text style={styles.text} selectable>
        {content}
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.xl, paddingBottom: 48 },
  text: { fontSize: theme.font.small, lineHeight: 21, color: theme.colors.ink },
});
