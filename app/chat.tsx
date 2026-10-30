import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme } from '@/constants/theme';
import { useChat } from '@/hooks/useChat';
import { useI18n } from '@/lib/i18n';
import { productHref } from '@/lib/routes';
import type { ChatProductRef } from '@/types';
import { useRouter } from 'expo-router';

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  products?: ChatProductRef[];
};

export default function ChatScreen() {
  const router = useRouter();
  const { t, language } = useI18n();
  const { mutateAsync, isPending } = useChat();
  const scrollRef = useRef<ScrollView>(null);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [failed, setFailed] = useState(false);
  const prompts = [t('ar.chatExample1'), t('ar.chatExample2'), t('ar.chatExample3')];

  useEffect(() => {
    if (messages.length) scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length]);

  const send = async (draft = input) => {
    const text = draft.trim();
    if (!text || isPending) return;
    setInput('');
    setFailed(false);
    setMessages((current) => [...current, { id: `user-${Date.now()}`, role: 'user', text }]);
    try {
      const response = await mutateAsync({ message: text, locale: language });
      setMessages((current) => [
        ...current,
        { id: `assistant-${Date.now()}`, role: 'assistant', text: response.answer, products: response.products },
      ]);
    } catch {
      setFailed(true);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <KeyboardAvoidingView style={styles.keyboard} behavior={Platform.select({ ios: 'padding', default: undefined })}>
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.messages}
          keyboardShouldPersistTaps="handled"
          onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: messages.length > 0 })}>
          {messages.length === 0 ? (
            <View style={styles.welcome}>
              <View style={styles.welcomeIcon}>
                <Ionicons name="sparkles" size={22} color={theme.colors.rose} />
              </View>
              <Text style={styles.welcomeTitle}>{t('ar.chatTitle')}</Text>
              <Text style={styles.welcomeBody}>{t('ar.chatBody')}</Text>
              <View style={styles.prompts}>
                {prompts.map((prompt) => (
                  <Pressable key={prompt} accessibilityRole="button" onPress={() => send(prompt)} style={({ pressed }) => [styles.prompt, pressed && styles.pressed]}>
                    <Text style={styles.promptText}>{prompt}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ) : null}

          {messages.map((message) => (
            <View key={message.id} style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}>
              <Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.text}</Text>
              {message.products?.length ? (
                <View style={styles.related}>
                  <Text style={styles.relatedTitle}>{t('chat.relatedProducts')}</Text>
                  {message.products.map((product) => (
                    <Pressable
                      key={product.id}
                      accessibilityRole="button"
                      accessibilityLabel={`${product.brand} ${product.name}`}
                      onPress={() => router.push(productHref(product.id))}
                      style={({ pressed }) => [styles.product, pressed && styles.pressed]}>
                      <View style={styles.productCopy}>
                        <Text style={styles.productBrand}>{product.brand}</Text>
                        <Text style={styles.productName} numberOfLines={1}>
                          {product.name}
                        </Text>
                      </View>
                      <Ionicons name="chevron-forward" size={18} color={theme.colors.rose} />
                    </Pressable>
                  ))}
                </View>
              ) : null}
            </View>
          ))}

          {isPending ? (
            <View style={[styles.message, styles.assistantMessage, styles.loadingMessage]} accessibilityRole="progressbar">
              <ActivityIndicator color={theme.colors.rose} size="small" />
            </View>
          ) : null}
          {failed ? <Text accessibilityRole="alert" style={styles.error}>{t('chat.unavailable')}</Text> : null}
        </ScrollView>

        <View style={styles.composer}>
          <TextInput
            accessibilityLabel={t('ar.chatPlaceholder')}
            editable={!isPending}
            multiline
            onChangeText={setInput}
            onSubmitEditing={() => send()}
            placeholder={t('ar.chatPlaceholder')}
            placeholderTextColor={theme.colors.inkFaint}
            returnKeyType="send"
            style={styles.input}
            value={input}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('ar.send')}
            accessibilityState={{ disabled: !input.trim() || isPending, busy: isPending }}
            disabled={!input.trim() || isPending}
            onPress={() => send()}
            style={({ pressed }) => [styles.send, (!input.trim() || isPending) && styles.sendDisabled, pressed && styles.pressed]}>
            <Ionicons name="arrow-up" size={20} color={theme.colors.white} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  keyboard: { flex: 1 },
  messages: { flexGrow: 1, gap: 12, padding: theme.spacing.lg, paddingBottom: 20 },
  welcome: { alignItems: 'center', marginTop: 40, paddingHorizontal: 12 },
  welcomeIcon: { alignItems: 'center', backgroundColor: theme.colors.roseSoft, borderRadius: 24, height: 48, justifyContent: 'center', width: 48 },
  welcomeTitle: { color: theme.colors.ink, fontSize: theme.font.title, fontWeight: '800', marginTop: 14 },
  welcomeBody: { color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 20, marginTop: 6, textAlign: 'center' },
  prompts: { alignItems: 'stretch', gap: 8, marginTop: 24, width: '100%' },
  prompt: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderRadius: theme.radius.md, borderWidth: 1, minHeight: 44, paddingHorizontal: 14, justifyContent: 'center' },
  promptText: { color: theme.colors.roseDark, fontSize: theme.font.small, fontWeight: '700' },
  message: { borderRadius: theme.radius.md, maxWidth: '88%', paddingHorizontal: 14, paddingVertical: 12 },
  userMessage: { alignSelf: 'flex-end', backgroundColor: theme.colors.rose },
  assistantMessage: { alignSelf: 'flex-start', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1 },
  messageText: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 22 },
  userMessageText: { color: theme.colors.white },
  loadingMessage: { minHeight: 44, minWidth: 54, justifyContent: 'center' },
  related: { borderTopColor: theme.colors.border, borderTopWidth: 1, gap: 8, marginTop: 12, paddingTop: 10 },
  relatedTitle: { color: theme.colors.inkMuted, fontSize: 11, fontWeight: '800', letterSpacing: 0.5, textTransform: 'uppercase' },
  product: { alignItems: 'center', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.sm, flexDirection: 'row', gap: 8, minHeight: 50, paddingHorizontal: 10 },
  productCopy: { flex: 1 },
  productBrand: { color: theme.colors.accent, fontSize: 11, fontWeight: '800' },
  productName: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', marginTop: 1 },
  error: { color: theme.colors.danger, fontSize: theme.font.small, lineHeight: 19, textAlign: 'center' },
  composer: { alignItems: 'flex-end', backgroundColor: theme.colors.card, borderTopColor: theme.colors.border, borderTopWidth: 1, flexDirection: 'row', gap: 8, padding: 12 },
  input: { color: theme.colors.ink, flex: 1, fontSize: theme.font.body, lineHeight: 20, maxHeight: 100, minHeight: 44, paddingHorizontal: 12, paddingTop: 11 },
  send: { alignItems: 'center', backgroundColor: theme.colors.rose, borderRadius: 22, height: 44, justifyContent: 'center', width: 44 },
  sendDisabled: { opacity: 0.4 },
  pressed: { opacity: 0.82 },
});
