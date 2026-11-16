import { adjacentIndex, intensityTarget, paintControl, reject, result, type ConfirmPaint, type ControlOperation } from './arControl';
import { effectiveHighlighterAreas, HIGHLIGHTER_AREAS, HIGHLIGHT_FACES } from './arFacePalette';
import { colorFamily, COLOR_FAMILIES } from './colorFamily';
import { LIP_TYPES, pickForMakeup, rankShadePreferences, shadeTone, usableShadeTone, type ShadePreference } from './arShadePreference';
import { HIGHLIGHTER_STYLE_IDS, type FaceShape } from './faceFit';
import { isLipBaseCare, lipCareKind, lipTextureChip, LIP_TEXTURE_CHIPS } from './lipCare';
import { LINER_LOOK_IDS, LINER_LOOKS } from './linerLooks';
import { SHADOW_FINISH_IDS } from './shadowFinishes';
import type { ColorSwatch } from './nearbyColors';
import { AR_PAINT_ZONES, isArPaintZone, useMakeupStore } from '@/store/makeupStore';
import type { MakeupState, MakeupZone, Product, ZoneGeometry } from '@/types';

export const shadeInfo = (item?: ColorSwatch | null) => item ? {
  productId: item.product.id, shadeId: item.shade.id, brand: item.product.brand,
  product: item.product.name, shade: item.shade.name, texture: item.product.texture,
} : null;

const normalizeCatalogName = (value: string) => value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, '');

/** Supply actual catalog names occurring in this message, including spaced shade names. */
export function catalogNameMatches(products: Product[], message: string) {
  const text = normalizeCatalogName(message);
  return products.filter(product => product.texture && product.makeupZone &&
    isArPaintZone(product.makeupZone) && !isLipBaseCare(product))
    .flatMap(product => product.shades.filter(shade => {
      const name = normalizeCatalogName(shade.name);
      return name.length > 0 && text.includes(name);
    }).map(shade => ({
      productId: product.id, shadeId: shade.id, zone: product.makeupZone,
      brand: product.brand, product: product.nameKo || product.name, shade: shade.name,
    })));
}

type Store = ReturnType<typeof useMakeupStore.getState>;
export function worn(s: Store, zone: MakeupZone, products: Product[], visibleMakeup = s.makeup) {
  const selected = s.selections[zone];
  const product = products.find(p => p.id === selected?.productId);
  const shade = product?.shades.find(i => i.id === selected?.shadeId);
  const layer = visibleMakeup[zone];
  const tone = layer && layer.intensity > 0 && shadeTone(layer.hex);
  return { zone, product: product && shade ? shadeInfo({ product, shade }) : selected ?? null,
    ...(tone && layer && {color:{family:colorFamily(layer.hex),lightness:tone.lightness,chroma:tone.chroma}}),
    intensity: s.makeup[zone]?.intensity ?? null, geometry: s.makeup[zone]?.geometry ?? null,
    ...(zone === 'lip' && { lipCare: s.careSelection }) };
}

