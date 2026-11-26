import { adjacentIndex, intensityTarget, paintControl, reject, result, type ConfirmPaint, type ControlOperation } from './arControl';
import { effectiveHighlighterAreas, highlighterAreaPatch, HIGHLIGHTER_AREAS, HIGHLIGHT_FACES } from './arFacePalette';
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

function featuredShade(item: ColorSwatch) {
  const care = item.product.makeupZone === 'lip' && lipCareKind(item.product);
  const tone = !care && usableShadeTone(item);
  return {
    brand: item.product.brand,
    product: item.product.name,
    productKo: item.product.nameKo,
    shade: item.shade.name,
    shadeNumber: shadeNumber(item.shade.id),
    ...(tone && { family: colorFamily(item.shade.hex), lightness: tone.lightness, chroma: tone.chroma }),
  };
}

const normalizeCatalogName = (value: string) => value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, '');
const shadeNumber = (id: string) => /^[0-9]{1,3}$/.test(id) ? id : undefined;

function productReference(product: Product, text: string) {
  const brand = product.brand.normalize('NFKC').trim();
  const references = [product.name, product.nameKo].filter(Boolean).flatMap(name => {
    const title = name.normalize('NFKC').trim();
    const label = title.replace(/\[[^\]]*\]|\([^)]*\)/g, ' ').trim()
      .replace(/\s+\d+(?:\.\d+)?\s*(?:ml|g|oz)\b(?:\s+.*)?$/i, '')
      .replace(/\s+\d+\s*(?:colors?|종)$/i, '').trim();
    const hasBrand = label.toLocaleLowerCase().startsWith(brand.toLocaleLowerCase() + ' ');
    return [title, label, hasBrand ? label.slice(brand.length).trim() : `${brand} ${label}`.trim()];
  });
  return references.filter(reference => {
    const key = normalizeCatalogName(reference);
    return key.length >= 2 && text.includes(key);
  }).sort((left, right) => normalizeCatalogName(right).length - normalizeCatalogName(left).length)[0];
}

/** Supply product and shade references grounded in the utterance and the current catalog. */
export function catalogMatches(products: Product[], message: string) {
  const text = normalizeCatalogName(message);
  const numbers = new Set((message.normalize('NFKC').match(/[0-9]+/g) ?? []).map(number => Number(number)));
  const catalogProductMatches = [];
  const catalogNameMatches = [];
  for (const product of products) {
    const zone = product.makeupZone;
    if (!product.texture || !zone || !isArPaintZone(zone) || isLipBaseCare(product)) continue;
    const entry = { productId: product.id, zone, brand: product.brand, product: product.nameKo || product.name };
    const reference = productReference(product, text);
    if (reference) catalogProductMatches.push({ ...entry, reference });
    for (const shade of product.shades) {
      const name = normalizeCatalogName(shade.name);
      const number = shadeNumber(shade.id);
      if ((name && text.includes(name)) || (reference && number && numbers.has(Number(number)))) {
        catalogNameMatches.push({ ...entry, shadeId: shade.id, shade: shade.name });
      }
    }
  }
  return { catalogProductMatches, catalogNameMatches };
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
    ...(zone === 'eyeshadow' && { point: layer?.hexTo ? { hex: layer.hexTo, family: colorFamily(layer.hexTo) } : null }),
    ...(zone === 'lip' && { lipCare: s.careSelection }) };
}

