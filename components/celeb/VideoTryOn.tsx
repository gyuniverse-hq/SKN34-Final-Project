import { StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';

export function VideoTryOn({ label, message, onPress, loading }: {
  label: string; message: string; onPress: () => void; loading: boolean;
}) {
  return <View style={styles.container}>
    <Button label={label} icon="scan-outline" onPress={onPress} loading={loading} />
    <Text style={styles.note}>{message}</Text>
  </View>;
}

const styles = StyleSheet.create({
  container: { marginTop: 18, gap: 8 },
  note: { color: theme.colors.inkMuted, fontSize: 12, lineHeight: 18 },
});
