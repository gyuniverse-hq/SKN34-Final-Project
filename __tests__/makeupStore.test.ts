import { AR_PAINT_ZONES, arPaintMakeup, MAKEUP_ZONES, useMakeupStore, type ArProposal } from '@/store/makeupStore';
import type { CelebLook, Product } from '@/types';

describe('makeup store zones', () => {
  beforeEach(() => useMakeupStore.getState().reset());

  it('starts with every zone off', () => {
    const { makeup } = useMakeupStore.getState();
    for (const zone of MAKEUP_ZONES) expect(makeup[zone]).toBeNull();
  });

  it('keeps a look makeup preset but never records a shade belonging to another product', () => {
    const product = { id: 'p', makeupZone: 'lip', texture: 'matte', shades: [{ id: '01', name: '01', hex: '#112233' }] } as Product;
    const look = { id: 'look', title: 'Look', items: [{ productId: 'p', shadeId: 'other', step: 'lips' }], makeup: { lip: { hex: '#112233', intensity: 0.5, texture: 'matte' } } } as unknown as CelebLook;
    useMakeupStore.getState().applyLook(look, [product]);
    expect(useMakeupStore.getState().selections.lip).toBeUndefined();
    expect(useMakeupStore.getState().makeup.lip?.hex).toBe('#112233');
  });

  it('loads a look saved before the newer zones without leaving them undefined', () => {
    const look = {
      id: 'old',
      title: 'Old look',
      items: [],
      makeup: { lip: { hex: '#B3202E', intensity: 0.6, texture: 'matte' }, blush: null, eyeshadow: null },
    } as unknown as CelebLook;
    useMakeupStore.getState().applyLook(look, []);
    const { makeup } = useMakeupStore.getState();
    expect(makeup.lip?.hex).toBe('#B3202E');
    for (const zone of ['eyeliner', 'mascara', 'highlighter', 'contour', 'brow', 'foundation'] as const) {
      expect(makeup[zone]).toBeNull();
    }
  });

  describe('color links', () => {
    const look = {
      id: 'peach',
      title: 'Peach',
      items: [],
      makeup: {
        lip: null,
        blush: { hex: '#F4A78A', intensity: 0.5, texture: 'sheer' },
        eyeshadow: { hex: '#F4A78A', hexTo: '#E38B6F', intensity: 0.44, texture: 'shimmer' },
      },
      colorLinks: [{ zones: ['eyeshadow', 'blush'], hex: '#F4A78A', followOnChange: true }],
    } as unknown as CelebLook;
    const product = (zone: 'blush' | 'eyeshadow', texture: string) =>
      ({ id: `p-${zone}`, makeupZone: zone, texture, shades: [] }) as unknown as Product;
    const shade = { id: 's1', name: 'Rose', hex: '#C97C8C' };

    it('moves the linked zone to the new color but keeps its own finish and strength', () => {
      const { applyLook, applyShade } = useMakeupStore.getState();
      applyLook(look, []);
      applyShade(product('blush', 'matte'), shade);
      const { makeup, selections } = useMakeupStore.getState();
      expect(makeup.blush?.hex).toBe('#C97C8C');
      expect(makeup.eyeshadow?.hex).toBe('#C97C8C');
      expect(makeup.eyeshadow?.texture).toBe('shimmer');
      expect(makeup.eyeshadow?.intensity).toBe(0.44);
      expect(makeup.eyeshadow?.hexTo).toBe('#E38B6F');
      // The follower no longer wears a product shade, so it must not stay in the cart selection.
      expect(selections.blush?.shadeId).toBe('s1');
      expect(selections.eyeshadow).toBeUndefined();
    });

    it('does not follow when the look has no link, and the link ends with the look', () => {
      const { applyShade, applyLook, reset } = useMakeupStore.getState();
      reset();
      applyLook({ ...look, colorLinks: undefined } as CelebLook, []);
      applyShade(product('blush', 'matte'), shade);
      expect(useMakeupStore.getState().makeup.eyeshadow?.hex).toBe('#F4A78A');
      reset();
      expect(useMakeupStore.getState().colorLinks).toEqual([]);
    });
  });

  describe('adjusting an applied look', () => {
    const shade = (id: string, hex: string) => ({ id, name: id, hex });
    const product = (zone: 'lip' | 'eyeliner', id = `p-${zone}`) =>
      ({ id, makeupZone: zone, texture: 'matte', shades: [] }) as unknown as Product;
    const lipA = product('lip', 'lip-a');
    const lipB = product('lip', 'lip-b');
    const liner = product('eyeliner');
    const look = {
      id: 'stage',
      title: 'Stage',
      heroZones: ['lip', 'eyeshadow'],
      items: [
        { productId: 'lip-a', shadeId: 'red', step: 'lips' },
        { productId: 'p-eyeliner', shadeId: 'black', step: 'eyes' },
      ],
      makeup: {
        lip: { hex: '#B3202E', intensity: 0.85, texture: 'velvet' },
        eyeliner: { hex: '#0E0C0C', intensity: 1, texture: 'glossy', geometry: { length: 0.3, angle: 15 } },
        eyeshadow: { hex: '#8A5A44', hexTo: '#3E271E', intensity: 0.7, texture: 'shimmer' },
      },
    } as unknown as CelebLook;
    const lipPro = { ...lipA, shades: [shade('red', '#B3202E')] } as Product;
    const linerPro = { ...liner, shades: [shade('black', '#0E0C0C')] } as Product;

    beforeEach(() => useMakeupStore.getState().applyLook(look, [lipPro, linerPro]));

    it('remembers the key zones and starts with nothing modified', () => {
      const s = useMakeupStore.getState();
      expect(s.heroZones).toEqual(['lip', 'eyeshadow']);
      expect(s.modified).toEqual([]);
      expect(s.activeLook?.id).toBe('stage');
    });

    it('keeps the look and its shape when a color is swapped, and lists the zone as modified', () => {
      useMakeupStore.getState().applyShade({ ...liner, texture: 'matte' } as Product, shade('brown', '#4A3026'));
      const s = useMakeupStore.getState();
      expect(s.activeLook?.id).toBe('stage');
      expect(s.makeup.eyeliner?.hex).toBe('#4A3026');
      // The wing angle and length belong to the look, not to the product.
      expect(s.makeup.eyeliner?.geometry).toEqual({ length: 0.3, angle: 15 });
      expect(s.modified).toEqual(['eyeliner']);
    });

    it('keeps the second shadow tone when the shadow color is swapped', () => {
      const shadow = { id: 's', makeupZone: 'eyeshadow', texture: 'shimmer', shades: [] } as unknown as Product;
      useMakeupStore.getState().applyShade(shadow, shade('x', '#B08A8C'));
      expect(useMakeupStore.getState().makeup.eyeshadow).toMatchObject({ hex: '#B08A8C', hexTo: '#3E271E' });
    });

    it('does not count intensity as a change of the look', () => {
      useMakeupStore.getState().setIntensity('lip', 0.3);
      const s = useMakeupStore.getState();
      expect(s.makeup.lip?.intensity).toBe(0.3);
      expect(s.modified).toEqual([]);
    });

    it('picking the look own shade again clears the modified mark', () => {
      const { applyShade } = useMakeupStore.getState();
      applyShade(lipB, shade('rose', '#C25A6E'));
      expect(useMakeupStore.getState().modified).toEqual(['lip']);
      applyShade(lipPro, shade('red', '#B3202E'));
      expect(useMakeupStore.getState().modified).toEqual([]);
    });

    it('turning a zone off keeps the look and marks it modified', () => {
      useMakeupStore.getState().clearZone('eyeliner');
      const s = useMakeupStore.getState();
      expect(s.activeLook?.id).toBe('stage');
      expect(s.makeup.eyeliner).toBeNull();
      expect(s.modified).toEqual(['eyeliner']);
    });

    it('reverts one zone to the look color and product but keeps the intensity set since', () => {
      const { applyShade, setIntensity, revertZone } = useMakeupStore.getState();
      applyShade(lipB, shade('rose', '#C25A6E'));
      setIntensity('lip', 0.4);
      revertZone('lip');
      const s = useMakeupStore.getState();
      expect(s.makeup.lip).toMatchObject({ hex: '#B3202E', texture: 'velvet', intensity: 0.4 });
      expect(s.selections.lip).toEqual({ productId: 'lip-a', shadeId: 'red' });
      expect(s.modified).toEqual([]);
    });

    it('AR paint strips mascara even when a look names it, and keeps highlighter and contour', () => {
      const look = {
        id: 'full',
        title: 'Full',
        items: [],
        makeup: {
          lip: { hex: '#B3202E', intensity: 0.6, texture: 'matte' },
          blush: null,
          eyeshadow: null,
          eyeliner: null,
          highlighter: { hex: '#F2DCC4', intensity: 0.7, texture: 'shimmer' },
          contour: { hex: '#8A5A44', intensity: 0.5, texture: 'matte' },
        },
      } as unknown as CelebLook;
      useMakeupStore.getState().applyLook(look, []);
      const worn = useMakeupStore.getState().makeup;
      expect(worn.mascara).toBeNull();
      expect(worn.highlighter?.hex).toBe('#F2DCC4');
      expect(worn.contour?.hex).toBe('#8A5A44');
      expect(arPaintMakeup(worn).mascara).toBeNull();
      expect(arPaintMakeup(worn).highlighter?.hex).toBe('#F2DCC4');
      expect(arPaintMakeup(worn).contour?.hex).toBe('#8A5A44');
      expect(arPaintMakeup(worn).lip?.hex).toBe('#B3202E');
      expect(AR_PAINT_ZONES).toEqual([
        'lip',
        'blush',
        'eyeshadow',
        'eyeliner',
        'highlighter',
        'contour',
        'brow',
        'foundation',
      ]);
    });

    it('a new look replaces the old origin, and reset forgets it', () => {
      useMakeupStore.getState().applyShade(lipB, shade('rose', '#C25A6E'));
      useMakeupStore.getState().applyLook({ ...look, id: 'other', heroZones: ['eyeliner'] } as CelebLook, []);
      expect(useMakeupStore.getState().modified).toEqual([]);
      expect(useMakeupStore.getState().heroZones).toEqual(['eyeliner']);
      useMakeupStore.getState().reset();
      const s = useMakeupStore.getState();
      expect([s.heroZones, s.modified, s.lookOrigin]).toEqual([[], [], null]);
    });
  });

  describe('product fit', () => {
    const lip = {
      id: 'lip-fit',
      makeupZone: 'lip',
      texture: 'glossy',
      shades: [{ id: 'cola', name: 'Cola', hex: '#5A2A24' }],
    } as unknown as Product;
    const blush = {
      id: 'blush-fit',
      makeupZone: 'blush',
      texture: 'sheer',
      shades: [{ id: 'peach', name: 'Peach', hex: '#F4A78A' }],
    } as unknown as Product;
    const mascara = {
      id: 'mascara-fit',
      makeupZone: 'mascara',
      texture: 'matte',
      shades: [{ id: 'black', name: 'Black', hex: '#121010' }],
    } as unknown as Product;

    it('keeps other zones as they were, paints the product color, and restores the face when the session ends', () => {
      const { applyShade, startFit, endFit } = useMakeupStore.getState();
      applyShade(blush, blush.shades[0]);
      applyShade(lip, lip.shades[0]);
      startFit(lip, { id: 'rose', name: 'Rose', hex: '#C25A6E' });
      const fitted = useMakeupStore.getState();
      expect(fitted.fit).toEqual({ productId: 'lip-fit', shadeId: 'rose' });
      expect(fitted.makeup.lip?.hex).toBe('#C25A6E');
      expect(fitted.makeup.blush?.hex).toBe('#F4A78A');
      applyShade(blush, { id: 'other', name: 'Other', hex: '#111111' });
      expect(useMakeupStore.getState().makeup.blush?.hex).toBe('#F4A78A');
      endFit();
      const restored = useMakeupStore.getState();
      expect(restored.fit).toBeNull();
      expect(restored.makeup.lip?.hex).toBe('#5A2A24');
      expect(restored.makeup.blush?.hex).toBe('#F4A78A');
    });

    it('keeps the first snapshot when another shade is fitted, and ignores a zone AR does not paint', () => {
      const { applyShade, startFit, endFit } = useMakeupStore.getState();
      applyShade(blush, blush.shades[0]);
      startFit(lip, lip.shades[0]);
      startFit(lip, { id: 'rose', name: 'Rose', hex: '#C25A6E' });
      expect(useMakeupStore.getState().makeup.lip?.hex).toBe('#C25A6E');
      startFit(mascara, mascara.shades[0]);
      expect(useMakeupStore.getState().makeup.mascara).toBeNull();
      expect(useMakeupStore.getState().fit?.shadeId).toBe('rose');
      endFit();
      expect(useMakeupStore.getState().makeup.blush?.hex).toBe('#F4A78A');
      expect(useMakeupStore.getState().makeup.lip).toBeNull();
    });
  });
});

