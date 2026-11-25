import { useState } from 'react';
import renderer, { act } from 'react-test-renderer';
import { hasAllConsents, NO_CONSENT, TermsAgreement } from '@/components/auth/TermsAgreement';

jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicon');
jest.mock('@/lib/i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));

it('lets a member accept everything once or sign up with only the required items', async () => {
  let selection = NO_CONSENT;
  function Form() {
    const [value, setValue] = useState(NO_CONSENT);
    selection = value;
    return <TermsAgreement value={value} onChange={setValue} onOpenDoc={() => {}} />;
  }
  let screen!: renderer.ReactTestRenderer;
  await act(async () => { screen = renderer.create(<Form />); });
  const toggle = async (label: string) => {
    const row = screen.root.findAllByProps({ accessibilityRole: 'checkbox', accessibilityLabel: label })
      .find(node => typeof node.props.onPress === 'function');
    await act(async () => { row!.props.onPress(); });
  };
  expect(hasAllConsents(selection)).toBe(false);
  await toggle('consent.all');
  expect(selection).toMatchObject({ cameraFeaturesConsent: true, arActivityConsent: true });
  await toggle('consent.cameraOptional');
  await toggle('consent.arOptional');
  expect(selection).toMatchObject({ cameraFeaturesConsent: false, arActivityConsent: false });
  expect(hasAllConsents(selection)).toBe(true);
  await act(async () => { screen.unmount(); });
});
