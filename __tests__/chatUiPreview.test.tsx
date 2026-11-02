import { createElement } from 'react';
import { ScrollView, Text, TextInput } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import ChatUiPreview from '@/app/chat-ui-preview';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';

jest.setTimeout(20000);

const mockPush = jest.fn();
const mockRedirect = jest.fn((props: unknown) => { void props; return null; });

jest.mock('expo-router', () => ({
  Stack: { Screen: () => null },
  Redirect: (props: unknown) => mockRedirect(props),
  useRouter: () => ({ push: mockPush }),
}));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: ({ children }: { children: unknown }) => children,
}));

const ingredientLabels = { product: 'product label', ingredients: 'ingredients label', source: 'source label' };
const stepNavigation = { previous: 'previous', next: 'next', position: (current: number, total: number) => `${current}/${total}` };

async function render(element: ReturnType<typeof createElement>): Promise<ReactTestRenderer> {
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(element); });
  return renderer;
}

afterEach(() => {
  Object.defineProperty(globalThis, '__DEV__', { value: true, configurable: true, writable: true });
  mockPush.mockReset();
  mockRedirect.mockClear();
});

it('switches example conversations while keeping the example notice and disabled composer visible', async () => {
  const renderer = await render(createElement(ChatUiPreview));
  const banner = renderer.root.findAllByType(Text).find((node) => node.props.children === 'chat.preview.notice');
  expect(banner).toBeDefined();
  expect(renderer.root.findByType(ScrollView).findAllByType(Text)).not.toContain(banner);
  expect(renderer.root.findByType(TextInput).props.editable).toBe(false);
  expect(renderer.root.findByProps({ accessibilityLabel: 'chat.ui.send' }).props.disabled).toBe(true);
  expect(renderer.root.findByType(ChatProducts).props.disabledActions).toBe(true);
  expect(renderer.root.findByType(ChatProducts).props.products[0].name).toBe('chat.preview.product');
  expect(renderer.root.findByType(ChatProducts).props.conditions.map((condition: { kind: string }) => condition.kind))
    .toEqual(['category', 'maxPrice', 'fragranceFree']);
  expect(renderer.root.findAllByType(Text).map((node) => node.props.children))
    .toContain('chat.ui.productQuestion2 · chat.preview.conditionPrice');
  expect(renderer.root.findAllByType(IngredientResult)).toHaveLength(0);
  expect(renderer.root.findAllByType(StyleRecipeResult)).toHaveLength(0);
  await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.ingredient' }).props.onPress(); });
  expect(renderer.root.findAllByType(ChatProducts)).toHaveLength(0);
  expect(renderer.root.findByType(IngredientResult).props.product.name).toBe('chat.preview.product');
  expect(renderer.root.findByType(IngredientResult).props.product.checks[0].status).toBe('chat.conditionUnknown');
  expect(renderer.root.findAllByType(Text).map((node) => node.props.children)).toContain('chat.ui.ingredientQuestion1');
  await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.ui.style' }).props.onPress(); });
  const style = renderer.root.findByType(StyleRecipeResult);
  expect(style.props.recipe.steps).toHaveLength(2);
  expect(style.props.recipe.steps[0].image).toBeDefined();
  const styleTexts = style.findAllByType(Text).map((node) => node.props.children);
  expect(styleTexts).toEqual(expect.arrayContaining(['chat.relatedProducts', 'chat.preview.product']));
  expect(styleTexts).toContain('chat.preview.stepOne');
  expect(styleTexts).not.toContain('chat.preview.stepTwo');
  expect(renderer.root.findByProps({ accessibilityLabel: 'chat.result.previousStep' }).props.disabled).toBe(true);
  await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.result.nextStep' }).props.onPress(); });
  expect(style.findAllByType(Text).map((node) => node.props.children)).toContain('chat.preview.stepTwo');
  expect(renderer.root.findByProps({ accessibilityLabel: 'chat.result.nextStep' }).props.disabled).toBe(true);
  await act(async () => { renderer.root.findByProps({ accessibilityLabel: 'chat.result.previousStep' }).props.onPress(); });
  expect(style.findAllByType(Text).map((node) => node.props.children)).toContain('chat.preview.stepOne');
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: 'chat.ui.styleBrowse' }).props.onPress();
  });
  expect(mockPush).toHaveBeenCalledWith('/style-browse');
  await act(async () => { renderer.unmount(); });
});

it('does not render the example preview in production mode', async () => {
  Object.defineProperty(globalThis, '__DEV__', { value: false, configurable: true, writable: true });
  const renderer = await render(createElement(ChatUiPreview));
  expect(renderer.toJSON()).toBeNull();
  expect(mockRedirect).toHaveBeenCalledWith(expect.objectContaining({ href: '/' }));
  await act(async () => { renderer.unmount(); });
});

it('does not invent product, source, ingredient, or recipe details when none are supplied', async () => {
  const ingredient = await render(createElement(IngredientResult, {
    heading: 'ingredient', summary: 'answer', notice: 'notice', labels: ingredientLabels,
  }));
  const ingredientTexts = ingredient.root.findAllByType(Text).map((node) => node.props.children);
  expect(ingredientTexts).toEqual(expect.arrayContaining(['ingredient', 'answer', 'notice']));
  expect(ingredientTexts).not.toEqual(expect.arrayContaining(['product label', 'ingredients label', 'source label']));
  await act(async () => { ingredient.unmount(); });

  const style = await render(createElement(StyleRecipeResult, {
    heading: 'style', summary: 'answer', browseImage: 1, browseLabel: 'browse', onBrowse: jest.fn(), stepsLabel: 'steps', stepNavigation,
  }));
  const styleTexts = style.root.findAllByType(Text).map((node) => node.props.children);
  expect(styleTexts).toEqual(expect.arrayContaining(['style', 'answer']));
  expect(styleTexts).not.toContain('steps');
  expect(styleTexts).not.toContain('related products');
  await act(async () => { style.unmount(); });
});

it('hides the related products section when its list is empty', async () => {
  const style = await render(createElement(StyleRecipeResult, {
    heading: 'style', summary: 'answer', browseImage: 1, browseLabel: 'browse', onBrowse: jest.fn(), stepsLabel: 'steps', stepNavigation,
    recipe: { title: 'look', relatedProducts: { label: 'related products', products: [] } },
  }));
  const texts = style.root.findAllByType(Text).map((node) => node.props.children);
  expect(texts).not.toContain('related products');
  await act(async () => { style.unmount(); });
});
