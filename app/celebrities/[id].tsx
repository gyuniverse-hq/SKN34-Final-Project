import { Image } from 'expo-image';
import { useLocalSearchParams, useRouter, type Href } from 'expo-router';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { PhotoCredit } from '@/components/celeb/PhotoCredit';
import { CelebrityVideoCard } from '@/components/celeb/CelebrityVideoCard';
import { InlineState } from '@/components/ui/InlineState';
import { CELEBRITIES } from '@/constants/celebrities';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useCelebrityVideos } from '@/lib/queries';
import { parseId } from '@/lib/routes';

export default function CelebrityScreen() {
  const { id } = useLocalSearchParams<{ id?: string | string[] }>();
  const { t } = useI18n();
  const router = useRouter();
  const query = useCelebrityVideos();
  const celebrity = CELEBRITIES.find((item) => item.id === parseId(id));
  if (!celebrity) {
    return <View style={styles.missing}><InlineState status="empty" message={t('celebrity.notFound')} /></View>;
  }
  const videos = query.data?.filter((video) => video.celebrityId === celebrity.id) ?? [];
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.heading}>
          <Image source={celebrity.image} style={styles.portrait} contentFit="cover" />
          <View style={styles.headingText}>
            {celebrity.group ? <Text style={styles.group}>{celebrity.group}</Text> : null}
            <Text style={styles.title} accessibilityRole="header">{t(celebrity.nameKey)}</Text>
          </View>
        </View>
        <PhotoCredit celebrity={celebrity} label={t('celebrity.photoCredit')} />
        <Text style={styles.sectionTitle} accessibilityRole="header">{t('celebrity.videosTitle')}</Text>
        <Text style={styles.notice}>{t('celebVideo.notice')}</Text>
        {query.isPending ? <InlineState status="loading" /> : query.isError ? <InlineState status="error" onRetry={() => query.refetch()} /> : videos.length === 0 ? (
          <InlineState status="empty" message={t('celebrity.videosEmpty')} />
        ) : videos.map((video) => <CelebrityVideoCard key={video.id} videoId={video.id} title={video.title || t('celebVideo.title', { number: video.number })}
          subtitle={[video.channelName, t('looks.itemCount', { count: video.products.length })].filter(Boolean).join(' · ')}
          onPress={() => router.push({ pathname: '/celebrity-video/[id]', params: { id: video.id } } as Href)} />)}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 32, gap: 8 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  portrait: { width: 96, height: 110, borderRadius: theme.radius.md, backgroundColor: theme.colors.surfaceAlt },
  headingText: { flex: 1, gap: 4 },
  group: { color: theme.colors.accent, fontWeight: '700', fontSize: theme.font.small },
  title: { color: theme.colors.ink, fontWeight: '800', fontSize: theme.font.h1 },
  sectionTitle: { color: theme.colors.ink, fontSize: 19, fontWeight: '800', marginTop: 24, marginBottom: 6 },
  notice: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 18, marginBottom: 6 },
  missing: { flex: 1, justifyContent: 'center', padding: theme.spacing.lg, backgroundColor: theme.colors.surface },
});
