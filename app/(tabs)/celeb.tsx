import { useRouter, type Href } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CelebrityAvatar } from '@/components/celeb/CelebrityAvatar';
import { StyleLookCard } from '@/components/celeb/StyleLookCard';
import { VideoCard } from '@/components/celeb/VideoCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { InlineState } from '@/components/ui/InlineState';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { CELEBRITIES } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n } from '@/lib/i18n';
import { useStyleLooks, useTutorials } from '@/lib/queries';
import { celebrityHref } from '@/lib/routes';
import { styleLookGroupLabel } from '@/lib/styleLookGroups';

export default function LooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { width } = useWindowDimensions();
  const looks = useStyleLooks();
  const [query, setQuery] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);
  const debounced = useDebouncedValue(query.trim(), 600);
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);

  const allLooks = looks.data ?? [];
  const groups = [...new Set(allLooks.map((look) => look.group))];
  const cardWidth = Math.max(120, (width - theme.spacing.lg * 2 - 10) / 2);

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
            eyebrow={t('home.collectionCelebrity')}
            title={t('idol.title')}
            actionLabel={t('home.viewAll')}
            onAction={() => router.push('/celebrities' as Href)}
          />
          <Text style={styles.sectionSubtitle}>{t('looks.celebritySubtitle')}</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.bleed} contentContainerStyle={styles.avatarRail}>
            {CELEBRITIES.map((celebrity) => (
              <CelebrityAvatar
                key={celebrity.id}
                celebrity={celebrity}
                name={t(celebrity.nameKey)}
                onPress={() => router.push(celebrityHref(celebrity.id))}
              />
            ))}
          </ScrollView>
        </View>

        <View style={styles.section}>
          <SectionHeader eyebrow={t('home.curatedEyebrow')} title={t('looks.curated')} />
          {looks.isPending ? (
            <InlineState status="loading" />
          ) : looks.isError ? (
            <InlineState status="error" onRetry={() => looks.refetch()} />
          ) : allLooks.length === 0 ? (
            <InlineState status="empty" message={t('looks.empty')} />
          ) : (
            <>
              {groups.map((group) => {
                const entries = allLooks.filter((look) => look.group === group);
                const expanded = expandedGroups.includes(group);
                return (
                  <View key={group} style={styles.lookGroup}>
                    <View style={styles.groupHeader}>
                      <View><Text style={styles.groupTitle}>{styleLookGroupLabel(group, t)}</Text><Text style={styles.groupCount}>{t('styleLooks.lookCount', { count: entries.length })}</Text></View>
                      {entries.length > 2 ? <Pressable accessibilityRole="button" accessibilityState={{ expanded }} hitSlop={8} style={styles.groupButton} onPress={() => setExpandedGroups((current) => expanded ? current.filter((value) => value !== group) : [...current, group])}><Text style={styles.groupAction}>{expanded ? t('styleLooks.less') : t('styleLooks.more')}  ›</Text></Pressable> : null}
                    </View>
                    <View style={styles.lookGrid}>
                      {(expanded ? entries : entries.slice(0, 2)).map((look) => (
                        <StyleLookCard key={look.id} look={look} groupLabel={styleLookGroupLabel(group, t)} width={cardWidth}
                          productLabel={t('looks.itemCount', { count: look.products.length })}
                          onPress={() => router.push({ pathname: '/style-look/[id]', params: { id: look.id } } as Href)} />
                      ))}
                    </View>
                  </View>
                );
              })}
            </>
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
  sectionSubtitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, lineHeight: 19, marginTop: -6, marginBottom: 12 },
  bleed: { marginHorizontal: -theme.spacing.lg },
  avatarRail: { gap: 10, paddingHorizontal: theme.spacing.lg },
  lookGroup: { marginBottom: 26 },
  groupHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  groupTitle: { fontSize: 17, fontWeight: '800', color: theme.colors.ink },
  groupCount: { color: theme.colors.inkMuted, fontSize: 12, marginTop: 3 },
  groupButton: { minHeight: theme.hitTarget, justifyContent: 'center' },
  groupAction: { color: theme.colors.rose, fontSize: 12, fontWeight: '700' },
  lookGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  results: { marginTop: 8 },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 12 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 24, lineHeight: 16 },
});
