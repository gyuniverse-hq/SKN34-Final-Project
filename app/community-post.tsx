import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { LookPostAuthor, LookPostVotes } from '@/components/community/LookPostMeta';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { ApiError, apiGet, apiPost } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';
import { communityFeedHref, communityWriteHref, LOOK_COMMUNITY, lookPhoto, type LookPost } from '@/lib/lookCommunity';
import { useProductsByIds } from '@/lib/queries';
import { loginHref, productHref } from '@/lib/routes';

type Viewer = { owned: boolean; recommended: boolean; reported: boolean };

export default function CommunityPost() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const { user } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const cache = useQueryClient();
  const { bottom } = useSafeAreaInsets();
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState('');
  const [feedback, setFeedback] = useState<'community.reported' | 'community.error'>();
  const path = `${LOOK_COMMUNITY}/${encodeURIComponent(id ?? '')}`;
  const key = ['look-community', 'post', id] as const;
  const post = useQuery({
    queryKey: key, queryFn: () => apiGet<LookPost>(path), enabled: !!id,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
  const detail = post.isError ? undefined : post.data;
  const products = useProductsByIds(detail?.products.map(item => item.productId) ?? []);
  const viewerKey = ['look-community', 'viewer', id, user?.id] as const;
  const viewer = useQuery({
    queryKey: viewerKey,
    queryFn: () => apiGet<Viewer>(`${path}/viewer`, { expectedUserId: user?.id }),
    enabled: !!id && !!user,
  });
  const { owned, recommended, reported } = viewer.data ?? {};
  const actionDisabled = busy || (!!user && viewer.isPending);
  const missing = !id || (post.error instanceof ApiError && post.error.status === 404);

  function openReport() {
    if (!user) {
      router.push(loginHref('community-post'));
      return;
    }
    setFeedback(undefined);
    setReason('');
    setReporting(true);
  }

  function closeReport() {
    if (pending.current) return;
    setReporting(false);
    setFeedback(undefined);
  }

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
      if (kind === 'report') {
        setReporting(false);
        setFeedback('community.reported');
      }
    } catch {
      setFeedback('community.error');
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{
        headerBackVisible: false,
        headerTitle: '',
        headerLeft: () => (
          <Button label={t('community.backToFeed')} icon="chevron-back" variant="ghost" compact
            style={styles.back} onPress={() => router.dismissTo(communityFeedHref)} />
        ),
        headerRight: detail && !owned ? () => (
          <Pressable accessibilityRole="button" accessibilityLabel={t(reported ? 'community.reported' : 'community.report')}
            accessibilityState={{ disabled: !!(actionDisabled || reported) }} disabled={actionDisabled || reported}
            onPress={openReport} style={({ pressed }) => [styles.reportAction, actionDisabled && styles.dimmed, pressed && styles.pressed]}>
            <Ionicons name={reported ? 'flag' : 'flag-outline'} color={theme.colors.inkMuted} size={17} />
            <Text style={styles.reportLabel} numberOfLines={1}>{t('community.report')}</Text>
          </Pressable>
        ) : undefined,
      }} />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
        {detail ? <>
          <Image source={{ uri: lookPhoto(detail.id, post.dataUpdatedAt) }} style={styles.photo} contentFit="contain"
            cachePolicy="none" accessibilityLabel={t('community.photo')} />
          <Text accessibilityRole="header" style={styles.title}>{detail.title}</Text>
          <LookPostAuthor displayName={detail.example ? 'VISHUE' : detail.displayName} createdAt={detail.createdAt} />
          {detail.description ? <Text style={styles.copy}>{detail.description}</Text> : null}
          {detail.products.length > 0 ? <Text accessibilityRole="header" style={styles.label}>{t('community.usedProducts')}</Text> : null}
          {detail.products.map((item, index) => {
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
          {detail.products.length > 0 && products.isPending ? <Text style={styles.copy}>{t('community.loading')}</Text> : null}
          {detail.products.length > 0 && products.isError ? <Button label={t('common.retry')} variant="secondary" onPress={() => void products.refetch()} /> : null}
        </> : <InlineState status={missing || post.isError ? 'error' : 'loading'}
          message={t(missing ? 'community.postMissing' : 'community.error')}
          onRetry={missing ? undefined : () => void post.refetch()} />}
      </ScrollView>
      {detail ? <View style={styles.footer}>
        <View style={styles.footerContent}>
          {feedback && !reporting ? (
            <Text accessibilityLiveRegion="polite" style={[styles.feedback, feedback === 'community.error' && styles.error]}>{t(feedback)}</Text>
          ) : null}
          <View style={styles.engagement}>
            <LookPostVotes count={detail.votes} />
            {owned ? (
              <Button label={t('community.edit')} icon="create-outline" variant="secondary" multiline
                style={styles.primaryAction} onPress={() => router.push(communityWriteHref({ id: detail.id }))} />
            ) : (
              <Button label={t(recommended ? 'community.recommended' : 'community.recommend')}
                icon={recommended ? 'heart' : 'heart-outline'} variant={recommended ? 'secondary' : 'primary'} multiline
                style={[styles.primaryAction, recommended && styles.recommended]}
                loading={busy && !reporting} disabled={actionDisabled || recommended}
                onPress={() => user ? void interact('recommend') : router.push(loginHref('community-post'))} />
            )}
          </View>
        </View>
      </View> : null}
      {reporting ? (
        <BottomSheet title={t('community.report')} closeLabel={t('common.cancel')} bottomInset={bottom}
          onClose={closeReport} avoidKeyboard>
          <ScrollView contentContainerStyle={styles.report} keyboardShouldPersistTaps="handled" bounces={false}>
            <TextInput style={styles.input} placeholder={t('community.reportReason')} placeholderTextColor={theme.colors.inkMuted}
              accessibilityLabel={t('community.reportReason')} value={reason} onChangeText={setReason}
              maxLength={300} multiline editable={!busy} textAlignVertical="top" />
            {feedback === 'community.error' ? <Text accessibilityRole="alert" style={styles.error}>{t(feedback)}</Text> : null}
            <Button label={t('community.report')} variant="danger" loading={busy} disabled={!reason.trim()}
              onPress={() => void interact('report')} />
          </ScrollView>
        </BottomSheet>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  back: { minHeight: theme.hitTarget, paddingHorizontal: 0 },
  reportAction: { minWidth: theme.hitTarget, minHeight: theme.hitTarget, flexDirection: 'row', gap: 5, alignItems: 'center' },
  reportLabel: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.inkMuted },
  dimmed: { opacity: 0.45 },
  content: { width: '100%', maxWidth: 600, alignSelf: 'center', padding: 20, gap: 14 },
  photo: { width: '100%', aspectRatio: 1.15, borderRadius: 16, backgroundColor: theme.colors.cream },
  title: { color: theme.colors.ink, fontSize: 26, fontWeight: '800' },
  label: { color: theme.colors.ink, fontSize: 17, fontWeight: '700', marginTop: 8 },
  copy: { fontSize: 16, color: theme.colors.inkMuted, lineHeight: 24 },
  footer: { backgroundColor: theme.colors.card, borderTopWidth: StyleSheet.hairlineWidth, borderColor: theme.colors.border },
  footerContent: { width: '100%', maxWidth: 600, alignSelf: 'center', paddingHorizontal: 20, paddingVertical: 10, gap: 8 },
  engagement: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  primaryAction: { flex: 1, minWidth: 0, borderRadius: theme.radius.pill },
  recommended: { opacity: 1, backgroundColor: theme.colors.roseSoft },
  feedback: { color: theme.colors.inkMuted, fontSize: theme.font.small },
  error: { color: theme.colors.danger, fontSize: theme.font.small },
  product: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 10, borderRadius: 14,
    backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border },
  pressed: { opacity: 0.8 },
  productPhoto: { width: 56, height: 56, borderRadius: 8 },
  productInfo: { flex: 1, minWidth: 0, gap: 3 },
  brand: { color: theme.colors.roseDark, fontSize: 12 },
  productName: { fontSize: 15, color: theme.colors.ink, fontWeight: '700' },
  shade: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  swatch: { width: 10, height: 10, borderRadius: 5, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.colors.border },
  shadeName: { color: theme.colors.inkMuted, fontSize: 13, flexShrink: 1 },
  report: { width: '100%', maxWidth: 600, alignSelf: 'center', paddingHorizontal: 20, paddingTop: 4, gap: 12 },
  input: { fontSize: 16, minHeight: 96, padding: 12, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 12,
    backgroundColor: theme.colors.card, color: theme.colors.ink },
});
