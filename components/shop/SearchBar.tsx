import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';
import { theme } from '@/constants/theme';

interface Props {
  value: string;
  onChangeText: (text: string) => void;
  placeholder: string;
  onSubmit?: () => void;
}

export function SearchBar({ value, onChangeText, placeholder, onSubmit }: Props) {
  return (
    <View style={styles.wrap}>
      <Ionicons name="search" size={18} color={theme.colors.inkFaint} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        onSubmitEditing={onSubmit}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.inkFaint}
        style={styles.input}
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
});
