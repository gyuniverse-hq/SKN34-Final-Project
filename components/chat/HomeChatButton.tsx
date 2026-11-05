import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

export function HomeChatButton({ label, hint, onPress }: { label: string; hint: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityHint={hint}
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
      <Ionicons name="chatbubble-ellipses" size={24} color={theme.colors.white} />
      <View style={styles.badge} pointerEvents="none">
        <Text style={styles.badgeText}>AI</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    backgroundColor: theme.colors.rose,
    borderColor: theme.colors.white,
    borderRadius: 29,
    borderWidth: 3,
    bottom: 20,
    elevation: 6,
    height: 58,
    justifyContent: 'center',
    position: 'absolute',
    right: 18,
    shadowColor: theme.colors.roseDark,
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.28,
    shadowRadius: 8,
    width: 58,
  },
  badge: {
    alignItems: 'center',
    backgroundColor: theme.colors.accent,
    borderColor: theme.colors.white,
    borderRadius: 10,
    borderWidth: 1.5,
    height: 20,
    justifyContent: 'center',
    position: 'absolute',
    right: -3,
    top: -3,
    width: 24,
  },
  badgeText: { color: theme.colors.white, fontSize: 9, fontWeight: '900', letterSpacing: 0.2 },
  pressed: { opacity: 0.88, transform: [{ scale: 0.96 }] },
});
