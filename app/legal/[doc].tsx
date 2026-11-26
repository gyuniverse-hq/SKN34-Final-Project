import { Stack, useLocalSearchParams } from 'expo-router';
import { ScrollView, StyleSheet, Text } from 'react-native';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { PRIVACY_POLICY } from '@/constants/legal';
import { useI18n } from '@/lib/i18n';

export default function LegalScreen() {
  const { doc } = useLocalSearchParams<{ doc: string }>();
  const { t } = useI18n();
  const documents = {
    privacy: { title: t('my.privacy'), content: PRIVACY_POLICY },
    terms: { title: t('consent.termsHeading'), content: t('consent.termsText') },
    'service-data': { title: t('consent.dataHeading'), content: t('consent.dataText') },
  };
  const document = doc === 'privacy' || doc === 'terms' || doc === 'service-data' ? documents[doc] : null;
  if (!document) return <EmptyState icon="document-outline" title={t('common.notFound')} />;

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Stack.Screen options={{ title: document.title }} />
      <Text style={styles.text} selectable>
        {document.content}
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.xl, paddingBottom: 48 },
  text: { fontSize: theme.font.small, lineHeight: 21, color: theme.colors.ink },
});
