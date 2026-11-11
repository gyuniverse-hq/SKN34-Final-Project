import { create } from 'zustand';
import { LIP_CARE_INTENSITY, lipCareFor } from '@/lib/lipCare';
import type { CelebLook, ColorLink, MakeupState, MakeupZone, Product, Shade, ZoneGeometry, ZoneSetting } from '@/types';

export interface ZoneSelection {
  productId: string;
  shadeId: string;
}

type ArProposalBase = {
  commandId: string;
  expectedStateVersion: number;
  productId: string;
  shadeId: string;
};

export type ArProposal =
  | (ArProposalBase & { action: 'set_intensity'; zone: 'lip'; value: number })
  | (ArProposalBase & { action: 'set_geometry'; zone: MakeupZone; style: string; geometry: ZoneGeometry });

export type ArOutcome = {
  status: 'APPLIED' | 'NO_CHANGE' | 'REJECTED' | 'FAILED' | 'UNKNOWN';
  actualStateVersion: number;
};

export type PendingArCommand = {
  requestId: string;
  sessionId: string;
  proposal: ArProposal;
};

/** Product-page try-on: this shade only, until the AR tab is left. Memory only. */
export interface ProductFit {
  productId: string;
  shadeId: string;
}

interface LookOrigin {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
}

interface FitOrigin {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
  careSelection: ZoneSelection | null;
  activeLook: { id: string; title: string } | null;
  colorLinks: ColorLink[];
  heroZones: MakeupZone[];
  stepOrder: MakeupZone[];
  modified: MakeupZone[];
  lookOrigin: LookOrigin | null;
}

/** Every zone a look can name. Look recipes, look cards, and look guides still keep mascara. */
export const MAKEUP_ZONES: MakeupZone[] = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour', 'brow', 'foundation'];

/** Zones the AR panel can pick. Mascara is look/video only (no explore chip). */
export const AR_PAINT_ZONES: MakeupZone[] = [
  'lip',
  'blush',
  'eyeshadow',
  'eyeliner',
  'highlighter',
  'contour',
  'brow',
  'foundation',
];

/** Camera paint for celebrity/style looks: AR chips plus mascara. */
export const LOOK_PAINT_ZONES: MakeupZone[] = [...AR_PAINT_ZONES, 'mascara'];

export function isArPaintZone(zone: MakeupZone): boolean {
  return AR_PAINT_ZONES.includes(zone);
}

export function isLookPaintZone(zone: MakeupZone): boolean {
  return LOOK_PAINT_ZONES.includes(zone);
}

const GEOMETRY_KEYS = new Set<string>([
  'length', 'angle', 'thickness', 'linerStyle', 'linerSoftness', 'linerLower', 'linerLowerThickness',
  'upperLine', 'underline', 'underlineThickness', 'underlineAlpha', 'underlineStart', 'underlineLength',
  'underlineJoin', 'lower', 'overlip', 'peakOverdraw', 'centerHighlight', 'areas', 'hlFace', 'hlStyle',
  'contourStyle', 'pearl', 'sparkle', 'glitter', 'shadowFinish', 'blushPlacement', 'blushSize',
  'blushSoftness', 'intensity',
]);

function geometrySnapshot(geometry: ZoneGeometry | undefined): string {
  const keys = Object.keys(geometry ?? {}).sort();
  return JSON.stringify(geometry ?? {}, keys);
}

function isCommandGeometry(value: unknown): value is ZoneGeometry {
  if (!value || typeof value !== 'object' || Array.isArray(value) || 'innerPoint' in value) return false;
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((key) => GEOMETRY_KEYS.has(key));
}

/** Face paint for the camera. Mascara is included when a look or video set it. */
export function arPaintMakeup(makeup: MakeupState): MakeupState {
  return makeup;
}

export const DEFAULT_INTENSITY: Record<MakeupZone, number> = {
  lip: 0.65,
  blush: 0.45,
  eyeshadow: 0.45,
  eyeliner: 0.85,
  mascara: 0.7,
  highlighter: 0.5,
  contour: 0.55,
  brow: 0.7,
  foundation: 0.45,
};

