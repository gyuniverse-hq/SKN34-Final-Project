import { createElement } from 'react';
import { Keyboard, KeyboardAvoidingView, Platform, Text, TextInput } from 'react-native';
import { act, create, type ReactTestInstance, type ReactTestRenderer } from 'react-test-renderer';
import ChatScreen from '@/app/chat';
import { ChatProducts } from '@/components/chat/ChatProducts';

jest.setTimeout(20000);

const mockMutateAsync = jest.fn();
const mockUseChat = jest.fn(() => ({ mutateAsync: mockMutateAsync, isPending: false }));
const mockProductsByIds = jest.fn();
const mockPush = jest.fn();
const mockRefetch = jest.fn();

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
