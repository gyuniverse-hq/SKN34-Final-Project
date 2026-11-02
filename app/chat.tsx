import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { Stack, useRouter } from 'expo-router';
import { useHeaderHeight } from 'expo-router/react-navigation';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator, Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import { theme } from '@/constants/theme';
import { useChat } from '@/hooks/useChat';
import { conditionsFromChatFilters, extractChatConditions } from '@/lib/chatConditions';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProductsByIds } from '@/lib/queries';
import { arHref, productHref } from '@/lib/routes';
import type { BeautyChatContext, ChatProductEvidence, ChatProductRef, ChatResponse } from '@/types';

type Category = 'product' | 'ingredient' | 'style';
type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  products?: ChatProductRef[];
  question?: string;
  category?: Category;
  failed?: boolean;
  chatContext?: BeautyChatContext;
  evidence?: ChatProductEvidence[];
  resultType?: ChatResponse['resultType'];
};

const styleBrowseImage = require('@/assets/images/chat/style-recipe.png');

const categories: { id: Category; image: number; label: TranslationKey; caption: TranslationKey; prompts: TranslationKey[] }[] = [
  { id: 'product', image: require('@/assets/images/chat/product-recommendation.png'), label: 'chat.ui.product', caption: 'chat.ui.productCaption', prompts: ['chat.ui.productQuestion1', 'chat.ui.productQuestion2', 'chat.ui.productQuestion3'] },
  { id: 'ingredient', image: require('@/assets/images/chat/ingredient-consultation.png'), label: 'chat.ui.ingredient', caption: 'chat.ui.ingredientCaption', prompts: ['chat.ui.ingredientQuestion1', 'chat.ui.ingredientQuestion2', 'chat.ui.ingredientQuestion3'] },
  { id: 'style', image: styleBrowseImage, label: 'chat.ui.style', caption: 'chat.ui.styleCaption', prompts: ['chat.ui.styleQuestion1', 'chat.ui.styleQuestion2', 'chat.ui.styleQuestion3'] },
];

