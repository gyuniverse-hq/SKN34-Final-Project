import type { ApplicationProfile, ApplicationProfileOverrides, LookApplicationProfile, MakeupZone } from '@/types';

/** No video-derived profile is shipped until fitting and different-angle validation both improve. */
export const APPLICATION_PROFILES: Readonly<Record<string, ApplicationProfile>> = {};

/**
 * Measured, validated look profiles. Video looks tuned by eye live in lib/videoLookStyles.ts (the Sullyoon lip candidate
 * #8D4A50 that used to sit here was replaced there on 2026-11-13).
 */
export const LOOK_APPLICATION_PROFILES: Readonly<Record<string, LookApplicationProfile>> = {};

export function validatedLookApplicationProfile(profile: LookApplicationProfile | undefined, zone?: MakeupZone): LookApplicationProfile | undefined {
  if (!profile || profile.source !== 'video-fit' || !profile.videoId || !profile.fitFrame ||
      !profile.validationFrame || profile.fitFrame === profile.validationFrame || !profile.overrides ||
      !['left', 'right', 'open'].includes(profile.validationView)) return undefined;
  if (profile.lookHex !== undefined && !/^#[0-9a-f]{6}$/i.test(profile.lookHex)) return undefined;
  const values = [profile.fitErrorBefore, profile.fitErrorAfter, profile.validationErrorBefore, profile.validationErrorAfter];
  if (values.some((value) => !Number.isFinite(value) || value < 0) ||
      profile.fitErrorAfter >= profile.fitErrorBefore || profile.validationErrorAfter >= profile.validationErrorBefore) return undefined;
  if (zone && profile.validationView === 'open') return undefined; // An open-mouth frame cannot replace an angle check.
  if (zone === 'lip') {
    const open = profile.lipOpenValidation;
    if (!open?.frame || open.frame === profile.fitFrame || open.frame === profile.validationFrame ||
        !Number.isFinite(open.errorBefore) || !Number.isFinite(open.errorAfter) ||
        open.errorBefore < 0 || open.errorAfter < 0 || open.errorAfter >= open.errorBefore) return undefined;
  }
  return profile;
}

export function lookApplicationProfileFor(videoId: string, zone: MakeupZone): LookApplicationProfile | undefined {
  const key = `${videoId}:${zone}`;
  const profile = Object.prototype.hasOwnProperty.call(LOOK_APPLICATION_PROFILES, key) ? LOOK_APPLICATION_PROFILES[key] : undefined;
  return profile?.videoId === videoId ? validatedLookApplicationProfile(profile, zone) : undefined;
}

export function validatedApplicationProfile(profile: ApplicationProfile | undefined): ApplicationProfileOverrides | undefined {
  if (!profile || profile.source !== 'video-fit' || profile.validationView !== 'different-angle' ||
      !profile.videoId || !profile.overrides) return undefined;
  const values = [profile.fitFrameSeconds, profile.validationFrameSeconds, profile.fitErrorBefore,
    profile.fitErrorAfter, profile.validationErrorBefore, profile.validationErrorAfter];
  if (values.some((value) => !Number.isFinite(value) || value < 0)) return undefined;
  if (profile.fitFrameSeconds === profile.validationFrameSeconds ||
      profile.fitErrorAfter >= profile.fitErrorBefore ||
      profile.validationErrorAfter >= profile.validationErrorBefore) return undefined;
  return profile.overrides;
}

export function applicationProfileFor(productId: string, shadeId: string): ApplicationProfileOverrides | undefined {
  const key = `${productId}:${shadeId}`;
  return Object.prototype.hasOwnProperty.call(APPLICATION_PROFILES, key)
    ? validatedApplicationProfile(APPLICATION_PROFILES[key]) : undefined;
}
