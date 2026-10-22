import { Image } from 'expo-image';
import type { ReactNode } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  type TextInputProps,
} from 'react-native';
import { theme } from '@/constants/theme';

export function AuthScreen({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Image
          source={require('@/assets/images/splash-icon.png')}
          style={styles.logo}
          contentFit="contain"
          accessibilityLabel="VISHUE"
        />
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        {children}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

export function AuthInput(props: TextInputProps) {
  return (
    <TextInput
      placeholderTextColor={theme.colors.inkFaint}
      accessibilityLabel={props.placeholder}
      {...props}
      style={[styles.input, props.style]}
    />
  );
}

export function FormMessage({ tone, text }: { tone: 'error' | 'info'; text: string | null }) {
  if (!text) return null;
  return (
    <Text
      accessibilityLiveRegion="polite"
      style={[styles.message, tone === 'error' ? styles.error : styles.info]}>
      {text}
    </Text>
  );
}

export const authStyles = StyleSheet.create({
  form: { gap: 10, marginTop: 28 },
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: theme.colors.border, marginVertical: 24 },
  gap: { marginTop: 10 },
  link: { alignSelf: 'center', marginTop: 20, padding: 6 },
  linkText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.rose },
});

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.xl, paddingTop: 40, paddingBottom: 48 },
  logo: { width: 96, height: 96, alignSelf: 'center' },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink, textAlign: 'center', marginTop: 18 },
  subtitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, textAlign: 'center', marginTop: 6, lineHeight: 19 },
  input: {
    minHeight: 50,
    borderRadius: theme.radius.md,
    borderWidth: 1,
    borderColor: theme.colors.border,
    backgroundColor: theme.colors.card,
    paddingHorizontal: 16,
    fontSize: theme.font.body,
    color: theme.colors.ink,
  },
  message: { fontSize: theme.font.small, lineHeight: 19, paddingHorizontal: 4 },
  error: { color: theme.colors.danger },
  info: { color: theme.colors.inkMuted },
});
