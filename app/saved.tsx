import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

type Tab = 'products' | 'looks';

export default function SavedScreen() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('products');

  return (
    <View style={styles.screen}>
      <View style={styles.tabs}>
        {(['products', 'looks'] as const).map((key) => (
          <Pressable
            key={key}
            onPress={() => setTab(key)}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab === key }}
            style={[styles.tab, tab === key && styles.tabActive]}>
            <Text style={[styles.tabText, tab === key && styles.tabTextActive]}>
              {t(key === 'products' ? 'saved.products' : 'saved.looks')}
            </Text>
          </Pressable>
        ))}
      </View>
      {tab === 'products' ? (
        <EmptyState icon="heart-outline" title={t('saved.productsEmpty')} />
      ) : (
        <EmptyState icon="sparkles-outline" title={t('saved.looksEmpty')} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  tabs: {
    flexDirection: 'row',
    margin: theme.spacing.lg,
    backgroundColor: theme.colors.surfaceAlt,
    borderRadius: theme.radius.md,
    padding: 3,
  },
  tab: { flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: 10 },
  tabActive: { backgroundColor: theme.colors.card, ...theme.shadow },
  tabText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.inkMuted },
  tabTextActive: { color: theme.colors.ink },
});
