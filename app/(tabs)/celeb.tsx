import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { IdolLookCard } from '@/components/celeb/IdolLookCard';
import { LookCard } from '@/components/celeb/LookCard';
import { VideoCard } from '@/components/celeb/VideoCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { InlineState } from '@/components/ui/InlineState';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n } from '@/lib/i18n';
import { displayableIdolLooks } from '@/lib/idolLooks';
import { idolLookMapping } from '@/lib/lookStatus';
import { useIdolLooks, useLooks, useTutorials } from '@/lib/queries';
import { idolLookHref, lookHref } from '@/lib/routes';

const IDOL_PREVIEW = 3;

export default function LooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const idolLooks = useIdolLooks();
  const looks = useLooks();
  const [query, setQuery] = useState('');
  const debounced = useDebouncedValue(query.trim(), 600);
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);
  const featuredIdolLooks = displayableIdolLooks(idolLooks.data);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
        <Text style={styles.eyebrow}>{t('looks.eyebrow')}</Text>
        <Text style={styles.title} accessibilityRole="header">
          {t('looks.title')}
        </Text>
        <Text style={styles.subtitle}>{t('looks.subtitle')}</Text>

        <View style={styles.section}>
          <SectionHeader
            eyebrow={t('home.idolEyebrow')}
            title={t('idol.title')}
            actionLabel={featuredIdolLooks.length > IDOL_PREVIEW ? t('home.viewAll') : undefined}
            onAction={() => router.push('/idol-looks')}
          />
          {idolLooks.isPending ? (
            <InlineState status="loading" />
          ) : idolLooks.isError ? (
            <InlineState status="error" onRetry={() => idolLooks.refetch()} />
          ) : featuredIdolLooks.length === 0 ? (
            <InlineState status="empty" message={t('home.collectionCelebrityEmpty')} />
          ) : (
            <View style={styles.list}>
              {featuredIdolLooks.slice(0, IDOL_PREVIEW).map((look) => {
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
          )}
        </View>

        <View style={styles.section}>
          <SectionHeader eyebrow={t('home.curatedEyebrow')} title={t('looks.curated')} />
          {looks.isPending ? (
            <InlineState status="loading" />
          ) : looks.isError ? (
            <InlineState status="error" onRetry={() => looks.refetch()} />
          ) : looks.data.length === 0 ? (
            <InlineState status="empty" message={t('looks.empty')} />
          ) : (
            <View style={styles.list}>
              {looks.data.map((look) => (
                <LookCard
                  key={look.id}
                  look={look}
                  subtitle={t('looks.itemCount', { count: look.items.length })}
                  onPress={() => router.push(lookHref(look.id))}
                />
              ))}
            </View>
          )}
        </View>

        <View style={styles.section}>
          <SectionHeader title={t('looks.tutorials')} />
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
        </View>

        <Text style={styles.disclaimer}>{t('looks.disclaimer')}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  eyebrow: { fontSize: 11, fontWeight: '800', letterSpacing: 1.2, color: theme.colors.accent },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink, letterSpacing: -0.5, marginTop: 2 },
  subtitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, marginTop: 4, lineHeight: 19 },
  section: { marginTop: 26 },
  list: { gap: 14 },
  results: { marginTop: 8 },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 12 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 24, lineHeight: 16 },
});
