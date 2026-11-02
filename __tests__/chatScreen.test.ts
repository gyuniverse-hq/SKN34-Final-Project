import { createElement } from 'react';
import { Keyboard, KeyboardAvoidingView, Platform, Text, TextInput } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import ChatScreen from '@/app/chat';
import type { BeautyChatContext, ChatStyleRecipe } from '@/types';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import { ApiError } from '@/lib/api';
import { en } from '@/lib/i18n/en';
import { ko } from '@/lib/i18n/ko';
import { ja } from '@/lib/i18n/ja';
import { zh } from '@/lib/i18n/zh';

jest.setTimeout(20000);

const mockMutateAsync = jest.fn();
const mockUseChat = jest.fn(() => ({ mutateAsync: mockMutateAsync, isPending: false }));
const mockProductsByIds = jest.fn();
const mockPush = jest.fn();
const mockRefetch = jest.fn();
const mockAuth = jest.fn((): { user: { id: string } | null; ready: boolean } => ({ user: null, ready: true }));
let mockLanguage = 'ko';
let mockDictionary: Record<string, string> | undefined;

const beautyContext: BeautyChatContext = {
  version: 1, issuedAt: 1000, candidateIds: ['p1', 'p2'], scopeIds: ['p1', 'p2'],
  selectedProductId: null,
  filters: { category: 'lip', maxPriceKRW: 20000, fragranceFree: false, moisturizing: true, query: '' },
};

jest.mock('@/hooks/useChat', () => ({ useChat: () => mockUseChat() }));
jest.mock('@/lib/auth', () => ({ useAuth: () => mockAuth(), getAccessToken: async () => null }));
jest.mock('@/lib/auth/client', () => ({ getSupabase: () => null, isAuthConfigured: () => false }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => mockDictionary?.[key] ?? key, language: mockLanguage }) }));
jest.mock('@/lib/queries', () => ({ useProductsByIds: (ids: string[]) => mockProductsByIds(ids) }));
jest.mock('@/components/chat/ChatProducts', () => ({ ChatProducts: () => null }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
const mockRouteParams: { recipeKind?: string; recipeLookId?: string } = {};
jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useRouter: () => ({ push: mockPush }), useLocalSearchParams: () => mockRouteParams }));
jest.mock('expo-router/react-navigation', () => ({ useHeaderHeight: () => 88 }));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: ({ children }: { children: unknown }) => children,
}));

function buttonWithText(root: ReactTestInstance, text: string) {
  const label = root.findAll((item) => item.props.children === text)[0];
  let button = label?.parent;
  while (button && typeof button.props.onPress !== 'function') button = button.parent;
  if (!button) throw new Error(`Button not found: ${text}`);
  return button;
}

async function renderScreen(): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(createElement(ChatScreen), {
      createNodeMock: () => ({ focus: jest.fn(), scrollToEnd: jest.fn() }),
    });
  });
  return renderer;
}

beforeEach(() => {
  delete mockRouteParams.recipeKind; delete mockRouteParams.recipeLookId;
  mockMutateAsync.mockReset();
  mockUseChat.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
  mockProductsByIds.mockReset().mockReturnValue({ data: [], isPending: false, isError: false, refetch: mockRefetch });
  mockPush.mockReset();
  mockRefetch.mockReset();
  mockAuth.mockReturnValue({ user: null, ready: true });
  mockLanguage = 'ko';
  mockDictionary = undefined;
});

