import { useState } from 'react';
import renderer, { act } from 'react-test-renderer';
import { hasAllConsents, NO_CONSENT, TermsAgreement } from '@/components/auth/TermsAgreement';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicon');
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

it('requires both agreements and keeps the two documents accessible', async () => {
  const openDoc = jest.fn();
  let selection = NO_CONSENT;
  function Form() {
    const [value, setValue] = useState(NO_CONSENT);
    selection = value;
    return <TermsAgreement value={value} onChange={setValue} onOpenDoc={openDoc} />;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Form />); });
  const toggle = async (label: string) => {
    const row = screen.root.findAllByProps({ accessibilityRole: 'checkbox', accessibilityLabel: label })
      .find(node => typeof node.props.onPress === 'function');
    await act(async () => { row!.props.onPress(); });
  };
  expect(hasAllConsents(selection)).toBe(false);
  for (const label of ['consent.viewTerms', 'consent.viewData']) {
    const link = screen.root.findAllByProps({ accessibilityRole: 'link', accessibilityLabel: label })
      .find(node => typeof node.props.onPress === 'function');
    link!.props.onPress();
  }
  expect(openDoc.mock.calls).toEqual([['terms'], ['service-data']]);
  await toggle('consent.terms');
  expect(hasAllConsents(selection)).toBe(false);
  await toggle('consent.privacy');
  expect(hasAllConsents(selection)).toBe(true);
  await act(async () => { screen.unmount(); });
});
