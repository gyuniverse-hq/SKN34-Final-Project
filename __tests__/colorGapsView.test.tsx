import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { ColorGaps, type ColorGapRow } from '@/components/look/ColorGaps';

const row = (over: Partial<ColorGapRow>): ColorGapRow => ({
  key: 'k',
  zone: 'Lips',
  hex: '#B3202E',
  status: 'nearest',
  badge: 'badge',
  ...over,
});

async function render(rows: ColorGapRow[]) {
  let r!: renderer.ReactTestRenderer;
  await act(async () => {
    r = renderer.create(<ColorGaps title="T" intro="I" rows={rows} />);
  });
  return r;
}

describe('ColorGaps', () => {
  it('renders nothing without rows', async () => {
    const r = await render([]);
    expect(r.toJSON()).toBeNull();
  });

  it('a sold-out color is not pressable and says why', async () => {
    const onPress = jest.fn();
    const r = await render([row({ status: 'soldout', badge: 'Sold out', note: 'Cannot add' })]);
    expect(r.root.findAllByProps({ accessibilityRole: 'button' })).toHaveLength(0);
    expect(r.root.findAllByProps({ accessibilityRole: 'link' })).toHaveLength(0);
    expect(JSON.stringify(r.toJSON())).toContain('Cannot add');
    expect(onPress).not.toHaveBeenCalled();
  });

  it('the nearest shade opens its product, and sellers open as links', async () => {
    const open = jest.fn();
    const seller = jest.fn();
    const r = await render([
      row({ key: 'a', onPress: open, headline: 'Brand Lip · Red' }),
      row({ key: 'b', status: 'offers', offers: [{ key: 'o', text: 'Mall', price: '1,000', onPress: seller }] }),
    ]);
    const buttons = r.root.findAllByProps({ accessibilityRole: 'button' });
    const links = r.root.findAllByProps({ accessibilityRole: 'link' });
    await act(async () => {
      buttons[0].props.onPress();
      links[0].props.onPress();
    });
    expect(open).toHaveBeenCalledTimes(1);
    expect(seller).toHaveBeenCalledTimes(1);
  });
});
