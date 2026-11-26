import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LookPreviewBody } from '@/components/look/LookPreviewBody';
import { theme } from '@/constants/theme';
import { demoLookTitleKey } from '@/lib/demoLookAr';
import { useI18n } from '@/lib/i18n';
import { buildLookPreview } from '@/lib/lookPreview';
import { arHref, paramValue, productHref } from '@/lib/routes';
import { useCartStore } from '@/store/cartStore';
import { useLookPreviewStore } from '@/store/lookPreviewStore';
import { useLookMakeupStore } from '@/store/makeupStore';

const ADDED_NOTICE_MS = 4000;

export default function LookPreviewScreen() {
  const router = useRouter();
  const { t } = useI18n();
  const { id, title: rawTitle } = useLocalSearchParams<{ id?: string; title?: string }>();
  const lookId = paramValue(id);
  const draft = useLookPreviewStore((state) => (state.draft?.look.id === lookId ? state.draft : null));
  const addToCart = useCartStore((state) => state.add);
  const entered = useRef(false);
  const [addedNotice, setAddedNotice] = useState(false);
  const zones = useMemo(
    () => (draft ? buildLookPreview(draft.look, draft.products, draft.video) : []),
    [draft],
  );
  const titleKey = draft?.video && lookId ? demoLookTitleKey(lookId) : null;
  const title =
    (titleKey ? t(titleKey) : undefined) ||
    draft?.look.title ||
    paramValue(rawTitle) ||
    t('lookPreview.fallbackTitle');

  useEffect(() => {
    if (!addedNotice) return;
    const timer = setTimeout(() => setAddedNotice(false), ADDED_NOTICE_MS);
    return () => clearTimeout(timer);
  }, [addedNotice]);

  const start = () => {
    if (!draft || !zones.length || entered.current) return;
    entered.current = true;
    useLookMakeupStore.getState().applyLook(draft.look, draft.products);
    router.replace(arHref(draft.video ? { video: true } : { look: true, compare: true }));
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.colors.surface }} edges={['bottom']}>
      <Stack.Screen options={{ title: t('lookPreview.title'), headerBackTitle: t('common.back') }} />
      <LookPreviewBody
        zones={zones}
        title={title}
        addedNotice={addedNotice}
        onStart={start}
        onProduct={(productId, shadeId) => router.push(productHref(productId, shadeId, undefined, true))}
        onAdd={(productId, shadeId) => {
          addToCart({ productId, shadeId });
          setAddedNotice(true);
        }}
        onOpenCart={() => router.push('/cart')}
        t={t}
      />
    </SafeAreaView>
  );
}
