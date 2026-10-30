import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useRouter } from 'expo-router';
import { useHeaderHeight } from 'expo-router/react-navigation';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator, Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { theme } from '@/constants/theme';
import { useChat } from '@/hooks/useChat';
import { extractChatConditions } from '@/lib/chatConditions';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProductsByIds } from '@/lib/queries';
import { arHref, productHref } from '@/lib/routes';
import type { ChatProductRef } from '@/types';

type Category = 'product' | 'ingredient' | 'style';
type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  products?: ChatProductRef[];
  question?: string;
  category?: Category;
  failed?: boolean;
};

const categories: { id: Category; icon: 'color-palette' | 'leaf' | 'flower'; label: TranslationKey; caption: TranslationKey; prompts: TranslationKey[] }[] = [
  { id: 'product', icon: 'color-palette', label: 'chat.ui.product', caption: 'chat.ui.productCaption', prompts: ['chat.ui.productQuestion1', 'chat.ui.productQuestion2', 'chat.ui.productQuestion3'] },
  { id: 'ingredient', icon: 'leaf', label: 'chat.ui.ingredient', caption: 'chat.ui.ingredientCaption', prompts: ['chat.ui.ingredientQuestion1', 'chat.ui.ingredientQuestion2', 'chat.ui.ingredientQuestion3'] },
  { id: 'style', icon: 'flower', label: 'chat.ui.style', caption: 'chat.ui.styleCaption', prompts: ['chat.ui.styleQuestion1', 'chat.ui.styleQuestion2', 'chat.ui.styleQuestion3'] },
];

function RelatedProducts({ refs, question, category }: { refs: ChatProductRef[]; question: string; category?: Category }) {
  const router = useRouter();
  const { t } = useI18n();
  const ids = [...new Set(refs.map((ref) => ref.id))];
  const query = useProductsByIds(ids);
  // keepPreviousData can belong to another ID set; never display it as this response.
  const data = query.isPlaceholderData ? [] : query.data ?? [];
  const byId = new Map(data.map((product) => [product.id, product]));
  const products = ids.flatMap((id) => {
    const product = byId.get(id);
    return product ? [product] : [];
  });
  return (
    <View>
      <Text style={styles.relatedTitle}>{t('chat.relatedProducts')}</Text>
      <ChatProducts
        products={products}
        conditions={extractChatConditions(question)}
        showIngredients={category === 'ingredient'}
        loading={query.isPending || query.isPlaceholderData}
        failed={query.isError}
        missingCount={!query.isPending && !query.isPlaceholderData && !query.isError ? ids.length - products.length : 0}
        onRetry={() => { void query.refetch(); }}
        onOpenProduct={(id) => router.push(productHref(id))}
        onOpenAr={(productId, shadeId) => router.push(arHref({ productId, shadeId }))}
      />
    </View>
  );
}

