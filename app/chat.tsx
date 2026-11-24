import Ionicons from '@expo/vector-icons/Ionicons';
import { uuid } from 'expo';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useHeaderHeight } from 'expo-router/react-navigation';
import { useEffect, useEffectEvent, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator, Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { KnowledgeCitations } from '@/components/chat/KnowledgeCitations';
import { RecentConversations } from '@/components/chat/RecentConversations';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import { theme } from '@/constants/theme';
import { useChat } from '@/hooks/useChat';
import { useChatMemory } from '@/hooks/useChatMemory';
import { useChatConversations } from '@/hooks/useChatConversations';
import { ApiError, apiChatUserRequest } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { getSupabase } from '@/lib/auth/client';
import { conditionsFromChatFilters, extractChatConditions } from '@/lib/chatConditions';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { useLook, useProduct, useProductsByIds, useStyleLooks } from '@/lib/queries';
import { arHref, parseId, paramValue, productHref } from '@/lib/routes';
import { refersToPreviousLooks, selectedLookOrdinal, wantsDifferentStyle, wantsStyleSearch } from '@/lib/styleCoaching';
import { isChatSessionExpired, recentChatMessages, recentStyleMessages, useChatConversationStore, type ConversationRecord } from '@/store/chatConversationStore';
import type { ChatCategory as Category, ChatMessage, ChatRequestSnapshot, ConversationEntry } from '@/types/chatConversation';
import type { BeautyChatContext, ChatProductEvidence, ChatProductRef } from '@/types';

let observedAuthClient: ReturnType<typeof getSupabase>;

function displayAssistantText(text: string) {
  return text.replace(/\*\*([^*\n]+)\*\*/g, '$1');
}

const styleBrowseImage = require('@/assets/images/chat/style-recipe.png');

const categories: { id: Category; image: number; label: TranslationKey; caption: TranslationKey; prompts: TranslationKey[] }[] = [
  { id: 'product', image: require('@/assets/images/chat/product-recommendation.png'), label: 'chat.ui.product', caption: 'chat.ui.productCaption', prompts: ['chat.ui.productQuestion1', 'chat.ui.productQuestion2', 'chat.ui.productQuestion3'] },
  { id: 'ingredient', image: require('@/assets/images/chat/ingredient-consultation.png'), label: 'chat.ui.ingredient', caption: 'chat.ui.ingredientCaption', prompts: ['chat.ui.ingredientQuestion1', 'chat.ui.ingredientQuestion2', 'chat.ui.ingredientQuestion3'] },
  { id: 'style', image: styleBrowseImage, label: 'chat.ui.style', caption: 'chat.ui.styleCaption', prompts: ['chat.ui.styleQuestion1', 'chat.ui.styleQuestion2', 'chat.ui.styleQuestion3'] },
];

function OptionSearchScope({ result }: { result: NonNullable<ChatMessage['optionSearch']> }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const scope = result.checkedScope;
  if (scope.stoppedReason === 'INGREDIENT_CONFIRMATION') return null;
  const reason = scope.stoppedReason === 'TIMEOUT' ? 'chat.option.scopeTimeout'
    : scope.exhaustive ? 'chat.option.scopeComplete' : 'chat.option.scopeLimited';
  return (
    <View style={styles.conditionArea}>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded }}
        onPress={() => setExpanded((open) => !open)} style={styles.retry}>
        <Text style={styles.retryText}>{t(expanded ? 'chat.option.scopeHide' : 'chat.option.scopeShow')}</Text>
      </Pressable>
      {expanded ? <>
        <Text style={styles.note}>{t(reason)}</Text>
        <Text style={styles.note}>{t('chat.option.scopeProgress', { checked: scope.checkedOptions, total: scope.candidateOptions })}</Text>
        <Text style={styles.note}>{t('chat.option.scopeResults', {
          matched: result.items.filter((item) => item.group === 'ELIGIBLE').length,
          reference: result.items.filter((item) => item.group === 'REFERENCE_ONLY').length,
          excluded: result.excludedCount,
        })}</Text>
        {scope.errors > 0 ? <Text style={styles.note}>{t('chat.option.scopeErrors', { count: scope.errors })}</Text> : null}
        {scope.unidentifiedOptions > 0 ? <Text style={styles.note}>{t('chat.option.scopeUnidentified', { count: scope.unidentifiedOptions })}</Text> : null}
        {result.omittedCount > 0 ? <Text style={styles.note}>{t('chat.option.scopeOmitted', { count: result.omittedCount })}</Text> : null}
      </> : null}
    </View>
  );
}

function RelatedProducts({ optionSearch, sourceProducts, refs, question, category, chatContext, evidence, selectedShades, onSelectShade, onSelectProduct, selectedProductId, fragrance, onOpenEvidence }: {
  optionSearch?: ChatMessage['optionSearch'];
  sourceProducts?: NonNullable<ChatMessage['styleRecipe']>['products'];
  refs: ChatProductRef[]; question: string; category?: Category;
  chatContext?: BeautyChatContext; evidence?: ChatProductEvidence[];
  selectedShades: Record<string, string>;
  onSelectShade: (productId: string, shadeId: string) => void;
  onSelectProduct?: (productId: string) => void;
  selectedProductId?: string | null;
  fragrance?: 'verified' | 'unknown';
  onOpenEvidence?: (id: string) => void;
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
      {!fragrance ? <Text style={styles.relatedTitle}>{t('chat.relatedProducts')}</Text> : null}
      {sourceProducts ? <Text style={styles.relatedTitle}>{t('chat.style.videoProductsCount', {
        total: sourceProducts.length, linked: sourceProducts.filter((product) => product.productId).length,
      })}</Text> : null}
      <ChatProducts
        products={products}
        sourceProducts={sourceProducts}
        optionSearch={optionSearch}
        fragrance={fragrance}
        onOpenEvidence={onOpenEvidence}
        expectedIds={ids}
        conditions={chatContext?.filters.optionSearch ? [] : chatContext ? conditionsFromChatFilters(chatContext.filters, t) : extractChatConditions(question)}
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
        loading={ids.length > 0 && (query.isPending || query.isPlaceholderData)}
        failed={ids.length > 0 && query.isError}
        missingCount={!query.isPending && !query.isPlaceholderData && !query.isError ? ids.length - products.length : 0}
        onRetry={() => { if (mounted.current) void query.refetch(); }}
        onOpenProduct={(id, shadeId) => { if (mounted.current) router.push(productHref(id, shadeId, undefined, !!sourceProducts)); }}
        onOpenAr={(productId, shadeId) => { if (mounted.current) router.push(arHref({ productId, shadeId })); }}
      />
    </View>
  );
}

