import { practiceDrawStep, practiceZones, revealedMakeup, visit } from '@/lib/practice';
import type { MakeupState, MakeupZone } from '@/types';

const stage: MakeupState = {
  lip: { hex: '#B3202E', intensity: 0.85, texture: 'velvet' },
  blush: { hex: '#F08C7A', intensity: 0.5, texture: 'matte' },
  eyeshadow: { hex: '#8A5A44', intensity: 0.7, texture: 'shimmer' },
  eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.3, angle: 15 } },
};
const stageOrder: MakeupZone[] = ['eyeshadow', 'blush', 'eyeliner', 'lip'];

const peach: MakeupState = {
  blush: { hex: '#F4A78A', intensity: 0.5, texture: 'sheer' },
  eyeshadow: { hex: '#F4A78A', intensity: 0.44, texture: 'shimmer' },
  lip: { hex: '#F2735B', intensity: 0.55, texture: 'sheer' },
};
const peachOrder: MakeupZone[] = ['blush', 'eyeshadow', 'lip'];

const glow: MakeupState = {
  blush: { hex: '#F08C7A', intensity: 0.4, texture: 'sheer' },
  eyeshadow: { hex: '#C9A27E', intensity: 0.4, texture: 'shimmer' },
  lip: { hex: '#C25A6E', intensity: 0.6, texture: 'glossy' },
};

describe('do it yourself mode', () => {
  it('starts with the brow, then the zones of the look in its own order', () => {
    expect(practiceZones(stage, stageOrder)).toEqual([null, ...stageOrder]);
    expect(practiceZones(peach, peachOrder).slice(0, 3)).toEqual([null, 'blush', 'eyeshadow']);
  });

  it('has only the zones the look wears', () => {
    expect(practiceZones(glow, ['blush', 'eyeshadow', 'lip'])).toEqual([null, 'blush', 'eyeshadow', 'lip']);
  });

  it('shows a bare face first and adds one layer per visited step, keeping the look values', () => {
    const bare = revealedMakeup(stage, []);
    for (const z of ['lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour'] as const) {
      expect(bare[z]).toBeNull();
    }
    const two = revealedMakeup(stage, ['eyeshadow', 'eyeliner']);
    expect(two.eyeshadow).toEqual(stage.eyeshadow);
    expect(two.eyeliner?.geometry).toEqual(stage.eyeliner?.geometry);
    expect(two.lip).toBeNull();
  });

  it('never changes the look it reads from', () => {
    const before = JSON.stringify(stage);
    revealedMakeup(stage, ['lip']);
    expect(JSON.stringify(stage)).toBe(before);
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
