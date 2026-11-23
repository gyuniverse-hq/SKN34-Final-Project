import Ionicons from '@expo/vector-icons/Ionicons';
import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState, type ComponentRef, type ReactNode } from 'react';
import { Keyboard, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { homeLayout, homeType } from '@/constants/homeLayout';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import { useRecentSearchStore } from '@/store/recentSearchStore';

/** The overlay and its touch targets live inside the feed, without taking up layout space. */
export function HomeSearch({ children, onSearch }: { children: ReactNode; onSearch: (query: string) => void }) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState(false);
  const input = useRef<ComponentRef<typeof TextInput>>(null);
  const [fieldHeight, setFieldHeight] = useState(38);
  const searches = useRecentSearchStore(s => s.searches);
  const add = useRecentSearchStore(s => s.add);
  const remove = useRecentSearchStore(s => s.remove);
  const showRecent = editing && !query.trim() && searches.length > 0;
  const dismiss = useCallback(() => {
    setEditing(false);
    input.current?.blur();
  }, []);
  useFocusEffect(useCallback(() => dismiss, [dismiss]));
  useEffect(() => {
    const subscription = Keyboard.addListener('keyboardDidHide', dismiss);
    return () => subscription.remove();
  }, [dismiss]);

  const submit = (value: string) => {
    const term = value.trim();
    if (!term) return;
    add(term);
    dismiss();
    setQuery('');
    onSearch(term);
  };

  return (
    <View>
      <View onLayout={event => setFieldHeight(event.nativeEvent.layout.height)} style={[styles.field, editing && styles.active]}>
        <Ionicons name="search-outline" size={18} color={theme.colors.roseDark} />
        <TextInput ref={input} accessibilityLabel={t('home.search')} placeholder={t('home.search')}
          placeholderTextColor={theme.colors.inkMuted} autoCapitalize="none" autoCorrect={false} maxLength={80}
          returnKeyType="search" value={query} onChangeText={setQuery} onFocus={() => setEditing(true)}
          onBlur={() => { if (!showRecent) setEditing(false); }}
          onPressIn={() => setEditing(true)} onSubmitEditing={() => submit(query)}
          onKeyPress={event => { if (event.nativeEvent.key === 'Escape') dismiss(); }} style={styles.input} />
        {!!query && <Pressable accessibilityRole="button" accessibilityLabel={t('home.clearQuery')} hitSlop={6}
          onPress={() => { setQuery(''); input.current?.focus(); }}>
          <Ionicons name="close-circle" size={17} color={theme.colors.inkFaint} />
        </Pressable>}
      </View>
      {children}
      {showRecent && (
        <View pointerEvents="box-none" style={[styles.overlay, { top: fieldHeight }]}>
          <Pressable accessible={false} tabIndex={-1} style={styles.backdrop} onPress={dismiss} />
          <View style={styles.panel}>
            <Text accessibilityRole="header" style={styles.recentTitle}>{t('discovery.recent')}</Text>
            <ScrollView style={styles.list} nestedScrollEnabled keyboardShouldPersistTaps="always">
              {searches.map(term => (
                <View key={term} style={styles.row}>
                  <Pressable accessibilityRole="button" accessibilityLabel={term} style={styles.term} onPress={() => submit(term)}>
                    <Ionicons name="time-outline" size={16} color={theme.colors.inkFaint} />
                    <Text numberOfLines={1} style={styles.termText}>{term}</Text>
                  </Pressable>
                  <Pressable accessibilityRole="button" accessibilityLabel={t('discovery.removeSearch', { query: term })}
                    onPress={() => remove(term)} style={styles.delete}>
                    <Ionicons name="close" size={15} color={theme.colors.inkMuted} />
                  </Pressable>
                </View>
              ))}
            </ScrollView>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  field: { marginHorizontal: homeLayout.gutter, flexDirection: 'row', alignItems: 'center', gap: 9,
    minHeight: 38, paddingHorizontal: 12, borderRadius: 20, backgroundColor: homeLayout.blush, borderWidth: 1, borderColor: 'transparent' },
  active: { backgroundColor: homeLayout.background, borderColor: '#AE6B7C' },
  input: { ...homeType(14), flex: 1, minHeight: 36, paddingVertical: 4, color: theme.colors.ink },
  overlay: { ...StyleSheet.absoluteFill, zIndex: 5 },
  backdrop: StyleSheet.absoluteFill,
  panel: { marginTop: 4, marginHorizontal: homeLayout.gutter, paddingHorizontal: 12, paddingVertical: 5,
    backgroundColor: theme.colors.card, borderRadius: 13, borderColor: theme.colors.border, borderWidth: 1, ...theme.shadow },
  recentTitle: { ...homeType(13), fontWeight: '600', marginTop: 3, marginBottom: 2, color: theme.colors.inkMuted },
  list: { maxHeight: 132 },
  row: { flexDirection: 'row', alignItems: 'center', minHeight: 44 },
  term: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 9, minHeight: 44 },
  termText: { ...homeType(14), flex: 1, color: theme.colors.ink },
  delete: { width: 44, minHeight: 44, justifyContent: 'center', alignItems: 'center' },
});
