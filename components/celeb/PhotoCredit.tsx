import * as WebBrowser from 'expo-web-browser';
import { Pressable, StyleSheet, Text } from 'react-native';
import { celebrityImageSource, type Celebrity } from '@/constants/celebrities';
import { theme } from '@/constants/theme';

export function PhotoCredit({ celebrity, label }: { celebrity: Celebrity; label: string }) {
  const credit = celebrity.credit;
  if (!credit) return null;
  return (
    <Pressable accessibilityRole="link" onPress={() => WebBrowser.openBrowserAsync(celebrityImageSource(credit.file))}>
      <Text style={styles.text}>{label}: {credit.author} · {credit.license} ↗</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  text: { color: theme.colors.inkMuted, fontSize: 11, lineHeight: 18, textDecorationLine: 'underline' },
});