describe('selected Style recipe flow', () => {
  const recipe: ChatStyleRecipe = {
    kind: 'video', lookId: '_video-1', sourceLookId: '_video-1', recipeId: 'video:_video-1', recipeVersion: 'fixture-v1',
    title: 'Synthetic selected look', basis: 'video_metadata', reviewStatus: 'unreviewed', videoAnalyzed: false,
    synthetic: true, source: 'fixture:metadata', features: ['Fixture'], products: [], arEligible: false,
    currentStep: 0, reason: 'video_not_analyzed', steps: [
      { order: 1, zone: 'eyeshadow', title: 'Fixture eyes', guideKey: 'eyeshadow' },
      { order: 2, zone: 'lip', title: 'Fixture lips', guideKey: 'lip' },
    ],
  };
  const context = { kind: 'video' as const, lookId: '_video-1', recipeId: recipe.recipeId,
    recipeVersion: recipe.recipeVersion, currentStep: 0 };
  async function submit(view: ReactTestRenderer, text: string) {
    await act(async () => view.root.findByType(TextInput).props.onChangeText(text));
    await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress());
  }
  it('uses the selected video, keeps displayed progress in followups and leaves product context separate', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Metadata, not video analysis', products: [], styleRecipe: recipe,
      styleContext: context, styleStatus: 'ready' }).mockResolvedValueOnce({ answer: 'Next', products: [],
      styleRecipe: { ...recipe, currentStep: 0 }, styleContext: { ...context, currentStep: 0 }, styleStatus: 'ready' });
    const view = await renderScreen();
    await submit(view, '이 룩 특징');
    expect(mockMutateAsync.mock.calls[0][0]).toMatchObject({ category: 'style', styleContext: { kind: 'video', lookId: '_video-1', currentStep: 0 } });
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    expect(view.root.findByType(StyleRecipeResult).props.result.currentStep).toBe(1);
    await submit(view, '눈 화장부터 알려줘');
    expect(mockMutateAsync.mock.calls[1][0].styleContext).toEqual({ ...context, currentStep: 1 });
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toBeUndefined();
    expect(view.root.findAllByType(StyleRecipeResult).every((node) => node.props.result.currentStep === 0)).toBe(true);
    await act(async () => view.unmount());
  });
  it('retries the exact Style snapshot and request UUID after a network failure', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockRejectedValueOnce(new ApiError('network', 0)).mockResolvedValueOnce({ answer: 'Recovered', products: [],
      styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    await submit(view, '이 룩 특징');
    const snapshot = mockMutateAsync.mock.calls[0][0];
    await act(async () => buttonWithText(view.root, 'chat.ui.retry').props.onPress());
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(snapshot);
    expect(view.root.findByType(StyleRecipeResult).props.result.lookId).toBe('_video-1');
    await act(async () => view.unmount());
  });
  it('does not carry prior Style progress across an authentication owner change', async () => {
    Object.assign(mockRouteParams, { recipeKind: 'video', recipeLookId: '_video-1' });
    mockMutateAsync.mockResolvedValue({ answer: 'Metadata', products: [], styleRecipe: recipe, styleContext: context });
    const view = await renderScreen();
    await submit(view, '이 룩 특징');
    await act(async () => view.root.findByType(StyleRecipeResult).props.onStepChange(1));
    mockAuth.mockReturnValue({ user: { id: 'new-owner' }, ready: true });
    await act(async () => view.update(createElement(ChatScreen)));
    await submit(view, '이 룩 특징');
    expect(mockMutateAsync.mock.calls.at(-1)[0].styleContext).toEqual({ kind: 'video', lookId: '_video-1', currentStep: 0 });
    await act(async () => view.unmount());
  });
});

