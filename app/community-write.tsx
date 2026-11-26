import { useQuery, useQueryClient } from '@tanstack/react-query';
import { uuid } from 'expo';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '@/components/ui/Button';
import { theme } from '@/constants/theme';
import { ApiError, apiForm, apiGet } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n } from '@/lib/i18n';
import { communityPostHref, LOOK_COMMUNITY, lookPhoto, parseSharedProducts, type LookPost, type LookProduct } from '@/lib/lookCommunity';
import { useProducts, useProductsByIds } from '@/lib/queries';
import { loginHref } from '@/lib/routes';

export default function CommunityWrite() {
  const params = useLocalSearchParams<{ id?: string; title?: string; products?: string }>();
  const { user } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const post = useQuery({
    queryKey: ['look-community', 'post', params.id],
    queryFn: () => apiGet<LookPost>(`${LOOK_COMMUNITY}/${encodeURIComponent(params.id ?? '')}`),
    enabled: !!user && !!params.id,
  });
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t(params.id ? 'community.edit' : 'community.write') }} />
      {!user ? <View style={styles.content}><Button label={t('my.login')} onPress={() => router.push(loginHref('community-write'))} /></View>
        : params.id && !post.data ? <View style={styles.content}>
          <Text style={styles.note}>{t(post.isError ? 'community.error' : 'community.loading')}</Text>
          {post.isError ? <Button label={t('common.retry')} onPress={() => void post.refetch()} /> : null}
        </View>
        : <Editor key={`${user.id}:${params.id ?? 'new'}`} owner={user.id} post={post.data}
          initialTitle={params.title} initialProducts={parseSharedProducts(params.products)} />}
    </SafeAreaView>
  );
}

