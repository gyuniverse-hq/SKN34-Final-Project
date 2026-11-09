import React from 'react';
import { Text } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { VideoProductActions } from '@/components/celeb/VideoProductActions';
import type { Product, VideoProductMapping } from '@/types';

jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

const product = {
  id: 'p1', makeupZone: 'lip', texture: 'matte',
  shades: [{ id: 's1', name: 'Pink', hex: '#112233' }],
} as Product;

async function render(mapping: VideoProductMapping, found: Product | undefined = product) {
  let screen!: renderer.ReactTestRenderer;
  const onProduct = jest.fn();
  const onTryOn = jest.fn();
  await act(async () => { screen = renderer.create(<VideoProductActions mapping={mapping} product={found} onProduct={onProduct} onTryOn={onTryOn} />); });
  return { screen, onProduct, onTryOn };
}

function buttons(screen: renderer.ReactTestRenderer) {
  return screen.root.findAll((node) => typeof node.type === 'string' && node.props.accessibilityRole === 'button');
}

test('only a verified matching product and shade can navigate to AR', async () => {
  const { screen, onProduct, onTryOn } = await render({ mappingVerified: true, catalogProductId: 'p1', catalogShadeId: 's1' });
  const actions = buttons(screen);
  expect(actions).toHaveLength(2);
  await act(async () => { actions[0].props.onClick(); actions[1].props.onClick(); });
  expect(onProduct).toHaveBeenCalledWith('p1', 's1');
  expect(onTryOn).toHaveBeenCalledWith('p1', 's1');
});

test('product-only approval links product but never guesses a shade', async () => {
  const { screen, onProduct } = await render({ mappingVerified: true, catalogProductId: 'p1' });
  const actions = buttons(screen);
  expect(actions).toHaveLength(1);
  await act(async () => { actions[0].props.onClick(); });
  expect(onProduct).toHaveBeenCalledWith('p1', undefined);
});

test('unverified, absent, mismatched or placeholder data cannot offer an AR button', async () => {
  const unverified = await render({ catalogProductId: 'p1', catalogShadeId: 's1' });
  expect(unverified.screen.root.findAllByType(Text).map((node) => node.props.children)).toEqual(['videoAr.similarProduct']);
  expect(buttons(unverified.screen)).toHaveLength(0);
  const missing = await render({ mappingVerified: true, catalogProductId: 'p1' }, { ...product, id: 'other' });
  expect(missing.screen.root.findAllByType(Text)).toHaveLength(0);
  const wrong = await render({ mappingVerified: true, catalogProductId: 'p1', catalogShadeId: 'wrong' });
  expect(buttons(wrong.screen)).toHaveLength(1);
  const placeholder = { ...product, shades: [{ ...product.shades[0], measureMethod: 'placeholder' }] } as Product;
  const noAr = await render({ mappingVerified: true, catalogProductId: 'p1', catalogShadeId: 's1' }, placeholder);
  expect(buttons(noAr.screen)).toHaveLength(1);
});
