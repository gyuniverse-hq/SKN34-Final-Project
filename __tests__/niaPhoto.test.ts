import { getNiaAcneView } from '@/lib/niaPhoto';

describe('NIA photo acne result availability', () => {
  const available = { acne: { configured: true, present: true, loaded: true } };

  it('marks a pre-acne result as outdated when a model is now available', () => {
    expect(getNiaAcneView(available, { ml_input: {} })).toEqual({ status: 'outdated' });
    expect(getNiaAcneView(available)).toEqual({ status: 'ready' });
  });

  it('accepts the exported JSON result even if the top-level optional field is absent', () => {
    const result = { status: 'predicted' as const, label: 0 as const, score: 0, threshold: 0.5 };
    expect(getNiaAcneView(available, { ml_input: { acne: result } }))
      .toEqual({ status: 'predicted', result });
  });

  it('preserves model failure and genuine unsupported states', () => {
    const result = { status: 'failed' as const, label: null, score: null, error: 'load failed' };
    expect(getNiaAcneView(available, { acne: result })).toEqual({ status: 'failed', result });
    expect(getNiaAcneView({ acne: { configured: false, present: false, loaded: false } }, {}))
      .toEqual({ status: 'unsupported' });
  });
});
