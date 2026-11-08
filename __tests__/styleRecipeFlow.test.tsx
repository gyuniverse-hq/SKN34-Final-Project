import { createElement } from 'react';
import { Text } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import LookDetail from '@/app/look/[id]';
import { en } from '@/lib/i18n/en';
import { ko } from '@/lib/i18n/ko';
import { ja } from '@/lib/i18n/ja';
import { zh } from '@/lib/i18n/zh';
import type { ChatStyleRecipe } from '@/types';

let mockDictionary: Record<string, string> = {};
const mockPush = jest.fn();
const mockApplyLook = jest.fn();
const mockLook = { id: 'catalog-1', title: 'Synthetic catalog look', inspiration: '', description: '', thumbnailUrl: '',
  tutorialQuery: '', items: [], tags: [], makeup: { lip: { hex: '#BB3344', intensity: 0.5, texture: 'matte' }, blush: null, eyeshadow: null } };
jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, useRouter: () => ({ push: mockPush }), useLocalSearchParams: () => ({ id: 'catalog-1' }) }));
jest.mock('@/lib/queries', () => ({ useLook: () => ({ data: { look: mockLook, products: [] } }), useTutorials: () => ({ data: { configured: false, videos: [] } }) }));
jest.mock('@/store/makeupStore', () => ({ useMakeupStore: (select: (s: unknown) => unknown) => select({ applyLook: mockApplyLook }) }));
jest.mock('@/store/cartStore', () => ({ useCartStore: (select: (s: unknown) => unknown) => select({ add: jest.fn(), addMany: jest.fn() }) }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: { children: unknown }) => children }));
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({
  t: (key: string, params?: Record<string, string | number>) => Object.entries(params ?? {}).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)), mockDictionary[key] ?? key),
}) }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
jest.mock('@/components/ui/StateViews', () => ({ LoadingState: () => null, ErrorState: () => null, EmptyState: () => null }));
jest.mock('@/components/ui/ProductImage', () => ({ ProductImage: () => null }));

const fixture: ChatStyleRecipe = {
  kind: 'video', lookId: 'SYNTHETIC', sourceLookId: 'SYNTHETIC', recipeId: 'video:SYNTHETIC', recipeVersion: 'test-only',
  title: 'SYNTHETIC source title', basis: 'video_metadata', reviewStatus: 'unreviewed',
  videoAnalyzed: false, synthetic: true, source: 'fixture:metadata', features: ['Fixture tag'],
  currentStep: 0, steps: [
    { order: 1, zone: 'eyeshadow', title: 'Fixture eyes', guideKey: 'eyeshadow' },
    { order: 2, zone: 'lip', title: 'Fixture lips', guideKey: 'lip' },
  ], products: [{ label: 'Listed only', zone: 'lip', mappingStatus: 'unknown', catalogValid: false, arEligible: false }],
  arEligible: false, reason: 'video_not_analyzed',
};
const props = {
  heading: 'Style', summary: 'Server explanation', browseImage: 1, browseLabel: 'Browse', onBrowse: jest.fn(),
  stepsLabel: 'Steps', stepNavigation: { previous: 'Previous', next: 'Next', position: (n: number, total: number) => `${n}/${total}` },
};
async function render(result?: ChatStyleRecipe, extra: object = {}) {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(StyleRecipeResult, { ...props, result, ...extra })); });
  return view;
}
function texts(view: ReactTestRenderer) { return view.root.findAllByType(Text).map((n) => n.props.children).flat().join(' '); }

test.each([en, ko, ja, zh])('localizes metadata provenance and real guide text without claiming video analysis', async (dictionary) => {
  mockDictionary = dictionary;
  const view = await render(fixture);
  const copy = texts(view);
  expect(copy).toContain(dictionary['chat.style.video_metadata']);
  expect(copy).toContain(dictionary['chat.style.unreviewed']);
  expect(copy).toContain(dictionary['chat.style.mappingUnknown']);
  expect(copy).toContain(dictionary['chat.style.basisLabel']);
  expect(copy).toContain(dictionary['chat.style.showSource']);
  expect(copy).toContain(dictionary['looks.guide.eyeshadow']);
  expect(copy).not.toContain(dictionary['chat.style.reviewed']);
  expect(copy).not.toMatch(/looks\.guide\.|\{angle\}/);
  await act(async () => view.unmount());
});