describe('AR command state', () => {
  const lip = { id: 'lip-ar', makeupZone: 'lip', texture: 'matte' } as unknown as Product;
  const blush = { id: 'blush-ar', makeupZone: 'blush', texture: 'cream' } as unknown as Product;
  const lipShade = { id: 'rose', name: 'Rose', hex: '#C25A6E' };
  const blushShade = { id: 'coral', name: 'Coral', hex: '#F4A78A' };
  let serial = 0;
  let session: string;
  let request: string;
  let proposal: ArProposal;

  beforeEach(() => {
    const store = useMakeupStore.getState();
    store.endArSession();
    store.reset();
    store.applyShade(lip, lipShade);
    store.applyShade(blush, blushShade);
    session = `ar-session-${++serial}`;
    request = `request-${serial}`;
    store.beginArSession(session);
    proposal = {
      commandId: `command-${serial}`, expectedStateVersion: useMakeupStore.getState().arVersion,
      action: 'set_intensity', zone: 'lip', value: 0.5, productId: lip.id, shadeId: lipShade.id,
    };
  });

  it.each([0, 0.5, 1])('applies intensity %s only after render confirmation', (value) => {
    const store = useMakeupStore.getState();
    const before = store.makeup;
    proposal.value = value;
    expect(store.prepareArCommand(request, session, proposal).status).toBe('PENDING');
    expect(useMakeupStore.getState().makeup).toEqual(before);
    const outcome = store.finishArCommand(proposal.commandId, session, 'rendered');
    expect(outcome).toEqual({ status: 'APPLIED', actualStateVersion: proposal.expectedStateVersion + 1 });
    const after = useMakeupStore.getState();
    expect(after.makeup.lip).toEqual({ ...before.lip, intensity: value });
    expect(after.makeup.blush).toEqual(before.blush);
    expect(after.selections.lip).toEqual({ productId: lip.id, shadeId: lipShade.id });
    expect(after.prepareArCommand(request, session, proposal).status).toBe('REJECTED');
  });

  it('returns NO_CHANGE without changing version when the current value is rendered', () => {
    const store = useMakeupStore.getState();
    proposal.value = store.makeup.lip!.intensity;
    expect(store.prepareArCommand(request, session, proposal).status).toBe('PENDING');
    expect(store.finishArCommand(proposal.commandId, session, 'rendered')).toEqual({
      status: 'NO_CHANGE', actualStateVersion: proposal.expectedStateVersion,
    });
  });

  it('invalidates undo after a manual edit, even if a proposal uses the new version', () => {
    const store = useMakeupStore.getState();
    const previous = store.makeup.lip!.intensity;
    expect(store.prepareArCommand(request, session, proposal).status).toBe('PENDING');
    expect(store.finishArCommand(proposal.commandId, session, 'rendered').status).toBe('APPLIED');
    expect(useMakeupStore.getState().arUndo).toEqual({ zone: 'lip', value: previous });
    store.setIntensity('lip', 0.8);
    const latest = useMakeupStore.getState();
    expect(latest.arUndo).toBeNull();
    expect(store.prepareArCommand('second', session, {
      ...proposal, commandId: 'undo', expectedStateVersion: latest.arVersion, action: 'undo', value: previous,
    }).status).toBe('REJECTED');
  });

  it.each(['failed', 'unknown'] as const)('does not change makeup when render is %s', (result) => {
    const store = useMakeupStore.getState();
    const before = store.makeup;
    store.prepareArCommand(request, session, proposal);
    expect(store.finishArCommand(proposal.commandId, session, result).status).toBe(result === 'failed' ? 'FAILED' : 'UNKNOWN');
    expect(useMakeupStore.getState().makeup).toEqual(before);
    expect(useMakeupStore.getState().arVersion).toBe(proposal.expectedStateVersion);
  });

  it('rejects an old version, wrong selection, invalid number, or locked fit', () => {
    const store = useMakeupStore.getState();
    expect(store.prepareArCommand(request, session, { ...proposal, expectedStateVersion: 0 }).status).toBe('REJECTED');
    expect(store.prepareArCommand(request, session, { ...proposal, shadeId: 'other' }).status).toBe('REJECTED');
    expect(store.prepareArCommand(request, session, { ...proposal, value: NaN }).status).toBe('REJECTED');
    store.startFit(lip, lipShade);
    expect(store.prepareArCommand(request, session, { ...proposal, expectedStateVersion: useMakeupStore.getState().arVersion }).status).toBe('REJECTED');
  });

  it('prefers a manual change during rendering and refuses a late result', () => {
    const store = useMakeupStore.getState();
    store.prepareArCommand(request, session, proposal);
    store.setIntensity('lip', 0.8);
    expect(useMakeupStore.getState().pendingArCommand).toBeNull();
    expect(store.finishArCommand(proposal.commandId, session, 'rendered').status).toBe('REJECTED');
    expect(useMakeupStore.getState().makeup.lip?.intensity).toBe(0.8);
    expect(useMakeupStore.getState().arVersion).toBe(proposal.expectedStateVersion + 1);
  });

  it('rejects a response from an exited or replaced session', () => {
    const store = useMakeupStore.getState();
    store.prepareArCommand(request, session, proposal);
    store.endArSession();
    store.beginArSession(`${session}-new`);
    expect(store.finishArCommand(proposal.commandId, session, 'rendered').status).toBe('REJECTED');
    expect(store.prepareArCommand(request, session, proposal).status).toBe('REJECTED');
  });

  it('rejects a repeated request even if the server issues another command ID', () => {
    const store = useMakeupStore.getState();
    store.prepareArCommand(request, session, proposal);
    store.finishArCommand(proposal.commandId, session, 'rendered');
    const next = { ...proposal, commandId: `second-${serial}`, expectedStateVersion: useMakeupStore.getState().arVersion };
    expect(store.prepareArCommand(request, session, next).status).toBe('REJECTED');
  });

  it('rejects a server reply after a manual change while the request was in flight', () => {
    const store = useMakeupStore.getState();
    store.setIntensity('lip', 0.25);
    expect(store.prepareArCommand(request, session, proposal).status).toBe('REJECTED');
    expect(useMakeupStore.getState().makeup.lip?.intensity).toBe(0.25);
  });

  it('rejects an in-flight proposal when the user reasserts the current intensity', () => {
    const store = useMakeupStore.getState();
    store.setIntensity('lip', store.makeup.lip!.intensity);
    expect(store.prepareArCommand(request, session, proposal).status).toBe('REJECTED');
  });
});
