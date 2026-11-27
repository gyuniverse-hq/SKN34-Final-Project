import { createElement } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import type { ChatStyleRecipe } from '@/types';

jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
jest.mock('@expo/vector-icons/Ionicons', () => () => null);

it('opens the exact sale option even when the recipe has no AR mapping', async () => {
  const result: ChatStyleRecipe = { kind: 'video', lookId: 'fixture', sourceLookId: 'fixture',
    recipeId: 'video:fixture', recipeVersion: 'test', title: 'Fixture', basis: 'video_metadata',
    reviewStatus: 'unreviewed', videoAnalyzed: false, synthetic: true, reason: 'video_not_analyzed', source: 'fixture', features: [],
    currentStep: 0, steps: [], products: [{ label: 'Sale option', zone: 'lip', productId: 'p',
      optionId: 'sale-a', mappingStatus: 'verified', catalogValid: true, arEligible: false }], arEligible: false };
  const open = jest.fn();
  let view!: ReactTestRenderer;
  await act(async () => { view = create(createElement(StyleRecipeResult, { result, onOpenProduct: open,
    heading: 'Style', summary: '', browseImage: 1, browseLabel: 'Browse', onBrowse: jest.fn(),
    stepsLabel: 'Steps', stepNavigation: { previous: 'Previous', next: 'Next', position: () => '' } })); });
  await act(async () => view.root.findByProps({ accessibilityLabel: 'chat.style.referenceProducts' }).props.onPress());
  await act(async () => view.root.findByProps({ accessibilityLabel: 'styleLooks.openProduct' }).props.onPress());
  expect(open).toHaveBeenCalledWith('p', undefined, 'sale-a');
  await act(async () => view.unmount());
});
