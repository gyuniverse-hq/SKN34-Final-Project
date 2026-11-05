import Ionicons from '@expo/vector-icons/Ionicons';
import { useRouter } from 'expo-router';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { formatDate, formatKRW } from '@/lib/format';
import { useI18n } from '@/lib/i18n';
import { useShoppingListStore } from '@/store/shoppingListStore';

export default function ShoppingListsScreen() {
  const router = useRouter();
  const { t, language } = useI18n();
  const lists = useShoppingListStore((s) => s.lists);

  return (
    <FlatList
      style={styles.screen}
      data={lists}
      keyExtractor={(l) => l.id}
      contentContainerStyle={lists.length ? styles.list : styles.emptyList}
      ListEmptyComponent={<EmptyState icon="list-outline" title={t('list.none')} />}
      renderItem={({ item }) => (
        <Pressable
          onPress={() => router.push(`/lists/${item.id}`)}
          accessibilityRole="button"
          style={({ pressed }) => [styles.row, pressed && { opacity: 0.85 }]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.date}>{formatDate(item.createdAt, language)}</Text>
            <Text style={styles.summary} numberOfLines={1}>
              {item.lines.map((l) => l.brand).join(' · ')}
            </Text>
            <Text style={styles.meta}>
              {t('list.itemCount', { count: item.lines.reduce((n, l) => n + l.quantity, 0) })} ·{' '}
              {formatKRW(item.totalKRW)}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.colors.inkFaint} />
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  list: { padding: theme.spacing.lg, gap: 10 },
  emptyList: { flexGrow: 1 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 16,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.card,
    ...theme.shadow,
  },
  date: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.ink },
  summary: { fontSize: 12, color: theme.colors.inkMuted, marginTop: 2 },
  meta: { fontSize: 12, color: theme.colors.inkMuted, marginTop: 2 },
});