export default function ChatScreen() {
  const router = useRouter();
  const headerHeight = useHeaderHeight();
  const { t, language } = useI18n();
  const { mutateAsync, isPending } = useChat();
  const scrollRef = useRef<ComponentRef<typeof ScrollView>>(null);
  const inputRef = useRef<ComponentRef<typeof TextInput>>(null);
  const sending = useRef(false);
  const serial = useRef(0);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [category, setCategory] = useState<Category>('product');
  const [editing, setEditing] = useState(false);
  const selected = categories.find((item) => item.id === category)!;
  const conditions = extractChatConditions(input);

  useEffect(() => {
    const shown = Keyboard.addListener('keyboardDidShow', () => setEditing(true));
    const hidden = Keyboard.addListener('keyboardDidHide', () => setEditing(false));
    return () => {
      shown.remove();
      hidden.remove();
    };
  }, []);

  useEffect(() => {
    if (messages.length) scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length]);

  useEffect(() => {
    if (editing && conditions.length) scrollRef.current?.scrollToEnd({ animated: true });
  }, [editing, conditions.length]);

  const send = async (textToSend = input, retryId?: string, retryCategory?: Category) => {
    const text = textToSend.trim();
    if (!text || sending.current || isPending) return;
    sending.current = true;
    const failedMatch = retryId ?? messages.find((message) => message.role === 'user' && message.failed && message.text === text)?.id;
    const messageId = failedMatch ?? `user-${++serial.current}`;
    const requestCategory = retryCategory ?? messages.find((message) => message.id === failedMatch)?.category ?? category;
    if (input.trim() === text) setInput('');
    if (failedMatch) {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, failed: false } : message));
    } else {
      setMessages((current) => [...current, { id: messageId, role: 'user', text, category: requestCategory }]);
    }
    try {
      const response = await mutateAsync({ message: text, locale: language });
      setMessages((current) => [...current, {
        id: `assistant-${++serial.current}`, role: 'assistant', text: response.answer,
        products: response.products, question: text, category: requestCategory,
      }]);
    } catch {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, failed: true } : message));
      setInput((current) => current || text);
    } finally {
      sending.current = false;
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: messages.length ? t('chat.ui.title') : '' }} />
      <KeyboardAvoidingView style={styles.keyboard} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={headerHeight}>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.messages} keyboardShouldPersistTaps="handled">
          {!messages.length ? (
            <View style={styles.welcome}>
              {!editing ? (
                <>
                  <View style={styles.welcomeIcon}><Ionicons name="sparkles" size={25} color={theme.colors.rose} /></View>
                  <Text style={styles.welcomeTitle}>{t('chat.ui.welcomeTitle')}</Text>
                  <Text style={styles.welcomeBody}>{t('chat.ui.welcomeBody')}</Text>
                </>
              ) : null}
              <View style={editing ? styles.categoryChips : styles.categories}>
                {categories.map((item) => (
                  <Pressable key={item.id} accessibilityRole="button" accessibilityLabel={`${t(item.label)}, ${t(item.caption)}`}
                    accessibilityState={{ selected: category === item.id }} onPress={() => setCategory(item.id)}
                    style={[editing ? styles.categoryChip : styles.category, category === item.id && styles.categorySelected]}>
                    {editing ? <Text style={styles.categoryText}>{t(item.label)}</Text> : (
                      <>
                        <View style={[styles.categoryArt, item.id === 'ingredient' ? styles.ingredientArt : item.id === 'style' ? styles.styleArt : styles.productArt]}>
                          <Ionicons name={item.icon} size={34} color={item.id === 'ingredient' ? theme.colors.success : theme.colors.rose} />
                        </View>
                        <View style={styles.categoryCopy}>
                          <Text style={styles.categoryText}>{t(item.label)}</Text>
                          <Text style={styles.categoryCaption}>{t(item.caption)}</Text>
                        </View>
                      </>
                    )}
                  </Pressable>
                ))}
              </View>
              {!editing ? (
                <>
                  <Text style={styles.examplesTitle}>{t('chat.ui.examples')}</Text>
                  {selected.prompts.map((prompt) => (
                    <Pressable key={prompt} accessibilityRole="button" onPress={() => { setInput(t(prompt)); inputRef.current?.focus(); }} style={styles.prompt}>
                      <Text style={styles.promptText}>{t(prompt)}</Text>
                      <Ionicons name="arrow-forward" size={16} color={theme.colors.rose} />
                    </Pressable>
                  ))}
                </>
              ) : null}
            </View>
          ) : (
            <View>
              {!editing ? <Text style={styles.contextNotice}>{t('chat.ui.contextNotice')}</Text> : null}
              <View style={styles.categoryChips}>
                {categories.map((item) => (
                  <Pressable key={item.id} accessibilityRole="button" accessibilityState={{ selected: category === item.id }}
                    onPress={() => setCategory(item.id)} style={[styles.categoryChip, category === item.id && styles.categorySelected]}>
                    <Text style={styles.categoryText}>{t(item.label)}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          )}
          {messages.map((message) => (
            <View key={message.id} style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}>
              {message.role === 'assistant' ? (
                <View style={styles.answerHeader}>
                  <View style={styles.answerIcon}><Ionicons name="sparkles" size={14} color={theme.colors.rose} /></View>
                  <Text style={styles.answerTitle}>{t(message.category === 'ingredient' ? 'chat.ui.ingredient' : message.category === 'style' ? 'chat.ui.style' : 'chat.ui.title')}</Text>
                </View>
              ) : null}
              {message.role === 'assistant' && message.category === 'style' ? (
                <View style={styles.styleGuide}>
                  <Ionicons name="flower-outline" size={28} color={theme.colors.rose} />
                  <Text style={styles.messageText}>{message.text}</Text>
                </View>
              ) : <Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.text}</Text>}
              {message.role === 'assistant' && message.category === 'ingredient' ? (
                <Text style={styles.ingredientNotice}>{t('chat.ui.ingredientGeneralNotice')}</Text>
              ) : null}
              {message.failed ? (
                <View style={styles.failure}>
                  <Text style={styles.failureText} accessibilityRole="alert">{t('chat.ui.error')}</Text>
                  <Pressable accessibilityRole="button" disabled={isPending} onPress={() => void send(message.text, message.id, message.category)} style={styles.retry}>
                    <Text style={styles.retryText}>{t('chat.ui.retry')}</Text>
                  </Pressable>
                </View>
              ) : null}
              {message.role === 'assistant' && message.products?.length ? <RelatedProducts refs={message.products} question={message.question ?? ''} category={message.category} /> : null}
              {message.role === 'assistant' && !message.products?.length && message.category === 'product' ? (
                <View style={styles.emptyState}>
                  <Ionicons name="search-outline" size={18} color={theme.colors.inkMuted} />
                  <Text style={styles.emptyText}>{t('chat.ui.noProducts')}</Text>
                </View>
              ) : null}
              {message.role === 'assistant' && message.category === 'style' ? (
                <Pressable accessibilityRole="button" onPress={() => router.push('/celeb')} style={styles.styleLink}>
                  <Text style={styles.linkText}>{t('chat.ui.styleBrowse')} ›</Text>
                </Pressable>
              ) : null}
            </View>
          ))}
          {conditions.length ? (
            <View style={styles.conditionArea}>
              <Text style={styles.conditionTitle}>{t('chat.ui.conditions')}</Text>
              {[true, false].map((required) => {
                const group = conditions.filter((condition) => condition.required === required);
                return group.length ? (
                  <View key={String(required)} style={styles.conditionGroup}>
                    <Text style={styles.conditionLabel}>{t(required ? 'chat.ui.required' : 'chat.ui.preferred')}</Text>
                    <View style={styles.conditionList}>
                      {group.map((condition, index) => <Text key={`${condition.kind}-${index}`} style={styles.condition}>{condition.text}</Text>)}
                    </View>
                  </View>
                ) : null;
              })}
            </View>
          ) : null}
          {isPending ? (
            <View style={[styles.message, styles.assistantMessage, styles.loading]} accessibilityRole="progressbar" accessibilityLabel={t('chat.ui.loading')}>
              <ActivityIndicator color={theme.colors.rose} size="small" />
              <Text style={styles.note}>{t('chat.ui.loading')}</Text>
            </View>
          ) : null}
        </ScrollView>
        <View style={styles.composer}>
          <View style={styles.inputRow}>
            <TextInput ref={inputRef} accessibilityLabel={t('chat.ui.placeholder')} editable={!isPending} maxLength={1000}
              multiline onChangeText={setInput} onFocus={() => setEditing(true)} onBlur={() => setEditing(false)}
              placeholder={t('chat.ui.placeholder')} placeholderTextColor={theme.colors.inkFaint}
              style={[styles.input, editing && styles.inputEditing]} value={input} />
            <Pressable accessibilityRole="button" accessibilityLabel={t('chat.ui.send')}
              accessibilityState={{ disabled: !input.trim() || isPending, busy: isPending }} disabled={!input.trim() || isPending}
              onPress={() => void send()} style={[styles.send, (!input.trim() || isPending) && styles.sendDisabled]}>
              <Ionicons name="arrow-up" size={20} color={theme.colors.white} />
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  keyboard: { flex: 1 },
  messages: { flexGrow: 1, gap: 12, padding: 16, paddingBottom: 20 },
  welcome: { gap: 10, paddingTop: 12 },
  welcomeIcon: { alignSelf: 'center', alignItems: 'center', justifyContent: 'center', width: 48, height: 48, borderRadius: 24, backgroundColor: theme.colors.roseSoft },
  welcomeTitle: { color: theme.colors.ink, fontSize: theme.font.title, fontWeight: '800', marginTop: 6, textAlign: 'center' },
  welcomeBody: { color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 20, textAlign: 'center' },
  categories: { flexDirection: 'row', gap: 8, marginTop: 14 },
  category: { flex: 1, minHeight: 130, overflow: 'hidden', borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card, borderRadius: theme.radius.md },
  categorySelected: { borderColor: theme.colors.rose },
  categoryArt: { minHeight: 70, alignItems: 'center', justifyContent: 'center' },
  productArt: { backgroundColor: theme.colors.roseSoft },
  ingredientArt: { backgroundColor: '#EAF4EE' },
  styleArt: { backgroundColor: theme.colors.surfaceAlt },
  categoryCopy: { paddingHorizontal: 8, paddingVertical: 8, gap: 3 },
  categoryText: { color: theme.colors.ink, fontSize: theme.font.caption, fontWeight: '700' },
  categoryCaption: { color: theme.colors.inkMuted, fontSize: 10, lineHeight: 14 },
  examplesTitle: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', marginTop: 10 },
  prompt: { minHeight: 44, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, backgroundColor: theme.colors.card, paddingHorizontal: 12, paddingVertical: 8, flexDirection: 'row', alignItems: 'center', gap: 8 },
  promptText: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small, lineHeight: 19 },
  categoryChips: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6, marginTop: 8 },
  categoryChip: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 10, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.pill },
  contextNotice: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 17, textAlign: 'center' },
  message: { borderRadius: theme.radius.md, maxWidth: '94%', paddingHorizontal: 14, paddingVertical: 12 },
  userMessage: { alignSelf: 'flex-end', backgroundColor: theme.colors.roseSoft },
  assistantMessage: { alignSelf: 'flex-start', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1 },
  messageText: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 22 },
  userMessageText: { color: theme.colors.ink },
  answerHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  answerIcon: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  styleGuide: { gap: 10, padding: 12, backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md },
  ingredientNotice: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18, backgroundColor: theme.colors.cream, borderRadius: theme.radius.sm, padding: 10, marginTop: 10 },
  relatedTitle: { color: theme.colors.inkMuted, fontSize: theme.font.caption, fontWeight: '700', marginTop: 14 },
  note: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18, marginTop: 8 },
  styleLink: { minHeight: 44, justifyContent: 'center', alignItems: 'center', marginTop: 12, paddingHorizontal: 12, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.pill },
  linkText: { color: theme.colors.rose, fontWeight: '700', fontSize: theme.font.small },
  loading: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8 },
  emptyState: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: theme.colors.cream, padding: 10, borderRadius: theme.radius.sm, marginTop: 10 },
  emptyText: { flex: 1, color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18 },
  failure: { marginTop: 8, borderTopWidth: 1, borderColor: theme.colors.border },
  failureText: { color: theme.colors.danger, fontSize: theme.font.caption, marginTop: 8 },
  retry: { minHeight: 44, justifyContent: 'center' },
  retryText: { color: theme.colors.roseDark, fontWeight: '700', textDecorationLine: 'underline' },
  composer: { backgroundColor: theme.colors.surface, paddingHorizontal: 12, paddingVertical: 8 },
  conditionArea: { gap: 10, backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, padding: 12 },
  conditionTitle: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700' },
  conditionGroup: { gap: 5 },
  conditionLabel: { color: theme.colors.inkMuted, fontSize: theme.font.caption, fontWeight: '700' },
  conditionList: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  condition: { overflow: 'hidden', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.sm, color: theme.colors.roseDark, fontSize: theme.font.caption, paddingHorizontal: 8, paddingVertical: 4 },
  inputRow: { alignItems: 'flex-end', flexDirection: 'row', gap: 8, backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg, padding: 4 },
  input: { color: theme.colors.ink, flex: 1, fontSize: theme.font.body, lineHeight: 20, maxHeight: 120, minHeight: 44, paddingHorizontal: 8, paddingTop: 11 },
  inputEditing: { minHeight: 68 },
  send: { alignItems: 'center', backgroundColor: theme.colors.rose, borderRadius: 22, height: 44, justifyContent: 'center', width: 44 },
  sendDisabled: { opacity: 0.4 },
});
