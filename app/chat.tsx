import Ionicons from '@expo/vector-icons/Ionicons';
import { uuid } from 'expo';
import { Image } from 'expo-image';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useHeaderHeight } from 'expo-router/react-navigation';
import { useEffect, useRef, useState, type ComponentRef, type Dispatch, type SetStateAction, type MutableRefObject } from 'react';
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
import { ApiError } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { getSupabase } from '@/lib/auth/client';
import { conditionsFromChatFilters, extractChatConditions } from '@/lib/chatConditions';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useProductsByIds } from '@/lib/queries';
import { arHref, parseId, paramValue, productHref } from '@/lib/routes';
import type { BeautyChatContext, ChatProductEvidence, ChatProductRef, ChatResponse, ChatScreenContext, ChatStyleContext } from '@/types';

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
  ingredientResults?: ChatResponse['ingredientResults'];
  screenContext?: ChatScreenContext;
  locale?: 'ko' | 'en' | 'ja' | 'zh';
  errorKey?: TranslationKey;
  selectionRevision?: number;
  generation?: number;
  ownerKey?: string;
  sessionStatus?: ChatResponse['sessionStatus'];
  retryable?: boolean;
  styleRecipe?: ChatResponse['styleRecipe'];
};

type Submission = Parameters<ReturnType<typeof useChat>['mutateAsync']>[0];
type RequestSnapshot = { args: Submission; revision: number; generation: number; styleRevision: number };

function displayContext(context?: BeautyChatContext): BeautyChatContext | undefined {
  return context ? { ...context, session: undefined } : undefined;
}

const styleBrowseImage = require('@/assets/images/chat/style-recipe.png');

const categories: { id: Category; image: number; label: TranslationKey; caption: TranslationKey; prompts: TranslationKey[] }[] = [
  { id: 'product', image: require('@/assets/images/chat/product-recommendation.png'), label: 'chat.ui.product', caption: 'chat.ui.productCaption', prompts: ['chat.ui.productQuestion1', 'chat.ui.productQuestion2', 'chat.ui.productQuestion3'] },
  { id: 'ingredient', image: require('@/assets/images/chat/ingredient-consultation.png'), label: 'chat.ui.ingredient', caption: 'chat.ui.ingredientCaption', prompts: ['chat.ui.ingredientQuestion1', 'chat.ui.ingredientQuestion2', 'chat.ui.ingredientQuestion3'] },
  { id: 'style', image: styleBrowseImage, label: 'chat.ui.style', caption: 'chat.ui.styleCaption', prompts: ['chat.ui.styleQuestion1', 'chat.ui.styleQuestion2', 'chat.ui.styleQuestion3'] },
];

function RelatedProducts({ refs, question, category, chatContext, evidence, selectedShades, onSelectShade, onSelectProduct, selectedProductId }: {
  refs: ChatProductRef[]; question: string; category?: Category;
  chatContext?: BeautyChatContext; evidence?: ChatProductEvidence[];
  selectedShades: Record<string, string>;
  onSelectShade: (productId: string, shadeId: string) => void;
  onSelectProduct?: (productId: string) => void;
  selectedProductId?: string | null;
}) {
  const router = useRouter();
  const { t } = useI18n();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
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
        expectedIds={ids}
        conditions={chatContext ? conditionsFromChatFilters(chatContext.filters, t) : extractChatConditions(question)}
        candidateOrder={chatContext?.candidateIds ?? ids}
        selectedShades={selectedShades}
        selectedProductId={selectedProductId}
        onSelectProduct={onSelectProduct ? (productId) => {
          // Old message cards may remain visible; only the live server candidate set is selectable.
          if (mounted.current && products.some((p) => p.id === productId)) onSelectProduct(productId);
        } : undefined}
        onSelectShade={(productId, shadeId) => {
          // A callback from an old/placeholder card cannot attach another product's shade.
          if (mounted.current && products.some((p) => p.id === productId && p.shades?.some((s) => s.id === shadeId))) {
            onSelectShade(productId, shadeId);
          }
        }}
        evidence={evidence}
        showIngredients={category === 'ingredient'}
        loading={query.isPending || query.isPlaceholderData}
        failed={query.isError}
        missingCount={!query.isPending && !query.isPlaceholderData && !query.isError ? ids.length - products.length : 0}
        onRetry={() => { if (mounted.current) void query.refetch(); }}
        onOpenProduct={(id, shadeId) => { if (mounted.current) router.push(productHref(id, shadeId)); }}
        onOpenAr={(productId, shadeId) => { if (mounted.current) router.push(arHref({ productId, shadeId })); }}
      />
    </View>
  );
}

