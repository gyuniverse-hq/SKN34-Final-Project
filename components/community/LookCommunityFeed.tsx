import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { apiDelete, apiGet } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { confirmAction, notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { communityPostHref, communityWriteHref, LOOK_COMMUNITY, lookPhoto, type LookPost } from '@/lib/lookCommunity';
import { loginHref } from '@/lib/routes';

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

  if (mine && !user) return <View style={styles.intro}><Button label={t('my.login')} onPress={() => router.push(loginHref('community-mine'))} /></View>;

  return (
    <FlatList
      data={rows}
      keyExtractor={post => post.id}
      contentContainerStyle={styles.list}
      onRefresh={() => void feed.refetch()}
      refreshing={feed.isRefetching}
      ListHeaderComponent={
        <View style={styles.intro}>
          <Text accessibilityRole="header" style={styles.heading}>{t(mine ? 'community.mine' : 'community.heading')}</Text>
          {!mine ? <Text style={styles.muted}>{t('community.intro')}</Text> : null}
          <Button label={t('community.write')} onPress={() => router.push(communityWriteHref())} />
          {!mine ? (
            <View style={styles.filters}>
              {([false, true] as const).map(value => (
                <Pressable key={String(value)} accessibilityRole="tab" accessibilityState={{ selected: popular === value }}
                  onPress={() => setPopular(value)} style={[styles.chip, popular === value && styles.active]}>
                  <Text style={styles.label}>{t(value ? 'community.popular' : 'community.latest')}</Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </View>
      }
      ListEmptyComponent={
        <View style={styles.empty}>
          <Text style={styles.muted}>{t(feed.isPending ? 'community.loading' : feed.isError ? 'community.error' : 'community.empty')}</Text>
          {feed.isError ? <Button label={t('common.retry')} variant="secondary" onPress={() => void feed.refetch()} /> : null}
        </View>
      }
      ListFooterComponent={feed.hasNextPage ? <Button label={t(feed.isFetchNextPageError ? 'common.retry' : 'community.more')}
        variant="secondary" loading={feed.isFetchingNextPage} onPress={() => void feed.fetchNextPage()} /> : undefined}
      renderItem={({ item }) => (
        <View style={styles.card}>
          <Pressable accessibilityRole="button" disabled={item.hidden} onPress={() => router.push(communityPostHref(item.id))}>
            {!item.hidden ? <Image source={{ uri: lookPhoto(item.id) }} contentFit="cover" style={styles.photo}
              cachePolicy="none" accessibilityLabel={t('community.photo')} /> : null}
            <View style={styles.body}>
              <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
              {item.description ? <Text style={styles.muted} numberOfLines={2}>{item.description}</Text> : null}
              <Text style={styles.label}>{item.hidden ? t('community.hidden') : t('community.count', { count: item.votes })}</Text>
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
  list: { padding: 18, gap: 16, width: '100%', maxWidth: 600, alignSelf: 'center' },
  intro: { gap: 12, marginBottom: 8 },
  heading: { fontSize: 26, fontWeight: '800', color: theme.colors.ink },
  title: { fontSize: 18, fontWeight: '700', color: theme.colors.ink },
  muted: { color: theme.colors.inkMuted, lineHeight: 21 },
  filters: { flexDirection: 'row', gap: 8 },
  chip: { paddingHorizontal: 16, minHeight: 44, justifyContent: 'center', borderRadius: 24 },
  active: { backgroundColor: theme.colors.roseSoft },
  label: { color: theme.colors.roseDark, fontWeight: '700' },
  card: { backgroundColor: theme.colors.card, borderRadius: 16, overflow: 'hidden', borderWidth: 1, borderColor: theme.colors.border },
  photo: { width: '100%', aspectRatio: 1.25, backgroundColor: theme.colors.cream },
  body: { padding: 15, gap: 6 },
  empty: { paddingVertical: 32, alignItems: 'center', gap: 12 },
  actions: { flexDirection: 'row', gap: 8, padding: 12, paddingTop: 0 },
});