describe('server session recovery', () => {
  const context: BeautyChatContext = { ...beautyContext, session: {
    sessionId: '10000000-0000-4000-8000-000000000001',
    sessionToken: 'SYNTHETIC_CAPABILITY_NEVER_DISPLAY_12345678',
    resultSetId: '10000000-0000-4000-8000-000000000002', stateVersion: 1, expiresAt: 9999999999,
  } };
  async function send(view: ReactTestRenderer, text: string) {
    await act(async () => { view.root.findByType(TextInput).props.onChangeText(text); });
    await act(async () => { view.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
  }
  function texts(view: ReactTestRenderer) { return view.root.findAllByType(Text).map((n) => n.props.children); }

  it('carries the session and version, uses a new UUID for each question, and never displays the token', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Stored first result', products: [], chatContext: context, sessionStatus: 'stored' })
      .mockResolvedValueOnce({ answer: 'Second product', products: [] });
    const view = await renderScreen();
    await send(view, '립 추천');
    await send(view, '두 번째 상품 가격');
    const first = mockMutateAsync.mock.calls[0][0];
    const next = mockMutateAsync.mock.calls[1][0];
    expect(next.chatContext.session).toEqual(context.session);
    expect(next.chatContext.candidateIds).toEqual(['p1', 'p2']);
    expect(first.requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(next.requestId).not.toBe(first.requestId);
    expect(JSON.stringify(view.toJSON())).not.toContain(context.session!.sessionToken);
    await act(async () => { view.unmount(); });
  });

  it('keeps UUID, language, category and session snapshot for a network retry', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'List', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockResolvedValueOnce({ answer: 'Retry', products: [] });
    const view = await renderScreen();
    await send(view, '추천');
    mockLanguage = 'ja';
    await act(async () => { view.update(createElement(ChatScreen)); });
    await act(async () => { buttonWithText(view.root, 'chat.ui.ingredient').props.onPress(); });
    await send(view, '성분');
    const snapshot = mockMutateAsync.mock.calls[1][0];
    mockLanguage = 'en';
    await act(async () => { view.update(createElement(ChatScreen)); });
    await act(async () => { buttonWithText(view.root, 'chat.ui.style').props.onPress(); });
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0]).toEqual(snapshot);
    expect(snapshot.locale).toBe('ja');
    expect(snapshot.category).toBe('ingredient');
    await act(async () => { view.unmount(); });
  });

  it.each([
    [403, 'chat_session_forbidden', 'chat.session.forbidden'],
    [409, 'chat_session_conflict', 'chat.session.conflict'],
    [409, 'chat_request_conflict', 'chat.session.conflict'],
    [410, 'chat_session_expired', 'chat.session.expired'],
  ])('recovers %s/%s with no stale retry or candidate reference', async (status, code, key) => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Last normal answer', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('failure', status as number, code as string))
      .mockResolvedValueOnce({ answer: 'Fresh search', products: [] });
    const view = await renderScreen();
    await send(view, '상품 검색');
    await send(view, '두 번째 상품');
    expect(texts(view)).toContain(key);
    expect(texts(view)).toContain('Last normal answer');
    expect(texts(view)).not.toContain('chat.ui.retry');
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    await act(async () => { buttonWithText(view.root, 'chat.session.newSearch').props.onPress(); });
    await send(view, '립 상품 검색');
    const fresh = mockMutateAsync.mock.calls[2][0];
    expect(fresh.chatContext).toBeUndefined();
    expect(fresh.screenContext).toBeUndefined();
    expect(fresh.requestId).not.toBe(mockMutateAsync.mock.calls[1][0].requestId);
    await act(async () => { view.unmount(); });
  });

  it('distinguishes storage failure from a successful answer whose session was not saved', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'List', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('storage', 503, 'chat_session_unavailable'))
      .mockResolvedValueOnce({ answer: 'Computed without persistence', products: [], chatContext: context, sessionStatus: 'unavailable' })
      .mockResolvedValueOnce({ answer: 'Independent', products: [] });
    const view = await renderScreen();
    await send(view, '검색');
    await send(view, '두 번째');
    expect(texts(view)).toContain('chat.session.storageError');
    const failed = mockMutateAsync.mock.calls[1][0];
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0]).toEqual(failed);
    expect(texts(view)).toContain('chat.session.unavailable');
    expect(texts(view)).toContain('Computed without persistence');
    expect(texts(view)).not.toContain('chat.ui.retry');
    await send(view, '립 검색');
    expect(mockMutateAsync.mock.calls[3][0].chatContext).toBeUndefined();
    await act(async () => { view.unmount(); });
  });

  it.each([[null, 'A'], ['A', null], ['A', 'B']] as const)(
    'clears private session references on identity switch %s -> %s', async (from, to) => {
      mockAuth.mockReturnValue({ user: from ? { id: from } : null, ready: true });
      mockMutateAsync.mockResolvedValueOnce({ answer: 'Old visible history', products: [], chatContext: context })
        .mockResolvedValueOnce({ answer: 'New owner search', products: [] });
      const view = await renderScreen();
      await send(view, '추천');
      mockAuth.mockReturnValue({ user: to ? { id: to } : null, ready: true });
      await act(async () => { view.update(createElement(ChatScreen)); });
      expect(texts(view)).toContain('Old visible history');
      expect(texts(view)).toContain('chat.session.identityChanged');
      await send(view, '새 립 검색');
      const fresh = mockMutateAsync.mock.calls[1][0];
      expect(fresh.expectedUserId).toBe(to);
      expect(fresh.chatContext).toBeUndefined();
      expect(fresh.screenContext).toBeUndefined();
      await act(async () => { view.unmount(); });
    }
  );

  it('ignores the previous owner response and allows the new owner to send while it is pending', async () => {
    mockAuth.mockReturnValue({ user: { id: 'A' }, ready: true });
    let finish!: (value: unknown) => void;
    mockMutateAsync.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce({ answer: 'B answer', products: [] });
    const view = await renderScreen();
    await send(view, 'A search');
    mockAuth.mockReturnValue({ user: { id: 'B' }, ready: true });
    await act(async () => { view.update(createElement(ChatScreen)); });
    await send(view, 'B search');
    await act(async () => { finish({ answer: 'Late A response', products: [], chatContext: context }); });
    expect(texts(view)).not.toContain('Late A response');
    expect(texts(view)).toContain('B answer');
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toBeUndefined();
    await act(async () => { view.unmount(); });
  });

  it('does not discard a newer normal session when an older failed request later conflicts', async () => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockResolvedValueOnce({ answer: 'Latest normal', products: [], chatContext: context })
      .mockRejectedValueOnce(new ApiError('conflict', 409, 'chat_request_conflict'))
      .mockResolvedValueOnce({ answer: 'Current followup', products: [] });
    const view = await renderScreen();
    await send(view, 'old search');
    await send(view, 'new search');
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    await send(view, '두 번째 상품');
    expect(mockMutateAsync.mock.calls[3][0].chatContext.session).toEqual(context.session);
    await act(async () => { view.unmount(); });
  });

  it('does not loop after a lost bootstrap response returns a duplicate-request conflict', async () => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockRejectedValueOnce(new ApiError('duplicate', 409, 'chat_request_conflict'));
    const view = await renderScreen();
    await send(view, '립 검색');
    const first = mockMutateAsync.mock.calls[0][0];
    await act(async () => { buttonWithText(view.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(first);
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    expect(texts(view)).not.toContain('chat.ui.retry');
    expect(texts(view)).toContain('chat.session.newSearch');
    await act(async () => { view.unmount(); });
  });

  it('waits for authentication readiness before submitting', async () => {
    mockAuth.mockReturnValue({ user: null, ready: false });
    const view = await renderScreen();
    await send(view, '추천');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    expect(view.root.findByType(TextInput).props.editable).toBe(false);
    await act(async () => { view.unmount(); });
  });

  it.each([['en', en], ['ko', ko], ['ja', ja], ['zh', zh]] as const)(
    'renders localized session and network errors in %s', async (locale, dictionary) => {
      mockLanguage = locale;
      mockDictionary = dictionary;
      for (const [status, code, key] of [
        [403, 'chat_session_forbidden', 'chat.session.forbidden'],
        [409, 'chat_session_conflict', 'chat.session.conflict'],
        [410, 'chat_session_expired', 'chat.session.expired'],
        [503, 'chat_session_unavailable', 'chat.session.storageError'],
        [0, 'network', 'chat.ingredient.network'],
      ] as const) {
        mockMutateAsync.mockRejectedValueOnce(new ApiError('error', status, code));
        const view = await renderScreen();
        await act(async () => { view.root.findByType(TextInput).props.onChangeText('query'); });
        await act(async () => { view.root.findByProps({ accessibilityLabel: dictionary['chat.ui.send'] }).props.onPress(); });
        expect(texts(view)).toContain(dictionary[key]);
        await act(async () => { view.unmount(); });
      }
    }
  );
});