function RelatedProducts({ refs, question, category, chatContext, evidence }: {
  refs: ChatProductRef[]; question: string; category?: Category;
  chatContext?: BeautyChatContext; evidence?: ChatProductEvidence[];
}) {
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
        conditions={chatContext ? conditionsFromChatFilters(chatContext.filters, t) : extractChatConditions(question)}
        candidateOrder={chatContext?.candidateIds}
        evidence={evidence}
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
  const nearBottom = useRef(true);
  const serial = useRef(0);
  const beautyContext = useRef<BeautyChatContext | undefined>(undefined);
  const beautyContextTurn = useRef(0);
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
    if (messages.length && nearBottom.current) scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length]);

  const send = async (textToSend = input, retryId?: string, retryCategory?: Category) => {
    const text = textToSend.trim();
    if (!text || sending.current || isPending) return;
    sending.current = true;
    const failedMatch = retryId ?? messages.find((message) => message.role === 'user' && message.failed && message.text === text)?.id;
    const messageId = failedMatch ?? `user-${++serial.current}`;
    const requestCategory = retryCategory ?? messages.find((message) => message.id === failedMatch)?.category ?? category;
    // A retry must use the original question's context, not a later candidate list.
    const requestContext = failedMatch
      ? messages.find((message) => message.id === failedMatch)?.chatContext
      : beautyContext.current;
    if (input.trim() === text) setInput('');
    if (failedMatch) {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, failed: false } : message));
    } else {
      nearBottom.current = true;
      setMessages((current) => [...current, { id: messageId, role: 'user', text,
        category: requestCategory, chatContext: requestContext }]);
    }
    try {
      const response = await mutateAsync({ message: text, locale: language, category: requestCategory,
        ...(requestContext ? { chatContext: requestContext } : {}) });
      const requestTurn = Number(messageId.slice('user-'.length));
      if (response.chatContext && requestTurn >= beautyContextTurn.current) {
        beautyContext.current = response.chatContext;
        beautyContextTurn.current = requestTurn;
      }
      const answer: ChatMessage = {
        id: `assistant-${++serial.current}`, role: 'assistant', text: response.answer,
        products: response.products, question: text, category: requestCategory,
        chatContext: response.chatContext, evidence: response.evidence, resultType: response.resultType,
      };
      setMessages((current) => {
        const questionIndex = current.findIndex((message) => message.id === messageId);
        return questionIndex < 0 ? current : [
          ...current.slice(0, questionIndex + 1), answer, ...current.slice(questionIndex + 1),
        ];
      });
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
        <ScrollView ref={scrollRef} contentContainerStyle={styles.messages} keyboardShouldPersistTaps="handled"
          onScroll={({ nativeEvent }) => {
            const { contentOffset, contentSize, layoutMeasurement } = nativeEvent;
            nearBottom.current = contentSize.height - (contentOffset.y + layoutMeasurement.height) < 80;
          }} scrollEventThrottle={16}>
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
                        <Image source={item.image} style={styles.categoryArt} contentFit="cover" accessible={false} />
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
            <View key={message.id} style={styles.messageGroup}>
              {message.role === 'assistant' && message.category === 'ingredient' ? (
                <IngredientResult
                  heading={t('chat.ui.ingredient')}
                  summary={message.text}
                  notice={t('chat.ui.ingredientGeneralNotice')}
                  labels={{ product: t('chat.result.productInfo'), ingredients: t('chat.result.ingredientList'), source: t('chat.result.source'), unknown: t('chat.conditionUnknown') }}
                />
              ) : message.role === 'assistant' && message.category === 'style' ? (
                <StyleRecipeResult
                  heading={t('chat.ui.style')}
                  summary={message.text}
                  browseImage={styleBrowseImage}
                  browseLabel={t('chat.ui.styleBrowse')}
                  stepsLabel={t('chat.result.steps')}
                  stepNavigation={{
                    previous: t('chat.result.previousStep'),
                    next: t('chat.result.nextStep'),
                    position: (current, total) => t('chat.result.stepPosition', { current, total }),
                  }}
                  onBrowse={() => router.push('/style-browse')}
                />
              ) : <View style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}>
                {message.role === 'assistant' ? (
                  <View style={styles.answerHeader}>
                    <View style={styles.answerIcon}><Ionicons name="sparkles" size={14} color={theme.colors.rose} /></View>
                    <Text style={styles.answerTitle}>{t('chat.ui.title')}</Text>
                  </View>
                ) : null}
                <Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.text}</Text>
              </View>}
              {message.failed ? (
                <View style={styles.failure}>
                  <View style={styles.stateIcon}><Ionicons name="alert-circle-outline" size={22} color={theme.colors.danger} /></View>
                  <Text style={styles.failureText} accessibilityRole="alert">{t('chat.ui.error')}</Text>
                  <Pressable accessibilityRole="button" accessibilityState={{ disabled: isPending }} disabled={isPending}
                    onPress={() => void send(message.text, message.id, message.category)} style={[styles.retry, isPending && styles.retryDisabled]}>
                    <Text style={styles.retryText}>{t('chat.ui.retry')}</Text>
                  </Pressable>
                </View>
              ) : null}
              {message.role === 'assistant' && message.products?.length ? <RelatedProducts refs={message.products}
                question={message.question ?? ''} category={message.category}
                chatContext={message.chatContext} evidence={message.evidence} /> : null}
              {message.role === 'assistant' && !message.products?.length && message.category === 'product' &&
                (message.resultType === 'empty' || (!message.resultType && extractChatConditions(message.question ?? '').length)) ? (
                <View style={styles.emptyState}>
                  <View style={styles.stateIcon}><Ionicons name="search-outline" size={22} color={theme.colors.rose} /></View>
                  <Text style={styles.emptyText}>{t('chat.ui.noProducts')}</Text>
                  {!input.trim() || input === message.question ? (
                    <Pressable accessibilityRole="button" onPress={() => { setInput(message.question ?? ''); inputRef.current?.focus(); }} style={styles.editQuestion}>
                      <Text style={styles.linkText}>{t('chat.ui.editQuestion')}</Text>
                    </Pressable>
                  ) : null}
                </View>
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
  category: { flex: 1, minHeight: 140, overflow: 'hidden', borderWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card, borderRadius: theme.radius.md },
  categorySelected: { borderColor: theme.colors.rose },
  categoryArt: { width: '100%', height: 80 },
  categoryCopy: { paddingHorizontal: 8, paddingVertical: 8, gap: 3 },
  categoryText: { color: theme.colors.ink, fontSize: theme.font.caption, fontWeight: '700' },
  categoryCaption: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 17 },
  examplesTitle: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', marginTop: 10 },
  prompt: { minHeight: 44, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.md, backgroundColor: theme.colors.card, paddingHorizontal: 12, paddingVertical: 8, flexDirection: 'row', alignItems: 'center', gap: 8 },
  promptText: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small, lineHeight: 19 },
  categoryChips: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6, marginTop: 8 },
  categoryChip: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 10, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.pill },
  contextNotice: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 17, textAlign: 'center' },
  messageGroup: { alignSelf: 'stretch', gap: 10 },
  message: { borderRadius: theme.radius.md, maxWidth: '94%', paddingHorizontal: 14, paddingVertical: 12 },
  userMessage: { alignSelf: 'flex-end', backgroundColor: theme.colors.roseSoft },
  assistantMessage: { alignSelf: 'flex-start', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, paddingVertical: 14 },
  messageText: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 22 },
  userMessageText: { color: theme.colors.ink },
  answerHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  answerIcon: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  relatedTitle: { color: theme.colors.inkMuted, fontSize: theme.font.caption, fontWeight: '700', marginBottom: 4 },
  note: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18, marginTop: 8 },
  linkText: { color: theme.colors.rose, fontWeight: '700', fontSize: theme.font.small },
  loading: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8 },
  emptyState: { alignItems: 'center', gap: 10, backgroundColor: theme.colors.cream, padding: 16, borderRadius: theme.radius.md },
  stateIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  emptyText: { color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 20, textAlign: 'center' },
  editQuestion: { minHeight: 44, justifyContent: 'center', alignItems: 'center', borderWidth: 1, borderColor: theme.colors.rose, borderRadius: theme.radius.pill, paddingHorizontal: 16 },
  failure: { alignItems: 'center', gap: 10, padding: 16, backgroundColor: theme.colors.warningBg, borderRadius: theme.radius.md },
  failureText: { color: theme.colors.danger, fontSize: theme.font.small, lineHeight: 20, textAlign: 'center' },
  retry: { minHeight: 44, justifyContent: 'center', alignItems: 'center', borderRadius: theme.radius.pill, backgroundColor: theme.colors.rose, paddingHorizontal: 20 },
  retryDisabled: { opacity: 0.4 },
  retryText: { color: theme.colors.white, fontWeight: '700', fontSize: theme.font.small },
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
