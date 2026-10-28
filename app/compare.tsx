import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CompareTable } from '@/components/shop/CompareTable';
import { Button } from '@/components/ui/Button';
import { Notice } from '@/components/ui/Notice';
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useCompareLines } from '@/hooks/useCompareLines';
import { confirmAction, notify } from '@/lib/confirm';
import { useI18n } from '@/lib/i18n';
import { productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { MAX_COMPARE, useCompareStore } from '@/store/compareStore';

export default function CompareScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { items, lines, query } = useCompareLines();
  const remove = useCompareStore((s) => s.remove);
  const clear = useCompareStore((s) => s.clear);
  const addToCart = useCartStore((s) => s.add);

  if (items.length === 0) {
    return (
      <EmptyState
        icon="git-compare-outline"
        title={t('compare.empty')}
        body={t('compare.emptyBody', { max: MAX_COMPARE })}
        action={<Button label={t('home.search')} onPress={() => router.push('/shop')} />}
      />
    );
  }
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.intro}>{t('compare.intro', { count: items.length, max: MAX_COMPARE })}</Text>
        <CompareTable
          lines={lines}
          onOpen={(productId, shadeId) => router.push(productHref(productId, shadeId))}
          onAddToCart={(productId, shadeId) => {
            addToCart({ productId, shadeId });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
            notify(t('product.added'));
          }}
          onRemove={remove}
        />
        <View style={styles.footer}>
          <Notice tone="neutral" body={t('compare.priceNote')} />
          {items.length < MAX_COMPARE ? (
            <Button label={t('compare.addMore')} icon="add" variant="secondary" onPress={() => router.push('/shop')} />
          ) : null}
          <Button
            label={t('compare.clear')}
            variant="ghost"
            compact
            onPress={() => confirmAction(t('compare.clear'), t('common.delete'), t('common.cancel'), clear)}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { paddingTop: theme.spacing.lg, paddingBottom: 40 },
  intro: { fontSize: theme.font.small, color: theme.colors.inkMuted, paddingHorizontal: theme.spacing.lg, marginBottom: 12 },
  footer: { gap: 10, padding: theme.spacing.lg },
});
