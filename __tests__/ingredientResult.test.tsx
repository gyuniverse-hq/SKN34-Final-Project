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
    reason: 'ingredient_present', evidenceId: 'fixture-evidence' }],
};

async function render(results?: ChatIngredientResult[], shadeSelections?: Record<string, string>) {
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(IngredientResult, {
    heading: 'Ingredients', summary: 'Original server answer', notice: 'Information',
    labels: { product: 'Product', ingredients: 'Ingredients', source: 'Source' },
    products: [product], results, shadeSelections,
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


it.each([false, true])('accepts direct review only without blocking issues (%s)', async (blocked) => {
  const view = await render([{ ...evidence, mappingStatus: 'directly_reviewed',
    collectedAt: null, collectedAtRaw: '2026-10-27T18:06:42',
    sourceFingerprint: null, generatorVersion: null,
    reviewedAt: '2026-11-11T00:00:00Z', reviewRef: 'fixture://review',
    issues: blocked ? ['source_timezone_unknown', 'ingredient_list_inconsistent'] : ['source_timezone_unknown'],
  }]);
  expect(text(view)).toContain(en['chat.ingredient.directly_reviewed']);
  expect(text(view)).toContain(en[blocked ? 'chat.ingredient.UNKNOWN' : 'chat.ingredient.MATCH']);
  if (blocked) expect(text(view)).not.toContain('1. Water');
  else expect(text(view)).toContain('1. Water');
  await act(async () => { view.unmount(); });
});


const colorlessEvidence: ChatIngredientResult = {
  ...evidence,
  shadeId: null,
  conditions: [{ ...evidence.conditions![0], shadeId: null }],
};

it.each(['MATCH', 'NOT_MATCH'] as const)('shows verified %s for a colorless product', async (verdict) => {
  const view = await render([{ ...colorlessEvidence, verdict,
    conditions: [{ ...colorlessEvidence.conditions![0], verdict,
      operator: verdict === 'MATCH' ? 'includes' : 'excludes' }],
  }], {});
  expect(text(view)).toContain(en[`chat.ingredient.${verdict}`]);
  expect(text(view)).toContain('1. Water');
  expect(text(view)).not.toContain(en['chat.ingredient.selection']);
  await act(async () => { view.unmount(); });
});

it.each([
  [{ reviewStatus: 'unreviewed' } as const, {}],
  [{ optionId: null }, {}],
  [{}, { p2: 'p2-03' }],
] as const)('withholds colorless evidence when review, option or shade validation fails', async (changes, selections) => {
  const view = await render([{ ...colorlessEvidence, ...changes }], selections);
  expect(text(view)).toContain(en['chat.ingredient.UNKNOWN']);
  expect(text(view)).not.toContain('1. Water');
  await act(async () => { view.unmount(); });
});

it('shows evidence only for the selected shade when a shade is supplied', async () => {
  const view = await render([evidence], { p2: 'p2-03' });
  const stale = await render([evidence], { p2: 'p2-04' });
  expect(text(view)).toContain('1. Water');
  expect(text(stale)).not.toContain('1. Water');
  await act(async () => { view.unmount(); stale.unmount(); });
});


describe.each([['en', en], ['ko', ko], ['ja', ja], ['zh', zh]] as const)(
  'verified ingredient absence in %s',
  (_locale, dictionary) => {
    it.each([['includes', 'NOT_MATCH'], ['excludes', 'MATCH']] as const)(
      'shows the absence explanation for %s with verdict %s',
      async (operator, verdict) => {
        mockI18n.mockReturnValue({ t: (key: keyof typeof en) => dictionary[key] });
        const view = await render([{
          ...colorlessEvidence, verdict, reason: 'ingredient_absent',
          conditions: [{
            ...colorlessEvidence.conditions![0], ingredientName: 'Glycerin',
            operator, verdict, reason: 'ingredient_absent',
          }],
        }], {});
        expect(text(view)).toContain(dictionary[`chat.ingredient.${verdict}`]);
        expect(text(view)).toContain(dictionary[`chat.ingredient.${operator}`]);
        expect(text(view)).toContain(dictionary['chat.ingredient.absent']);
        expect(text(view)).not.toContain(dictionary['chat.ingredient.unknown']);
        await act(async () => { view.unmount(); });
      }
    );
  }
);

describe.each([['en', en], ['ko', ko], ['ja', ja], ['zh', zh]] as const)(
  'compound lookup failure in %s',
  (_locale, dictionary) => {
    it.each([false, true])('shows a separate error for matching selection (colorless=%s)', async (colorless) => {
      mockI18n.mockReturnValue({ t: (key: keyof typeof en) => dictionary[key] });
      const shadeId = colorless ? null : 'p2-03';
      const result: ChatIngredientResult = {
        ...evidence, shadeId, verdict: 'NOT_MATCH',
        conditions: [
          { ...evidence.conditions![0], shadeId, ingredientName: 'A', operator: 'excludes',
            verdict: 'NOT_MATCH', evidenceId: 'fixture-evidence' },
          { ...evidence.conditions![0], shadeId, ingredientName: 'B', operator: 'excludes',
            optionId: null, verdict: 'ERROR', reason: 'timeout', evidenceId: null },
        ],
      };
      const view = await render([result], colorless ? {} : { p2: 'p2-03' });
      const rows = text(view).split('\n');
      expect(rows.find(row => row.startsWith('A ·'))).toContain(dictionary['chat.ingredient.NOT_MATCH']);
      expect(rows.find(row => row.startsWith('B ·'))).toContain(dictionary['chat.ingredient.ERROR']);
      expect(rows.find(row => row.startsWith('B ·'))).toContain(dictionary['chat.ingredient.network']);
      await act(async () => { view.unmount(); });
    });
  }
);

it('rejects foreign selection, mismatched options and unverifiable null-option conditions', async () => {
  const base = evidence.conditions![0];
  const view = await render([{ ...evidence, verdict: 'NOT_MATCH', conditions: [
    { ...base, ingredientName: 'A', verdict: 'NOT_MATCH', evidenceId: 'fixture-evidence' },
    { ...base, ingredientName: 'B', optionId: null, verdict: 'ERROR', reason: 'source_unavailable', evidenceId: null },
    { ...base, ingredientName: 'Foreign product', productId: 'other', optionId: null, verdict: 'ERROR' },
    { ...base, ingredientName: 'Foreign shade', shadeId: 'other', optionId: null, verdict: 'ERROR' },
    { ...base, ingredientName: 'Foreign option', optionId: 'other', verdict: 'MATCH' },
    { ...base, ingredientName: 'Unproven match', optionId: null, verdict: 'MATCH' },
    { ...base, ingredientName: 'Fake error evidence', optionId: null, evidenceId: 'fabricated', verdict: 'ERROR' },
    { ...base, ingredientName: 'Unknown', verdict: 'UNKNOWN', reason: 'evidence_requires_review' },
  ] }], { p2: 'p2-03' });
  const rows = text(view).split('\n');
  expect(rows.find(row => row.startsWith('B ·'))).toContain(en['chat.ingredient.server']);
  expect(rows.find(row => row.startsWith('Unknown ·'))).toContain(en['chat.ingredient.UNKNOWN']);
  for (const name of ['Foreign product', 'Foreign shade', 'Foreign option', 'Unproven match', 'Fake error evidence']) {
    expect(text(view)).not.toContain(name);
  }
  await act(async () => { view.unmount(); });
});


it.each([
  ['error', 'ERROR', 'ERROR', 'timeout'],
  ['unknown', 'UNKNOWN', 'UNKNOWN', 'evidence_requires_review'],
] as const)('retains independently verified match beside %s', async (status, verdict, conditionVerdict, reason) => {
  const view = await render([{ ...evidence, status, verdict, reason,
    conditions: [
      { ...evidence.conditions![0], ingredientName: 'A', evidenceId: 'fixture-evidence' },
      { ...evidence.conditions![0], ingredientName: 'B', optionId: null, evidenceId: null,
        verdict: conditionVerdict, reason },
    ],
  }], { p2: 'p2-03' });
  const rows = text(view).split('\n');
  expect(rows.find(row => row.startsWith('A ·'))).toContain(en['chat.ingredient.MATCH']);
  expect(rows.find(row => row.startsWith('B ·'))).toContain(en[`chat.ingredient.${conditionVerdict}`]);
  expect(rows.find(row => row.startsWith('B ·'))).toContain(en[
    conditionVerdict === 'ERROR' ? 'chat.ingredient.network' : 'chat.ingredient.review'
  ]);
  await act(async () => { view.unmount(); });
});

it('does not confirm an individual verdict with a mismatched evidence ID', async () => {
  const view = await render([{ ...evidence, conditions: [
    { ...evidence.conditions![0], ingredientName: 'A', evidenceId: 'foreign-evidence' },
  ] }], { p2: 'p2-03' });
  const row = text(view).split('\n').find(value => value.startsWith('A ·'));
  expect(row).toContain(en['chat.ingredient.UNKNOWN']);
  expect(row).not.toContain(en['chat.ingredient.MATCH']);
  await act(async () => { view.unmount(); });
});
