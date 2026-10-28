import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { Button } from '@/components/ui/Button';
import { ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { hasIdolLookArSettings, idolLookAsCelebLook } from '@/lib/idolLooks';
import { useIdolLook } from '@/lib/queries';
import { useMakeupStore } from '@/store/makeupStore';
import type { IdolLookProduct } from '@/types';

function statusKey(product: IdolLookProduct) {
  return product.status === 'verified_used' ? 'idol.verified' : product.status === 'similar' ? 'idol.similar' : 'idol.unverified';
}

export default function IdolLookDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const query = useIdolLook(id);
  const applyLook = useMakeupStore((s) => s.applyLook);
  const [showPlayer, setShowPlayer] = useState(false);
  const [playerFailed, setPlayerFailed] = useState(false);
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const { look, products } = query.data;
  const hasArSettings = hasIdolLookArSettings(look);
  const watch = () => {
    setPlayerFailed(false);
    setShowPlayer(true);
  };
  const openYoutube = () => WebBrowser.openBrowserAsync(look.video.youtubeUrl);
  const embedUrl = `https://www.youtube.com/embed/${encodeURIComponent(look.video.videoId)}?playsinline=1&start=${look.video.startSeconds}`;
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: look.displayName }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Image source={{ uri: look.video.thumbnailUrl }} style={styles.hero} contentFit="cover" />
        <View style={styles.body}>
          <Text accessibilityRole="header" style={styles.title}>{look.displayName}</Text>
          {look.video.channelName ? <Text style={styles.channel}>{look.video.channelName}</Text> : null}
          {look.video.analysisStatus === 'metadata_unavailable' ? <Text style={styles.notice}>{t('idol.videoUnavailable')}</Text> : null}
          <Button label={t('idol.video')} icon="logo-youtube" onPress={watch} />
          {showPlayer && !playerFailed ? <View style={styles.player}><WebView source={{ uri: embedUrl }} allowsInlineMediaPlayback mediaPlaybackRequiresUserAction={false} onError={() => setPlayerFailed(true)} /></View> : null}
          {playerFailed ? <Button label={t('idol.openYoutube')} variant="secondary" icon="open-outline" onPress={openYoutube} /> : null}
          <Text style={styles.heading}>{t('idol.style')}</Text>
          <Text style={styles.description}>{look.styleDescription}</Text>
          <Text style={styles.heading}>{t('idol.products')}</Text>
          {look.products.length === 0 ? <Text style={styles.description}>{t('idol.noProducts')}</Text> : look.products.map((entry) => {
            const product = products.find((item) => item.id === entry.productId);
            const shade = product?.shades.find((item) => item.id === entry.shadeId);
            return <Pressable key={entry.id} disabled={!product} onPress={() => product && router.push(`/product/${product.id}`)} style={styles.product}>
              <View style={styles.productCopy}><Text style={styles.productStatus}>{t(statusKey(entry))}</Text><Text style={styles.productName}>{product ? `${product.brand} ${product.name}` : t('idol.unverified')}</Text>{shade ? <Text style={styles.description}>{shade.name}</Text> : null}{entry.recommendationReason ? <Text style={styles.reason}>{entry.recommendationReason}</Text> : null}</View>
            </Pressable>;
          })}
        </View>
      </ScrollView>
      <View style={styles.footer}>
        <Button label={t('idol.tryAr')} icon="scan-outline" disabled={!hasArSettings} onPress={() => { applyLook(idolLookAsCelebLook(look), products); router.push({ pathname: '/ar', params: { compare: '1' } }); }} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface }, content: { paddingBottom: 24 }, hero: { width: '100%', aspectRatio: 16 / 9, backgroundColor: theme.colors.surfaceAlt }, body: { padding: theme.spacing.lg, gap: 8 },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink }, channel: { color: theme.colors.rose, fontSize: theme.font.small, fontWeight: '700' }, notice: { backgroundColor: theme.colors.warningBg, color: theme.colors.warning, padding: 10, borderRadius: theme.radius.sm, fontSize: 12, lineHeight: 17 }, player: { width: '100%', aspectRatio: 16 / 9, backgroundColor: theme.colors.black, overflow: 'hidden', borderRadius: theme.radius.md },
  heading: { marginTop: 16, fontSize: theme.font.title, color: theme.colors.ink, fontWeight: '800' }, description: { color: theme.colors.inkMuted, fontSize: theme.font.body, lineHeight: 21 }, product: { borderWidth: 1, borderColor: theme.colors.border, padding: 12, borderRadius: theme.radius.md }, productCopy: { gap: 3 }, productStatus: { color: theme.colors.rose, fontSize: 11, fontWeight: '800' }, productName: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700' }, reason: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 17 }, footer: { padding: theme.spacing.lg, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border },
});