interface Palette {
  products: Product[]; ready: boolean; display: readonly ColorSwatch[]; center: number;
  visibleMakeup?: MakeupState;
  swatchesOnly: boolean; tracking: boolean; faceShape: FaceShape | null;
  faceTemporarilyMissing?: boolean;
  shadowPointing?: boolean;
  onShadowPointCleared?: () => void;
  onShadeSelected?: (zone: MakeupZone, care: ReturnType<typeof lipCareKind>, item: ColorSwatch, point: boolean) => void;
}
export function makeupControls(choices: Map<string, ControlOperation>, p: Palette) {
  const store = useMakeupStore.getState();
  const paint = (zone: MakeupZone, edit: (s: Store) => void, confirm: ConfirmPaint, selectOnly = false) => {
    const skipFrame = p.swatchesOnly || selectOnly;
    return !p.tracking && !skipFrame ? reject('face tracking unavailable') :
      paintControl(edit, confirm, skipFrame, s => worn(s, zone, p.products));
  };
  const apply = async (item: ColorSwatch | undefined, confirm: ConfirmPaint) => {
    if (!p.ready || !item || !item.product.makeupZone) return reject('no available shade');
    const z = item.product.makeupZone;
    const care = z === 'lip' ? lipCareKind(item.product) : null;
    const selected = care ? store.careSelection : store.selections[z];
    const same = selected?.productId === item.product.id && selected.shadeId === item.shade.id;
    const renderPending = !!p.faceTemporarilyMissing && !p.tracking && !p.swatchesOnly;
    const outcome = same ? result('NO_CHANGE', worn(store, z, p.products))
      : await paint(z, s => s.applyShade(item.product, item.shade), confirm, renderPending);
    if (outcome.status === 'APPLIED' || outcome.status === 'NO_CHANGE') {
      p.onShadeSelected?.(z, care, item, false);
      if (renderPending) return { ...outcome, status: 'OK' as const, renderPending: true as const, featuredShade: featuredShade(item) };
    }
    return outcome;
  };
  const recommend = async (item: ColorSwatch | undefined, confirm: ConfirmPaint) => {
    if (!p.ready) return reject('catalog unavailable');
    if (!item) return result('OK', { applied:false, count:0 });
    const outcome = await apply(item, confirm);
    if (outcome.status !== 'APPLIED' && outcome.status !== 'NO_CHANGE') return outcome;
    return { ...outcome, featuredShade: featuredShade(item) };
  };
  const pick = async (items: ColorSwatch[], zone: MakeupZone, confirm: ConfirmPaint) => {
    const { item, sources } = pickForMakeup(items, zone, p.visibleMakeup ?? store.makeup);
    const outcome = await recommend(item, confirm);
    return outcome.featuredShade && sources.length ? { ...outcome, matchedTo: sources } : outcome;
  };
  const paintPoint = (hex: string | null, confirm: ConfirmPaint) =>
    store.makeup.eyeshadow ? paint('eyeshadow', s => s.setShadowPoint(hex), confirm) : reject('no eyeshadow base');
  const applyPoint = async (item: ColorSwatch | undefined, confirm: ConfirmPaint) => {
    if (!p.ready || !item || item.product.makeupZone !== 'eyeshadow') return reject('no available eyeshadow shade');
    const outcome = await paintPoint(item.shade.hex, confirm);
    if (outcome.status !== 'APPLIED' && outcome.status !== 'NO_CHANGE') return outcome;
    p.onShadeSelected?.('eyeshadow', null, item, true);
    return { ...outcome, data: { pointShade: shadeInfo(item) } };
  };
  const applyDisplayed = p.shadowPointing ? applyPoint : apply;
  choices.set('apply_shade/palette_center', (_, c) => applyDisplayed(p.display[p.center], c));
  choices.set('set_shadow_point/palette_center', (_, c) => applyPoint(p.display[p.center], c));
  choices.set('set_shadow_point/product_shade', ({ productId, shadeId }, c) => {
    const product = p.products.find(item => item.id === productId && item.makeupZone === 'eyeshadow');
    const shade = product?.shades.find(item => item.id === shadeId);
    return applyPoint(product && shade ? { product, shade } : undefined, c);
  });
  choices.set('set_shadow_point/clear', async (_, c) => {
    if (store.makeup.eyeshadow && !store.makeup.eyeshadow.hexTo) {
      p.onShadowPointCleared?.();
      return result('NO_CHANGE', worn(store, 'eyeshadow', p.products));
    }
    const outcome = await paintPoint(null, c);
    if (outcome.status === 'APPLIED' || outcome.status === 'NO_CHANGE') p.onShadowPointCleared?.();
    return outcome;
  });
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
        ? applyDisplayed(p.display[adjacentIndex(p.center, delta * steps, p.display.length)], c)
        : reject('invalid step count'));
  }
  choices.set('apply_shade/product_shade', ({ productId, shadeId }, c) => {
    const product = p.products.find(item => item.id === productId && !isLipBaseCare(item));
    const shade = product?.shades.find(item => item.id === shadeId);
    return recommend(product && shade ? { product, shade } : undefined, c);
  });
  choices.set('apply_shade/product_pick', ({ productId, family, lightness, chroma }, confirm) => {
    const product = p.products.find(item => item.id === productId && !isLipBaseCare(item));
    if (!product?.makeupZone) return reject('no available product');
    const items = product.shades.map(shade => ({ product, shade }));
    const candidates = family || lightness || chroma ? rankShadePreferences(items, { family, lightness, chroma }) : items;
    return pick(candidates, product.makeupZone, confirm);
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
    if (z === 'eyeshadow') {
      choices.set('set_shadow_point/by_color', (args, confirm) => {
        if (!args.family && !args.lightness && !args.chroma) return reject('color preference required');
        return applyPoint(rankShadePreferences(colorOptions(args.name), args)[0], confirm);
      });
    }
    choices.set('apply_shade/' + z + '/pick', ({ name, lipType }, confirm) => pick(colorOptions(name, lipType), z, confirm));
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
      if (!p.ready) return reject('catalog unavailable');
      const key = normalizeCatalogName(name ?? '');
      if (!key) return reject('shade name required');
      const items = matches().filter(({ product, shade }) =>
        product.texture && normalizeCatalogName(shade.name) === key);
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
  for (const area of HIGHLIGHTER_AREAS) {
    for (const enabled of [true,false]) {
      const key = 'set_style/highlighter/' + area + (enabled ? '_on' : '_off');
      choices.set(key, (_, c) => {
        const layer = store.makeup.highlighter;
        if (!layer) return reject('no applied highlighter');
        const patch = highlighterAreaPatch(layer.geometry, p.faceShape, area, enabled);
        if (!patch) return result('NO_CHANGE', { areas: effectiveHighlighterAreas(layer.geometry, p.faceShape) });
        return paint('highlighter', s => s.patchGeometry('highlighter', patch), c);
      });
    }
  }
  return { apply, recommend };
}
