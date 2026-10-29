import { createElement } from 'react';
import { Text, TextInput } from 'react-native';
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