function FragranceSearchResult({ message, ...actions }: {
  message: ChatMessage;
} & Pick<Parameters<typeof RelatedProducts>[0], 'selectedShades' | 'selectedProductId' | 'onSelectProduct' | 'onSelectShade'>) {
  const { t } = useI18n();
  const [showUnverified, setShowUnverified] = useState(false);
  const [evidenceId, setEvidenceId] = useState<string>();
  const summary = message.fragranceSearchSummary;
  if (!summary) return null;
  const refs = message.products ?? [];
  const verified = refs.filter((item) => summary.verifiedProductIds.includes(item.id));
  const unverified = refs.filter((item) => !summary.verifiedProductIds.includes(item.id));
  const filters = message.chatContext?.filters;
  const conditions = filters ? conditionsFromChatFilters(filters, t).map((condition) => condition.text) : [];
  const shared = { ...actions, question: message.question ?? '', chatContext: message.chatContext,
    evidence: message.evidence, onOpenEvidence: (id: string) => setEvidenceId((current) => current === id ? undefined : id) };
  return <View style={styles.conditionArea}>
    <Text style={styles.conditionTitle}>{t('chat.ingredient.fragranceSummary', {
      total: summary.total, checked: summary.checked, matches: verified.length,
    })}</Text>
    {conditions.length ? <Text style={styles.note}>{conditions.join(' · ')}</Text> : null}
    {verified.length ? <RelatedProducts {...shared} refs={verified} fragrance="verified"
      selectedShades={message.chatContext?.shadeSelections ?? {}} /> : null}
    {unverified.length ? <>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded: showUnverified }}
        onPress={() => { setShowUnverified((visible) => !visible); setEvidenceId(undefined); }} style={styles.retry}>
        <Text style={styles.retryText}>{t('chat.ingredient.showUnverified')} ({unverified.length})</Text>
      </Pressable>
      {showUnverified ? <RelatedProducts {...shared} refs={unverified} fragrance="unknown" /> : null}
    </> : null}
    {evidenceId ? <IngredientResult evidenceOnly heading={t('chat.ui.ingredient')} summary="" notice=""
      labels={{ product: t('chat.result.productInfo'), ingredients: t('chat.result.ingredientList'),
        source: t('chat.result.source'), unknown: t('chat.conditionUnknown') }}
      results={message.ingredientResults?.filter((item) => item.productId === evidenceId)}
      products={refs.filter((item) => item.id === evidenceId)} shadeSelections={message.chatContext?.shadeSelections} /> : null}
  </View>;
}

export default function ChatScreen() {
  const params = useLocalSearchParams<{ recipeKind?: string; recipeLookId?: string; productId?: string; shadeId?: string }>();
  const rawKind = paramValue(params.recipeKind);
  const kind = rawKind === 'video' || rawKind === 'catalog' ? rawKind : undefined;
  const rawLookId = paramValue(params.recipeLookId);
  const lookId = kind === 'video' ? rawLookId && /^[A-Za-z0-9_-]{1,64}$/.test(rawLookId) ? rawLookId : undefined : parseId(params.recipeLookId);
  const productId = kind && lookId ? undefined : parseId(params.productId);
  const shadeId = parseId(params.shadeId);
  const { user, ready } = useAuth();
  const userId = user?.id ?? null;
  const identity = useChatConversationStore((state) => state.identity);
  const rooms = useChatConversationStore((state) => state.conversations);
  const routeKey = JSON.stringify([userId, kind, lookId, productId, shadeId]);
  const [active, setActive] = useState<{ routeKey: string; id?: string }>();
  const setActiveId = (id?: string) => setActive({ routeKey, id });
  const [recentVisible, setRecentVisible] = useState(false);
  const savedRooms = useChatConversations(userId, identity?.key);
  const { t } = useI18n();

  useEffect(() => {
    const client = getSupabase();
    const store = useChatConversationStore.getState();
    if (client && observedAuthClient !== client) {
      observedAuthClient = client;
      // Observe logout even after the chat route has been closed.
      client.auth.onAuthStateChange((_event, session) => {
        if (observedAuthClient === client) store.activate(session?.user.id ?? null);
      });
    }
    if (!ready) return;
    if (store.identity?.userId !== userId) store.activate(userId);
    const entry: ConversationEntry = kind && lookId ? { type: 'look', kind, lookId }
      : productId ? { type: 'product', productId, shadeId } : { type: 'general' };
    let current = true;
    void Promise.resolve().then(() => {
      if (!current || useChatConversationStore.getState().identity?.userId !== userId) return;
      setActive({ routeKey, id: store.open(entry) });
      setRecentVisible(false);
    });
    return () => { current = false; };
  }, [ready, userId, kind, lookId, productId, shadeId, routeKey]);

  const record = ready && identity?.userId === userId && active?.routeKey === routeKey && active.id ? rooms[active.id] : undefined;
  if (!record) return <SafeAreaView style={styles.screen} edges={['bottom']}>
    <ActivityIndicator />
    <TextInput editable={false} onChangeText={() => {}} />
    <Pressable accessibilityLabel={t('chat.ui.send')} disabled onPress={() => {}} />
  </SafeAreaView>;

  const startNew = () => {
    if (useChatConversationStore.getState().conversations[record.conversation.id]?.conversation.ownerKey !== record.conversation.ownerKey) return;
    const { subject } = record.conversation;
    const product = record.view.linkedProduct;
    const style = record.view.activeStyle;
    const entry = subject.type === 'product'
      ? { ...subject, shadeId: product?.productId === subject.productId ? product?.shadeId ?? undefined
        : record.conversation.entryProduct?.shadeId ?? undefined }
      : subject;
    const focus = subject.type === 'general'
      ? { product: product?.productId ? { ...product, screenId: 'product-detail' } : undefined, style }
      : undefined;
    setActiveId(useChatConversationStore.getState().open(entry, true, focus));
    setRecentVisible(false);
  };
  return <>
    <ChatConversation key={record.conversation.id} record={record}
      onRecent={() => { setRecentVisible(true); if (userId) void savedRooms.list(); }} onNew={startNew}
      onReload={() => savedRooms.open(record.conversation.id, true)}
      onOlder={() => { void savedRooms.older(record.conversation.id); }} olderLoading={savedRooms.loading} olderError={savedRooms.error} />
    {recentVisible ? <RecentConversations rooms={Object.values(rooms)} activeId={record.conversation.id}
      onClose={() => setRecentVisible(false)} onNew={startNew}
      loading={savedRooms.loading} error={savedRooms.error} hasMore={savedRooms.hasMore || savedRooms.error}
      onMore={() => { void savedRooms.list(!savedRooms.error); }}
      onSelect={(id) => { void savedRooms.open(id).then((opened) => {
        if (opened && useChatConversationStore.getState().resume(opened)) { setActiveId(opened); setRecentVisible(false); }
      }); }}
      renderSubject={(item) => {
        const { subject } = item.conversation;
        if (subject.type === 'look') return subject.kind === 'video'
          ? <VideoEntryLabel id={subject.lookId} /> : <CatalogEntryLabel id={subject.lookId} />;
        if (subject.type === 'product') return <ProductEntryLabel id={subject.productId} showShade={false} />;
        return null;
      }} /> : null}
  </>;
}

function VideoEntryLabel({ id }: { id: string }) {
  const query = useStyleLooks();
  return <EntryLabel name={query.data?.find((look) => look.id === id)?.title} />;
}

function CatalogEntryLabel({ id }: { id: string }) {
  const query = useLook(id);
  return <EntryLabel name={query.data?.look.id === id ? query.data.look.title : undefined} />;
}

function ProductEntryLabel({ id, shadeId, showShade = true }: { id: string; shadeId?: string | null; showShade?: boolean }) {
  const query = useProduct(id);
  const product = query.data;
  const shade = product?.shades?.find((item) => item.id === shadeId)?.name;
  const { t } = useI18n();
  if (product?.id !== id) return <EntryLabel name={query.isError && query.error instanceof ApiError && query.error.status === 404
    ? t('chat.ingredient.productMissing') : undefined} />;
  return <EntryLabel name={showShade ? `${product.name} · ${shade ?? t('chat.room.shadeUnselected')}` : product.name} />;
}

function EntryLabel({ name }: { name?: string }) {
  const { t } = useI18n();
  return name ? <Text numberOfLines={2} style={styles.entryLabel}>{t('chat.entry.context', { name })}</Text> : null;
}

