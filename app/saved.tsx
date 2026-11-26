import { StyleSheet, View } from 'react-native';
import { EmptyState } from '@/components/ui/StateViews';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export default function SavedScreen() {
  const { t } = useI18n();
  return (
    <View style={styles.screen}>
      <EmptyState icon="heart-outline" title={t('saved.productsEmpty')} />
    </View>
  );
}

const styles = StyleSheet.create({ screen: { flex: 1, backgroundColor: theme.colors.surface } });
