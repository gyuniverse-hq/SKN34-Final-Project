import { useRouter } from 'expo-router';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { IdolLookCard } from '@/components/celeb/IdolLookCard';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { displayableIdolLooks } from '@/lib/idolLooks';
import { idolLookMapping } from '@/lib/lookStatus';
import { useIdolLooks } from '@/lib/queries';
import { idolLookHref } from '@/lib/routes';

export default function IdolLooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const query = useIdolLooks();
  const looks = displayableIdolLooks(query.data);
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (looks.length === 0) return <EmptyState icon="sparkles-outline" title={t('home.collectionCelebrityEmpty')} />;
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text accessibilityRole="header" style={styles.title}>
          {t('idol.title')}
        </Text>
        <Text style={styles.subtitle}>{t('idol.subtitle')}</Text>
        <View style={styles.list}>
          {looks.map((look) => {
            const mapping = idolLookMapping(look);
            return (
              <IdolLookCard
                key={look.id}
                look={look}
                statusLabel={t(mapping.key, { count: mapping.count })}
                statusTone={mapping.tone}
                onPress={() => router.push(idolLookHref(look.id))}
              />
            );
          })}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32 },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink },
  subtitle: { marginTop: 6, color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 19 },
  list: { gap: 16, marginTop: 22 },
});