function InlineStyleLookPicker({ question, onSelect }: { question: string; onSelect: (id: string) => void }) {
  const { t } = useI18n();
  const query = useStyleLooks();
  const [expanded, setExpanded] = useState(false);
  const looks = query.data ?? [];
  const zone = [/립|입술|\blips?\b|リップ|唇/i, /아이라인|눈 화장|\beye(?:liner|s)?\b|アイメイク|眼妆/i,
    /볼터치|블러셔|\bblush\b|チーク|腮红/i].find((pattern) => pattern.test(question));
  const matching = zone ? looks.filter((look) => look.products.some((product) => zone.test(product.zone)))
    : /룩|look|ルック|妆容/i.test(question) ? looks : [];
  if (!matching.length && !query.isError) return null;
  if (!expanded) return <Pressable accessibilityRole="button" onPress={() => setExpanded(true)} style={styles.retry}>
    <Text style={styles.retryText}>{t('chat.style.chooseInline')}</Text>
  </Pressable>;
  return <View style={styles.conditionArea}>
    {query.isPending ? <ActivityIndicator /> : null}
    {query.isError ? <Pressable accessibilityRole="button" onPress={() => void query.refetch()} style={styles.retry}>
      <Text style={styles.retryText}>{t('chat.ui.retry')}</Text>
    </Pressable> : null}
    {matching.slice(0, 6).map((look) => (
      <Pressable key={look.id} accessibilityRole="button" onPress={() => onSelect(look.id)} style={styles.retry}>
        <Text style={styles.retryText}>{look.title}</Text>
      </Pressable>
    ))}
  </View>;
}