export default function ChatScreen() {
  const params = useLocalSearchParams<{ recipeKind?: string; recipeLookId?: string }>();
  const rawKind = paramValue(params.recipeKind);
  const kind = rawKind === 'video' || rawKind === 'catalog' ? rawKind : undefined;
  const rawLookId = paramValue(params.recipeLookId);
  const lookId = kind === 'video' ? rawLookId && /^[A-Za-z0-9_-]{1,64}$/.test(rawLookId) ? rawLookId : undefined : parseId(params.recipeLookId);
  const initialStyle: ChatStyleContext | undefined = kind && lookId ? { kind, lookId, currentStep: 0 } : undefined;
  const { user, ready } = useAuth();
  const [identityGeneration, setIdentityGeneration] = useState(0);
  useEffect(() => {
    const client = getSupabase();
    let previous: string | null | undefined;
    const subscription = client?.auth.onAuthStateChange((_event, session) => {
      const id = session?.user.id ?? null;
      if (previous !== undefined && previous !== id) setIdentityGeneration((value) => value + 1);
      previous = id;
    }).data.subscription;
    return () => subscription?.unsubscribe();
  }, []);
  const ownerKey = `${ready ? user?.id ?? 'guest' : 'loading'}:${identityGeneration}`;
  return <ChatOwner key={ownerKey} ownerKey={ownerKey} userId={user?.id ?? null} initialStyle={initialStyle}
    styleKey={`${kind ?? ''}:${lookId ?? ''}`} ready={ready} />;
}

