import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

interface Props {
  value: number;
  max: number;
  onChange: (value: number) => void;
}

export function QuantityStepper({ value, max, onChange }: Props) {
  return (
    <View style={styles.wrap}>
      <Pressable
        onPress={() => onChange(value - 1)}
        accessibilityRole="button"
        accessibilityLabel="Decrease quantity"
        hitSlop={8}
        style={styles.btn}>
        <Ionicons name={value <= 1 ? 'trash-outline' : 'remove'} size={16} color={theme.colors.ink} />
      </Pressable>
      <Text style={styles.value} accessibilityLabel={`Quantity ${value}`}>
        {value}
      </Text>
      <Pressable
        onPress={() => onChange(value + 1)}
        disabled={value >= max}
        accessibilityRole="button"
        accessibilityLabel="Increase quantity"
        hitSlop={8}
        style={[styles.btn, value >= max && { opacity: 0.4 }]}>
        <Ionicons name="add" size={16} color={theme.colors.ink} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.pill,
    alignSelf: 'flex-start',
  },
  btn: { width: 34, height: 32, alignItems: 'center', justifyContent: 'center' },
  value: { minWidth: 24, textAlign: 'center', fontSize: theme.font.body, fontWeight: '600', color: theme.colors.ink },
});
