import { useState } from 'react';
import LooksScreen from '@/components/celeb/LooksScreen';
import { SearchBar } from '@/components/shop/SearchBar';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useI18n } from '@/lib/i18n';
import { useStyleLooks, useTutorials } from '@/lib/queries';

export default function LooksTab() {
  const [query, setQuery] = useState('');
  const { t } = useI18n();
  const debounced = useDebouncedValue(query.trim(), 600);
  const looks = useStyleLooks();
  const tutorials = useTutorials(debounced.length >= 2 ? debounced : undefined, 8);
  return <LooksScreen searchBar={<SearchBar value={query} onChangeText={setQuery} placeholder={t('looks.searchPlaceholder')} />} looks={looks} tutorials={tutorials} />;
}
