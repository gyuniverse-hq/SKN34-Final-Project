import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';
import { YoutubePlayer } from '@/components/celeb/YoutubePlayer';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { CELEBRITIES } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useCelebrityVideos } from '@/lib/queries';
import { parseId } from '@/lib/routes';
import { celebrityProductSourceLabel, styleLookZoneLabel } from '@/lib/styleLookGroups';

export default function CelebrityVideoDetail() {
  const { id: rawId } = useLocalSearchParams<{ id: string }>();
  const id = parseId(rawId);
  const { t } = useI18n();
  const query = useCelebrityVideos();
  const [expandedTitleId, setExpandedTitleId] = useState<string | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<{ id: string; zones: string[] }>({ id: '', zones: [] });
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const video = query.data.find((item) => item.id === id);
  const celebrity = CELEBRITIES.find((item) => item.id === video?.celebrityId);
  if (!video || !celebrity) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  const title = video.title || t('celebVideo.title', { number: video.number });
  const zones = [...new Set(video.products.map((product) => product.zone))];
  const titleExpanded = expandedTitleId === video.id;
  const canExpandTitle = title.length > 50;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t(celebrity.nameKey) }} />
      <ScrollView contentContainerStyle={styles.content}>
        <YoutubePlayer videoId={video.id} startSeconds={video.startSeconds} title={title} />
        <Text style={styles.title} accessibilityRole="header" accessibilityLabel={title} numberOfLines={canExpandTitle && !titleExpanded ? 2 : undefined}>{title}</Text>
        {canExpandTitle ? <Pressable accessibilityRole="button" accessibilityState={{ expanded: titleExpanded }} onPress={() => setExpandedTitleId(titleExpanded ? null : video.id)} style={styles.titleToggle}><Text style={styles.titleToggleText}>{t(titleExpanded ? 'celebVideo.titleLess' : 'celebVideo.titleMore')}</Text></Pressable> : null}
        {video.channelName ? <Text style={styles.channel}>{video.channelName}</Text> : null}
        {video.linkStatus === 'needs_review' ? <Text style={styles.linkNote}>{t('celebVideo.linkUnverified')}</Text> : null}
        <Pressable accessibilityRole="link" style={({ pressed }) => [styles.video, pressed && styles.pressed]}
          onPress={() => { openYoutubeVideo(video.id, video.startSeconds).catch(() => Alert.alert(t('celebVideo.videoError'))); }}>
          <Text style={styles.videoText}>{t('celebVideo.openYoutube')}</Text>
          <Ionicons name="open-outline" size={15} color={theme.colors.rose} />
        </Pressable>
        <View style={styles.headingRow}><Text style={styles.heading} accessibilityRole="header">{t('styleLooks.products')}</Text><Text style={styles.total}>{t('looks.itemCount', { count: video.products.length })}</Text></View>
        <View style={styles.notice}><Ionicons name="information-circle-outline" size={16} color={theme.colors.rose} /><Text style={styles.noticeText}>{t('celebVideo.productsNotice')} {t('celebVideo.notice')}</Text></View>
        {zones.map((zone) => {
          const products = video.products.filter((item) => item.zone === zone);
          const expanded = expandedGroups.id === video.id && expandedGroups.zones.includes(zone);
          return <View key={zone} style={styles.zone}>
            <Pressable accessibilityRole="button" accessibilityState={{ expanded }} accessibilityLabel={`${styleLookZoneLabel(zone, t)}, ${t('looks.itemCount', { count: products.length })}`}
              onPress={() => setExpandedGroups((current) => {
                const currentZones = current.id === video.id ? current.zones : [];
                return { id: video.id, zones: expanded ? currentZones.filter((item) => item !== zone) : [...currentZones, zone] };
              })} style={styles.zoneHeader}>
              <Text style={styles.zoneTitle}>{styleLookZoneLabel(zone, t)}</Text><Text style={styles.zoneCount}>{products.length}</Text>
              <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={18} color={theme.colors.inkMuted} />
            </Pressable>
            {expanded ? products.map((product) => {
              const source = celebrityProductSourceLabel(product.sourceType, t);
              const option = product.option.trim();
              const showOption = option && option !== '원본에 별도 옵션 없음' && !product.name.toLowerCase().includes(option.toLowerCase());
              return <View key={product.number} style={styles.product}>
                <View style={styles.productCopy}>
                  <Text style={styles.brand}>{product.brand}</Text><Text style={styles.name}>{product.name}</Text>
                  {showOption ? <Text style={styles.option}>{option}</Text> : null}
                  {product.reviewStatus === '브랜드 확인 필요' ? <Text style={styles.review}>{t('celebVideo.brandReview')}</Text> : null}
                  {source ? <Text style={styles.option}>{source}</Text> : null}
                </View>
              </View>;
            }) : null}
          </View>;
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 48 },
  title: { fontSize: 18, lineHeight: 25, fontWeight: '800', color: theme.colors.ink, marginTop: 16 },
  titleToggle: { alignSelf: 'flex-start', minHeight: 36, justifyContent: 'center' },
  titleToggleText: { color: theme.colors.rose, fontSize: 12, fontWeight: '700' },
  channel: { color: theme.colors.inkMuted, fontSize: 13, marginTop: 4 },
  linkNote: { marginTop: 10, color: theme.colors.inkMuted, fontSize: 12 },
  video: { alignSelf: 'flex-start', marginTop: 8, minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6 },
  videoText: { color: theme.colors.rose, fontSize: 12, fontWeight: '700' },
  pressed: { opacity: 0.8 },
  headingRow: { marginTop: 28, flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  heading: { fontSize: 20, fontWeight: '800', color: theme.colors.ink }, total: { fontSize: 12, color: theme.colors.inkMuted },
  notice: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md, padding: 12, marginTop: 12 },
  noticeText: { flex: 1, fontSize: 12, color: theme.colors.inkMuted, lineHeight: 18 }, zone: { marginTop: 10, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.lg, backgroundColor: theme.colors.card, overflow: 'hidden' },
  zoneHeader: { flexDirection: 'row', alignItems: 'center', gap: 7, paddingHorizontal: 16, minHeight: 54 }, zoneTitle: { flex: 1, fontSize: 15, fontWeight: '800', color: theme.colors.ink },
  zoneCount: { color: theme.colors.accent, fontSize: 12, fontWeight: '700', marginRight: 4 },
  product: { paddingHorizontal: 16, paddingVertical: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border },
  productCopy: { flex: 1 },
  brand: { fontSize: 12, color: theme.colors.inkMuted, fontWeight: '600' }, name: { marginTop: 3, fontSize: 15, lineHeight: 21, fontWeight: '700', color: theme.colors.ink },
  option: { marginTop: 4, fontSize: 12, color: theme.colors.inkMuted }, review: { marginTop: 4, fontSize: 12, color: theme.colors.warning },
});