function ChatConversation({ record, onRecent, onNew, onReload, onOlder, olderLoading, olderError }: {
  record: ConversationRecord;
  onRecent: () => void;
  onNew: () => void;
  onReload: () => Promise<string | undefined>;
  onOlder: () => void;
  olderLoading: boolean;
  olderError: boolean;
}) {
  const { conversation, messages, view } = record;
  const { pending: chatPending, notice: sessionNotice, activeStyle, linkedProduct, generation: conversationGeneration,
    selectedShades, chosenProductId, sessionCandidateIds, draft: input, sessionExpiry } = view;
  const router = useRouter();
  const headerHeight = useHeaderHeight();
  const { ownerKey, userId, subject } = conversation;
  const target = { id: conversation.id, ownerKey };
  const { t, language } = useI18n();
  const { mutateAsync } = useChat();
  const memory = useChatMemory(userId);
  const mounted = useRef(true);
  const store = useChatConversationStore.getState;
  const currentRoom = () => store().conversations[target.id]?.conversation;
  const owned = () => store().identity?.key === ownerKey && currentRoom()?.ownerKey === ownerKey;
  const setInput = (value: string) => store().setDraft(target, value);
  const scrollRef = useRef<ComponentRef<typeof ScrollView>>(null);
  const inputRef = useRef<ComponentRef<typeof TextInput>>(null);
  const nearBottom = useRef(true);
  const { category } = view;
  const setCategory = (next: Category) => store().setCategory(target, next);
  const [editing, setEditing] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memoryError, setMemoryError] = useState(false);
  const [memorySaved, setMemorySaved] = useState(false);
  const [dismissedProposals, setDismissedProposals] = useState<string[]>([]);
  const [memoryEdit, setMemoryEdit] = useState<{ id: string; value: string }>();
  const [memoryDelete, setMemoryDelete] = useState<string>();
  const [statePending, setStatePending] = useState(false);
  const stateBusy = useRef(false);
  const stateRequestIds = useRef(new Map<string, string>());
  const isPending = chatPending || statePending;
  const conditions = extractChatConditions(input);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const resetSession = (key: TranslationKey, keepSelection = false) => store().resetSession(target, key, keepSelection);

  const expireSession = useEffectEvent(() => {
    const room = currentRoom();
    const ref = room?.beautyContext?.session;
    if (!room?.request && ref && isChatSessionExpired(ref.expiresAt)) resetSession('chat.session.expired');
  });
  useEffect(() => {
    if (!sessionExpiry || isPending) return;
    const delay = sessionExpiry * 1000 - Date.now();
    if (delay <= 0) expireSession();
    else if (delay <= 2_147_483_647) {
      const timer = setTimeout(() => expireSession(), delay);
      return () => clearTimeout(timer);
    }
  }, [sessionExpiry, isPending]);

  const newSearch = () => {
    void persistSelection('clear_selection', {}, () => {
      resetSession('chat.session.newSearchHint');
      if (subject.type === 'general') store().setStyle(target);
      setInput('');
      inputRef.current?.focus();
    });
  };

  const persistSelection = async (operation: string, payload: object, apply: () => void) => {
    const room = currentRoom();
    if (!room || !owned() || stateBusy.current) return;
    if (!userId || !room.serverId) { apply(); return; }
    if (room.request) return;
    stateBusy.current = true;
    setStatePending(true);
    const key = JSON.stringify([room.serverId, room.serverVersion, operation, payload]);
    try {
      const requestId = stateRequestIds.current.get(key) ?? uuid.v4();
      stateRequestIds.current.set(key, requestId);
      const result = await apiChatUserRequest<{ conversationVersion: number }>(
        `/api/chat/conversations/${room.serverId}/state`, 'PATCH', userId,
        { requestId, expectedConversationVersion: room.serverVersion, operation, payload },
      );
      if (!owned() || currentRoom()?.serverId !== room.serverId || currentRoom()?.generation !== room.generation) return;
      store().bindServerRoom(target, room.serverId, result.conversationVersion);
      stateRequestIds.current.delete(key);
      apply();
    } catch (error) {
      if (owned() && currentRoom()?.generation === room.generation) {
        const api = error instanceof ApiError ? error : undefined;
        store().setNotice(target, api?.status === 409 ? 'chat.session.conflict' : 'chat.session.storageError');
        if (api?.code === 'conversation_conflict') {
          stateRequestIds.current.delete(key);
          await onReload();
        }
      }
    } finally {
      stateBusy.current = false;
      if (mounted.current) setStatePending(false);
    }
  };

  const clearFocus = () => void persistSelection('clear_selection', {}, () => {
    if (userId && currentRoom()?.serverId) {
      store().setStyle(target);
      store().clearProduct(target);
    } else if (activeStyle && category === 'style') store().setStyle(target);
    else store().clearProduct(target);
  });

  const selectProduct = (productId: string, message: ChatMessage) => {
    const room = currentRoom();
    const session = room?.beautyContext?.session;
    if (!room || !session || isChatSessionExpired(session.expiresAt) ||
      message.ownerKey !== ownerKey || message.generation !== room.generation ||
      message.resultSetId !== session.resultSetId || !room.beautyContext?.candidateIds.includes(productId)) return;
    const shadeId = room.selection.shades[productId];
    void persistSelection(shadeId ? 'select_shade' : 'select_product', { productId, ...(shadeId ? { shadeId } : {}) },
      () => store().selectProduct(target, productId, message));
  };
  const selectShade = (productId: string, shadeId: string, message: ChatMessage) => {
    const room = currentRoom();
    const session = room?.beautyContext?.session;
    if (!room || message.ownerKey !== ownerKey || message.generation !== room.generation ||
      (session && (isChatSessionExpired(session.expiresAt) || message.resultSetId !== session.resultSetId))) return;
    void persistSelection('select_shade', { productId, shadeId }, () => store().selectShade(target, productId, shadeId, message));
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

  const send = async (textToSend = input, retryId?: string, retryCategory?: Category, automatic = false) => {
    const text = textToSend.trim();
    if (!text || !owned() || currentRoom()?.request || stateBusy.current) return;
    let room = currentRoom()!;
    const expired = room.beautyContext?.session;
    if (expired && isChatSessionExpired(expired.expiresAt)) {
      resetSession('chat.session.expired');
      room = currentRoom()!;
      if (retryId) return;
    }
    const failedMatch = retryId ?? messages.find((message) => message.role === 'user' &&
      message.failed && message.text === text && room.snapshots.has(message.id))?.id;
    const original = failedMatch ? room.snapshots.get(failedMatch) : undefined;
    if (retryId && !original) return;
    let requestId: string;
    try { requestId = original?.args.requestId ?? uuid.v4(); }
    catch { store().setNotice(target, 'chat.session.idUnavailable'); return; }
    const lookReference = /이\s*(?:룩|스타일)|\bthis (?:look|style)\b|このルック|这个妆容/i.test(text);
    const shopping = /추천|구매|가격|얼마|비교|성분|향료|recommend|price|compare|ingredient|fragrance|おすすめ|比較|価格|推荐|比较|价格|成分|香料/i.test(text);
    const makeupTopic = /립|입술|아이라인|블러셔|아이섀도|화장|메이크업|\b(?:lip|lips|makeup|eyeliner|blush|eyeshadow)\b|メイク|リップ|化妆|唇|眼妆/i.test(text);
    const technique = /어떻게|방법|하는\s*법|하는\s*거|바르는\s*법|\bhow\b|やり方|方法|怎么|如何/i.test(text);
    const styleSearchActive = messages.some((message) => message.ownerKey === ownerKey &&
      message.generation === room.generation && message.styleCandidates !== undefined);
    const latestLooks = messages.findLast((message) => message.ownerKey === ownerKey &&
      message.generation === room.generation && message.styleCandidates !== undefined)?.styleCandidates;
    const previousLookReference = refersToPreviousLooks(text);
    const listedLooks = previousLookReference
      ? messages.findLast((message) => message.ownerKey === ownerKey && message.generation === room.generation &&
        message.styleCandidates?.length)?.styleCandidates : latestLooks;
    const earlierRecipe = previousLookReference ? messages.findLast((message) => message.ownerKey === ownerKey &&
      message.generation === room.generation && message.styleRecipe &&
      (message.styleRecipe.kind !== room.styleContext?.kind || message.styleRecipe.lookId !== room.styleContext?.lookId))?.styleRecipe : undefined;
    const previousLooks = earlierRecipe && !listedLooks?.some((look) => look.kind === earlierRecipe.kind && look.lookId === earlierRecipe.lookId)
      ? [...(listedLooks ?? []), { kind: earlierRecipe.kind, lookId: earlierRecipe.lookId, title: earlierRecipe.title, tags: [] }]
      : listedLooks;
    const unresolvedLookReference = !room.styleContext && /(?:그|이)\s*(?:룩|스타일)|\b(?:this|that) look\b|このルック|这个妆容/i.test(text);
    const ordinal = selectedLookOrdinal(text);
    const compareLooks = !!previousLooks?.length && /비교|차이|compare|difference|比較|違い|比较|区别/i.test(text) &&
      /룩|후보|첫|두|세|[123]|look|first|second|ルック|妆容/i.test(text) &&
      !/제품|상품|product|商品|製品|产品/i.test(text);
    const previousLookRequest = !!previousLooks?.length && (previousLookReference || unresolvedLookReference || ordinal !== undefined || compareLooks);
    const wantsExplanation = /설명|어떻게|방법|explain|how|説明|方法|解释|怎么/i.test(text);
    const singlePrevious = !compareLooks && previousLookRequest
      ? ordinal !== undefined ? previousLooks?.[ordinal] : previousLooks?.length === 1 && wantsExplanation ? previousLooks[0] : undefined
      : undefined;
    const differentLook = wantsDifferentStyle(text);
    const styleSearch = original?.args.styleSearch ?? ((subject.type === 'general' || (subject.type === 'look' && (differentLook || previousLookRequest))) &&
      (previousLookRequest ? !singlePrevious : ((!room.styleContext || differentLook) &&
        (wantsStyleSearch(text, styleSearchActive) || (room.category === 'style' && !room.styleContext &&
          makeupTopic && !technique && !shopping && !/제품|상품|product|商品|製品|产品/i.test(text))))));
    const requestedStyle = singlePrevious
      ? room.styleContext?.kind === singlePrevious.kind && room.styleContext.lookId === singlePrevious.lookId
        ? room.styleContext : { kind: singlePrevious.kind, lookId: singlePrevious.lookId, currentStep: 0 }
      : room.styleContext;
    const generalMakeup = original?.generalMakeup ??
      (!styleSearch && !retryCategory && !room.styleContext && !lookReference && !shopping && makeupTopic && technique);
    const requestCategory = original?.args.category ?? retryCategory ??
      (styleSearch || singlePrevious ? 'style' : generalMakeup && room.category ? 'product' : lookReference ? 'style' : room.category);
    const context = styleSearch || (generalMakeup && !room.beautyContext?.session) ? undefined : room.beautyContext;
    const focusedProduct = generalMakeup ? undefined : room.selection.screen ?? room.entryProduct;
    const styleHistory = styleSearch ? recentStyleMessages(messages, room.ownerKey, room.generation) : [];
    const lastReply = messages.at(-1);
    const comparing = /비교|차이|\bcompar(?:e|ison)\b|\bdiffer(?:s|ent|ence|ences)?\b|比較|違い|对比|比较|区别/i;
    const comparisonTarget = !!focusedProduct?.productId && lastReply?.resultType === 'clarification' &&
      comparing.test(lastReply.question ?? '') && !comparing.test(text) && !shopping && !technique && !/[?？]/.test(text);
    const pendingComparison = lastReply?.ingredientComparison;
    const ingredientComparison = /성분|향료|\bingredients?\b|\bfragrance\b|成分|香料/i.test(lastReply?.question ?? '');
    const screen = comparisonTarget ? {
      ...focusedProduct, screenId: ingredientComparison ? 'product-ingredient-comparison' : 'product-comparison',
      ...(pendingComparison?.currentProductId === focusedProduct?.productId ? { ingredientComparison: pendingComparison } : {}),
    } : focusedProduct;
    const snapshot: ChatRequestSnapshot = original ?? {
      automatic,
      generalMakeup,
      styleRevision: room.styleRevision,
      generation: room.generation,
      revision: room.selection.revision,
      serverBaseVersion: room.serverVersion,
      statePatchId: requestId.slice(0, -1) + (parseInt(requestId.slice(-1), 16) ^ 1).toString(16),
      args: {
        message: text, locale: language, category: requestCategory, requestId, expectedUserId: userId,
        ...((styleSearch || (language === 'ko' && !room.styleContext)) ? {
          recentMessages: styleHistory.length ? styleHistory : recentChatMessages(messages, room.ownerKey, room.generation),
          ...(!styleSearch && room.pendingClarification ? { clarificationId: room.pendingClarification.id } : {}),
        } : {}),
        ...(styleSearch ? { styleSearch: true, styleConditions: room.styleConditions.map((item) => ({ ...item })),
          ...(!previousLookRequest && differentLook && room.styleContext ? { excludedStyle: { kind: room.styleContext.kind, lookId: room.styleContext.lookId } } : {}),
          ...(compareLooks ? { styleCompare: true } : {}),
          ...(previousLookRequest ? { previousStyleCandidates: previousLooks!.map(({ kind, lookId }) => ({ kind, lookId })),
            ...(room.styleContext ? { previousStyleSelection: { kind: room.styleContext.kind, lookId: room.styleContext.lookId } } : {}) } : {}) } : {}),
        ...(generalMakeup ? { generalMakeup: true } : {}),
        ...(!styleSearch && !generalMakeup && requestedStyle
          ? { styleContext: { ...requestedStyle } } : {}),
        ...(context ? { chatContext: { ...context, filters: { ...context.filters },
          candidateIds: [...context.candidateIds], scopeIds: [...context.scopeIds],
          ...(context.session ? { session: { ...context.session } } : {}),
          ...(context.shadeSelections ? { shadeSelections: { ...context.shadeSelections } } : {}) } } : {}),
        ...(!styleSearch && screen ? { screenContext: { ...screen } } : {}),
      },
    };
    const ticket = store().beginRequest(target, snapshot, failedMatch);
    if (!ticket) return;
    if (!failedMatch) nearBottom.current = true;
    try {
      const wantsMemory = /기억해|\bremember\b|覚えて|记住/i.test(text) &&
        !/기억하지\s*마|기억하지\s*말|(?:do\s+not|don't|never)\s+remember|\b(?:i|we)\s+remember\b|覚えない|不要记住|别记住/i.test(text);
      if (!userId && wantsMemory) throw new ApiError('Memory unavailable', 503, 'memory_unavailable');
      if (userId && !room.serverId && room.persistenceMode !== 'disabled') {
        try {
          const entry = subject.type === 'product'
            ? { ...subject, ...(room.entryProduct?.shadeId ? { shadeId: room.entryProduct.shadeId } : {}) }
            : subject;
          const created = await apiChatUserRequest<{ conversationId: string; conversationVersion: number }>(
            '/api/chat/conversations', 'POST', userId, { requestId: room.id, entry },
          );
          if (!owned()) return;
          store().bindServerRoom(target, created.conversationId, created.conversationVersion);
          store().setPersistenceMode(target, 'enabled');
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 503 || error.code !== 'persistence_disabled') throw error;
          if (!owned()) return;
          store().setPersistenceMode(target, 'disabled');
        }
      }
      room = currentRoom()!;
      if (userId && wantsMemory) {
        if (!room.serverId) throw new ApiError('Memory unavailable', 503, 'memory_unavailable');
        await memory.refresh();
        if (!owned()) return;
      }
      let version = snapshot.serverBaseVersion ?? room.serverVersion;
      if (userId && room.serverId) {
        const style = snapshot.args.styleContext;
        const screen = snapshot.args.screenContext;
        const state = style ? {
          operation: style.recipeVersion ? 'set_recipe_step' : 'select_look',
          payload: { kind: style.kind, lookId: style.lookId,
            ...(style.recipeVersion ? { recipeVersion: style.recipeVersion, currentStep: style.currentStep } : {}) },
        } : screen?.productId ? {
          operation: screen.shadeId ? 'select_shade' : 'select_product',
          payload: { productId: screen.productId, ...(screen.shadeId ? { shadeId: screen.shadeId } : {}) },
        } : undefined;
        if (state) {
          const patched = await apiChatUserRequest<{ conversationVersion: number }>(
            `/api/chat/conversations/${room.serverId}/state`, 'PATCH', userId,
            { requestId: snapshot.statePatchId, expectedConversationVersion: version, ...state },
          );
          if (!owned()) return;
          version = patched.conversationVersion;
          store().bindServerRoom(target, room.serverId, version);
        }
      }
      const response = await mutateAsync({ ...snapshot.args,
        ...(room.serverId ? { conversationId: room.serverId, expectedConversationVersion: version } : {}) });
      if (room.serverId && (!response.conversation || response.conversation.id !== room.serverId)) {
        throw new ApiError('Invalid conversation response', 502, 'invalid_response');
      }
      if (response.styleStatus === 'error') throw new ApiError(response.answer, 502, 'style_search_unavailable');
      const expectedStyle = snapshot.args.styleContext;
      const actualRecipe = response.styleRecipe;
      if (actualRecipe && (!expectedStyle || actualRecipe.kind !== expectedStyle.kind || actualRecipe.lookId !== expectedStyle.lookId)) {
        throw new ApiError('Recipe does not match the requested look', 502);
      }
      store().completeRequest(ticket, response, comparisonTarget && lastReply?.question ? lastReply.question : text);
    } catch (error) {
      const api = error instanceof ApiError ? error : undefined;
      const clarificationConflict = api?.code === 'chat_clarification_conflict';
      const fatal = api && !clarificationConflict && ([403, 409, 410].includes(api.status) ||
        ['chat_owner_changed', 'chat_owner_unavailable'].includes(api.code ?? ''));
      const errorKey: TranslationKey = api?.code === 'memory_unavailable' ? 'chat.memory.unavailable'
        : api?.code === 'chat_owner_changed'
        ? 'chat.session.identityChanged'
        : api?.code === 'chat_owner_unavailable' ? 'chat.session.identityUnavailable'
        : api?.status === 403 ? 'chat.session.forbidden'
          : api?.status === 409 ? 'chat.session.conflict'
            : api?.status === 410 ? 'chat.session.expired'
              : api?.status === 503 && api.code?.startsWith('chat_session_') ? 'chat.session.storageError'
                : api?.code === 'shade_not_found' ? 'chat.ingredient.shadeMissing'
                  : api?.status === 404 ? 'chat.ingredient.productMissing'
                    : api?.code === 'option_search_unavailable' ? 'chat.option.searchUnavailable'
                    : (snapshot.args.styleSearch || snapshot.args.styleContext) && api?.status === 503 ? 'chat.ui.error'
                      : api?.status === 503 ? 'chat.ingredient.server'
                      : api?.status === 0 ? 'chat.ingredient.network' : 'chat.ui.error';
      const active = currentRoom();
      const recover = api?.code === 'conversation_conflict' && owned() && mounted.current &&
        active?.request === ticket.requestId && active.generation === ticket.generation && active.attempt === ticket.attempt;
      store().failRequest(ticket, errorKey, !!fatal, !!api?.code?.startsWith('chat_owner_'), clarificationConflict);
      if (recover) {
        stateBusy.current = true;
        setStatePending(true);
        try {
          await onReload();
        } finally {
          stateBusy.current = false;
          if (mounted.current) setStatePending(false);
        }
      }
    }
  };

  const bootstrapLook = useEffectEvent(() => {
    if (currentRoom()?.bootstrap === 'not-started') void send(t('chat.room.recipePrompt'), undefined, 'style', true);
  });
  useEffect(() => {
    if (subject.type === 'look') bootstrapLook();
  }, [subject]);

  const visibleMessages = messages.filter((message) => !message.automatic || message.failed);
  const latestStyleMessageId = messages.findLast((message) => message.ownerKey === ownerKey &&
    message.generation === conversationGeneration && message.styleCandidates !== undefined)?.id;
  const hasStyleConversation = !!activeStyle || messages.some((message) => message.ownerKey === ownerKey &&
    message.generation === conversationGeneration && (message.styleCandidates !== undefined ||
      (message.role === 'user' && message.category === 'style')));
  const canSelect = (message: ChatMessage) => sessionCandidateIds.length > 0 &&
    message.generation === conversationGeneration && message.resultSetId === view.resultSetId;

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{
        title: subject.type === 'look' ? (messages.findLast((item) => item.styleRecipe)?.styleRecipe?.title ?? t('chat.room.look'))
          : subject.type === 'product' ? t('chat.room.product') : t('chat.ui.title'),
        headerRight: () => (
        <View style={styles.headerActions}>
          {userId ? <Pressable accessibilityRole="button" accessibilityLabel={t('chat.memory.manage')}
            onPress={() => {
              const next = !memoryOpen;
              setMemoryOpen(next);
              setMemoryError(false);
              if (next) void memory.refresh().catch(() => { if (mounted.current && owned()) setMemoryError(true); });
            }} style={styles.headerAction}>
            <Ionicons name="bookmark-outline" size={21} color={theme.colors.roseDark} />
          </Pressable> : null}
          <Pressable accessibilityRole="button" accessibilityLabel={t('chat.room.recent')} onPress={onRecent} style={styles.headerAction}>
            <Ionicons name="time-outline" size={22} color={theme.colors.roseDark} />
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel={t('chat.session.newConversation')} onPress={onNew} style={styles.headerAction}>
            <Ionicons name="add" size={25} color={theme.colors.roseDark} />
          </Pressable>
        </View>
      ) }} />
      <KeyboardAvoidingView style={styles.keyboard} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={headerHeight}>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.messages} keyboardShouldPersistTaps="handled"
          onScroll={({ nativeEvent }) => {
            const { contentOffset, contentSize, layoutMeasurement } = nativeEvent;
            nearBottom.current = contentSize.height - (contentOffset.y + layoutMeasurement.height) < 80;
          }} scrollEventThrottle={16}>
          {conversation.olderMessageCursor ? <Pressable accessibilityRole="button" disabled={olderLoading}
            onPress={() => { nearBottom.current = false; onOlder(); }} style={styles.retry}><Text style={styles.retryText}>{t('chat.room.older')}</Text></Pressable> : null}
          {olderError && conversation.olderMessageCursor ? <Text accessibilityRole="alert" style={styles.failureText}>{t('chat.room.loadError')}</Text> : null}
          {!messages.length && !isPending && subject.type !== 'general' ? <View style={styles.targetWelcome}>
            <Text accessibilityRole="header" style={styles.welcomeTitle}>{t(subject.type === 'look' ? 'chat.room.look' : 'chat.room.product')}</Text>
            {subject.type === 'look' ? subject.kind === 'video' ? <VideoEntryLabel id={subject.lookId} /> : <CatalogEntryLabel id={subject.lookId} />
              : <ProductEntryLabel id={subject.productId} shadeId={linkedProduct?.shadeId} />}
            <Text style={styles.welcomeBody}>{t('chat.welcome.ask')}</Text>
            {(subject.type === 'look'
              ? ['chat.room.recipePrompt', 'chat.room.lookTip', 'chat.room.lookProduct'] as const
              : ['chat.carousel.ingredient', 'chat.carousel.details', 'chat.room.pricePrompt', 'chat.room.comparePrompt'] as const).map((key) =>
              <Pressable key={key} accessibilityRole="button" style={styles.problemPrompt}
                onPress={() => {
                  if (key === 'chat.room.comparePrompt') { setInput(t(key)); inputRef.current?.focus(); }
                  else void send(t(key), undefined, subject.type === 'look' ? 'style' : key === 'chat.carousel.ingredient' ? 'ingredient' : 'product');
                }}>
                <Text style={styles.problemText}>{t(key)}</Text>
                <Ionicons name="arrow-forward" size={16} color={theme.colors.rose} />
              </Pressable>)}
          </View> : null}
          {!messages.length && subject.type === 'general' ? (
            <View style={styles.welcome}>
              {!editing ? (
                <>
                  <View style={styles.welcomeIcon}><Ionicons name="sparkles" size={25} color={theme.colors.rose} /></View>
                  <Text style={styles.welcomeTitle}>{t('chat.ui.welcomeTitle')}</Text>
                  <Text style={styles.welcomeBody}>{t('chat.ui.welcomeBody')}</Text>
                </>
              ) : null}
              {!editing ? (
                <>
                  <Text style={styles.problemHeading}>{t('chat.welcome.ask')}</Text>
                  <View style={styles.problemPrompts}>
                    {([
                      { id: 'product' as Category, text: 'chat.welcome.promptA' as TranslationKey, icon: 'heart-outline' as const },
                      { id: 'ingredient' as Category, text: 'chat.welcome.promptB' as TranslationKey, icon: 'flask-outline' as const },
                      { id: 'style' as Category, text: 'chat.welcome.promptC' as TranslationKey, icon: 'color-palette-outline' as const },
                      { id: 'product' as Category, text: 'chat.welcome.promptD' as TranslationKey, icon: 'sparkles-outline' as const },
                    ]).map((prompt) => (
                      <Pressable key={prompt.text} accessibilityRole="button" accessibilityLabel={t(prompt.text)}
                        onPress={() => { setCategory(prompt.id); setInput(t(prompt.text)); inputRef.current?.focus(); }}
                        style={styles.problemPrompt}>
                        <View style={styles.problemIcon}><Ionicons name={prompt.icon} size={20} color={theme.colors.rose} /></View>
                        <Text style={styles.problemText}>{t(prompt.text)}</Text>
                        <Ionicons name="arrow-forward" size={16} color={theme.colors.rose} />
                      </Pressable>
                    ))}
                  </View>
                  <Text style={styles.problemHint}>{t('chat.welcome.chooseHint')}</Text>
                </>
              ) : (
                <View style={styles.categoryChips}>
                  {categories.map((item) => (
                    <Pressable key={item.id} accessibilityRole="button"
                      accessibilityLabel={`${t(item.label)}, ${t(item.caption)}`}
                      accessibilityState={{ selected: category === item.id }}
                      onPress={() => setCategory(item.id)}
                      style={[styles.categoryChip, category === item.id && styles.categorySelected]}>
                      <Text style={styles.categoryText}>{t(item.label)}</Text>
                    </Pressable>
                  ))}
                </View>
              )}
            </View>
          ) : (
            <View>
              {messages.length && !editing && subject.type === 'general' && !hasStyleConversation ? <Text style={styles.contextNotice}>{t('chat.ui.contextNotice')}</Text> : null}
              {subject.type === 'general' ? <View style={styles.categoryChips}>
                {categories.map((item) => (
                  <Pressable key={item.id} accessibilityRole="button" accessibilityState={{ selected: category === item.id }}
                    onPress={() => setCategory(item.id)} style={[styles.categoryChip, category === item.id && styles.categorySelected]}>
                    <Text style={styles.categoryText}>{t(item.label)}</Text>
                  </Pressable>
                ))}
              </View> : null}
            </View>
          )}
          {sessionNotice ? <View style={styles.failure}>
            <Text accessibilityRole="alert" style={styles.failureText}>{t(sessionNotice)}</Text>
            <Pressable accessibilityRole="button" onPress={newSearch} style={styles.retry}>
              <Text style={styles.retryText}>{t('chat.session.newSearch')}</Text>
            </Pressable>
          </View> : null}
          {memorySaved ? <Text accessibilityRole="alert" style={styles.note}>{t('chat.memory.saved')}</Text> : null}
          {memoryError ? <Text accessibilityRole="alert" style={styles.failureText}>{t('chat.memory.error')}</Text> : null}
          {memoryOpen && userId ? <View style={styles.conditionArea}>
            <Text accessibilityRole="header" style={styles.conditionTitle}>{t('chat.memory.manage')}</Text>
            {!memory.memories.length && !memory.busy && !memoryError ? <Text style={styles.note}>{t('chat.memory.empty')}</Text> : null}
            {memory.memories.map((item) => <View key={item.id} style={styles.conditionGroup}>
              <Text style={styles.conditionLabel}>{t(item.kind === 'profile' ? 'chat.memory.profile'
                : item.kind === 'owned_product' ? 'chat.memory.ownedProduct' : 'chat.memory.preference')}</Text>
              {memoryEdit?.id === item.id ? <TextInput accessibilityLabel={t('chat.memory.edit')}
                value={memoryEdit.value} maxLength={500}
                onChangeText={(value) => setMemoryEdit({ id: item.id, value })} style={styles.input} />
                : <Text style={styles.messageText}>{item.value}</Text>}
              <View style={styles.conditionList}>
                <Pressable accessibilityRole="button" disabled={memory.busy || isPending}
                  onPress={() => {
                    if (memoryEdit?.id !== item.id) { setMemoryEdit({ id: item.id, value: item.value }); return; }
                    void memory.update(item, memoryEdit.value).then(() => {
                      if (mounted.current && owned()) {
                        store().invalidateMemoryContext(ownerKey);
                        setMemoryEdit(undefined); setMemoryError(false);
                      }
                    }).catch(() => { if (mounted.current && owned()) setMemoryError(true); });
                  }} style={styles.retry}>
                  <Text style={styles.retryText}>{t(memoryEdit?.id === item.id ? 'chat.memory.saveEdit' : 'chat.memory.edit')}</Text>
                </Pressable>
                {memoryEdit?.id === item.id ? <Pressable accessibilityRole="button"
                  onPress={() => setMemoryEdit(undefined)} style={styles.retry}>
                  <Text style={styles.retryText}>{t('chat.memory.cancel')}</Text>
                </Pressable> : null}
                <Pressable accessibilityRole="button" disabled={memory.busy || isPending}
                  onPress={() => {
                    if (memoryDelete !== item.id) { setMemoryDelete(item.id); return; }
                    void memory.remove(item).then(() => {
                      if (mounted.current && owned()) {
                        store().invalidateMemoryContext(ownerKey);
                        setMemoryDelete(undefined); setMemoryError(false); setMemorySaved(false);
                      }
                    }).catch(() => { if (mounted.current && owned()) setMemoryError(true); });
                  }} style={styles.retry}>
                  <Text style={styles.retryText}>{t(memoryDelete === item.id ? 'chat.memory.confirmDelete' : 'chat.memory.delete')}</Text>
                </Pressable>
                {memoryDelete === item.id ? <Pressable accessibilityRole="button"
                  onPress={() => setMemoryDelete(undefined)} style={styles.retry}>
                  <Text style={styles.retryText}>{t('chat.memory.cancel')}</Text>
                </Pressable> : null}
              </View>
            </View>)}
          </View> : null}
          {visibleMessages.map((message, messageIndex) => (
            <View key={message.id} style={styles.messageGroup}>
              {message.role === 'assistant' && message.fragranceSearchSummary ? (
                <FragranceSearchResult message={message} selectedShades={selectedShades} selectedProductId={chosenProductId}
                  onSelectProduct={canSelect(message) ? (productId) => selectProduct(productId, message) : undefined}
                  onSelectShade={(productId, shadeId) => selectShade(productId, shadeId, message)} />
              ) : message.role === 'assistant' && !message.knowledge && !message.styleRecipe && (message.category === 'ingredient' || message.ingredientResults?.length) ? (
                <IngredientResult
                  heading={t('chat.ui.ingredient')}
                  summary={displayAssistantText(message.text)}
                  notice={t('chat.ui.ingredientGeneralNotice')}
                  labels={{ product: t('chat.result.productInfo'), ingredients: t('chat.result.ingredientList'), source: t('chat.result.source'), unknown: t('chat.conditionUnknown') }}
                  results={message.ingredientResults}
                  products={message.products}
                  shadeSelections={message.chatContext?.shadeSelections}
                />
              ) : message.role === 'assistant' && message.styleRecipe && !visibleMessages.slice(0, messageIndex).some((item) =>
                item.styleRecipe?.recipeId === message.styleRecipe?.recipeId && item.styleRecipe?.recipeVersion === message.styleRecipe?.recipeVersion) ? (
                <>
                {message.text && message.styleRecipe.steps.length ? <View style={[styles.message, styles.assistantMessage]}><Text style={styles.messageText}>{displayAssistantText(message.text)}</Text></View> : null}
                <StyleRecipeResult
                  result={message.styleRecipe && message.styleRecipe.recipeId === activeStyle?.recipeId &&
                    message.styleRecipe.recipeVersion === activeStyle?.recipeVersion
                    ? { ...message.styleRecipe, currentStep: activeStyle.currentStep } : message.styleRecipe}
                  disabled={isPending || message.ownerKey !== ownerKey ||
                    message.styleRecipe?.recipeId !== activeStyle?.recipeId || message.styleRecipe?.recipeVersion !== activeStyle?.recipeVersion}
                  onStepChange={(index) => {
                    const recipe = message.styleRecipe;
                    if (mounted.current && recipe && recipe.recipeId === activeStyle?.recipeId &&
                      recipe.recipeVersion === activeStyle?.recipeVersion && Number.isInteger(index) && index >= 0 && index < recipe.steps.length) {
                      void persistSelection('set_recipe_step', { kind: recipe.kind, lookId: recipe.lookId,
                        recipeVersion: recipe.recipeVersion, currentStep: index },
                      () => store().setRecipeStep(target, message.id, index));
                    }
                  }}
                  onOpenProduct={(id, shadeId) => { if (mounted.current) router.push(productHref(id, shadeId, undefined, message.styleRecipe?.kind === 'video')); }}
                  onOpenAr={(productId, shadeId) => { if (mounted.current) router.push(arHref({ productId, shadeId })); }}
                  onManualAr={() => { if (mounted.current) router.push(arHref()); }}
                  heading={t('chat.ui.style')}
                  summary={displayAssistantText(message.text)}
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
                </>
              ) : <View style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}>
                {message.role === 'assistant' ? (
                  <View style={styles.answerHeader}>
                    <View style={styles.answerIcon}><Ionicons name="sparkles" size={14} color={theme.colors.rose} /></View>
                    <Text style={styles.answerTitle}>{t('chat.ui.title')}</Text>
                  </View>
                ) : null}
                <Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.role === 'assistant' ? displayAssistantText(message.text) : message.text}</Text>
                {message.knowledge ? <KnowledgeCitations evidence={message.knowledge.evidence} /> : null}
              </View>}
              {message.memoryProposal && userId && message.ownerKey === ownerKey &&
                message.generation === conversationGeneration && !dismissedProposals.includes(message.memoryProposal.proposalId)
                ? <View style={styles.conditionArea}>
                  <Text accessibilityRole="header" style={styles.conditionTitle}>{t('chat.memory.proposal')}</Text>
                  <Text style={styles.conditionLabel}>{t(message.memoryProposal.kind === 'profile' ? 'chat.memory.profile'
                    : message.memoryProposal.kind === 'owned_product' ? 'chat.memory.ownedProduct' : 'chat.memory.preference')}</Text>
                  <Text style={styles.messageText}>{message.memoryProposal.value}</Text>
                  <Text style={styles.note}>{t('chat.memory.purpose')}</Text>
                  <View style={styles.conditionList}>
                    <Pressable accessibilityRole="button" disabled={memory.busy || isPending}
                      onPress={() => {
                        const proposal = message.memoryProposal!;
                        void memory.confirm(proposal).then(() => {
                          if (mounted.current && owned()) {
                            store().invalidateMemoryContext(ownerKey);
                            setDismissedProposals((ids) => [...ids, proposal.proposalId]);
                            setMemorySaved(true);
                            setMemoryError(false);
                          }
                        }).catch(() => { if (mounted.current && owned()) setMemoryError(true); });
                      }} style={styles.retry}>
                      <Text style={styles.retryText}>{t('chat.memory.confirm')}</Text>
                    </Pressable>
                    <Pressable accessibilityRole="button" disabled={memory.busy || isPending}
                      onPress={() => setDismissedProposals((ids) => [...ids, message.memoryProposal!.proposalId])}
                      style={styles.retry}>
                      <Text style={styles.retryText}>{t('chat.memory.dismiss')}</Text>
                    </Pressable>
                  </View>
                </View> : null}
              {message.role === 'assistant' && message.styleCandidates?.length ? <View style={styles.conditionArea}>
                {message.styleCandidates.map((look) => <Pressable key={`${look.kind}:${look.lookId}`}
                  accessibilityRole="button" disabled={isPending || message.ownerKey !== ownerKey || message.generation !== conversationGeneration || message.id !== latestStyleMessageId}
                  accessibilityState={{ disabled: isPending || message.ownerKey !== ownerKey || message.generation !== conversationGeneration || message.id !== latestStyleMessageId }}
                  onPress={() => {
                    if (!mounted.current || !owned() || currentRoom()?.request) return;
                    store().setStyle(target, { kind: look.kind, lookId: look.lookId, currentStep: 0 });
                    void send(t('chat.room.recipePrompt'), undefined, 'style');
                  }} style={[styles.retry, message.id !== latestStyleMessageId && styles.retryDisabled]}>
                  <Text style={styles.retryText}>{look.title}</Text>
                  {look.match ? <Text style={styles.retryText}>{t('chat.style.match', { match: look.match })}</Text> : null}
                </Pressable>)}
              </View> : null}
              {subject.type === 'general' && message.role === 'assistant' && message.category === 'style' && !message.styleRecipe && !message.knowledge && !message.styleCandidates && !activeStyle && message.styleStatus !== 'not_found'
                ? <InlineStyleLookPicker question={message.question ?? ''} onSelect={(lookId) => {
                  if (!mounted.current || !owned() || currentRoom()?.request) return;
                  store().setStyle(target, { kind: 'video', lookId, currentStep: 0 });
                  void send(t('chat.room.recipePrompt'), undefined, 'style');
                }} /> : null}
              {message.failed ? (
                <View style={styles.failure}>
                  <View style={styles.stateIcon}><Ionicons name="alert-circle-outline" size={22} color={theme.colors.danger} /></View>
                  <Text style={styles.failureText} accessibilityRole="alert">{t((message.errorKey ?? 'chat.ui.error') as TranslationKey)}</Text>
                  {message.retryable && message.ownerKey === ownerKey ? <Pressable accessibilityRole="button" accessibilityState={{ disabled: isPending }} disabled={isPending}
                    onPress={() => void send(message.text, message.id, message.category)} style={[styles.retry, isPending && styles.retryDisabled]}>
                    <Text style={styles.retryText}>{t('chat.ui.retry')}</Text>
                  </Pressable> : null}
                  {!message.automatic ? <Pressable accessibilityRole="button" onPress={newSearch} style={styles.retry}>
                    <Text style={styles.retryText}>{t('chat.session.newSearch')}</Text>
                  </Pressable> : null}
                </View>
              ) : null}
              {message.role === 'assistant' && message.optionSearch ? <OptionSearchScope result={message.optionSearch} /> : null}
              {message.role === 'assistant' && !message.fragranceSearchSummary &&
                !!(message.products?.length || (message.styleRecipe?.kind === 'video' && message.styleRecipe.products.length)) &&
                (!message.styleRecipe || (message.styleRecipe.productQuestion ?? /제품|상품|product|商品|製品|产品|사용한.{0,12}(?:립|입술|아이라인|아이라이너|마스카라|컨실러)/i.test(message.question ?? ''))) ? <RelatedProducts refs={message.products ?? []} optionSearch={message.optionSearch}
                sourceProducts={message.styleRecipe?.kind === 'video' ? message.styleRecipe.products : undefined}
                question={message.question ?? ''} category={message.category}
                chatContext={message.chatContext} evidence={message.evidence}
                selectedShades={selectedShades}
                selectedProductId={chosenProductId}
                onSelectProduct={canSelect(message) ? (productId) => selectProduct(productId, message) : undefined}
                onSelectShade={(productId, shadeId) => selectShade(productId, shadeId, message)} /> : null}
              {message.role === 'assistant' && !message.fragranceSearchSummary && !message.knowledge && !message.products?.length && (message.category === 'product' || message.category === undefined) &&
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
          {(messages.length > 0 || subject.type === 'general') && (linkedProduct?.productId || (activeStyle && category === 'style')) ? <View style={styles.targetRow}>
            <View style={styles.selectionInfo}>
              {activeStyle && (subject.type === 'look' || category === 'style')
                ? activeStyle.kind === 'video' ? <VideoEntryLabel id={activeStyle.lookId} /> : <CatalogEntryLabel id={activeStyle.lookId} />
                : linkedProduct?.productId ? <ProductEntryLabel id={linkedProduct.productId} shadeId={linkedProduct.shadeId} /> : null}
            </View>
            {subject.type === 'general' ? <Pressable accessibilityRole="button" accessibilityLabel={t('chat.room.clearFocus')}
              onPress={clearFocus} style={styles.headerAction}><Ionicons name="close" size={20} color={theme.colors.roseDark} /></Pressable> : null}
          </View> : null}
          {messages.length > 0 && subject.type === 'product' && linkedProduct?.productId ? <View style={styles.selectionBar}>
            {([['chat.carousel.ingredient', 'ingredient'], ['chat.carousel.details', 'product'], ['chat.room.compare', 'product']] as const).map(([key, kind]) =>
              <Pressable key={key} accessibilityRole="button" accessibilityLabel={t(key)} disabled={isPending}
                onPress={() => {
                  if (key === 'chat.room.compare') { setInput(t('chat.room.comparePrompt')); inputRef.current?.focus(); }
                  else void send(t(key), undefined, kind);
                }} style={styles.selectionAction}><Text style={styles.selectionActionText}>{t(key)}</Text></Pressable>)}
          </View> : null}
          {subject.type !== 'product' && category !== 'style' && chosenProductId && sessionCandidateIds.includes(chosenProductId) ? (
            <View style={styles.selectionBar}>
              <View style={styles.selectionInfo}>
                <Text style={styles.selectionLabel}>{t('chat.carousel.chosen')}</Text>
                <Text style={styles.selectionName} numberOfLines={1}>
                  {sessionCandidateIds.indexOf(chosenProductId) + 1}{t('chat.carousel.ordinal')}
                  {' · '}
                  {messages.flatMap((item) => item.products ?? []).find((p) => p.id === chosenProductId)?.name ?? chosenProductId}
                </Text>
              </View>
              <Pressable accessibilityRole="button" accessibilityLabel={t('chat.carousel.ingredient')}
                accessibilityState={{ disabled: isPending }}
                disabled={isPending} onPress={() => void send(t('chat.carousel.ingredient'), undefined, 'ingredient')}
                style={styles.selectionAction}>
                <Text style={styles.selectionActionText}>{t('chat.carousel.ingredient')}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={t('chat.carousel.details')}
                accessibilityState={{ disabled: isPending }}
                disabled={isPending} onPress={() => void send(t('chat.carousel.details'), undefined, 'product')}
                style={styles.selectionAction}>
                <Text style={styles.selectionActionText}>{t('chat.carousel.details')}</Text>
              </Pressable>
            </View>
          ) : null}
          <View style={styles.inputRow}>
            <TextInput ref={inputRef} accessibilityLabel={t('chat.ui.placeholder')} editable={!isPending} maxLength={2000}
              multiline onChangeText={(value) => setInput(Array.from(value).slice(0, 1000).join(''))} onFocus={() => setEditing(true)} onBlur={() => setEditing(false)}
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
  problemHeading: { marginTop: 16, marginBottom: 4, color: theme.colors.ink, fontWeight: '700', fontSize: theme.font.body },
  problemPrompts: { gap: 9 },
  problemPrompt: { minHeight: 70, flexDirection: 'row', alignItems: 'center', gap: 12,
    paddingHorizontal: 14, paddingVertical: 12, borderRadius: theme.radius.lg, borderColor: theme.colors.border, borderWidth: 1,
    backgroundColor: theme.colors.card },
  problemIcon: { height: 38, width: 38, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  problemText: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '600', lineHeight: 20 },
  problemHint: { marginTop: 4, color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 18 },
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
  entryLabel: { color: theme.colors.roseDark, fontSize: theme.font.caption, paddingHorizontal: 10 },
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
  headerActions: { flexDirection: 'row' },
  headerAction: { minHeight: 44, minWidth: 44, alignItems: 'center', justifyContent: 'center' },
  targetWelcome: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg, padding: 16, gap: 10 },
  targetRow: { flexDirection: 'row', alignItems: 'center', minHeight: 35, marginBottom: 4 },
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
