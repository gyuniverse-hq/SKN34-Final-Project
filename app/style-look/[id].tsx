import { Stack, useLocalSearchParams } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { openYoutubeVideo } from '@/components/celeb/VideoCard';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useStyleLooks } from '@/lib/queries';
import { parseId } from '@/lib/routes';

export default function StyleLookDetail() {
  const { id: rawId } = useLocalSearchParams<{ id: string }>();
  const id = parseId(rawId);
  const { t } = useI18n();
  const query = useStyleLooks();
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const look = query.data.find((item) => item.id === id);
  if (!look) return <EmptyState icon="search-outline" title={t('common.notFound')} />;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: look.title }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>{look.title}</Text>
        <Text style={styles.tag}>{look.tag}</Text>
        <Pressable accessibilityRole="link" style={styles.video} onPress={() => { openYoutubeVideo(look.id).catch(() => {}); }}>
          <Text style={styles.videoText}>{t('styleLooks.video')}</Text>
        </Pressable>
        <Text style={styles.heading}>{t('styleLooks.products')}</Text>
        <Text style={styles.note}>{t('styleLooks.unverified')}</Text>
        {look.products.map((product) => (
          <View key={product.number} style={styles.product}>
            <Text style={styles.brand}>{product.brand}</Text>
            <Text style={styles.name}>{product.name}</Text>
            <Text style={styles.note}>{product.option}</Text>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  title: { fontSize: 24, fontWeight: '800', color: theme.colors.ink },
  tag: { color: theme.colors.inkMuted, marginTop: 6 },
  video: { marginTop: 20, padding: 16, backgroundColor: theme.colors.accent, borderRadius: theme.radius.lg },
  videoText: { color: theme.colors.white, fontWeight: '700', textAlign: 'center' },
  heading: { marginTop: 26, fontSize: 18, fontWeight: '700', color: theme.colors.ink },
  note: { marginTop: 5, fontSize: 12, color: theme.colors.inkMuted },
  product: { paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.colors.inkFaint },
  brand: { fontSize: 12, color: theme.colors.inkMuted },
  name: { marginTop: 3, fontSize: 15, fontWeight: '600', color: theme.colors.ink },
});
