import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { apiGet, apiPost } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';
import { communityFeedHref, LOOK_COMMUNITY, lookPhoto, type LookPost } from '@/lib/lookCommunity';
import { useProductsByIds } from '@/lib/queries';
import { loginHref, productHref } from '@/lib/routes';

type Viewer = { owned: boolean; recommended: boolean; reported: boolean };

export default function CommunityPost() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const { user } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState('');
  const [feedback, setFeedback] = useState<'community.recommended' | 'community.reported' | 'community.error'>();
  const path = `${LOOK_COMMUNITY}/${encodeURIComponent(id ?? '')}`;
  const key = ['look-community', 'post', id] as const;
  const post = useQuery({ queryKey: key, queryFn: () => apiGet<LookPost>(path), enabled: !!id });
  const products = useProductsByIds(post.data?.products.map(item => item.productId) ?? []);
  const viewerKey = ['look-community', 'viewer', id, user?.id] as const;
  const viewer = useQuery({
    queryKey: viewerKey,
    queryFn: () => apiGet<Viewer>(`${path}/viewer`, { expectedUserId: user?.id }),
    enabled: !!id && !!user,
  });
  const own = viewer.data?.owned;

  async function interact(kind: 'recommend' | 'report') {
    if (!user || pending.current) return;
    pending.current = true;
    setBusy(true);
    setFeedback(undefined);
    try {
      const updated = await apiPost<LookPost>(`${path}/${kind}`, kind === 'report' ? { reason: reason.trim() } : {}, { expectedUserId: user.id });
      cache.setQueryData(key, updated);
      cache.setQueryData<Viewer>(viewerKey, previous => previous && {
        ...previous, [kind === 'recommend' ? 'recommended' : 'reported']: true,
      });
      void cache.invalidateQueries({ queryKey: ['look-community'], refetchType: 'inactive' });
      setReporting(false);
      setFeedback(kind === 'recommend' ? 'community.recommended' : 'community.reported');
    } catch {
      setFeedback('community.error');
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t('community.heading') }} />
      <ScrollView contentContainerStyle={styles.content}>
        {post.data && !post.isError ? <>
          <Image source={{ uri: lookPhoto(post.data.id, post.dataUpdatedAt) }} style={styles.photo} contentFit="contain"
            cachePolicy="none" accessibilityLabel={t('community.photo')} />
          <Text accessibilityRole="header" style={styles.title}>{post.data.title}</Text>
          {post.data.description ? <Text style={styles.copy}>{post.data.description}</Text> : null}
          <Text style={styles.copy}>{t('community.count', { count: post.data.votes })}</Text>
          {!own ? <Button label={t(viewer.data?.recommended ? 'community.recommended' : 'community.recommend')} loading={busy && !reporting}
            disabled={busy || viewer.data?.recommended || (!!user && viewer.isPending)}
            onPress={() => user ? void interact('recommend') : router.push(loginHref('community-post'))} /> : null}
          {post.data.products.length > 0 ? <Text accessibilityRole="header" style={styles.label}>{t('community.products')}</Text> : null}
          {post.data.products.map((item, index) => {
            const product = products.data?.find(candidate => candidate.id === item.productId);
            const shade = product?.shades?.find(color => color.id === item.shadeId);
            if (!product) return null;
            return (
              <Pressable key={`${item.productId}:${item.shadeId}:${index}`} accessibilityRole="button"
                style={({ pressed }) => [styles.product, pressed && styles.pressed]}
                onPress={() => router.push(productHref(product.id, shade?.id))}>
                <ProductImage uri={product.imageUrl} category={product.category} style={styles.productPhoto} compact />
                <View style={styles.productInfo}>
                  <Text style={styles.brand}>{product.brand}</Text>
                  <Text style={styles.productName} numberOfLines={2}>{product.name}</Text>
                  {shade ? <View style={styles.shade}>
                    <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                    <Text style={styles.shadeName}>{shade.name}</Text>
                  </View> : null}
                </View>
                <Ionicons name="chevron-forward" color={theme.colors.inkMuted} size={18} />
              </Pressable>
            );
          })}
          {post.data.products.length > 0 && products.isPending ? <Text style={styles.copy}>{t('community.loading')}</Text> : null}
          {post.data.products.length > 0 && products.isError ? <Button label={t('common.retry')} variant="secondary" onPress={() => void products.refetch()} /> : null}
          {reporting ? <View style={styles.report}>
            <TextInput style={styles.input} placeholder={t('community.reportReason')} accessibilityLabel={t('community.reportReason')}
              value={reason} onChangeText={setReason} maxLength={300} multiline editable={!busy} />
            <Button label={t('community.report')} loading={busy} disabled={!reason.trim()} onPress={() => void interact('report')} />
            <Button label={t('common.cancel')} disabled={busy} variant="ghost" onPress={() => setReporting(false)} />
          </View> : !own ? <Button label={t(viewer.data?.reported ? 'community.reported' : 'community.report')} variant="ghost"
            disabled={busy || viewer.data?.reported || (!!user && viewer.isPending)}
            onPress={() => user ? setReporting(true) : router.push(loginHref('community-post'))} /> : null}
        </> : <>
          <Text style={styles.copy}>{t(post.isError || !id ? 'community.error' : 'community.loading')}</Text>
          {post.isError ? <Button label={t('common.retry')} variant="secondary" onPress={() => void post.refetch()} /> : null}
        </>}
        {feedback ? <Text accessibilityLiveRegion="polite" style={styles.copy}>{t(feedback)}</Text> : null}
        <Button label={t('community.backToFeed')} variant="ghost" onPress={() => router.dismissTo(communityFeedHref)} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { width: '100%', maxWidth: 600, alignSelf: 'center', padding: 20, gap: 14 },
  photo: { width: '100%', aspectRatio: 1.15, borderRadius: 16, backgroundColor: theme.colors.cream },
  title: { color: theme.colors.ink, fontSize: 26, fontWeight: '800' },
  label: { color: theme.colors.ink, fontSize: 17, fontWeight: '700', marginTop: 8 },
  copy: { color: theme.colors.inkMuted, lineHeight: 22 },
  product: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 10, borderRadius: 14,
    backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border },
  pressed: { opacity: 0.8 },
  productPhoto: { width: 56, height: 56, borderRadius: 8 },
  productInfo: { flex: 1, minWidth: 0, gap: 3 },
  brand: { color: theme.colors.roseDark, fontSize: 12 },
  productName: { color: theme.colors.ink, fontWeight: '700' },
  shade: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  swatch: { width: 10, height: 10, borderRadius: 5, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.colors.border },
  shadeName: { color: theme.colors.inkMuted, fontSize: 12, flexShrink: 1 },
  report: { gap: 8 },
  input: { minHeight: 70, padding: 12, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 12, color: theme.colors.ink },
});
