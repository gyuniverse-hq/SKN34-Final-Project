import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { PracticePanel, type PracticePanelProps } from '@/components/ar/PracticePanel';

// The icon font is not in the test asset registry; the icons are not what these tests check.
jest.mock('@expo/vector-icons/Ionicons', () => 'Ionicons');

const base = (over: Partial<PracticePanelProps> = {}): PracticePanelProps => ({
  title: 'Do it yourself',
  intro: 'intro',
  steps: [
    { key: 'eyebrow', label: 'Brow', done: true },
    { key: 'eyeshadow', label: 'Shadow', done: false },
    { key: 'lip', label: 'Lip', done: false },
  ],
  activeIndex: 1,
  text: 'Spread a light color over the lid.',
  peeking: false,
  labels: { prev: 'Back', next: 'Next', finish: 'Finish', peek: 'Peek', peekOff: 'My steps', exit: 'Exit' },
  onPick: jest.fn(),
  onPrev: jest.fn(),
  onNext: jest.fn(),
  onPeek: jest.fn(),
  onExit: jest.fn(),
  ...over,
});

async function render(props: PracticePanelProps) {
  let r!: renderer.ReactTestRenderer;
  await act(async () => {
    r = renderer.create(<PracticePanel {...props} />);
  });
  return r;
}
const text = (r: renderer.ReactTestRenderer) => JSON.stringify(r.toJSON());
// The step chips (the Pressable itself, not the host view it renders with the same role).
const tabs = (r: renderer.ReactTestRenderer) =>
  r.root.findAll((n) => n.props.accessibilityRole === 'tab' && typeof n.props.onPress === 'function');

describe('PracticePanel', () => {
  it('shows the steps in order with their numbers and the sentence of the current step', async () => {
    const r = await render(base());
    const t = text(r);
    for (const part of ['1. Brow', '2. Shadow', '3. Lip', 'Spread a light color over the lid.']) expect(t).toContain(part);
    expect(tabs(r)).toHaveLength(3);
  });

  it('picks a step by pressing its chip', async () => {
    const props = base();
    const r = await render(props);
    await act(async () => {
      tabs(r)[2].props.onPress();
    });
    expect(props.onPick).toHaveBeenCalledWith(2);
  });

  it('offers Finish instead of Next on the last step, and cannot go back from the first', async () => {
    expect(text(await render(base({ activeIndex: 2 })))).toContain('Finish');
    expect(text(await render(base({ activeIndex: 1 })))).toContain('Next');
    const first = await render(base({ activeIndex: 0 }));
    const back = first.root.findAll((n) => n.props.accessibilityLabel === 'Back' || n.props.label === 'Back');
    expect(back.some((n) => n.props.disabled === true)).toBe(true);
  });

  it('switches the peek chip label and exits', async () => {
    expect(text(await render(base({ peeking: true })))).toContain('My steps');
    expect(text(await render(base()))).toContain('Peek');
  });
});
