import { createElement } from 'react';
import { Keyboard, KeyboardAvoidingView, Platform, Text, TextInput } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import ChatScreen from '@/app/chat';
import type { BeautyChatContext } from '@/types';
import { ChatProducts } from '@/components/chat/ChatProducts';

jest.setTimeout(20000);

const mockMutateAsync = jest.fn();
const mockUseChat = jest.fn(() => ({ mutateAsync: mockMutateAsync, isPending: false }));
const mockProductsByIds = jest.fn();
const mockPush = jest.fn();
const mockRefetch = jest.fn();

const beautyContext: BeautyChatContext = {
  version: 1, issuedAt: 1000, candidateIds: ['p1', 'p2'], scopeIds: ['p1', 'p2'],
  selectedProductId: null,
  filters: { category: 'lip', maxPriceKRW: 20000, fragranceFree: false, moisturizing: true, query: '' },
};

jest.mock('@/hooks/useChat', () => ({ useChat: () => mockUseChat() }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key, language: 'ko' }) }));
jest.mock('@/lib/queries', () => ({ useProductsByIds: (ids: string[]) => mockProductsByIds(ids) }));
jest.mock('@/components/chat/ChatProducts', () => ({ ChatProducts: () => null }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useRouter: () => ({ push: mockPush }) }));
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
  mockMutateAsync.mockReset();
  mockUseChat.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
  mockProductsByIds.mockReset().mockReturnValue({ data: [], isPending: false, isError: false, refetch: mockRefetch });
  mockPush.mockReset();
  mockRefetch.mockReset();
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
    expect(mockMutateAsync.mock.calls[0][0]).toEqual({ message: '2만원 이하 립 추천', locale: 'ko', category: 'product' });
    expect(mockMutateAsync.mock.calls[1][0]).toEqual({ message: '두 번째 제품 자세히', locale: 'ko', category: 'product', chatContext: beautyContext });
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
    mockUseChat.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: true });
    await act(async () => { renderer.update(createElement(ChatScreen)); });
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
