import { DEMO_LOOKS } from '@/lib/devCatalog/demo';
import { practiceDrawStep, practiceZones, revealedMakeup, visit } from '@/lib/practice';
import type { MakeupZone } from '@/types';

const look = (id: string) => DEMO_LOOKS.find((l) => l.id === id)!;

describe('do it yourself mode', () => {
  it('starts with the brow, then the zones of the look in its own order', () => {
    const stage = look('demo-look-stage-red');
    expect(practiceZones(stage.makeup, stage.stepOrder)).toEqual([null, ...(stage.stepOrder as MakeupZone[])]);
    const peach = look('demo-look-soft-peach-coral');
    expect(practiceZones(peach.makeup, peach.stepOrder).slice(0, 3)).toEqual([null, 'blush', 'eyeshadow']);
  });

  it('has only the zones the look wears', () => {
    const glow = look('demo-look-glass-rose');
    expect(practiceZones(glow.makeup, glow.stepOrder)).toEqual([null, 'blush', 'eyeshadow', 'lip']);
  });

  it('shows a bare face first and adds one layer per visited step, keeping the look values', () => {
    const stage = look('demo-look-stage-red');
    const bare = revealedMakeup(stage.makeup, []);
    for (const z of ['lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour'] as const) {
      expect(bare[z]).toBeNull();
    }
    const two = revealedMakeup(stage.makeup, ['eyeshadow', 'eyeliner']);
    expect(two.eyeshadow).toEqual(stage.makeup.eyeshadow);
    expect(two.eyeliner?.geometry).toEqual(stage.makeup.eyeliner?.geometry);
    expect(two.lip).toBeNull();
  });

  it('never changes the look it reads from', () => {
    const stage = look('demo-look-stage-red');
    const before = JSON.stringify(stage.makeup);
    revealedMakeup(stage.makeup, ['lip']);
    expect(JSON.stringify(stage.makeup)).toBe(before);
  });

  it('keeps a visited step on, and the brow adds no color', () => {
    expect(visit([], 'lip')).toEqual(['lip']);
    expect(visit(['lip'], 'lip')).toEqual(['lip']);
    expect(visit(['lip'], null)).toEqual(['lip']);
  });

  it('draws the camera guide for the brow, shadow, liner and lip, and none for the other zones', () => {
    expect(practiceDrawStep(null)).toBe('eyebrow');
    expect(practiceDrawStep('eyeliner')).toBe('eyeliner');
    expect(practiceDrawStep('lip')).toBe('lip');
    expect(practiceDrawStep('blush')).toBeNull();
    expect(practiceDrawStep('mascara')).toBeNull();
  });
});
