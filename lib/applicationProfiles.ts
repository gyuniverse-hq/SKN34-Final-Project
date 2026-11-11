import type { ApplicationProfile, ApplicationProfileOverrides } from '@/types';

/** No video-derived profile is shipped until fitting and different-angle validation both improve. */
export const APPLICATION_PROFILES: Readonly<Record<string, ApplicationProfile>> = {};

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
