import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter, type Href } from 'expo-router';
import type { ReactNode } from 'react';
import { ActivityIndicator, FlatList, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CelebrityCard } from './CelebrityCard';
import { StyleLookCard } from './StyleLookCard';
import { VideoCard } from './VideoCard';
import { InlineState } from '@/components/ui/InlineState';
import { homeHeading, homeLayout, homeType, tabTitle } from '@/constants/homeLayout';
import { CELEBRITIES } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { celebrityHref } from '@/lib/routes';
import { styleLookGroupLabel } from '@/lib/styleLookGroups';
import type { StyleLook, YoutubeSearchResult } from '@/types';

const CARD_GAP = homeLayout.productGap;
const NEXT_CARD_PEEK = 32;

function LookSeparator() {
  return <View style={styles.lookGap} />;
}

type LooksScreenProps = {
  inStack?: boolean;
  showTitle?: boolean;
  searchBar: ReactNode;
  looks: { data?: StyleLook[]; isPending: boolean; isError: boolean; refetch: () => unknown };
  tutorials: { data?: YoutubeSearchResult; isFetching: boolean; isError: boolean };
};

export default function LooksScreen({ inStack = false, showTitle = true, searchBar, looks, tutorials }: LooksScreenProps) {
  const router = useRouter();
  const { t } = useI18n();
  const { width } = useWindowDimensions();

  const allLooks = looks.data ?? [];
  const groups = [...new Set(allLooks.map((look) => look.group))];
  const pageWidth = Math.min(width, homeLayout.maxWidth);
  const portraitWidth = Math.min(150, Math.floor((pageWidth - 2 * homeLayout.gutter - 2 * CARD_GAP) / 3.2));
  const cardWidth = Math.max(120, Math.min(220, (pageWidth - homeLayout.gutter - 2 * CARD_GAP - NEXT_CARD_PEEK) / 2));

  return (
    <SafeAreaView style={styles.screen} edges={inStack ? [] : ['top']}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
        {showTitle ? <View style={styles.header}>
          <Text style={tabTitle} accessibilityRole="header">{t('looks.title')}</Text>
        </View> : null}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={homeHeading} accessibilityRole="header">{t('home.collectionCelebrity')}</Text>
            <Pressable accessibilityRole="button" onPress={() => router.push('/celebrities' as Href)} style={styles.all}>
              <Text style={styles.allText}>{t('home.viewAll')}</Text>
              <Ionicons name="chevron-forward" size={13} color={theme.colors.rose} />
            </Pressable>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.bleed} contentContainerStyle={styles.avatarRail}>
            {CELEBRITIES.map((celebrity) => (
              <CelebrityCard width={portraitWidth}
                key={celebrity.id}
                celebrity={celebrity}
                name={t(celebrity.nameKey)}
                onPress={() => router.push(celebrityHref(celebrity.id))}
              />
            ))}
          </ScrollView>
        </View>

        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>{t('looks.curated')}</Text>
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
                const groupLabel = styleLookGroupLabel(group, t);
                return (
                  <View key={group} style={styles.lookGroup}>
                    <View style={styles.groupHeader}>
                      <Text style={styles.groupTitle}>{groupLabel}</Text>
                      <Text style={styles.groupCount}>{t('styleLooks.lookCount', { count: entries.length })}</Text>
                    </View>
                    <FlatList horizontal data={entries} keyExtractor={look => look.id}
                      style={styles.bleed} contentContainerStyle={styles.lookRail}
                      showsHorizontalScrollIndicator={false} initialNumToRender={4} ItemSeparatorComponent={LookSeparator}
                      snapToInterval={cardWidth + CARD_GAP} decelerationRate="fast"
                      renderItem={({ item: look }) => (
                        <StyleLookCard look={look} groupLabel={groupLabel} width={cardWidth}
                          productLabel={t('looks.itemCount', { count: look.products.length })}
                          onPress={() => router.push({ pathname: '/style-look/[id]', params: { id: look.id } } as Href)} />
                      )} />
                  </View>
                );
              })}
            </>
          )}
        </View>

        <View style={styles.section}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>{t('looks.tutorials')}</Text>
          {searchBar}
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
  screen: { flex: 1, backgroundColor: homeLayout.background },
  content: { width: '100%', maxWidth: homeLayout.maxWidth, alignSelf: 'center', paddingHorizontal: homeLayout.gutter, paddingBottom: 90 },
  header: { minHeight: homeLayout.headerHeight, justifyContent: 'center' },
  section: { marginBottom: 22 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6 },
  all: { minHeight: theme.hitTarget, flexDirection: 'row', alignItems: 'center', gap: 2 },
  allText: { ...homeType(12), color: theme.colors.rose },
  sectionTitle: { ...homeHeading, marginBottom: 10 },
  bleed: { marginHorizontal: -homeLayout.gutter },
  avatarRail: { gap: CARD_GAP, paddingHorizontal: homeLayout.gutter },
  lookGroup: { marginBottom: 18 },
  groupHeader: { flexDirection: 'row', alignItems: 'baseline', gap: 8, marginBottom: 7 },
  groupTitle: { ...homeType(14), flexShrink: 1, fontWeight: '600', color: theme.colors.roseDark },
  groupCount: { ...homeType(11), color: theme.colors.inkMuted },
  lookRail: { paddingHorizontal: homeLayout.gutter },
  lookGap: { width: CARD_GAP },
  results: { marginTop: 8 },
  note: { ...homeType(13), color: theme.colors.inkMuted, paddingVertical: 12 },
  disclaimer: { ...homeType(11), color: theme.colors.inkMuted, lineHeight: 16 },
});
