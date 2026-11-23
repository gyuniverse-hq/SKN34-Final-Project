import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';
import { theme } from '@/constants/theme';
import { homeLayout, homeType } from '@/constants/homeLayout';

interface Props {
  value: string;
  onChangeText: (text: string) => void;
  placeholder: string;
  onSubmit?: () => void;
  tonal?: boolean;
}

export function SearchBar({ value, onChangeText, placeholder, onSubmit, tonal }: Props) {
  return (
    <View style={[styles.wrap, tonal && styles.tonal]}>
      <Ionicons name={tonal ? 'search-outline' : 'search'} size={18} color={tonal ? theme.colors.roseDark : theme.colors.inkFaint} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        onSubmitEditing={onSubmit}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.inkFaint}
        style={[styles.input, tonal && styles.tonalInput]}
        autoCapitalize="none"
        autoCorrect={false}
        returnKeyType="search"
        accessibilityLabel={placeholder}
        maxLength={80}
      />
      {value ? (
        <Pressable onPress={() => onChangeText('')} hitSlop={10} accessibilityRole="button" accessibilityLabel="Clear">
          <Ionicons name="close-circle" size={18} color={theme.colors.inkFaint} />
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: theme.colors.card,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    paddingHorizontal: 14,
  },
  input: { flex: 1, fontSize: theme.font.body, color: theme.colors.ink, paddingVertical: 12 },
  tonal: { backgroundColor: homeLayout.blush, borderColor: 'transparent', borderRadius: 20, paddingHorizontal: 12 },
  tonalInput: { ...homeType(14), minHeight: 36, paddingVertical: 4 },
});
