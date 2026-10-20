import { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SearchBar } from '@/components/shop/SearchBar';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export default function IngredientsScreen() {
  const { t } = useI18n();
  const [query, setQuery] = useState('');

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Text style={styles.intro}>{t('ingredients.intro')}</Text>
      <SearchBar value={query} onChangeText={setQuery} placeholder={t('ingredients.searchPlaceholder')} />

      <View style={styles.results}>
        <EmptyState icon="flask-outline" title={t('ingredients.empty')} />
      </View>

      <Text style={styles.sectionTitle}>{t('ingredients.similar')}</Text>
      <View style={styles.placeholder}>
        <Text style={styles.placeholderText}>{t('common.comingSoon')}</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.lg, paddingBottom: 40 },
  intro: { fontSize: theme.font.small, color: theme.colors.inkMuted, lineHeight: 19, marginBottom: 14 },
  results: { marginTop: 8 },
  sectionTitle: { fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink, marginTop: 10, marginBottom: 8 },
  placeholder: {
    height: 120,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  placeholderText: { fontSize: theme.font.small, color: theme.colors.inkFaint },
});