describe('ingredient selection and request snapshots', () => {
  async function send(renderer: ReactTestRenderer, text: string) {
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(text); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
  }
  function catalog() {
    mockProductsByIds.mockReturnValue({ data: [
      { id: 'p2', shades: [{ id: 'p2-03' }, { id: 'p2-04' }] },
      { id: 'p1', shades: [{ id: 'p1-01' }] },
    ], isPending: false, isError: false, refetch: mockRefetch });
  }
  const refs = [{ id: 'p1', name: 'First', brand: 'B', category: 'lip' },
    { id: 'p2', name: 'Second', brand: 'B', category: 'lip' }];

  it('validates selection, retains numbering, sends the latest shade and shows server results', async () => {
    catalog();
    const results = [{ productId: 'p2', shadeId: 'p2-04', verdict: 'UNKNOWN', status: 'unknown',
      mappingStatus: 'candidate', ingredientCoverage: 'unknown', reviewStatus: 'unreviewed',
      normalizationStatus: 'unverified', ingredients: [], reason: 'mapping_not_verified' }];
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'Unknown ingredients', products: [refs[1]], ingredientResults: results });
    const renderer = await renderScreen();
    await send(renderer, '상품 추천');
    let cards = renderer.root.findByType(ChatProducts).props;
    expect(cards.products.map((p: { id: string }) => p.id)).toEqual(['p1', 'p2']);
    await act(async () => { cards.onSelectShade('p1', 'p2-03'); });
    expect(renderer.root.findByType(ChatProducts).props.selectedShades).toEqual({});
    await act(async () => { cards.onSelectShade('p2', 'p2-03'); });
    cards = renderer.root.findByType(ChatProducts).props;
    await act(async () => { cards.onSelectShade('p2', 'p2-04'); });
    await send(renderer, '두 번째 상품 성분');
    const sent = mockMutateAsync.mock.calls[1][0];
    expect(sent.chatContext.candidateIds).toEqual(['p1', 'p2']);
    expect(sent.chatContext.shadeSelections).toEqual({ p2: 'p2-04' });
    expect(sent.screenContext).toEqual({ screenId: 'chat', productId: 'p2', shadeId: 'p2-04' });
    expect(renderer.root.findByType(IngredientResult).props.results).toEqual(results);
    await act(async () => { renderer.unmount(); });
  });

  it('keeps retry snapshots and a later user shade against an older server response', async () => {
    catalog();
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: beautyContext })
      .mockRejectedValueOnce(new ApiError('offline', 0, 'network'))
      .mockResolvedValueOnce({ answer: 'Retry result', products: [], chatContext: {
        ...beautyContext, shadeSelections: { p2: 'p2-03' }, selectedProductId: 'p2',
      } })
      .mockResolvedValueOnce({ answer: 'Next', products: [] });
    const renderer = await renderScreen();
    await send(renderer, '추천');
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-03'); });
    await send(renderer, '성분 확인');
    expect(renderer.root.findAllByType(Text).some((n) => n.props.children === 'chat.ingredient.network')).toBe(true);
    const original = mockMutateAsync.mock.calls[1][0];
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-04'); });
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0]).toEqual(original);
    await send(renderer, '다시 성분');
    expect(mockMutateAsync.mock.calls[3][0].chatContext.shadeSelections).toEqual({ p2: 'p2-04' });
    await act(async () => { renderer.unmount(); });
  });

  it.each([
    [503, undefined, 'chat.ingredient.server'],
    [404, 'not_found', 'chat.ingredient.productMissing'],
    [404, 'shade_not_found', 'chat.ingredient.shadeMissing'],
  ])('localizes transport error %s/%s', async (status, code, key) => {
    mockMutateAsync.mockRejectedValueOnce(new ApiError('failure', status as number, code as string));
    const renderer = await renderScreen();
    await send(renderer, '성분');
    expect(renderer.root.findAllByType(Text).some((n) => n.props.children === key)).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  it('merges a shade selected during a pending request with the latest server candidate order', async () => {
    catalog();
    let finish!: (value: unknown) => void;
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: refs, chatContext: beautyContext })
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce({ answer: 'Next', products: [] });
    const renderer = await renderScreen();
    await send(renderer, '추천');
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-03'); });
    await send(renderer, '성분');
    await act(async () => { renderer.root.findByType(ChatProducts).props.onSelectShade('p2', 'p2-04'); });
    await act(async () => { finish({ answer: 'Old shade result', products: [], chatContext: {
      ...beautyContext, candidateIds: ['p2', 'p1'], selectedProductId: 'p2', shadeSelections: { p2: 'p2-03' },
    } }); });
    await send(renderer, '두 번째 성분');
    const sent = mockMutateAsync.mock.calls[2][0];
    expect(sent.chatContext.candidateIds).toEqual(['p2', 'p1']);
    expect(sent.chatContext.shadeSelections).toEqual({ p2: 'p2-04' });
    await act(async () => { renderer.unmount(); });
  });
});

