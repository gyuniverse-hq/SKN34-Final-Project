import { useAuth } from '@/lib/auth';
import { useMe } from '@/lib/queries';

export function useMemberCameraConsent() {
  const { user, ready } = useAuth();
  const me = useMe(user?.id);
  const terms = user && me.data?.user.id === user.id ? me.data.terms : undefined;
  return {
    member: !!user,
    loading: !ready || (!!user && me.isPending),
    granted: terms?.cameraFeaturesConsent === true,
  };
}
