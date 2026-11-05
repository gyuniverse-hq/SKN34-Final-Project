import { createElement } from 'react';
import { Text } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { en } from '@/lib/i18n/en';
import { ko } from '@/lib/i18n/ko';
import { ja } from '@/lib/i18n/ja';
import { zh } from '@/lib/i18n/zh';
import type { ChatIngredientResult } from '@/types';

const mockI18n = jest.fn();
jest.mock('@/lib/i18n', () => ({ useI18n: () => mockI18n() }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);
const product = { id: 'p2', name: 'Synthetic product', brand: 'Fixture', category: 'lip' };
const evidence: ChatIngredientResult = {
  productId: 'p2', shadeId: 'p2-03', optionId: 'synthetic-option', status: 'ok', verdict: 'MATCH',
  mappingStatus: 'reproduced', reviewStatus: 'verified', ingredientCoverage: 'full',
  normalizationStatus: 'verified', source: 'fixture://notice', collectedAt: '2026-11-02T12:00:00+09:00',
  sourceVersion: 'fixture-v1', sourceFingerprint: 'fixture-hash', generatorVersion: 'fixture-gen',
  evidenceId: 'fixture-evidence', ingredients: [{ name: 'Water', sequence: 1 }],
  reason: 'ingredient_present', synthetic: true,
  conditions: [{ productId: 'p2', shadeId: 'p2-03', optionId: 'synthetic-option',
    ingredientName: 'Water', operator: 'includes', condition: 'ingredient', verdict: 'MATCH',
    reason: 'ingredient_present' }],
};

async function render(results?: ChatIngredientResult[]) {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(IngredientResult, {
    heading: 'Ingredients', summary: 'Original server answer', notice: 'Information',
    labels: { product: 'Product', ingredients: 'Ingredients', source: 'Source' },
    products: [product], results,
  })); });
  return view;
}
function text(view: ReactTestRenderer) {
  return view.root.findAllByType(Text).map((n) => [n.props.children].flat().join('')).join('\n');
}

beforeEach(() => { mockI18n.mockReturnValue({ t: (key: keyof typeof en) => en[key] }); });

it.each([['en', en], ['ko', ko], ['ja', ja], ['zh', zh]] as const)(
  'renders server verdicts and evidence in %s without truncating text props', async (_locale, dictionary) => {
    mockI18n.mockReturnValue({ t: (key: keyof typeof en) => dictionary[key] });
    const view = await render([evidence]);
    expect(text(view)).toContain(dictionary['chat.ingredient.MATCH']);
    expect(text(view)).toContain(dictionary['chat.ingredient.includes']);
    expect(text(view)).toContain(dictionary['chat.ingredient.synthetic']);
    expect(text(view)).toContain('p2-03');
    expect(text(view)).toContain('fixture://notice');
    expect(text(view)).toContain('1. Water');
    expect(view.root.findAllByType(Text).every((node) => node.props.numberOfLines === undefined)).toBe(true);
    await act(async () => { view.unmount(); });
  }
);

it.each(['NOT_MATCH', 'UNKNOWN', 'ERROR'] as const)('keeps %s distinct', async (verdict) => {
  const view = await render([{ ...evidence, verdict,
    status: verdict === 'NOT_MATCH' ? 'ok' : verdict === 'ERROR' ? 'error' : 'unknown',
    conditions: [{ ...evidence.conditions![0], verdict }],
  }]);
  expect(text(view)).toContain(en[`chat.ingredient.${verdict}`]);
  if (verdict !== 'NOT_MATCH') {
    expect(text(view)).not.toContain('1. Water');
    expect(text(view)).not.toContain('fixture://notice');
  }
  await act(async () => { view.unmount(); });
});

it('does not fabricate structured ingredients when the server returns only an answer', async () => {
  const view = await render();
  expect(text(view)).toContain('Original server answer');
  expect(text(view)).not.toContain('Water');
  expect(text(view)).not.toContain(en['chat.ingredient.MATCH']);
  await act(async () => { view.unmount(); });
});

it('does not display unreviewed lists or foreign-product evidence', async () => {
  const view = await render([{ ...evidence, mappingStatus: 'candidate', reviewStatus: 'unreviewed' },
    { ...evidence, productId: 'other', ingredients: [{ name: 'Foreign ingredient', sequence: 1 }] }]);
  expect(text(view)).toContain(en['chat.ingredient.UNKNOWN']);
  expect(text(view)).not.toContain('1. Water');
  expect(text(view)).not.toContain('Foreign ingredient');
  await act(async () => { view.unmount(); });
});

it('does not turn a partial list into an exclusion match', async () => {
  const view = await render([{ ...evidence, ingredientCoverage: 'partial',
    conditions: [{ ...evidence.conditions![0], ingredientName: 'Fragrance', operator: 'excludes' }],
  }]);
  expect(text(view)).toContain(en['chat.ingredient.UNKNOWN']);
  expect(text(view)).not.toContain(en['chat.ingredient.MATCH']);
  expect(text(view)).toContain(en['chat.ingredient.partial']);
  await act(async () => { view.unmount(); });
});

it('never publishes synthetic evidence as verified in a production build', async () => {
  const original = __DEV__;
  Object.defineProperty(globalThis, '__DEV__', { value: false, configurable: true });
  try {
    const view = await render([evidence]);
    expect(text(view)).toContain(en['chat.ingredient.UNKNOWN']);
    expect(text(view)).toContain(en['chat.ingredient.synthetic']);
    expect(text(view)).not.toContain(en['chat.ingredient.MATCH']);
    expect(text(view)).not.toContain('1. Water');
    expect(text(view)).not.toContain('fixture://notice');
    await act(async () => { view.unmount(); });
  } finally {
    Object.defineProperty(globalThis, '__DEV__', { value: original, configurable: true });
  }
});