describe('standalone chat input', () => {
  it('carries effective filters and candidate order into a follow-up', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Candidates', products: [], chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'Details', products: [] });
    const renderer = await renderScreen();
    for (const text of ['2만원 이하 립 추천', '두 번째 제품 자세히']) {
      await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(text); });
      await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    }
    expect(mockMutateAsync.mock.calls[0][0]).toEqual(expect.objectContaining({ message: '2만원 이하 립 추천', locale: 'ko', category: 'product' }));
    expect(mockMutateAsync.mock.calls[1][0]).toEqual(expect.objectContaining({ message: '두 번째 제품 자세히', locale: 'ko', category: 'product', chatContext: beautyContext }));
    await act(async () => { renderer.unmount(); });
  });

  it('retries with original context without replacing a newer successful candidate list', async () => {
    const newer = { ...beautyContext, candidateIds: ['new-1'], scopeIds: ['new-1'] };
    mockMutateAsync.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ answer: 'New list', products: [], chatContext: newer })
      .mockResolvedValueOnce({ answer: 'Old retry', products: [], chatContext: beautyContext })
      .mockResolvedValueOnce({ answer: 'Latest', products: [] });
    const renderer = await renderScreen();
    for (const text of ['Old question', 'New question']) {
      await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(text); });
      await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    }
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync.mock.calls[2][0].chatContext).toBeUndefined();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('그 제품 자세히'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[3][0].chatContext).toEqual(newer);
    await act(async () => { renderer.unmount(); });
  });

  it('shows the price and moisturizing preference for the English example', async () => {
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Recommend a moisturizing lip product under ₩20,000.'); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('under ₩20,000');
    expect(texts).toContain('moisturizing');
    expect(texts).toContain('chat.ui.preferred');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('shows extracted required and preferred conditions only while present in the draft', async () => {
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onFocus(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 중 2만 원 이하 추천해줘, 촉촉함 우선'); });
    const texts = () => renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts()).toContain('chat.ui.conditions');
    expect(texts()).toContain('chat.ui.required');
    expect(texts()).toContain('chat.ui.preferred');
    expect(texts()).toContain('2만 원 이하');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('메이크업 방법 알려줘'); });
    expect(texts()).not.toContain('chat.ui.conditions');
    expect(texts()).not.toContain('2만 원 이하');
    await act(async () => { renderer.unmount(); });
  });

  it('keeps the draft and controls available while focused, and restores the welcome area on blur or keyboard dismissal', async () => {
    const listeners: Partial<Record<'keyboardDidShow' | 'keyboardDidHide', Parameters<typeof Keyboard.addListener>[1]>> = {};
    const removals: Partial<Record<'keyboardDidShow' | 'keyboardDidHide', jest.Mock>> = {};
    const keyboardListener = jest.spyOn(Keyboard, 'addListener').mockImplementation((event, listener) => {
      const remove = jest.fn();
      if (event === 'keyboardDidShow' || event === 'keyboardDidHide') {
        listeners[event] = listener;
        removals[event] = remove;
      }
      return { remove };
    });
    const renderer = await renderScreen();
    if (Platform.OS === 'ios') {
      expect(renderer.root.findByType(KeyboardAvoidingView).props.keyboardVerticalOffset).toBe(88);
    }
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(true);
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('draft question'); });
    await act(async () => { renderer.root.findByType(TextInput).props.onFocus(); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(false);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeBody')).toBe(false);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.examples')).toBe(false);
    expect(buttonWithText(renderer.root, 'chat.ui.product')).toBeTruthy();
    expect(renderer.root.findByType(TextInput).props.value).toBe('draft question');
    expect(renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.disabled).toBe(false);
    await act(async () => { renderer.root.findByType(TextInput).props.onBlur(); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(true);
    await act(async () => { renderer.root.findByType(TextInput).props.onFocus(); });
    expect(listeners.keyboardDidHide).toBeDefined();
    await act(async () => { listeners.keyboardDidHide?.({} as never); });
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'chat.ui.welcomeTitle')).toBe(true);
    expect(renderer.root.findByType(TextInput).props.value).toBe('draft question');
    await act(async () => { renderer.unmount(); });
    expect(removals.keyboardDidShow).toHaveBeenCalledTimes(1);
    expect(removals.keyboardDidHide).toHaveBeenCalledTimes(1);
    keyboardListener.mockRestore();
  });

  it('changes category examples and fills the draft without sending', async () => {
    const renderer = await renderScreen();
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.ingredient').props.onPress(); });
    expect(buttonWithText(renderer.root, 'chat.ui.ingredientQuestion1')).toBeTruthy();
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.ingredientQuestion1').props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('chat.ui.ingredientQuestion1');
    expect(mockMutateAsync).not.toHaveBeenCalled();
    await act(async () => { renderer.unmount(); });
  });

  it('shows the ingredient guidance with its general-information notice', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Ingredient explanation', products: [] });
    const renderer = await renderScreen();
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.ingredient').props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Ingredient question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('Ingredient explanation');
    expect(texts).toContain('chat.ui.ingredientGeneralNotice');
    expect(texts).not.toContain('chat.ui.noProducts');
    await act(async () => { renderer.unmount(); });
  });

  it('opens style browsing above chat while keeping the current draft', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Style answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.style').props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Style question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Next draft'); });
    const browseLabel = renderer.root.findAllByType(Text).find((item) =>
      Array.isArray(item.props.children) && item.props.children[0] === 'chat.ui.styleBrowse');
    let browseButton = browseLabel?.parent;
    while (browseButton && typeof browseButton.props.onPress !== 'function') browseButton = browseButton.parent;
    if (!browseButton) throw new Error('Style browse button not found');
    await act(async () => { browseButton!.props.onPress(); });
    expect(mockPush).toHaveBeenCalledWith('/style-browse');
    expect(renderer.root.findByType(TextInput).props.value).toBe('Next draft');
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'Style answer')).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  it('restores a failed draft and retries without duplicating the user message', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ answer: 'Answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('test question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('test question');
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    expect(mockMutateAsync).toHaveBeenCalledTimes(2);
    expect(renderer.root.findAllByType(Text).filter((item) => item.props.children === 'test question')).toHaveLength(1);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'Answer')).toBe(true);
    await act(async () => { renderer.unmount(); });
  });

  it('marks a failed message retry unavailable while another response is pending', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('offline'));
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('test question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('test question');
    expect(renderer.root.findByProps({ accessibilityRole: 'alert' }).props.children).toBe('chat.ui.error');
    mockMutateAsync.mockImplementationOnce(() => new Promise(() => {}));
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('another question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const retry = buttonWithText(renderer.root, 'chat.ui.retry');
    expect(retry.props.disabled).toBe(true);
    expect(retry.props.accessibilityState).toEqual({ disabled: true });
    await act(async () => { renderer.unmount(); });
  });

  it('places an older retried answer immediately after its question', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ answer: 'Second answer', products: [] })
      .mockResolvedValueOnce({ answer: 'First answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('First question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('Second question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.retry').props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts.indexOf('First question')).toBeLessThan(texts.indexOf('First answer'));
    expect(texts.indexOf('First answer')).toBeLessThan(texts.indexOf('Second question'));
    expect(texts.indexOf('Second question')).toBeLessThan(texts.indexOf('Second answer'));
    await act(async () => { renderer.unmount(); });
  });

  it('does not show a product-empty state for a general question in the default tab', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'General answer', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('메이크업 방법 알려줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findAllByType(Text).map((item) => item.props.children)).not.toContain('chat.ui.noProducts');
    await act(async () => { renderer.unmount(); });
  });

  it('lets the user edit a product question when no products were returned', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'No matches', products: [] });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 추천해줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(renderer.root.findAllByType(Text).map((item) => item.props.children)).toContain('chat.ui.noProducts');
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('다른 초안'); });
    expect(renderer.root.findAllByType(Text).map((item) => item.props.children)).not.toContain('chat.ui.editQuestion');
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText(''); });
    await act(async () => { buttonWithText(renderer.root, 'chat.ui.editQuestion').props.onPress(); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('립 제품 추천해줘');
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => { renderer.unmount(); });
  });

  it('prevents concurrent submissions while a response is pending', async () => {
    let finish!: (value: { answer: string; products: never[] }) => void;
    mockMutateAsync.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('question'); });
    const send = renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress;
    await act(async () => { send(); send(); });
    expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ answer: 'Answer', products: [] }); });
    await act(async () => { renderer.unmount(); });
  });
});