function ChatOwner({ ownerKey, userId, ready, initialStyle, styleKey }: {
  ownerKey: string; userId: string | null; ready: boolean; initialStyle?: ChatStyleContext; styleKey: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const serialRef = useRef(0);
  return <ChatConversation key={styleKey} ownerKey={ownerKey} userId={userId} initialStyle={initialStyle}
    ready={ready} messages={messages} setMessages={setMessages} serialRef={serialRef} />;
}

function ChatConversation({ ownerKey, userId, ready, messages, setMessages, serialRef, initialStyle }: {
  ownerKey: string; userId: string | null; ready: boolean; messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>; serialRef: MutableRefObject<number>;
  initialStyle?: ChatStyleContext;
}) {
  const router = useRouter();
  const headerHeight = useHeaderHeight();
  const styleContext = useRef<ChatStyleContext | undefined>(initialStyle);
  const [activeStyle, setActiveStyle] = useState<ChatStyleContext | undefined>(initialStyle);
  const styleRevision = useRef(0);
  const { t, language } = useI18n();
  const { mutateAsync, reset: resetMutation } = useChat();
  const [pendingRequestId, setPendingRequestId] = useState<string>();
  const isPending = !!pendingRequestId;
  const [sessionNotice, setSessionNotice] = useState<TranslationKey | undefined>(
    messages.length ? 'chat.session.identityChanged' : undefined
  );
  const mounted = useRef(true);
  const generation = useRef(0);
  const [conversationGeneration, setConversationGeneration] = useState(0);
  const activeRequest = useRef<string | undefined>(undefined);
  const snapshots = useRef(new Map<string, RequestSnapshot>());
  const scrollRef = useRef<ComponentRef<typeof ScrollView>>(null);
  const inputRef = useRef<ComponentRef<typeof TextInput>>(null);
  const sending = useRef(false);
  const nearBottom = useRef(true);
  const beautyContext = useRef<BeautyChatContext | undefined>(undefined);
  const beautyContextTurn = useRef(0);
  const selection = useRef({ revision: 0, shades: {} as Record<string, string>,
    changed: {} as Record<string, number>, screen: undefined as ChatScreenContext | undefined });
  const [selectedShades, setSelectedShades] = useState<Record<string, string>>({});
  const [chosenProductId, setChosenProductId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [category, setCategory] = useState<Category>(initialStyle ? 'style' : 'product');
  const [editing, setEditing] = useState(false);
  const selected = categories.find((item) => item.id === category)!;
  const conditions = extractChatConditions(input);

  useEffect(() => {
    mounted.current = true;
    const requests = snapshots.current;
    return () => { mounted.current = false; requests.clear(); };
  }, []);

  const resetSession = (notice: TranslationKey, keepSelection = false) => {
    generation.current += 1;
    setConversationGeneration(generation.current);
    beautyContext.current = undefined;
    beautyContextTurn.current = 0;
    snapshots.current.clear();
    resetMutation?.();
    setMessages((current) => current.map((message) => ({ ...message, retryable: false })));
    if (!keepSelection) {
      selection.current = { revision: selection.current.revision + 1, shades: {}, changed: {}, screen: undefined };
      setSelectedShades({});
      setChosenProductId(null);
    }
    activeRequest.current = undefined;
    sending.current = false;
    setPendingRequestId(undefined);
    setSessionNotice(notice);
  };

  const newSearch = () => {
    resetSession('chat.session.newSearchHint');
    styleContext.current = undefined;
    setActiveStyle(undefined);
    styleRevision.current += 1;
    setCategory('product');
    setInput('');
    inputRef.current?.focus();
  };

  const selectProduct = (productId: string, message: ChatMessage) => {
    if (message.ownerKey !== ownerKey || message.generation !== generation.current) return;
    const current = beautyContext.current;
    if (!current?.session || !current.candidateIds.includes(productId)) return;
    selection.current.revision += 1;
    const shadeId = selection.current.shades[productId];
    selection.current.screen = { screenId: 'chat', productId, ...(shadeId ? { shadeId } : {}) };
    beautyContext.current = { ...current, selectedProductId: productId };
    setChosenProductId(productId);
  };

  const selectShade = (productId: string, shadeId: string, message: ChatMessage) => {
    const current = selection.current;
    current.revision += 1;
    current.shades = { ...current.shades, [productId]: shadeId };
    current.changed[productId] = current.revision;
    current.screen = { screenId: 'chat', productId, shadeId };
    const source = beautyContext.current ?? (message.ownerKey === ownerKey &&
      message.generation === generation.current ? message.chatContext : undefined);
    // Keep the latest candidate numbering; screenContext can identify an older selected card.
    if (source?.candidateIds.includes(productId)) {
      beautyContext.current = { ...source, selectedProductId: productId,
        shadeSelections: { ...source.shadeSelections, [productId]: shadeId } };
    } else if (!beautyContext.current) beautyContext.current = source;
    setSelectedShades(current.shades);
    if (source?.candidateIds.includes(productId)) setChosenProductId(productId);
  };

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
    if (!text || sending.current || isPending || !ready) return;
    const failedMatch = retryId ?? messages.find((message) => message.role === 'user' &&
      message.failed && message.text === text && snapshots.current.has(message.id))?.id;
    const original = failedMatch ? snapshots.current.get(failedMatch) : undefined;
    if (retryId && !original) return;
    let requestId: string;
    try { requestId = original?.args.requestId ?? uuid.v4(); }
    catch { setSessionNotice('chat.session.idUnavailable'); return; }
    const messageId = failedMatch ?? `user-${++serialRef.current}`;
    const requestCategory = original?.args.category ?? retryCategory ?? category;
    const context = beautyContext.current;
    const snapshot: RequestSnapshot = original ?? {
      styleRevision: styleRevision.current,
      generation: generation.current,
      revision: selection.current.revision,
      args: {
        message: text, locale: language, category: requestCategory, requestId, expectedUserId: userId,
        ...(requestCategory === 'style' && styleContext.current ? { styleContext: { ...styleContext.current } } : {}),
        ...(context ? { chatContext: { ...context, filters: { ...context.filters },
          candidateIds: [...context.candidateIds], scopeIds: [...context.scopeIds],
          ...(context.session ? { session: { ...context.session } } : {}),
          ...(context.shadeSelections ? { shadeSelections: { ...context.shadeSelections } } : {}) } } : {}),
        ...(selection.current.screen ? { screenContext: { ...selection.current.screen } } : {}),
      },
    };
    if (snapshot.generation !== generation.current) return;
    snapshots.current.set(messageId, snapshot);
    sending.current = true;
    activeRequest.current = requestId;
    setPendingRequestId(requestId);
    if (input.trim() === text) setInput('');
    if (failedMatch) {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, failed: false } : message));
    } else {
      nearBottom.current = true;
      setMessages((current) => [...current, { id: messageId, role: 'user', text,
        category: requestCategory, ownerKey, generation: snapshot.generation }]);
    }
    try {
      const response = await mutateAsync(snapshot.args);
      if (!mounted.current || generation.current !== snapshot.generation) return;
      if (requestCategory === 'style' && styleRevision.current === snapshot.styleRevision) {
        const expected = snapshot.args.styleContext;
        const next = response.styleContext;
        if (next && expected && next.kind === expected.kind && next.lookId === expected.lookId) {
          styleContext.current = { ...next };
          setActiveStyle({ ...next });
        }
      }
      const requestTurn = Number(messageId.slice('user-'.length));
      if (response.sessionStatus === 'unavailable' && requestTurn >= beautyContextTurn.current) {
        resetSession('chat.session.unavailable', selection.current.revision > snapshot.revision);
      } else if (response.chatContext && requestTurn >= beautyContextTurn.current) {
        const next = response.chatContext;
        const current = beautyContext.current?.session;
        const olderVersion = current && next.session?.sessionId === current.sessionId &&
          next.session.stateVersion < current.stateVersion;
        if (!olderVersion) {
          const shades = { ...next.shadeSelections };
          for (const pid of next.candidateIds) {
            if ((selection.current.changed[pid] ?? 0) > snapshot.revision) shades[pid] = selection.current.shades[pid];
          }
          const latestProduct = selection.current.screen?.productId;
          beautyContext.current = { ...next,
            ...(Object.keys(shades).length ? { shadeSelections: shades } : {}),
            ...(selection.current.revision > snapshot.revision && latestProduct && next.candidateIds.includes(latestProduct)
              ? { selectedProductId: latestProduct } : {}) };
          const nextShades = { ...selection.current.shades };
          for (const pid of next.candidateIds) {
            if (shades[pid]) nextShades[pid] = shades[pid]; else delete nextShades[pid];
          }
          selection.current.shades = nextShades;
          if (selection.current.revision === snapshot.revision && selection.current.screen &&
            (!next.candidateIds.includes(selection.current.screen.productId ?? '') ||
             shades[selection.current.screen.productId ?? ''] !== selection.current.screen.shadeId)) {
            selection.current.screen = undefined;
          }
          setSelectedShades(nextShades);
          setChosenProductId(beautyContext.current.selectedProductId ?? null);
          beautyContextTurn.current = requestTurn;
          setSessionNotice(undefined);
        }
      }
      snapshots.current.delete(messageId);
      const answer: ChatMessage = {
        id: `assistant-${++serialRef.current}`, role: 'assistant', text: response.answer,
        products: response.products, question: text, category: requestCategory,
        ownerKey, generation: snapshot.generation, sessionStatus: response.sessionStatus,
        chatContext: displayContext(response.chatContext), evidence: response.evidence,
        resultType: response.resultType, ingredientResults: response.ingredientResults,
        styleRecipe: response.styleRecipe,
      };
      setMessages((current) => {
        const questionIndex = current.findIndex((message) => message.id === messageId);
        return questionIndex < 0 ? current : [
          ...current.slice(0, questionIndex + 1), answer, ...current.slice(questionIndex + 1),
        ];
      });
    } catch (error) {
      if (!mounted.current || generation.current !== snapshot.generation) return;
      const api = error instanceof ApiError ? error : undefined;
      const fatal = api && ([403, 409, 410].includes(api.status) ||
        ['chat_owner_changed', 'chat_owner_unavailable'].includes(api.code ?? ''));
      const errorKey: TranslationKey = api?.code === 'chat_owner_changed'
        ? 'chat.session.identityChanged'
        : api?.code === 'chat_owner_unavailable' ? 'chat.session.identityUnavailable'
        : api?.status === 403 ? 'chat.session.forbidden'
          : api?.status === 409 ? 'chat.session.conflict'
            : api?.status === 410 ? 'chat.session.expired'
              : api?.status === 503 && api.code?.startsWith('chat_session_') ? 'chat.session.storageError'
                : api?.code === 'shade_not_found' ? 'chat.ingredient.shadeMissing'
                  : api?.status === 404 ? 'chat.ingredient.productMissing'
                    : api?.status === 503 ? 'chat.ingredient.server'
                      : api?.status === 0 ? 'chat.ingredient.network' : 'chat.ui.error';
      if (fatal) {
        const oldTurn = Number(messageId.slice('user-'.length)) < beautyContextTurn.current;
        if (oldTurn && beautyContext.current?.session && !api?.code?.startsWith('chat_owner_')) {
          snapshots.current.clear();
          setMessages((current) => current.map((message) => ({ ...message, retryable: false })));
          setSessionNotice(errorKey);
        } else resetSession(errorKey);
      }
      setMessages((current) => current.map((message) => message.id === messageId
        ? { ...message, failed: true, errorKey, retryable: !fatal } : message));
      setInput((current) => current || text);
    } finally {
      if (mounted.current && activeRequest.current === requestId) {
        sending.current = false;
        activeRequest.current = undefined;
        setPendingRequestId(undefined);
      }
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
          {sessionNotice ? <View style={styles.failure}>
            <Text accessibilityRole="alert" style={styles.failureText}>{t(sessionNotice)}</Text>
            <Pressable accessibilityRole="button" onPress={newSearch} style={styles.retry}>
              <Text style={styles.retryText}>{t('chat.session.newSearch')}</Text>
            </Pressable>
          </View> : null}
          {messages.map((message) => (
            <View key={message.id} style={styles.messageGroup}>
              {message.role === 'assistant' && (message.category === 'ingredient' || message.ingredientResults?.length) ? (
                <IngredientResult
                  heading={t('chat.ui.ingredient')}
                  summary={message.text}
                  notice={t('chat.ui.ingredientGeneralNotice')}
                  labels={{ product: t('chat.result.productInfo'), ingredients: t('chat.result.ingredientList'), source: t('chat.result.source'), unknown: t('chat.conditionUnknown') }}
                  results={message.ingredientResults}
                  products={message.products}
                  shadeSelections={message.chatContext?.shadeSelections}
                />
              ) : message.role === 'assistant' && message.category === 'style' ? (
                <StyleRecipeResult
                  result={message.styleRecipe && message.styleRecipe.recipeId === activeStyle?.recipeId &&
                    message.styleRecipe.recipeVersion === activeStyle?.recipeVersion
                    ? { ...message.styleRecipe, currentStep: activeStyle.currentStep } : message.styleRecipe}
                  disabled={isPending || message.ownerKey !== ownerKey || message.generation !== conversationGeneration ||
                    message.styleRecipe?.recipeId !== activeStyle?.recipeId || message.styleRecipe?.recipeVersion !== activeStyle?.recipeVersion}
                  onStepChange={(index) => {
                    const recipe = message.styleRecipe;
                    if (!mounted.current || !recipe || isPending || index < 0 || index >= recipe.steps.length ||
                      message.ownerKey !== ownerKey || message.generation !== generation.current ||
                      recipe.recipeId !== styleContext.current?.recipeId || recipe.recipeVersion !== styleContext.current?.recipeVersion) return;
                    styleRevision.current += 1;
                    styleContext.current = { kind: recipe.kind, lookId: recipe.lookId,
                      recipeId: recipe.recipeId, recipeVersion: recipe.recipeVersion, currentStep: index };
                    setActiveStyle({ ...styleContext.current });
                    setMessages((current) => current.map((item) => item.id === message.id
                      ? { ...item, styleRecipe: { ...recipe, currentStep: index } } : item));
                  }}
                  onOpenProduct={(id, shadeId) => { if (mounted.current) router.push(productHref(id, shadeId)); }}
                  onOpenAr={(productId, shadeId) => { if (mounted.current) router.push(arHref({ productId, shadeId })); }}
                  onManualAr={() => { if (mounted.current) router.push(arHref()); }}
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
                  onBrowse={() => { if (mounted.current) router.push('/style-browse'); }}
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
                  <Text style={styles.failureText} accessibilityRole="alert">{t(message.errorKey ?? 'chat.ui.error')}</Text>
                  {message.retryable && message.ownerKey === ownerKey ? <Pressable accessibilityRole="button" accessibilityState={{ disabled: isPending }} disabled={isPending}
                    onPress={() => void send(message.text, message.id, message.category)} style={[styles.retry, isPending && styles.retryDisabled]}>
                    <Text style={styles.retryText}>{t('chat.ui.retry')}</Text>
                  </Pressable> : null}
                  <Pressable accessibilityRole="button" onPress={newSearch} style={styles.retry}>
                    <Text style={styles.retryText}>{t('chat.session.newSearch')}</Text>
                  </Pressable>
                </View>
              ) : null}
              {message.role === 'assistant' && message.products?.length ? <RelatedProducts refs={message.products}
                question={message.question ?? ''} category={message.category}
                chatContext={message.chatContext} evidence={message.evidence}
                selectedShades={selectedShades}
                selectedProductId={chosenProductId}
                onSelectProduct={beautyContext.current?.session ? (productId) => selectProduct(productId, message) : undefined}
                onSelectShade={(productId, shadeId) => selectShade(productId, shadeId, message)} /> : null}
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
          {chosenProductId && beautyContext.current?.session &&
            beautyContext.current.candidateIds.includes(chosenProductId) ? (
            <View style={styles.selectionBar}>
              <View style={styles.selectionInfo}>
                <Text style={styles.selectionLabel}>{t('chat.carousel.chosen')}</Text>
                <Text style={styles.selectionName} numberOfLines={1}>
                  {beautyContext.current.candidateIds.indexOf(chosenProductId) + 1}{t('chat.carousel.ordinal')}
                  {' · '}
                  {messages.flatMap((item) => item.products ?? []).find((p) => p.id === chosenProductId)?.name ?? chosenProductId}
                </Text>
              </View>
              <Pressable accessibilityRole="button" accessibilityLabel={t('chat.carousel.ingredient')}
                accessibilityState={{ disabled: isPending || !ready }}
                disabled={isPending || !ready} onPress={() => void send(t('chat.carousel.ingredient'), undefined, 'ingredient')}
                style={styles.selectionAction}>
                <Text style={styles.selectionActionText}>{t('chat.carousel.ingredient')}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={t('chat.carousel.details')}
                accessibilityState={{ disabled: isPending || !ready }}
                disabled={isPending || !ready} onPress={() => void send(t('chat.carousel.details'), undefined, 'product')}
                style={styles.selectionAction}>
                <Text style={styles.selectionActionText}>{t('chat.carousel.details')}</Text>
              </Pressable>
            </View>
          ) : null}
          <View style={styles.inputRow}>
            <TextInput ref={inputRef} accessibilityLabel={t('chat.ui.placeholder')} editable={!isPending && ready} maxLength={1000}
              multiline onChangeText={setInput} onFocus={() => setEditing(true)} onBlur={() => setEditing(false)}
              placeholder={t('chat.ui.placeholder')} placeholderTextColor={theme.colors.inkFaint}
              style={[styles.input, editing && styles.inputEditing]} value={input} />
            <Pressable accessibilityRole="button" accessibilityLabel={t('chat.ui.send')}
              accessibilityState={{ disabled: !input.trim() || isPending || !ready, busy: isPending }} disabled={!input.trim() || isPending || !ready}
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
  selectionBar: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, paddingBottom: 8 },
  selectionInfo: { flexGrow: 1, flexShrink: 1, minWidth: 104 },
  selectionLabel: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  selectionName: { color: theme.colors.ink, fontSize: theme.font.small },
  selectionAction: { borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.pill, minHeight: theme.hitTarget, paddingHorizontal: 9, justifyContent: 'center', backgroundColor: theme.colors.card },
  selectionActionText: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
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
