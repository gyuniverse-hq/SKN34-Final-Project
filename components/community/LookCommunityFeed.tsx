import Ionicons from '@expo/vector-icons/Ionicons';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { homeLayout } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { ApiError, apiDelete, apiGet } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { communityMineHref, communityPostHref, communityWriteHref, LOOK_COMMUNITY, lookPhoto, type LookPost } from '@/lib/lookCommunity';
import { loginHref } from '@/lib/routes';
import { LookPostAuthor, LookPostVotes } from './LookPostMeta';

export function LookCommunityFeed({ mine = false }: { mine?: boolean }) {
  const { t } = useI18n();
  const { user } = useAuth();
  const router = useRouter();
  const cache = useQueryClient();
  const [popular, setPopular] = useState(false);
  const feed = useInfiniteQuery({
    queryKey: ['look-community', mine ? user?.id : 'public', popular],
    queryFn: ({ pageParam }) => apiGet<LookPost[]>(`${LOOK_COMMUNITY}${mine ? '/mine' : ''}?popular=${popular}&offset=${pageParam}`, {
      expectedUserId: mine ? user?.id : undefined,
    }),
    initialPageParam: 0,
    getNextPageParam: (last, _pages, offset) => last.length === 20 ? offset + 20 : undefined,
    retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    enabled: !mine || !!user,
  });
  const rows = [...new Map(feed.data?.pages.flat().map(post => [post.id, post])).values()];

  function remove(post: LookPost) {
    if (!user) return;
    confirmAction(t('community.deleteConfirm'), t('community.delete'), t('common.cancel'), () => {
      void apiDelete(`${LOOK_COMMUNITY}/${post.id}`, { expectedUserId: user.id })
        .then(() => cache.invalidateQueries({ queryKey: ['look-community'] }))
        .catch(() => notify(t('community.error')));
    });
  }

  if (mine && !user) return <View style={styles.list}><Button label={t('my.login')} onPress={() => router.push(loginHref('community-mine'))} /></View>;

  const unavailable = feed.error instanceof ApiError && feed.error.status === 404;

  return (
    <FlatList
      data={rows}
      style={styles.feed}
      keyExtractor={post => post.id}
      contentContainerStyle={styles.list}
      onRefresh={() => void feed.refetch()}
      refreshing={feed.isRefetching}
      ListHeaderComponent={
        <View style={styles.toolbar}>
          {!mine ? (
            <View accessibilityRole="tablist" style={styles.filters}>
              {([false, true] as const).map(value => (
                <Pressable key={String(value)} accessibilityRole="tab" accessibilityState={{ selected: popular === value }}
                  onPress={() => setPopular(value)} style={styles.filter}>
                  <Text style={[styles.filterLabel, popular === value && styles.selected]}>{t(value ? 'community.popular' : 'community.latest')}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
          <View style={styles.toolbarActions}>
            {!mine ? <Pressable accessibilityRole="button" accessibilityLabel={t('community.mine')}
              onPress={() => router.push(communityMineHref)} style={styles.mineButton}>
              <Ionicons name="person-circle-outline" size={24} color={theme.colors.roseDark} />
            </Pressable> : null}
            <Pressable accessibilityRole="button" disabled={unavailable} accessibilityState={{ disabled: unavailable }}
              onPress={() => router.push(communityWriteHref())}
              style={({ pressed }) => [styles.write, pressed && styles.pressed, unavailable && styles.disabled]}>
              <Ionicons name="add" size={19} color={theme.colors.roseDark} />
              <Text style={styles.writeLabel}>{t('community.write')}</Text>
            </Pressable>
          </View>
        </View>
      }
      ListEmptyComponent={
        <InlineState status={feed.isPending ? 'loading' : feed.isError ? 'error' : 'empty'}
          message={t(feed.isError ? (unavailable ? 'community.unavailable' : 'community.feedError')
            : mine ? 'community.mineEmpty' : 'community.empty')}
          onRetry={unavailable ? undefined : () => void feed.refetch()} />
      }
      ListFooterComponent={feed.hasNextPage ? <Button label={t(feed.isFetchNextPageError ? 'common.retry' : 'community.more')}
        variant="secondary" loading={feed.isFetchingNextPage} onPress={() => void feed.fetchNextPage()} /> : undefined}
      renderItem={({ item }) => (
        <View style={styles.card}>
          <Pressable accessibilityRole="button" disabled={item.hidden}
            style={({ pressed }) => [styles.postRow, pressed && styles.pressed]}
            onPress={() => router.push(communityPostHref(item.id))}>
            {!item.hidden ? <Image source={{ uri: lookPhoto(item.id) }} contentFit="cover" style={styles.photo}
              cachePolicy="none" accessibilityLabel={t('community.photo')} /> : null}
            <View style={styles.body}>
              <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
              {item.description ? <Text style={styles.description} numberOfLines={2}>{item.description}</Text> : null}
              <View style={styles.meta}>
                <LookPostAuthor compact displayName={item.example ? 'VISHUE' : item.displayName} createdAt={item.createdAt} />
                {item.hidden ? <Text style={styles.muted}>{t('community.hidden')}</Text> : <LookPostVotes count={item.votes} />}
              </View>
            </View>
          </Pressable>
          {mine ? <View style={styles.actions}>
            {!item.hidden ? <Button label={t('community.edit')} compact variant="secondary" onPress={() => router.push(communityWriteHref({ id: item.id }))} /> : null}
            <Button label={t('community.delete')} compact variant="ghost" onPress={() => remove(item)} />
          </View> : null}
        </View>
      )}
    />
  );
}

const styles = StyleSheet.create({
  feed: { flex: 1 },
  list: { paddingHorizontal: homeLayout.gutter, paddingBottom: 92, gap: 10, width: '100%', maxWidth: 600, alignSelf: 'center' },
  toolbar: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 6 },
  toolbarActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, alignItems: 'center', marginLeft: 'auto' },
  filters: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  filter: { minHeight: 44, justifyContent: 'center', paddingVertical: 5, paddingHorizontal: 2 },
  filterLabel: { fontSize: 14, color: theme.colors.inkMuted, fontWeight: '600' },
  selected: { color: theme.colors.roseDark, fontWeight: '800' },
  mineButton: { minHeight: 44, minWidth: 44, alignItems: 'center', justifyContent: 'center' },
  write: { flexDirection: 'row', alignItems: 'center', gap: 4, minHeight: 44, paddingHorizontal: 10,
    paddingVertical: 7, backgroundColor: theme.colors.roseSoft, borderRadius: 10, flexShrink: 1 },
  writeLabel: { fontSize: 14, color: theme.colors.roseDark, fontWeight: '700', flexShrink: 1 },
  pressed: { opacity: 0.75 },
  disabled: { opacity: 0.55 },
  title: { fontSize: 17, lineHeight: 23, fontWeight: '800', color: theme.colors.ink },
  description: { fontSize: 13, lineHeight: 19, color: theme.colors.inkMuted, marginBottom: 2 },
  muted: { fontSize: 14, color: theme.colors.inkMuted, lineHeight: 19 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-end',
    columnGap: 8, rowGap: 4, marginTop: 3 },
  card: { backgroundColor: theme.colors.card, borderRadius: 16, overflow: 'hidden', borderWidth: 1, borderColor: theme.colors.border },
  postRow: { flexDirection: 'row', alignItems: 'center', padding: 11, gap: 12 },
  photo: { width: 86, height: 96, flexShrink: 0, borderRadius: 10, backgroundColor: theme.colors.cream },
  body: { flex: 1, minWidth: 0, gap: 5 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, padding: 12, paddingTop: 0 },
});