function Editor({ owner, post, initialTitle, initialProducts }: {
  owner: string; post?: LookPost; initialTitle?: string; initialProducts: LookProduct[];
}) {
  const { t } = useI18n();
  const router = useRouter();
  const cache = useQueryClient();
  const [id] = useState(() => post?.id ?? uuid.v4());
  const [title, setTitle] = useState(post?.title ?? initialTitle?.slice(0, 80) ?? '');
  const [description, setDescription] = useState(post?.description ?? '');
  const [picked, setPicked] = useState(post?.products ?? initialProducts);
  const [selectedPhoto, setSelectedPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [approved, setApproved] = useState(false);
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const saving = useRef(false);
  const productCatalog = useProductsByIds(picked.map(product => product.productId));
  const catalog = useProducts({ q: query.trim() }, !preview && query.trim().length >= 2);
  const photo = selectedPhoto?.uri ?? (post ? lookPhoto(post.id) : undefined);

  async function choosePhoto() {
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7, exif: false });
      if (result.canceled) return;
      const asset = result.assets[0];
      if (asset.fileSize && asset.fileSize > 2 * 1024 * 1024) {
        setError(t('community.photoSize'));
        return;
      }
      setSelectedPhoto(asset);
      setApproved(false);
      setError(undefined);
    } catch {
      setError(t('community.photoError'));
    }
  }

  async function publish() {
    if (saving.current || !title.trim() || !photo || !approved) return;
    saving.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const form = new FormData();
      form.append('content', JSON.stringify({ title: title.trim(), description: description.trim(), products: picked }));
      form.append('consent', 'true');
      if (selectedPhoto) {
        const name = selectedPhoto.fileName ?? 'look.jpg';
        if (Platform.OS === 'web') {
          const file = selectedPhoto.file ?? await (await fetch(selectedPhoto.uri)).blob();
          form.append('image', file, name);
        } else {
          form.append('image', { uri: selectedPhoto.uri, name, type: selectedPhoto.mimeType ?? 'image/jpeg' } as unknown as Blob);
        }
      }
      const saved = await apiForm<LookPost>(`${LOOK_COMMUNITY}/${id}`, post ? 'PATCH' : 'POST', form, owner);
      void cache.invalidateQueries({ queryKey: ['look-community'] });
      router.replace(communityPostHref(saved.id));
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : undefined;
      setError(t(code === 'look_photo_too_large' ? 'community.photoSize'
        : code === 'look_photo_invalid' ? 'community.photoError'
        : code === 'look_member_required' ? 'community.memberRequired' : 'community.error'));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Text accessibilityRole="header" style={styles.heading}>{t(preview ? 'community.review' : 'community.write')}</Text>
      {photo ? <Image source={{ uri: photo }} style={styles.photo} contentFit="contain" cachePolicy="none"
        accessibilityLabel={t('community.photo')} /> : null}
      {preview ? <>
        <Text style={styles.label}>{title}</Text>
        {description ? <Text style={styles.note}>{description}</Text> : null}
      </> : <>
        <Button label={t('community.pickPhoto')} onPress={() => void choosePhoto()} variant="secondary" />
        <Text style={styles.note}>{t('community.photoHelp')}</Text>
        <TextInput style={styles.input} accessibilityLabel={t('community.title')} placeholder={t('community.title')} value={title}
          maxLength={80} onChangeText={setTitle} />
        <TextInput style={[styles.input, styles.description]} accessibilityLabel={t('community.description')} placeholder={t('community.description')}
          value={description} maxLength={500} multiline onChangeText={setDescription} />
      </>}
      <Text style={styles.label}>{t('community.products')}</Text>
      {picked.length === 0 ? <Text style={styles.note}>{t('community.noProducts')}</Text> : null}
      {picked.map((selection, index) => {
        const item = productCatalog.data?.find(product => product.id === selection.productId);
        const shade = item?.shades?.find(color => color.id === selection.shadeId);
        return (
          <View key={`${selection.productId}:${selection.shadeId ?? ''}:${index}`} style={styles.product}>
            <Text style={styles.productText}>{item?.name ?? selection.productId}{shade ? ` · ${shade.name}` : ''}</Text>
            {!preview ? <Button label={t('community.remove')} variant="ghost" compact
              onPress={() => setPicked(current => current.filter((_, i) => index !== i))} /> : null}
          </View>
        );
      })}
      {!preview && picked.length < 12 ? <>
        <TextInput style={styles.input} accessibilityLabel={t('community.searchProducts')} placeholder={t('community.searchProducts')}
          value={query} maxLength={80} onChangeText={setQuery} />
        {query.trim().length >= 2 ? catalog.data?.slice(0, 5).map(product => (
          <View key={product.id} style={styles.product}>
            <Text style={styles.productText}>{product.name}</Text>
            <Button label={t('community.add')} variant="secondary" compact disabled={picked.some(item => item.productId === product.id)}
              onPress={() => setPicked(current => [...current, { productId: product.id }].slice(0, 12))} />
          </View>
        )) : null}
      </> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {preview ? <>
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: approved, disabled: busy }} disabled={busy}
          onPress={() => setApproved(value => !value)} style={styles.consent}>
          <Text style={styles.check}>{approved ? '☑' : '☐'}</Text>
          <Text style={styles.productText}>{t('community.consent')}</Text>
        </Pressable>
        <Button label={t('community.publish')} loading={busy} disabled={!approved} onPress={() => void publish()} />
        <Button label={t('common.back')} variant="ghost" disabled={busy} onPress={() => { setPreview(false); setApproved(false); }} />
      </> : <Button label={t('community.review')} disabled={!title.trim() || !photo} onPress={() => { setError(undefined); setPreview(true); }} />}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  content: { width: '100%', maxWidth: 570, alignSelf: 'center', padding: 20, gap: 14 },
  heading: { color: theme.colors.ink, fontSize: 26, fontWeight: '800' },
  label: { color: theme.colors.ink, fontSize: 17, fontWeight: '700' },
  note: { color: theme.colors.inkMuted, lineHeight: 21 },
  photo: { aspectRatio: 1.2, backgroundColor: theme.colors.cream, borderRadius: 16 },
  input: { color: theme.colors.ink, backgroundColor: theme.colors.card, borderWidth: 1, borderColor: theme.colors.border, borderRadius: 12, padding: 13, minHeight: 48 },
  description: { minHeight: 100, textAlignVertical: 'top' },
  product: { paddingVertical: 6, flexDirection: 'row', alignItems: 'center', gap: 10 },
  productText: { flex: 1, color: theme.colors.ink, lineHeight: 22 },
  consent: { backgroundColor: theme.colors.roseSoft, flexDirection: 'row', gap: 10, alignItems: 'center', borderRadius: 12, padding: 14 },
  check: { color: theme.colors.roseDark, fontSize: 23 },
  error: { color: theme.colors.roseDark, lineHeight: 21 },
});
