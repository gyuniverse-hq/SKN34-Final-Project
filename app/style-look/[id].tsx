import { Stack, useLocalSearchParams } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';
import { YoutubePlayer } from '@/components/celeb/YoutubePlayer';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useStyleLooks } from '@/lib/queries';
import { parseId } from '@/lib/routes';
import { styleLookGroupLabel, styleLookZoneLabel } from '@/lib/styleLookGroups';

export default function StyleLookDetail() {
  const { id: rawId } = useLocalSearchParams<{ id: string }>();
  const id = parseId(rawId);
  const { t } = useI18n();
  const query = useStyleLooks();
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const look = query.data.find((item) => item.id === id);
  if (!look) return <EmptyState icon="search-outline" title={t('common.notFound')} />;
  const zones = [...new Set(look.products.map((product) => product.zone))];

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: look.title }} />
      <ScrollView contentContainerStyle={styles.content}>
        <YoutubePlayer videoId={look.id} title={look.title} />
        <Text style={styles.heroGroup}>{styleLookGroupLabel(look.group, t)}</Text>
        <Text style={styles.title} accessibilityRole="header">{look.title}</Text>
        <Text style={styles.tag}>{look.tag}</Text>
        <Pressable accessibilityRole="link" style={({ pressed }) => [styles.video, pressed && styles.pressed]} onPress={() => { openYoutubeVideo(look.id).catch(() => Alert.alert(t('styleLooks.videoError'))); }}>
          <Text style={styles.videoText}>{t('celebVideo.openYoutube')}</Text>
          <Ionicons name="open-outline" size={15} color={theme.colors.rose} />
        </Pressable>
        <View style={styles.headingRow}><Text style={styles.heading} accessibilityRole="header">{t('styleLooks.products')}</Text><Text style={styles.total}>{t('looks.itemCount', { count: look.products.length })}</Text></View>
        <View style={styles.notice}><Ionicons name="information-circle-outline" size={18} color={theme.colors.rose} /><Text style={styles.noticeText}>{t('styleLooks.unverified')}</Text></View>
        {zones.map((zone) => {
          const products = look.products.filter((product) => product.zone === zone);
          return (
            <View key={zone} style={styles.zone}>
              <View style={styles.zoneHeader}><Text style={styles.zoneTitle}>{styleLookZoneLabel(zone, t)}</Text><Text style={styles.zoneCount}>{products.length}</Text></View>
              {products.map((product) => (
                <View key={product.number} style={styles.product}>
                  <View style={styles.productNumber}><Text style={styles.productNumberText}>{String(product.number).padStart(2, '0')}</Text></View>
                  <View style={styles.productCopy}>
                    <Text style={styles.brand}>{product.brand}</Text>
                    <Text style={styles.name}>{product.name}</Text>
                    <Text style={styles.option}>{product.option === '원문에 명시 정보 없음' ? t('styleLooks.optionUnknown') : product.option}</Text>
                  </View>
                </View>
              ))}
            </View>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 48 },
  heroGroup: { color: theme.colors.accent, fontSize: 12, fontWeight: '700', marginTop: 16 },
  title: { fontSize: 22, lineHeight: 30, fontWeight: '800', color: theme.colors.ink, marginTop: 4 },
  tag: { color: theme.colors.inkMuted, fontSize: 13, marginTop: 4 },
  video: { alignSelf: 'flex-start', marginTop: 8, minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 6 },
  videoText: { color: theme.colors.rose, fontSize: 12, fontWeight: '700' },
  pressed: { opacity: 0.8 },
  headingRow: { marginTop: 32, flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' },
  heading: { fontSize: 20, fontWeight: '800', color: theme.colors.ink },
  total: { fontSize: 12, color: theme.colors.inkMuted },
  notice: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md, padding: 12, marginTop: 12 },
  noticeText: { flex: 1, fontSize: 12, color: theme.colors.inkMuted, lineHeight: 18 },
  zone: { marginTop: 26 },
  zoneHeader: { flexDirection: 'row', alignItems: 'center', gap: 7, marginBottom: 6 },
  zoneTitle: { fontSize: 16, fontWeight: '800', color: theme.colors.ink },
  zoneCount: { color: theme.colors.accent, fontSize: 12, fontWeight: '700' },
  product: { flexDirection: 'row', gap: 12, paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.colors.border },
  productNumber: { width: 34, height: 34, borderRadius: 12, backgroundColor: theme.colors.cream, alignItems: 'center', justifyContent: 'center' },
  productNumberText: { fontSize: 11, fontWeight: '700', color: theme.colors.rose },
  productCopy: { flex: 1 },
  brand: { fontSize: 12, color: theme.colors.inkMuted, fontWeight: '600' },
  name: { marginTop: 3, fontSize: 15, lineHeight: 21, fontWeight: '700', color: theme.colors.ink },
  option: { marginTop: 4, fontSize: 12, color: theme.colors.inkMuted },
});
