import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LookCard } from '@/components/celeb/LookCard';
import { VideoCard } from '@/components/celeb/VideoCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n } from '@/lib/i18n';
import { useLooks, useTutorials } from '@/lib/queries';

export default function LooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const looks = useLooks();
  const [query, setQuery] = useState('');
  const debounced = useDebouncedValue(query.trim(), 600);
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
        <Text style={styles.title} accessibilityRole="header">
          {t('looks.title')}
        </Text>
        <Text style={styles.subtitle}>{t('looks.subtitle')}</Text>

        <Text style={styles.sectionTitle}>{t('looks.curated')}</Text>
        {looks.isPending ? (
          <LoadingState />
        ) : looks.isError ? (
          <ErrorState error={looks.error} onRetry={() => looks.refetch()} />
        ) : (
          <View style={styles.looks}>
            {looks.data.length === 0 ? <Text style={styles.note}>{t('looks.empty')}</Text> : null}
            {looks.data.map((look) => (
              <LookCard
                key={look.id}
                look={look}
                subtitle={t('looks.itemCount', { count: look.items.length })}
                onPress={() => router.push(`/look/${look.id}`)}
              />
            ))}
          </View>
        )}

        <Text style={styles.sectionTitle}>{t('looks.tutorials')}</Text>
        <SearchBar value={query} onChangeText={setQuery} placeholder={t('looks.searchPlaceholder')} />
        <View style={styles.results}>
          {tutorials.isFetching ? (
            <ActivityIndicator color={theme.colors.rose} style={{ marginVertical: 16 }} />
          ) : tutorials.isError || tutorials.data?.configured === false ? (
            <Text style={styles.note}>{t('looks.tutorialsUnavailable')}</Text>
          ) : tutorials.data && tutorials.data.videos.length === 0 ? (
            <Text style={styles.note}>{t('looks.noTutorials')}</Text>
          ) : (
            tutorials.data?.videos.map((video) => <VideoCard key={video.videoId} video={video} />)
          )}
        </View>

        <Text style={styles.disclaimer}>{t('looks.disclaimer')}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink, letterSpacing: -0.5 },
  subtitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, marginTop: 4, lineHeight: 19 },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 26, marginBottom: 12 },
  looks: { gap: 14 },
  results: { marginTop: 8 },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 12 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 24, lineHeight: 16 },
});