interface Palette {
  products: Product[]; ready: boolean; display: readonly ColorSwatch[]; center: number;
  visibleMakeup?: MakeupState;
  swatchesOnly: boolean; tracking: boolean; faceShape: FaceShape | null;
  onShadeSelected?: (zone: MakeupZone, care: ReturnType<typeof lipCareKind>) => void;
}
export function makeupControls(choices: Map<string, ControlOperation>, p: Palette) {
  const store = useMakeupStore.getState();
  const paint = (zone: MakeupZone, edit: (s: Store) => void, confirm: ConfirmPaint) =>
    !p.tracking && !p.swatchesOnly ? reject('face tracking unavailable') :
      paintControl(edit, confirm, p.swatchesOnly, s => worn(s, zone, p.products));
  const apply = async (item: ColorSwatch | undefined, confirm: ConfirmPaint) => {
    if (!p.ready || !item || !item.product.makeupZone) return reject('no available shade');
    const z = item.product.makeupZone;
    const care = z === 'lip' ? lipCareKind(item.product) : null;
    const selected = care ? store.careSelection : store.selections[z];
    const same = selected?.productId === item.product.id && selected.shadeId === item.shade.id;
    const outcome = same ? result('NO_CHANGE', worn(store, z, p.products))
      : await paint(z, s => s.applyShade(item.product, item.shade), confirm);
    if (same || outcome.status === 'APPLIED') p.onShadeSelected?.(z, care);
    return outcome;
  };
  const recommend = async (item: ColorSwatch | undefined, confirm: ConfirmPaint) => {
    if (!p.ready) return reject('catalog unavailable');
    if (!item) return result('OK', { applied:false, count:0 });
    const outcome = await apply(item, confirm);
    if (outcome.status !== 'APPLIED' && outcome.status !== 'NO_CHANGE') return outcome;
    const care = item.product.makeupZone === 'lip' && lipCareKind(item.product);
    const tone = !care && usableShadeTone(item);
    return { ...outcome, featuredShade: {
      brand:item.product.brand, product:item.product.name, productKo:item.product.nameKo,
      shade:item.shade.name,
      ...(tone && {family:colorFamily(item.shade.hex), lightness:tone.lightness, chroma:tone.chroma}),
    } };
  };
  choices.set('apply_shade/palette_center', (_, c) => apply(p.display[p.center], c));
  for (const scope of ['all', ...AR_PAINT_ZONES, 'lipCare']) {
    choices.set('reapply_try_on/' + scope, ({ ordinal }, confirm) => {
      if (ordinal === undefined || !Number.isSafeInteger(ordinal) || ordinal < 1) return reject('invalid try-on position');
      const history = useMakeupStore.getState().tryOnHistory ?? [];
      const entries = scope === 'all' ? history : history.filter(entry => entry.zone === scope);
      const entry = entries[ordinal - 1];
      if (!entry) return { status: 'REJECTED', reason: 'no try-on at that position in this session',
        data: { scope, ordinal, triedCount: entries.length } };
      const product = p.products.find(item => item.id === entry.productId);
      const shade = product?.shades.find(item => item.id === entry.shadeId);
      if (!product || !shade) return reject('previously tried product or shade unavailable');
      return recommend({ product, shade }, confirm);
    });
  }
  for (const [key, delta] of [['next', 1], ['previous', -1]] as const) {
    choices.set('step_shade/' + key, ({ steps = 1 }, c) =>
      Number.isSafeInteger(steps) && steps > 0 && steps <= 100
        ? apply(p.display[adjacentIndex(p.center, delta * steps, p.display.length)], c)
        : reject('invalid step count'));
  }
  choices.set('apply_shade/product_shade', ({ productId, shadeId }, c) => {
    const product = p.products.find(item => item.id === productId && !isLipBaseCare(item));
    const shade = product?.shades.find(item => item.id === shadeId);
    return recommend(product && shade ? { product, shade } : undefined, c);
  });
  for (const z of AR_PAINT_ZONES) {
    const matches = (name?: string | null, family?: string, texture?: string, care?: string) => {
      const term = name?.trim().toLocaleLowerCase();
      return p.products.filter(item => item.makeupZone === z && (z !== 'lip' || !isLipBaseCare(item)) &&
        (care ? lipCareKind(item) === care : !(family || texture) || !lipCareKind(item)))
        .flatMap(product => product.shades.filter(shade =>
          (!family || colorFamily(shade.hex) === family) &&
          (!texture || (z === 'lip' ? lipTextureChip(product.texture) : product.texture) === texture) &&
          (!term || [product.name, product.nameKo, product.brand, shade.name, shade.id,
            product.id + '/' + shade.id].some(n => n?.toLocaleLowerCase().includes(term))))
          .map(shade => ({ product, shade })));
    };
    const search = (family?: string, texture?: string, care?: string): ControlOperation => ({ name }) => {
      if (!p.ready) return reject('catalog unavailable');
      const items = matches(name, family, texture, care);
      return result('OK', { count: items.length, shades: items.slice(0, 12).map(shadeInfo) });
    };
    choices.set('get_state/' + z, () => result('OK', worn(store, z, p.products)));
    choices.set('find_shades/' + z, search());
    const colorOptions = (name?: string | null, lipType?: ShadePreference['lipType']) => matches(name)
      .filter(({product}) => (z !== 'lip' || !lipCareKind(product)) && (!lipType || product.tags.includes(LIP_TYPES[lipType])));
    choices.set('apply_shade/' + z + '/pick', async ({name,lipType}, confirm) => {
      const {item,sources} = pickForMakeup(colorOptions(name,lipType), z, p.visibleMakeup ?? store.makeup);
      const outcome = await recommend(item, confirm);
      return outcome.featuredShade && sources.length ? {...outcome, matchedTo:sources} : outcome;
    });
    for (const action of ['apply_shade', 'find_shades']) {
      choices.set(action + '/' + z + '/by_color', (args, confirm) => {
        if (!p.ready) return reject('catalog unavailable');
        if (!args.family && !args.lightness && !args.chroma) return reject('color preference required');
        const ranked = rankShadePreferences(colorOptions(args.name,args.lipType), args);
        if (action === 'find_shades') return result('OK', { count:ranked.length, shades:ranked.slice(0, 12).map(shadeInfo) });
        return recommend(ranked[0], confirm);
      });
    }
    if (z === 'lip' || z === 'blush' || z === 'eyeshadow') {
      for (const family of COLOR_FAMILIES) {
        choices.set('find_shades/' + z + '/' + family, search(family));
      }
    }
    if (z === 'lip') {
      for (const f of COLOR_FAMILIES) {
        for (const t of LIP_TEXTURE_CHIPS) choices.set('find_shades/lip/' + f + '/' + t, search(f,t));
      }
      for (const t of LIP_TEXTURE_CHIPS) choices.set('find_shades/lip/' + t, search(undefined, t));
      for (const k of ['oil','balm']) {
        choices.set('find_shades/lip/' + k, search(undefined, undefined, k));
        choices.set('apply_shade/lip/' + k, ({name}, confirm) =>
          recommend(matches(name, undefined, undefined, k)[0], confirm));
      }
    }
    choices.set('apply_shade/' + z + '/named', ({ name }, c) => {
      if (!name) return reject('shade name required');
      const items = matches(name);
      return items.length === 1 ? apply(items[0], c) : reject(items.length ? 'ambiguous shade' : 'no matching shade');
    });
    for (const mode of ['up', 'down', 'half', 'absolute']) {
      choices.set((['up','down'].includes(mode) ? 'adjust_intensity/' : 'set_intensity/') + z + '/' + mode,
        ({ value, previousIntensityChange }, c) => {
          const layer = store.makeup[z];
          if (!layer) return reject('no applied layer');
          const target = intensityTarget(layer.intensity, mode, z === 'blush' ? 0.15 : 0, value, previousIntensityChange);
          if (target === null) return reject('intensity outside slider range');
          if (target === layer.intensity) return { status: 'NO_CHANGE', data: worn(store, z, p.products), reason: 'already at requested level or limit' };
          return paint(z, s => s.setIntensity(z, target), c);
        });
    }
    choices.set('clear_layer/' + z, (_, c) => !store.makeup[z] ? result('NO_CHANGE', worn(store, z, p.products)) : paint(z, s => s.clearZone(z), c));
    choices.set('restore_makeup/' + z, (_, c) => !store.lookOrigin ? reject('no original look') : paint(z, s => {
      s.revertZone(z, true);
    }, c));
  }
  choices.set('clear_layer/lipCare', (_, c) => !store.makeup.lipCare ? result('NO_CHANGE', worn(store, 'lip', p.products)) : paint('lip', s => s.clearLipCare(), c));
  const style = (z: MakeupZone, key: string, geometry: ZoneGeometry) =>
    choices.set('set_style/' + z + '/' + key, (_, c) => !store.makeup[z] ? reject('no applied layer') :
      paint(z, s => s.patchGeometry(z, geometry), c));
  for (const id of SHADOW_FINISH_IDS) style('eyeshadow', id, { shadowFinish: id });
  for (const id of LINER_LOOK_IDS) style('eyeliner', id, LINER_LOOKS[id]);
  for (const id of HIGHLIGHTER_STYLE_IDS) style('highlighter', id, { hlStyle: id });
  style('highlighter', 'default', { hlStyle: undefined });
  for (const id of [...HIGHLIGHT_FACES, undefined]) style('highlighter', 'face_' + (id ?? 'auto'),
    { hlFace: id, hlStyle: undefined, areas: undefined });
  const areas = effectiveHighlighterAreas(store.makeup.highlighter?.geometry, p.faceShape);
  for (const area of HIGHLIGHTER_AREAS) {
    for (const enabled of [true,false]) {
      const key = 'set_style/highlighter/' + area + (enabled ? '_on' : '_off');
      choices.set(key, (_, c) => {
        if (!store.makeup.highlighter) return reject('no applied highlighter');
        if (enabled === areas.includes(area) || (!enabled && areas.length === 1))
          return result('NO_CHANGE', { areas });
        const next = HIGHLIGHTER_AREAS.filter(a => a === area ? enabled : areas.includes(a));
        return paint('highlighter', s => s.patchGeometry('highlighter', { hlStyle: undefined, areas: next }), c);
      });
    }
  }
  return { apply, recommend };
}