describe('standalone chat product references', () => {
  const refs = [
    { id: 'p1', brand: 'B1', name: 'N1', category: 'lip' },
    { id: 'p2', brand: 'B2', name: 'N2', category: 'lip' },
    { id: 'p1', brand: 'B1', name: 'N1', category: 'lip' },
  ];

  async function showProducts() {
    mockMutateAsync.mockResolvedValueOnce({ answer: 'Answer', products: refs });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('question'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    return renderer;
  }

  it('matches only response IDs and reports missing products', async () => {
    const found = { id: 'p2', name: 'Real product' };
    mockProductsByIds.mockReturnValue({ data: [{ id: 'unrelated' }, found], isPending: false, isError: false, refetch: mockRefetch });
    const renderer = await showProducts();
    expect(mockProductsByIds).toHaveBeenCalledWith(['p1', 'p2']);
    const props = renderer.root.findByType(ChatProducts).props;
    expect(props.products).toEqual([found]);
    expect(props.missingCount).toBe(1);
    expect(props.failed).toBe(false);
    const answer = renderer.root.findAllByType(Text).find((item) => item.props.children === 'Answer');
    expect(answer?.parent?.findAllByType(ChatProducts)).toHaveLength(0);
    await act(async () => { renderer.unmount(); });
  });

  it('hides placeholder products from an earlier lookup', async () => {
    mockProductsByIds.mockReturnValue({ data: [{ id: 'p1' }], isPending: false, isPlaceholderData: true, isError: false, refetch: mockRefetch });
    const renderer = await showProducts();
    const props = renderer.root.findByType(ChatProducts).props;
    expect(props.products).toEqual([]);
    expect(props.loading).toBe(true);
    expect(props.missingCount).toBe(0);
    await act(async () => { renderer.unmount(); });
  });

  it('exposes product lookup failure and retry', async () => {
    mockProductsByIds.mockReturnValue({ data: undefined, isPending: false, isError: true, refetch: mockRefetch });
    const renderer = await showProducts();
    const props = renderer.root.findByType(ChatProducts).props;
    expect(props.failed).toBe(true);
    expect(props.missingCount).toBe(0);
    await act(async () => { props.onRetry(); });
    expect(mockRefetch).toHaveBeenCalledTimes(1);
    await act(async () => { renderer.unmount(); });
  });

  it('keeps message and draft on product navigation while the screen stays mounted', async () => {
    mockProductsByIds.mockReturnValue({ data: [{ id: 'p1' }], isPending: false, isError: false, refetch: mockRefetch });
    const renderer = await showProducts();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('next draft'); });
    await act(async () => { renderer.root.findByType(ChatProducts).props.onOpenProduct('p1'); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: '/product/[id]', params: { id: 'p1' } });
    await act(async () => { renderer.update(createElement(ChatScreen)); });
    expect(renderer.root.findByType(TextInput).props.value).toBe('next draft');
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'question')).toBe(true);
    expect(renderer.root.findAllByType(Text).some((item) => item.props.children === 'Answer')).toBe(true);
    await act(async () => { renderer.unmount(); });
  });
});