interface MakeupStore {
  makeup: MakeupState;
  selections: Partial<Record<MakeupZone, ZoneSelection>>;
  /** The lip oil / balm worn over the colour lip (makeup.lipCare). Separate from selections: it layers, it never replaces. */
  careSelection: ZoneSelection | null;
  activeLook: { id: string; title: string } | null;
  /** Links of the applied look: zones that keep one shared color while the user swaps products. */
  colorLinks: ColorLink[];
  /** Key zones of the applied look, in the order to show them. */
  heroZones: MakeupZone[];
  /** The applied look's own order of zones (empty = default order). */
  stepOrder: MakeupZone[];
  /** Zones whose color or on/off state differs from the applied look (intensity does not count). */
  modified: MakeupZone[];
  /** The applied look as it was loaded, so a zone can go back to it. */
  lookOrigin: LookOrigin | null;
  /** Shop try-on: lock to one product shade. Null in the explore tab. */
  fit: ProductFit | null;
  fitOrigin: FitOrigin | null;
  arVersion: number;
  arSessionId: string | null;
  pendingArCommand: PendingArCommand | null;
  processedArCommands: Record<string, true>;
  processedArRequests: Record<string, true>;
  beginArSession: (sessionId: string) => void;
  endArSession: () => void;
  prepareArCommand: (
    requestId: string, sessionId: string, proposal: ArProposal
  ) => ArOutcome | { status: 'PENDING'; actualStateVersion: number };
  finishArCommand: (
    commandId: string, sessionId: string, result: 'rendered' | 'failed' | 'unknown'
  ) => ArOutcome;
  cancelArCommand: () => ArOutcome | null;
  applyShade: (product: Product, shade: Shade) => void;
  applyLook: (look: CelebLook, products: Product[]) => void;
  setIntensity: (zone: MakeupZone, intensity: number) => void;
  /** Merge shape fields (liner wing, shadow gradient). Hex and texture stay. */
  patchGeometry: (zone: MakeupZone, geometry: ZoneGeometry) => void;
  clearZone: (zone: MakeupZone) => void;
  /** Take the lip oil / balm off; the colour lip stays. */
  clearLipCare: () => void;
  /** Put a zone (and the zones linked to it) back to the look's color and product, keeping the user's intensity. */
  revertZone: (zone: MakeupZone) => void;
  /** Paint only this product shade; snapshot the current face to restore when the AR tab is left. */
  startFit: (product: Product, shade: Shade) => void;
  endFit: () => void;
  /** Look-only mascara: drop it when leaving the look camera. */
  clearLookMascara: () => void;
  reset: () => void;
}

/**
 * Same color and product as the look loaded (intensity and shape are the user's to move). A zone the look
 * fills with a product is the same when that product and shade are worn again; otherwise the color decides.
 */
function sameAsOrigin(
  zone: MakeupZone,
  makeup: MakeupState,
  selections: Partial<Record<MakeupZone, ZoneSelection>>,
  origin: LookOrigin
): boolean {
  const a = makeup[zone], b = origin.makeup[zone];
  if (!a || !b) return !a && !b;
  const sa = selections[zone], sb = origin.selections[zone];
  if (sb) return sa?.productId === sb.productId && sa?.shadeId === sb.shadeId;
  return !sa && a.hex === b.hex && a.texture === b.texture;
}

function modifiedZones(
  makeup: MakeupState,
  selections: Partial<Record<MakeupZone, ZoneSelection>>,
  origin: LookOrigin | null
): MakeupZone[] {
  return origin ? MAKEUP_ZONES.filter((z) => !sameAsOrigin(z, makeup, selections, origin)) : [];
}

const EMPTY: MakeupState = {
  lip: null,
  blush: null,
  eyeshadow: null,
  eyeliner: null,
  mascara: null,
  highlighter: null,
  contour: null,
  brow: null,
  foundation: null,
};

