import { Stack, useRouter } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ConcernPicker } from '@/components/skin/ConcernPicker';
import { ProductLineCard } from '@/components/shop/ProductLineCard';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { Notice } from '@/components/ui/Notice';
import { LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { formatDate } from '@/lib/format';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useSkinRecommendations } from '@/lib/queries';
import { productHref, searchHref, SKIN_CONCERNS } from '@/lib/routes';
import { suggestConcerns, toggleConcern } from '@/lib/skinFilters';
import { buildSkinRecommendationRequest } from '@/lib/skinRecommendations';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinConcern, SkinRecommendationRequest } from '@/types';

/** Confirm concerns derived from analysis + survey, then request ranked care products. */
export default function SkinRecommendationsScreen() {
  const router = useRouter();
  const { t, language } = useI18n();
  const profile = useSkinProfileStore((s) => s.profile);
  const hydrate = useSkinProfileStore((s) => s.hydrate);
  const [hydrated, setHydrated] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const suggested = useMemo(() => suggestConcerns(profile), [profile]);
  const [selected, setSelected] = useState<SkinConcern[]>([]);
  const [request, setRequest] = useState<SkinRecommendationRequest>();
  const recommendations = useSkinRecommendations(request);
  const seeded = useRef(false);

  useEffect(() => {
    hydrate()
      .catch(() => setLoadFailed(true))
      .finally(() => setHydrated(true));
  }, [hydrate]);

  useEffect(() => {
    if (!hydrated || seeded.current) return;
    seeded.current = true;
    setSelected(suggested);
  }, [hydrated, suggested]);

  if (!hydrated) return <LoadingState />;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t('skinFlow.resultTitle') }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">
          {t('skinFlow.resultTitle')}
        </Text>
        <Text style={styles.body}>
          {profile
            ? t('skinFlow.resultFrom', { date: formatDate(profile.registeredAt, language) })
            : t('skinFlow.noResult')}
        </Text>
        {loadFailed ? <Notice tone="warning" body={t('skin.loadFailed')} /> : null}
        {profile && suggested.length === 0 ? <Notice body={t('skinFlow.noSuggestions')} /> : null}

        <ConcernPicker
          concerns={SKIN_CONCERNS}
          selected={selected}
          suggested={suggested}
          onToggle={(c) => {
            setSelected((prev) => toggleConcern(prev, c));
            setRequest(undefined);
          }}
        />

        <Notice tone="neutral" title={t('skinFlow.notMedicalTitle')} body={t('skinFlow.notMedicalBody')} />

        {request ? (
          <View style={styles.results}>
            <Text style={styles.title} accessibilityRole="header">{t('skinRec.title')}</Text>
            <Text style={styles.body}>{t('skinRec.how')}</Text>
            {recommendations.isPending ? <InlineState status="loading" />
              : recommendations.isError ? (
                <InlineState status="error" onRetry={() => recommendations.refetch()} />
              ) : recommendations.data?.status !== 'ok' ? (
                <InlineState status="empty" message={t(
                  recommendations.data?.status === 'empty_catalog' ? 'skinRec.emptyCatalog'
                    : recommendations.data?.status === 'no_concerns' ? 'skinRec.noConcerns' : 'skinRec.noMatches'
                )} />
              ) : recommendations.data.matches.map(({ product, matchedConcerns }) => (
                <ProductLineCard
                  key={product.id}
                  product={product}
                  badges={matchedConcerns.map((c) => ({ label: t(`concern.${c}` as TranslationKey), tone: 'brand' }))}
                  note={t('skinRec.matched', { count: matchedConcerns.length })}
                  onPress={() => router.push(productHref(product.id))}
                />
              ))}
          </View>
        ) : null}
      </ScrollView>
      <View style={styles.footer}>
        <Button
          label={t('skinRec.show')}
          icon="sparkles-outline"
          disabled={selected.length === 0}
          loading={recommendations.isFetching}
          onPress={() => {
            if (request) void recommendations.refetch();
            else setRequest(buildSkinRecommendationRequest(profile, selected));
          }}
        />
        <Button
          label={t('skinFlow.browse', { count: selected.length })}
          variant="secondary"
          onPress={() => router.push(searchHref({ concerns: selected, source: 'skin' }))}
        />
        <Button
          label={t('skinFlow.skip')}
          variant="secondary"
          onPress={() => router.push(searchHref({ source: 'skin' }))}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, gap: 14, paddingBottom: 32 },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink },
  body: { fontSize: theme.font.body, color: theme.colors.inkMuted, lineHeight: 22 },
  results: { gap: 10 },
  footer: {
    gap: 8,
    paddingHorizontal: theme.spacing.lg,
    paddingTop: 12,
    paddingBottom: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: theme.colors.border,
  },
});
