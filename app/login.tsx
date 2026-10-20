import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export default function LoginScreen() {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.logo}>
          <Ionicons name="sparkles" size={32} color={theme.colors.white} />
        </View>
        <Text style={styles.title}>{t('login.title')}</Text>
        <Text style={styles.subtitle}>{t('login.subtitle')}</Text>

        <View style={styles.form}>
          <TextInput
            value={email}
            onChangeText={setEmail}
            placeholder={t('login.email')}
            placeholderTextColor={theme.colors.inkFaint}
            keyboardType="email-address"
            autoCapitalize="none"
            autoComplete="email"
            style={styles.input}
          />
          <TextInput
            value={password}
            onChangeText={setPassword}
            placeholder={t('login.password')}
            placeholderTextColor={theme.colors.inkFaint}
            secureTextEntry
            autoComplete="password"
            style={styles.input}
          />
          <Button label={t('login.submit')} onPress={() => {}} disabled={!email || !password} />
        </View>

        <View style={styles.divider} />

        <Button label={t('login.apple')} icon="logo-apple" variant="secondary" onPress={() => {}} />
        <Button label={t('login.google')} icon="logo-google" variant="secondary" onPress={() => {}} style={styles.gap} />

        <Pressable accessibilityRole="button" style={styles.signup}>
          <Text style={styles.signupText}>{t('login.signup')}</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { padding: theme.spacing.xl, paddingTop: 40, paddingBottom: 48 },
  logo: {
    width: 64,
    height: 64,
    borderRadius: 20,
    backgroundColor: theme.colors.rose,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
  },
  title: { fontSize: theme.font.h2, fontWeight: '800', color: theme.colors.ink, textAlign: 'center', marginTop: 18 },
  subtitle: { fontSize: theme.font.small, color: theme.colors.inkMuted, textAlign: 'center', marginTop: 6, lineHeight: 19 },
  form: { gap: 10, marginTop: 28 },
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
  divider: { height: StyleSheet.hairlineWidth, backgroundColor: theme.colors.border, marginVertical: 24 },
  gap: { marginTop: 10 },
  signup: { alignSelf: 'center', marginTop: 20, padding: 6 },
  signupText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.rose },
});