export const useMakeupStore = create<MakeupStore>((rawSet) => {
  // All existing manual mutations pass this gate, including fit and look restoration.
  const set = (update: Partial<MakeupStore> | ((state: MakeupStore) => Partial<MakeupStore> | MakeupStore)) => {
    rawSet((state) => {
      const patch = typeof update === 'function' ? update(state) : update;
      if (patch === state) return state;
      const arFields = ['makeup', 'selections', 'careSelection', 'fit', 'fitOrigin', 'activeLook',
        'colorLinks', 'heroZones', 'stepOrder', 'modified', 'lookOrigin'] as const;
      const affectsAr = arFields.some((key) => key in patch);
      if (!affectsAr) return patch;
      return {
        ...patch,
        // Even a repeated value is a later user decision and invalidates an in-flight proposal.
        arVersion: Math.min(state.arVersion + 1, Number.MAX_SAFE_INTEGER),
        pendingArCommand: null,
      };
    });
  };
  return {
  makeup: EMPTY,
  selections: {},
  careSelection: null,
  activeLook: null,
  colorLinks: [],
  heroZones: [],
  stepOrder: [],
  modified: [],
  lookOrigin: null,
  fit: null,
  fitOrigin: null,
  arVersion: 0,
  arSessionId: null,
  pendingArCommand: null,
  processedArCommands: {},
  processedArRequests: {},

  beginArSession: (sessionId) => rawSet({ arSessionId: sessionId || null, pendingArCommand: null }),
  endArSession: () => rawSet({ arSessionId: null, pendingArCommand: null }),

  prepareArCommand: (requestId, sessionId, proposal) => {
    let outcome: ArOutcome | { status: 'PENDING'; actualStateVersion: number } = {
      status: 'REJECTED', actualStateVersion: 0,
    };
    rawSet((state) => {
      outcome = { status: 'REJECTED', actualStateVersion: state.arVersion };
      const zone = proposal?.zone;
      const selected = zone ? state.selections[zone] : undefined;
      const painted = zone ? state.makeup[zone] : undefined;
      const intensityOk = proposal?.action === 'set_intensity' && proposal.zone === 'lip' &&
        Number.isFinite(proposal.value) && proposal.value >= 0 && proposal.value <= 1;
      const geometryOk = proposal?.action === 'set_geometry' && isLookPaintZone(proposal.zone) &&
        typeof proposal.style === 'string' && proposal.style && isCommandGeometry(proposal.geometry);
      if (typeof requestId !== 'string' || !requestId || typeof sessionId !== 'string' || !sessionId ||
          !proposal || typeof proposal !== 'object' || typeof proposal.commandId !== 'string' || !proposal.commandId ||
          state.processedArRequests[requestId] || state.processedArCommands[proposal.commandId] ||
          state.pendingArCommand || state.arSessionId !== sessionId || state.fit || !painted ||
          !Number.isSafeInteger(proposal.expectedStateVersion) || proposal.expectedStateVersion !== state.arVersion ||
          state.arVersion >= Number.MAX_SAFE_INTEGER || (!intensityOk && !geometryOk) ||
          !selected || selected.productId !== proposal.productId || selected.shadeId !== proposal.shadeId) return state;
      outcome = { status: 'PENDING', actualStateVersion: state.arVersion };
      return {
        pendingArCommand: { requestId, sessionId, proposal: { ...proposal } },
        processedArCommands: { ...state.processedArCommands, [proposal.commandId]: true },
        processedArRequests: { ...state.processedArRequests, [requestId]: true },
      };
    });
    return outcome;
  },

  finishArCommand: (commandId, sessionId, result) => {
    let outcome: ArOutcome = { status: 'REJECTED', actualStateVersion: 0 };
    rawSet((state) => {
      outcome = { status: 'REJECTED', actualStateVersion: state.arVersion };
      const pending = state.pendingArCommand;
      if (!pending || pending.sessionId !== sessionId || pending.proposal.commandId !== commandId) return state;
      if (result !== 'rendered') {
        outcome = { status: result === 'failed' ? 'FAILED' : 'UNKNOWN', actualStateVersion: state.arVersion };
        return { pendingArCommand: null };
      }
      const proposal = pending.proposal;
      const painted = state.makeup[proposal.zone];
      const selected = state.selections[proposal.zone];
      if (state.arSessionId !== sessionId || state.fit || !painted || !selected ||
          state.arVersion !== proposal.expectedStateVersion || selected.productId !== proposal.productId ||
          selected.shadeId !== proposal.shadeId) return { pendingArCommand: null };
      if (proposal.action === 'set_intensity') {
        if (painted.intensity === proposal.value) {
          outcome = { status: 'NO_CHANGE', actualStateVersion: state.arVersion };
          return { pendingArCommand: null };
        }
        const arVersion = state.arVersion + 1;
        outcome = { status: 'APPLIED', actualStateVersion: arVersion };
        return { makeup: { ...state.makeup, lip: { ...painted, intensity: proposal.value } }, arVersion, pendingArCommand: null };
      }
      const nextGeometry = { ...painted.geometry, ...proposal.geometry };
      if (geometrySnapshot(painted.geometry) === geometrySnapshot(nextGeometry)) {
        outcome = { status: 'NO_CHANGE', actualStateVersion: state.arVersion };
        return { pendingArCommand: null };
      }
      const arVersion = state.arVersion + 1;
      outcome = { status: 'APPLIED', actualStateVersion: arVersion };
      return {
        makeup: { ...state.makeup, [proposal.zone]: { ...painted, geometry: nextGeometry } },
        arVersion,
        pendingArCommand: null,
      };
    });
    return outcome;
  },

  cancelArCommand: () => {
    let outcome: ArOutcome | null = null;
    rawSet((state) => {
      if (!state.pendingArCommand) return state;
      outcome = { status: 'REJECTED', actualStateVersion: state.arVersion };
      return { pendingArCommand: null };
    });
    return outcome;
  },

  applyShade: (product, shade) => {
    const zone = product.makeupZone;
    const texture = product.texture;
    if (!zone || !isArPaintZone(zone)) return;
    // A lip oil / balm is a layer over the colour lip: it replaces the other care product (oil <-> balm), never the colour.
    const care = zone === 'lip' ? lipCareFor(product, shade) : undefined;
    if (care) {
      set((s) => {
        if (s.fit) return s;
        const layer: ZoneSetting = { hex: shade.hex, texture: texture ?? 'glossy', intensity: LIP_CARE_INTENSITY, care };
        return { makeup: { ...s.makeup, lipCare: layer }, careSelection: { productId: product.id, shadeId: shade.id } };
      });
      return;
    }
    if (!texture) return;
    set((s) => {
      if (s.fit) return s;
      // Only the color and finish change: the look's shape (wing angle, second shadow tone, ...) stays.
      const prev = s.makeup[zone];
      const next: ZoneSetting = {
        hex: shade.hex,
        texture,
        intensity: prev?.intensity ?? DEFAULT_INTENSITY[zone],
        ...(prev?.hexTo ? { hexTo: prev.hexTo } : {}),
        ...(prev?.geometry ? { geometry: prev.geometry } : {}),
      };
      const makeup: MakeupState = { ...s.makeup, [zone]: next };
      const selections = { ...s.selections, [zone]: { productId: product.id, shadeId: shade.id } };
      // A linked zone follows the new color but keeps its own finish and strength. It no longer shows a
      // product shade, so it drops out of the selection (the cart must not list a shade it is not wearing).
      for (const link of s.colorLinks) {
        if (!link.followOnChange || !link.zones.includes(zone)) continue;
        for (const other of link.zones) {
          const current = makeup[other];
          if (other === zone || !current) continue;
          makeup[other] = { ...current, hex: shade.hex };
          delete selections[other];
        }
      }
      // The look stays applied; the zones that moved off it are listed in `modified`.
      return { makeup, selections, modified: modifiedZones(makeup, selections, s.lookOrigin) };
    });
  },

  applyLook: (look, products) => {
    set((s) => {
      if (s.fit) return s;
      const selections: Partial<Record<MakeupZone, ZoneSelection>> = {};
      for (const item of look.items) {
        const product = products.find((p) => p.id === item.productId);
        if (product?.makeupZone && item.shadeId && product.shades.some((shade) => shade.id === item.shadeId)) {
          selections[product.makeupZone] = { productId: product.id, shadeId: item.shadeId };
        }
      }
      const makeup = { ...EMPTY, ...look.makeup };
      // A look's lip made of a care product (oil / balm) becomes the care layer, drawn see-through like a picked one.
      let careSelection: ZoneSelection | null = null;
      const lipSel = selections.lip;
      const lipProduct = lipSel ? products.find((p) => p.id === lipSel.productId) : undefined;
      const lipShade = lipProduct?.shades.find((sh) => sh.id === lipSel?.shadeId);
      const lipCare = makeup.lip && lipProduct && lipShade ? lipCareFor(lipProduct, lipShade) : undefined;
      if (makeup.lip && lipCare && lipSel) {
        makeup.lipCare = { ...makeup.lip, intensity: LIP_CARE_INTENSITY, care: lipCare };
        makeup.lip = null;
        careSelection = lipSel;
        delete selections.lip;
      }
      return {
        makeup,
        selections,
        careSelection,
        activeLook: { id: look.id, title: look.title },
        colorLinks: look.colorLinks ?? [],
        heroZones: look.heroZones ?? [],
        stepOrder: look.stepOrder ?? [],
        modified: [],
        lookOrigin: { makeup, selections },
      };
    });
  },

  setIntensity: (zone, intensity) =>
    set((s) => {
      if (s.fit) return s;
      const current = s.makeup[zone];
      if (!current) return s;
      return { makeup: { ...s.makeup, [zone]: { ...current, intensity } } };
    }),

  patchGeometry: (zone, geometry) =>
    set((s) => {
      if (s.fit) return s;
      const current = s.makeup[zone];
      if (!current) return s;
      return {
        makeup: { ...s.makeup, [zone]: { ...current, geometry: { ...current.geometry, ...geometry } } },
      };
    }),

  clearZone: (zone) =>
    set((s) => {
      if (s.fit) return s;
      const selections = { ...s.selections };
      delete selections[zone];
      const makeup = { ...s.makeup, [zone]: null };
      return { makeup, selections, modified: modifiedZones(makeup, selections, s.lookOrigin) };
    }),

  clearLipCare: () =>
    set((s) => {
      if (s.fit || !s.makeup.lipCare) return s;
      return { makeup: { ...s.makeup, lipCare: null }, careSelection: null };
    }),

  revertZone: (zone) =>
    set((s) => {
      if (s.fit) return s;
      const origin = s.lookOrigin;
      if (!origin) return s;
      const zones = new Set<MakeupZone>([zone]);
      for (const link of s.colorLinks) if (link.zones.includes(zone)) link.zones.forEach((z) => zones.add(z));
      const makeup = { ...s.makeup };
      const selections = { ...s.selections };
      for (const z of zones) {
        const back = origin.makeup[z];
        makeup[z] = back ? { ...back, intensity: s.makeup[z]?.intensity ?? back.intensity } : null;
        const sel = origin.selections[z];
        if (sel) selections[z] = sel;
        else delete selections[z];
      }
      return { makeup, selections, modified: modifiedZones(makeup, selections, origin) };
    }),

  startFit: (product, shade) => {
    const zone = product.makeupZone;
    const texture = product.texture;
    if (!zone || !isArPaintZone(zone)) return;
    const care = zone === 'lip' ? lipCareFor(product, shade) : undefined;
    if (!texture && !care) return;
    set((s) => {
      const origin: FitOrigin = s.fitOrigin ?? {
        makeup: s.makeup,
        selections: s.selections,
        careSelection: s.careSelection,
        activeLook: s.activeLook,
        colorLinks: s.colorLinks,
        heroZones: s.heroZones,
        stepOrder: s.stepOrder,
        modified: s.modified,
        lookOrigin: s.lookOrigin,
      };
      if (care) {
        // Fitting a care product: it goes over the user's current colour lip (the other zones stay as they were).
        const layer: ZoneSetting = { hex: shade.hex, texture: texture ?? 'glossy', intensity: LIP_CARE_INTENSITY, care };
        return {
          fit: { productId: product.id, shadeId: shade.id },
          fitOrigin: origin,
          makeup: { ...origin.makeup, lipCare: layer },
          careSelection: { productId: product.id, shadeId: shade.id },
        };
      }
      const painted: ZoneSetting = {
        hex: shade.hex,
        texture: texture!,
        intensity: DEFAULT_INTENSITY[zone],
      };
      return {
        fit: { productId: product.id, shadeId: shade.id },
        fitOrigin: origin,
        makeup: { ...origin.makeup, [zone]: painted },
        selections: { ...origin.selections, [zone]: { productId: product.id, shadeId: shade.id } },
      };
    });
  },

  endFit: () =>
    set((s) => {
      const origin = s.fitOrigin;
      if (!origin) return { fit: null, fitOrigin: null };
      return {
        fit: null,
        fitOrigin: null,
        makeup: origin.makeup,
        selections: origin.selections,
        careSelection: origin.careSelection,
        activeLook: origin.activeLook,
        colorLinks: origin.colorLinks,
        heroZones: origin.heroZones,
        stepOrder: origin.stepOrder,
        modified: origin.modified,
        lookOrigin: origin.lookOrigin,
      };
    }),

  clearLookMascara: () =>
    set((s) => {
      if (s.fit || !s.makeup.mascara) return s;
      const selections = { ...s.selections };
      delete selections.mascara;
      const makeup = { ...s.makeup, mascara: null };
      return { makeup, selections, modified: modifiedZones(makeup, selections, s.lookOrigin) };
    }),

  reset: () =>
    set({
      makeup: EMPTY,
      selections: {},
      careSelection: null,
      activeLook: null,
      colorLinks: [],
      heroZones: [],
      stepOrder: [],
      modified: [],
      lookOrigin: null,
      fit: null,
      fitOrigin: null,
    }),
  };
});