describe('structured consultation outcomes', () => {
  it('shows an empty outcome without failure or a retry and preserves follow-up scope', async () => {
    const empty = { ...beautyContext, candidateIds: [],
      filters: { ...beautyContext.filters, fragranceFree: true } };
    mockMutateAsync.mockResolvedValueOnce({ answer: '전성분 미확인', products: [],
      resultType: 'empty', chatContext: empty })
      .mockResolvedValueOnce({ answer: 'Restored', products: [], resultType: 'recommendations' });
    const renderer = await renderScreen();
    // No keyword heuristic is needed for the server's structured empty result.
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('아까 것 중 향료 없는 것만'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('전성분 미확인');
    expect(texts).toContain('chat.ui.noProducts');
    expect(texts).not.toContain('chat.ui.error');
    expect(texts).not.toContain('chat.ui.retry');
    expect(renderer.root.findAllByProps({ accessibilityRole: 'alert' })).toHaveLength(0);
    expect(mockProductsByIds).not.toHaveBeenCalled();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('향료 조건만 빼줘.'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    expect(mockMutateAsync.mock.calls[1][0].chatContext).toEqual(empty);
    await act(async () => { renderer.unmount(); });
  });

  it('does not turn clarification into a second empty-result message', async () => {
    mockMutateAsync.mockResolvedValueOnce({ answer: '후보 번호를 알려주세요', products: [],
      resultType: 'clarification', chatContext: beautyContext });
    const renderer = await renderScreen();
    await act(async () => { renderer.root.findByType(TextInput).props.onChangeText('립 제품 중 그 제품 알려줘'); });
    await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.onPress(); });
    const texts = renderer.root.findAllByType(Text).map((item) => item.props.children);
    expect(texts).toContain('후보 번호를 알려주세요');
    expect(texts).not.toContain('chat.ui.noProducts');
    expect(texts).not.toContain('chat.ui.retry');
    await act(async () => { renderer.unmount(); });
  });
});
