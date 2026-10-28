import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useIdolLooks } from '@/lib/queries';
import type { IdolLook } from '@/types';

function mappingLabel(look: IdolLook, t: ReturnType<typeof useI18n>['t']) {
  if (look.video.productMappingStatus === 'mapped') return t('idol.mapping.mapped', { count: look.products.length });
  return look.video.productMappingStatus === 'no_verified_products' ? t('idol.mapping.empty') : t('idol.mapping.registered');
}

export default function IdolLooksScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const query = useIdolLooks();
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text accessibilityRole="header" style={styles.title}>{t('idol.title')}</Text>
        <Text style={styles.subtitle}>{t('idol.subtitle')}</Text>
        <View style={styles.list}>
          {query.data.map((look) => (
            <Pressable key={look.id} onPress={() => router.push(`/idol-look/${look.id}` as never)} style={({ pressed }) => [styles.card, pressed && styles.pressed]} accessibilityRole="button">
              <Image source={{ uri: look.video.thumbnailUrl }} style={styles.thumbnail} contentFit="cover" />
              <View style={styles.body}>
                <Text numberOfLines={2} style={styles.name}>{look.displayName}</Text>
                {look.video.channelName ? <Text numberOfLines={1} style={styles.channel}>{look.video.channelName}</Text> : null}
                <Text numberOfLines={2} style={styles.style}>{look.styleDescription}</Text>
                <View style={styles.badge}><Text style={styles.badgeText}>{mappingLabel(look, t)}</Text></View>
                <Text style={styles.link}>{t('idol.details')} ›</Text>
              </View>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface }, content: { padding: theme.spacing.lg, paddingBottom: 32 },
  title: { fontSize: theme.font.h1, fontWeight: '800', color: theme.colors.ink }, subtitle: { marginTop: 6, color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 19 },
  list: { gap: 16, marginTop: 22 }, card: { overflow: 'hidden', borderRadius: theme.radius.lg, backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border }, pressed: { opacity: 0.86 },
  thumbnail: { width: '100%', aspectRatio: 16 / 9, backgroundColor: theme.colors.surfaceAlt }, body: { padding: 14, gap: 5 }, name: { fontSize: theme.font.title, color: theme.colors.ink, fontWeight: '800' },
  channel: { fontSize: 12, color: theme.colors.rose, fontWeight: '700' }, style: { color: theme.colors.inkMuted, fontSize: theme.font.small }, badge: { alignSelf: 'flex-start', paddingHorizontal: 8, paddingVertical: 4, borderRadius: theme.radius.pill, backgroundColor: theme.colors.roseSoft, marginTop: 2 }, badgeText: { fontSize: 11, color: theme.colors.roseDark, fontWeight: '700' }, link: { color: theme.colors.rose, fontSize: theme.font.small, fontWeight: '800', marginTop: 3 },
});
