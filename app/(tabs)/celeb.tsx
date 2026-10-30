import { useRouter, type Href } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CelebrityAvatar } from '@/components/celeb/CelebrityAvatar';
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

const GROUP_LABELS = {
  '컬러·톤 스타일': 'styleLooks.color',
  '콘셉트·분위기': 'styleLooks.mood',
  '시즌·데일리': 'styleLooks.season',
  '보정·맞춤': 'styleLooks.custom',
  '데일리·활용': 'styleLooks.daily',
  '베이스·피부 표현': 'styleLooks.base',
  '아이 메이크업': 'styleLooks.eye',
} as const;

export default function LooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const looks = useStyleLooks();
  const [query, setQuery] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);
  const debounced = useDebouncedValue(query.trim(), 600);
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);

  const allLooks = looks.data ?? [];
  const groups = [...new Set(allLooks.map((look) => look.group))];

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
                      <Text style={styles.groupTitle}>{group in GROUP_LABELS ? t(GROUP_LABELS[group as keyof typeof GROUP_LABELS]) : group}</Text>
                      {entries.length > 3 ? <Pressable accessibilityRole="button" onPress={() => setExpandedGroups((current) => expanded ? current.filter((value) => value !== group) : [...current, group])}><Text style={styles.groupAction}>{expanded ? t('styleLooks.less') : t('styleLooks.more')}</Text></Pressable> : null}
                    </View>
                    {(expanded ? entries : entries.slice(0, 3)).map((look) => (
                      <Pressable key={look.id} accessibilityRole="button" style={styles.lookRow} onPress={() => router.push({ pathname: '/style-look/[id]', params: { id: look.id } } as Href)}>
                        <Text style={styles.lookName}>{look.title}</Text>
                        <Text style={styles.lookMeta}>{t('looks.itemCount', { count: look.products.length })} ›</Text>
                      </Pressable>
                    ))}
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
  lookGroup: { marginBottom: 18 },
  groupHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  groupTitle: { fontSize: 16, fontWeight: '700', color: theme.colors.ink },
  groupAction: { color: theme.colors.accent, fontWeight: '600' },
  lookRow: { padding: 14, marginBottom: 6, borderRadius: theme.radius.lg, backgroundColor: theme.colors.surfaceAlt },
  lookName: { fontSize: 15, fontWeight: '700', color: theme.colors.ink },
  lookMeta: { fontSize: 12, color: theme.colors.inkMuted, marginTop: 4 },
  results: { marginTop: 8 },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 12 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 24, lineHeight: 16 },
});
