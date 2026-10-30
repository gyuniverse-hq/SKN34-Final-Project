import { useRouter, type Href } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CelebrityAvatar } from '@/components/celeb/CelebrityAvatar';
import { ColorChip } from '@/components/celeb/ColorChip';
import { LookCard } from '@/components/celeb/LookCard';
import { VideoCard } from '@/components/celeb/VideoCard';
import { SearchBar } from '@/components/shop/SearchBar';
import { InlineState } from '@/components/ui/InlineState';
import { SectionHeader } from '@/components/ui/SectionHeader';
import { CELEBRITIES } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n } from '@/lib/i18n';
import { availableColorFamilies, COLOR_FAMILY_SWATCH, lookColorFamily, type ColorFamily } from '@/lib/lookColors';
import { useLooks, useTutorials } from '@/lib/queries';
import { celebrityHref, lookHref } from '@/lib/routes';

const GRID_GAP = 12;

export default function LooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { width } = useWindowDimensions();
  const looks = useLooks();
  const [query, setQuery] = useState('');
  const [colorFamily, setColorFamily] = useState<ColorFamily | null>(null);
  const debounced = useDebouncedValue(query.trim(), 600);
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);

  const allLooks = looks.data ?? [];
  const families = availableColorFamilies(allLooks);
  const activeFamily = colorFamily && families.includes(colorFamily) ? colorFamily : null;
  const visibleLooks = activeFamily ? allLooks.filter((look) => lookColorFamily(look) === activeFamily) : allLooks;
  const cardWidth = (width - theme.spacing.lg * 2 - GRID_GAP) / 2;

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
              {families.length > 0 ? (
                <>
                  <Text style={styles.sectionSubtitle}>{t('looks.colorSubtitle')}</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={[styles.bleed, styles.chipBar]} contentContainerStyle={styles.chipRail}>
                    <ColorChip label={t('looks.color.all')} selected={!activeFamily} onPress={() => setColorFamily(null)} />
                    {families.map((family) => (
                      <ColorChip
                        key={family}
                        label={t(`looks.color.${family}`)}
                        swatch={COLOR_FAMILY_SWATCH[family]}
                        selected={activeFamily === family}
                        onPress={() => setColorFamily(family)}
                      />
                    ))}
                  </ScrollView>
                </>
              ) : null}
              <View style={styles.grid}>
                {visibleLooks.map((look) => (
                  <LookCard
                    key={look.id}
                    look={look}
                    width={cardWidth}
                    subtitle={t('looks.itemCount', { count: look.items.length })}
                    onPress={() => router.push(lookHref(look.id))}
                  />
                ))}
              </View>
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
  chipBar: { marginBottom: 14 },
  chipRail: { gap: 8, paddingHorizontal: theme.spacing.lg },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: GRID_GAP },
  results: { marginTop: 8 },
  note: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingVertical: 12 },
  disclaimer: { fontSize: 11, color: theme.colors.inkFaint, marginTop: 24, lineHeight: 16 },
});
