import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useLocalSearchParams } from 'expo-router';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StyleLookArtwork } from '@/components/celeb/StyleLookCard';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';
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
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const video = query.data.find((item) => item.id === id);
  const celebrity = CELEBRITIES.find((item) => item.id === video?.celebrityId);
  if (!video || !celebrity) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  const title = video.title || t('celebVideo.title', { number: video.number });
  const zones = [...new Set(video.products.map((product) => product.zone))];

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title }} />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.hero}>
          <StyleLookArtwork group="콘셉트·분위기" videoId={video.id} />
          <Text style={styles.heroGroup}>{[t(celebrity.nameKey), video.channelName].filter(Boolean).join(' · ')}</Text>
          <Text style={styles.title} accessibilityRole="header">{title}</Text>
        </View>
        {video.linkStatus === 'needs_review' ? <Text style={styles.linkNote}>{t('celebVideo.linkUnverified')}</Text> : null}
        <Pressable accessibilityRole="link" style={({ pressed }) => [styles.video, pressed && styles.pressed]}
          onPress={() => { openYoutubeVideo(video.id, video.startSeconds).catch(() => Alert.alert(t('celebVideo.videoError'))); }}>
          <View style={styles.play}><Ionicons name="play" size={18} color={theme.colors.white} /></View>
          <View style={styles.videoCopy}><Text style={styles.videoText}>{t('styleLooks.video')}</Text><Text style={styles.videoHint}>{t('styleLooks.videoHint')}</Text></View>
          <Ionicons name="open-outline" size={19} color={theme.colors.rose} />
        </Pressable>
        <View style={styles.headingRow}><Text style={styles.heading} accessibilityRole="header">{t('styleLooks.products')}</Text><Text style={styles.total}>{t('looks.itemCount', { count: video.products.length })}</Text></View>
        <View style={styles.notice}><Ionicons name="information-circle-outline" size={18} color={theme.colors.rose} /><Text style={styles.noticeText}>{t('celebVideo.productsNotice')} {t('celebVideo.notice')}</Text></View>
        {zones.map((zone) => {
          const products = video.products.filter((item) => item.zone === zone);
          return <View key={zone} style={styles.zone}>
            <View style={styles.zoneHeader}><Text style={styles.zoneTitle}>{styleLookZoneLabel(zone, t)}</Text><Text style={styles.zoneCount}>{products.length}</Text></View>
            {products.map((product) => {
              const source = celebrityProductSourceLabel(product.sourceType, t);
              return <View key={product.number} style={styles.product}>
                <View style={styles.number}><Text style={styles.numberText}>{String(product.number).padStart(2, '0')}</Text></View>
                <View style={styles.productCopy}>
                  <Text style={styles.brand}>{product.brand}</Text><Text style={styles.name}>{product.name}</Text>
                  <Text style={styles.option}>{product.option === '원본에 별도 옵션 없음' ? t('styleLooks.optionUnknown') : product.option}</Text>
                  {product.reviewStatus === '브랜드 확인 필요' ? <Text style={styles.review}>{t('celebVideo.brandReview')}</Text> : null}
                  {source ? <Text style={styles.option}>{source}</Text> : null}
                </View>
              </View>;
            })}
          </View>;
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 48 },
  hero: { minHeight: 230, padding: 22, borderRadius: 24, overflow: 'hidden', justifyContent: 'space-between', backgroundColor: theme.colors.rose },
  heroGroup: { color: 'rgba(255,255,255,0.9)', fontSize: 12, fontWeight: '700' },
  title: { fontSize: 27, lineHeight: 35, fontWeight: '800', color: theme.colors.white },
  linkNote: { marginTop: 10, color: theme.colors.inkMuted, fontSize: 12 },
  video: { marginTop: 10, padding: 15, backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg, flexDirection: 'row', alignItems: 'center', gap: 12 },
  play: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.colors.rose, alignItems: 'center', justifyContent: 'center' },
  videoCopy: { flex: 1 }, videoText: { color: theme.colors.ink, fontSize: 15, fontWeight: '800' },
  videoHint: { color: theme.colors.inkMuted, fontSize: 12, marginTop: 4 }, pressed: { opacity: 0.8 },
  headingRow: { marginTop: 32, flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  heading: { fontSize: 20, fontWeight: '800', color: theme.colors.ink }, total: { fontSize: 12, color: theme.colors.inkMuted },
  notice: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md, padding: 12, marginTop: 12 },
  noticeText: { flex: 1, fontSize: 12, color: theme.colors.inkMuted, lineHeight: 18 }, zone: { marginTop: 26 },
  zoneHeader: { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 6 }, zoneTitle: { fontSize: 16, fontWeight: '800', color: theme.colors.ink },
  zoneCount: { color: theme.colors.accent, fontSize: 12, fontWeight: '700' },
  product: { flexDirection: 'row', gap: 12, paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.colors.border },
  number: { width: 34, height: 34, borderRadius: 12, backgroundColor: theme.colors.cream, alignItems: 'center', justifyContent: 'center' },
  numberText: { fontSize: 11, fontWeight: '700', color: theme.colors.rose }, productCopy: { flex: 1 },
  brand: { fontSize: 12, color: theme.colors.inkMuted, fontWeight: '600' }, name: { marginTop: 3, fontSize: 15, lineHeight: 21, fontWeight: '700', color: theme.colors.ink },
  option: { marginTop: 4, fontSize: 12, color: theme.colors.inkMuted }, review: { marginTop: 4, fontSize: 12, color: theme.colors.warning },
});