test('uses controlled progress, boundaries and callbacks; no implicit AR for unverified mappings', async () => {
  mockDictionary = en;
  const change = jest.fn(), ar = jest.fn(), manual = jest.fn();
  const view = await render(fixture, { onStepChange: change, onOpenAr: ar, onManualAr: manual });
  expect(view.root.findByProps({ accessibilityLabel: 'Previous' }).props.disabled).toBe(true);
  await act(async () => view.root.findByProps({ accessibilityLabel: 'Next' }).props.onPress());
  expect(change).toHaveBeenCalledWith(1);
  expect(texts(view)).toContain('Fixture eyes'); // Parent owns progress until it accepts the change.
  expect(ar).not.toHaveBeenCalled();
  expect(texts(view)).not.toContain(en['styleLooks.tryAr']);
  const manualButton = view.root.findByProps({ accessibilityLabel: en['chat.style.manualAr'] });
  await act(async () => manualButton.props.onPress());
  expect(manual).toHaveBeenCalledTimes(1);
  await act(async () => view.update(createElement(StyleRecipeResult, { ...props, result: { ...fixture, currentStep: 1 }, onStepChange: change })));
  expect(view.root.findByProps({ accessibilityLabel: 'Next' }).props.disabled).toBe(true);
  expect(texts(view)).toContain(en['looks.guide.lip']);
  await act(async () => view.unmount());
});

test('keeps reviewed instructions and exact product/shade navigation separate from manual AR', async () => {
  mockDictionary = en;
  const open = jest.fn(), ar = jest.fn();
  const result: ChatStyleRecipe = { ...fixture, basis: 'reviewed_recipe', reviewStatus: 'verified',
    steps: [{ order: 1, zone: 'lip', title: 'Synthetic reviewed step', description: 'Exact synthetic instruction' }],
    products: [{ label: 'Catalog product', productId: 'p-1', shadeId: 'shade-03', zone: 'lip', mappingStatus: 'verified', catalogValid: true, arEligible: true }], arEligible: true };
  const view = await render(result, { onOpenProduct: open, onOpenAr: ar });
  expect(texts(view)).toContain('Exact synthetic instruction');
  for (const [label, callback, args] of [
    [en['styleLooks.openProduct'], open, ['p-1', 'shade-03']], [en['styleLooks.tryAr'], ar, ['p-1', 'shade-03']],
  ] as const) {
    const button = view.root.findByProps({ accessibilityLabel: label });
    await act(async () => button.props.onPress());
    expect(callback).toHaveBeenCalledWith(...args);
  }
  await act(async () => view.unmount());
});

test('does not synthesize a recipe when the server returned none', async () => {
  mockDictionary = en;
  const view = await render();
  expect(texts(view)).not.toContain('Steps');
  expect(texts(view)).not.toContain('Fixture eyes');
  await act(async () => view.unmount());
});

test('Catalog look entry carries its namespace and preserves the existing full-look AR handler', async () => {
  mockDictionary = en;
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(LookDetail)); });
  await act(async () => view.root.findByProps({ accessibilityLabel: en['chat.style.openGuide'] }).props.onPress());
  expect(mockPush).toHaveBeenCalledWith({ pathname: '/chat', params: { recipeKind: 'catalog', recipeLookId: 'catalog-1' } });
  await act(async () => view.root.findByProps({ label: en['looks.applyInAr'] }).props.onPress());
  expect(mockApplyLook).toHaveBeenCalledWith(mockLook, []);
  await act(async () => view.unmount());
});


test('expands source details and step overview without changing controlled recipe progress', async () => {
  mockDictionary = en;
  const onStepChange = jest.fn();
  const view = await render(fixture, { onStepChange });
  expect(texts(view)).not.toContain('fixture:metadata');
  expect(texts(view)).toContain(en['chat.style.showSteps']);
  await act(async () => {
    view.root.findByProps({ accessibilityLabel: en['chat.style.showSource'] }).props.onPress();
  });
  expect(texts(view)).toContain('fixture:metadata');
  await act(async () => {
    view.root.findByProps({ accessibilityLabel: en['chat.style.showSteps'] }).props.onPress();
  });
  const second = view.root.findByProps({ accessibilityLabel: 'Fixture lips' });
  await act(async () => second.props.onPress());
  expect(onStepChange).toHaveBeenCalledWith(1);
  expect(texts(view)).toContain('Fixture eyes');
  expect(texts(view)).toContain(en['chat.style.unreviewed']);
  await act(async () => view.unmount());
});
