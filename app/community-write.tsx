import Ionicons from '@expo/vector-icons/Ionicons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { uuid } from 'expo';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useRef, useState } from 'react';
import { Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LookPostAuthor } from '@/components/community/LookPostMeta';
import { Button } from '@/components/ui/Button';
import { InlineState } from '@/components/ui/InlineState';
import { ProductImage } from '@/components/ui/ProductImage';
import { theme } from '@/constants/theme';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { ApiError, apiForm, apiGet } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { communityPostHref, LOOK_COMMUNITY, lookPhoto, parseSharedProducts, type LookPost, type LookProduct } from '@/lib/lookCommunity';
import { prepareCommunityPhoto } from '@/lib/lookCommunityPhoto';
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
  const [displayName, setDisplayName] = useState(post?.displayName ?? '');
  const [picked, setPicked] = useState(post?.products ?? initialProducts);
  const [selectedPhoto, setSelectedPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [photoIssue, setPhotoIssue] = useState<TranslationKey>();
  const [pickerFailed, setPickerFailed] = useState(false);
  const [preparingPhoto, setPreparingPhoto] = useState(false);
  const [approved, setApproved] = useState(false);
  const [query, setQuery] = useState('');
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const saving = useRef(false);
  const picking = useRef(false);
  const productCatalog = useProductsByIds(picked.map(product => product.productId));
  const search = useDebouncedValue(query.trim(), 350);
  const showSearchResults = !preview && search.length >= 2 && search === query.trim();
  const catalog = useProducts({ q: search }, showSearchResults);
  const productsSearching = showSearchResults && (catalog.isPending || catalog.isPlaceholderData);
  const productResults = showSearchResults && !productsSearching ? catalog.data : undefined;
  const photo = selectedPhoto?.uri ?? (post ? lookPhoto(post.id) : undefined);
  const photoMessage = photoIssue ?? (pickerFailed ? 'community.photoUnreadable' : undefined);
  const canReview = !!photo && !!title.trim() && !photoIssue && !preparingPhoto;
  const actionHint = preparingPhoto ? 'community.preparingPhoto'
    : photoIssue ? 'community.replacePhotoToContinue'
    : !photo ? 'community.photoNeeded'
    : !title.trim() ? 'community.titleNeeded'
    : preview && !approved ? 'community.consentNeeded'
    : undefined;

  async function choosePhoto() {
    if (picking.current) return;
    picking.current = true;
    setPickerFailed(false);
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7, exif: false });
      if (result.canceled) return;
      const asset = result.assets[0];
      if (!asset?.uri) {
        setPickerFailed(true);
        return;
      }
      setSelectedPhoto(asset);
      setPhotoIssue(undefined);
      setApproved(false);
      setError(undefined);
      setPreparingPhoto(true);
      try {
        const prepared = await prepareCommunityPhoto(asset);
        if (prepared) {
          setSelectedPhoto(prepared);
          if (prepared.uri !== asset.uri) setPhotoIssue(undefined);
        } else {
          setPhotoIssue('community.photoSize');
        }
      } catch {
        setPhotoIssue('community.photoUnreadable');
      }
    } catch {
      setPickerFailed(true);
    } finally {
      setPreparingPhoto(false);
      picking.current = false;
    }
  }

  async function publish() {
    if (saving.current || !canReview || !approved) return;
    saving.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const form = new FormData();
      form.append('content', JSON.stringify({
        title: title.trim(), description: description.trim(), displayName: displayName.trim() || null, products: picked,
      }));
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
      cache.setQueryData(['look-community', 'post', saved.id], saved);
      void cache.invalidateQueries({ queryKey: ['look-community'] });
      router.replace(communityPostHref(saved.id));
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : undefined;
      if (code === 'look_photo_too_large' || code === 'look_photo_invalid') {
        setPhotoIssue(code === 'look_photo_too_large' ? 'community.photoSize' : 'community.photoError');
        setApproved(false);
        setPreview(false);
      } else {
        setError(t(code === 'look_member_required' ? 'community.memberRequired' : 'community.error'));
      }
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <ScrollView key={preview ? 'preview' : 'editor'} contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
      <Stack.Screen options={{ title: t(preview ? 'community.review' : post ? 'community.edit' : 'community.write') }} />
      {photo ? <View style={styles.photoFrame}>
        <Image key={photo} source={{ uri: photo }} style={styles.photo} contentFit="contain" cachePolicy="none"
          onError={selectedPhoto && !preparingPhoto ? () => setPhotoIssue('community.photoUnreadable') : undefined}
          accessibilityLabel={t('community.photo')} />
        {!preview ? <Pressable accessibilityRole="button" accessibilityLabel={t('community.changePhoto')} disabled={preparingPhoto}
          onPress={() => void choosePhoto()} style={styles.replacePhoto}>
          <Ionicons name="images-outline" size={17} color={theme.colors.roseDark} />
          <Text style={styles.fieldLabel}>{t('community.changePhoto')}</Text>
        </Pressable> : null}
      </View> : (
        <Pressable accessibilityRole="button" accessibilityLabel={t('community.pickPhoto')}
          onPress={() => void choosePhoto()} style={styles.photoPicker}>
          <View style={styles.photoIcon}><Ionicons name="camera-outline" size={26} color={theme.colors.roseDark} /></View>
          <Text style={styles.heading}>{t('community.pickPhoto')}</Text>
          <Text style={styles.note}>{t('community.photoHelp')}</Text>
        </Pressable>
      )}
      {photoMessage ? <Text accessibilityRole="alert" style={styles.error}>{t(photoMessage)}</Text> : null}
      {preview ? <>
        <Text accessibilityRole="header" style={styles.heading}>{title.trim()}</Text>
        <LookPostAuthor displayName={displayName.trim()} createdAt={post?.createdAt} />
        {description ? <Text style={styles.note}>{description}</Text> : null}
      </> : null}
      {!preview || picked.length > 0 ? (
        <View style={styles.products}>
          <Text accessibilityRole="header" style={styles.label}>{t(preview ? 'community.usedProducts' : 'community.products')}</Text>
          {picked.map((selection, index) => {
            const item = productCatalog.data?.find(product => product.id === selection.productId);
            const shade = item?.shades?.find(color => color.id === selection.shadeId);
            return (
              <View key={`${selection.productId}:${selection.shadeId ?? ''}:${index}`} style={styles.product}>
                <ProductImage uri={item?.imageUrl} category={item?.category} style={styles.thumbnail} compact />
                <View style={styles.productInfo}>
                  {item?.brand ? <Text style={styles.brand}>{item.brand}</Text> : null}
                  <Text style={styles.productName}>{item?.name ?? selection.productId}</Text>
                  {shade ? <View style={styles.shade}>
                    <View style={[styles.swatch, { backgroundColor: shade.hex }]} />
                    <Text style={styles.note}>{shade.name}</Text>
                  </View> : null}
                </View>
                {!preview ? <Button label={t('community.remove')} variant="ghost" compact
                  onPress={() => setPicked(current => current.filter((_, i) => index !== i))} /> : null}
              </View>
            );
          })}
          {!preview && picked.length < 12 ? <>
            <View style={styles.search}>
              <Ionicons name="search" size={19} color={theme.colors.roseDark} />
              <TextInput style={styles.searchInput} accessibilityLabel={t('community.searchProducts')} placeholder={t('community.searchProducts')}
                placeholderTextColor={theme.colors.inkMuted} value={query} maxLength={80} onChangeText={setQuery} />
            </View>
            {productResults?.slice(0, 5).map(product => (
              <View key={product.id} style={styles.product}>
                <ProductImage uri={product.imageUrl} category={product.category} style={styles.thumbnail} compact />
                <View style={styles.productInfo}>
                  <Text style={styles.brand}>{product.brand}</Text>
                  <Text style={styles.productName}>{product.name}</Text>
                </View>
                <Button label={t('community.add')} variant="secondary" compact disabled={picked.some(item => item.productId === product.id)}
                  onPress={() => {
                    setPicked(current => current.some(item => item.productId === product.id)
                      ? current
                      : [...current, { productId: product.id }].slice(0, 12));
                    setQuery('');
                    Keyboard.dismiss();
                  }} />
              </View>
            ))}
            {productsSearching ? <InlineState status="loading" /> : null}
            {showSearchResults && catalog.isError ? <InlineState status="error" onRetry={() => void catalog.refetch()} /> : null}
            {productResults?.length === 0 && !catalog.isError
              ? <Text style={styles.note}>{t('community.noProductResults')}</Text> : null}
          </> : null}
        </View>
      ) : null}
      {!preview ? <View style={styles.fields}>
        <View style={styles.field}>
          <Text style={styles.fieldLabel}>{t('community.title')}</Text>
          <TextInput style={styles.input} accessibilityLabel={t('community.title')} value={title}
            placeholder={t('community.titlePlaceholder')} placeholderTextColor={theme.colors.inkMuted}
            maxLength={80} onChangeText={setTitle} />
        </View>
        <View style={styles.field}>
          <Text style={styles.fieldLabel}>{t('community.description')}</Text>
          <TextInput style={[styles.input, styles.description]} accessibilityLabel={t('community.description')}
            placeholder={t('community.descriptionPlaceholder')} placeholderTextColor={theme.colors.inkMuted}
            value={description} maxLength={500} multiline onChangeText={setDescription} />
        </View>
        <View style={styles.field}>
          <Text style={styles.fieldLabel}>{t('community.displayName')}</Text>
          <TextInput style={styles.input} accessibilityLabel={t('community.displayName')} value={displayName}
            autoComplete="off" maxLength={24} onChangeText={setDisplayName} />
          <Text style={styles.note}>{t('community.displayNameHelp')}</Text>
        </View>
      </View> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {preview ? (
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: approved, disabled: busy }} disabled={busy}
          onPress={() => setApproved(value => !value)} style={styles.consent}>
          <Ionicons name={approved ? 'checkbox' : 'square-outline'} size={23} color={theme.colors.roseDark} />
          <Text style={styles.productText}>{t('community.consent')}</Text>
        </Pressable>
      ) : null}
    </ScrollView>
    <View style={styles.footer}>
      {actionHint ? <Text style={styles.actionHint} accessibilityLiveRegion="polite">{t(actionHint)}</Text> : null}
      {preview ? <View style={styles.footerActions}>
        <Button label={t('common.back')} variant="secondary" disabled={busy} style={styles.backAction}
          onPress={() => { setPreview(false); setApproved(false); }} />
        <Button label={t('community.publish')} icon="checkmark" loading={busy} disabled={!approved || !canReview}
          style={[styles.primaryAction, styles.publishAction]} onPress={() => void publish()} />
      </View> : <Button label={t('community.review')} icon="arrow-forward" disabled={!canReview}
        accessibilityHint={actionHint ? t(actionHint) : undefined} style={styles.primaryAction}
        onPress={() => { Keyboard.dismiss(); setError(undefined); setPreview(true); }} />}
    </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#FFFAF8' },
  content: { width: '100%', maxWidth: 570, alignSelf: 'center', padding: 18, paddingBottom: 24, gap: 20 },
  footer: { alignSelf: 'center', width: '100%', maxWidth: 570, borderTopWidth: StyleSheet.hairlineWidth,
    backgroundColor: theme.colors.card, borderColor: theme.colors.border, paddingHorizontal: 18, paddingVertical: 12, gap: 8 },
  actionHint: { color: theme.colors.inkMuted, textAlign: 'center', fontSize: 13, lineHeight: 18 },
  footerActions: { flexDirection: 'row', gap: 10 },
  backAction: { minHeight: 52, borderRadius: 14 },
  primaryAction: { minHeight: 52, backgroundColor: theme.colors.roseDark, borderRadius: 14 },
  publishAction: { flex: 1 },
  heading: { color: theme.colors.ink, fontSize: 25, fontWeight: '800' },
  label: { color: theme.colors.ink, fontSize: 18, fontWeight: '700' },
  note: { color: theme.colors.inkMuted, fontSize: 14, lineHeight: 21 },
  photoPicker: { alignItems: 'center', justifyContent: 'center', gap: 9, minHeight: 172,
    backgroundColor: theme.colors.roseSoft, borderRadius: 22, padding: 20 },
  photoIcon: { width: 52, height: 52, borderRadius: 26, backgroundColor: theme.colors.card,
    alignItems: 'center', justifyContent: 'center' },
  photoFrame: { backgroundColor: theme.colors.cream, borderRadius: 20, overflow: 'hidden' },
  replacePhoto: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, justifyContent: 'center',
    padding: 8, backgroundColor: theme.colors.roseSoft },
  fields: { gap: 18 },
  field: { gap: 7 },
  fieldLabel: { color: theme.colors.ink, fontSize: 15, fontWeight: '700' },
  products: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.border, paddingTop: 15, gap: 9 },
  photo: { width: '100%', aspectRatio: 1.24 },
  input: { fontSize: 16, color: theme.colors.ink, borderBottomWidth: StyleSheet.hairlineWidth,
    borderColor: theme.colors.border, paddingVertical: 9, minHeight: 44 },
  description: { minHeight: 66, textAlignVertical: 'top' },
  search: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 13,
    backgroundColor: theme.colors.cream, borderRadius: 12 },
  searchInput: { flex: 1, minWidth: 0, minHeight: 46, color: theme.colors.ink, fontSize: 16 },
  product: { paddingVertical: 6, flexDirection: 'row', alignItems: 'center', gap: 10 },
  thumbnail: { width: 48, height: 48, borderRadius: 10 },
  productInfo: { flex: 1, minWidth: 0, gap: 3 },
  brand: { fontSize: 12, color: theme.colors.roseDark },
  productName: { fontSize: 14, color: theme.colors.ink, fontWeight: '600' },
  shade: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  swatch: { width: 11, height: 11, borderRadius: 6, borderWidth: StyleSheet.hairlineWidth, borderColor: theme.colors.border },
  productText: { flex: 1, color: theme.colors.ink, fontSize: 15, lineHeight: 22 },
  consent: { backgroundColor: theme.colors.roseSoft, flexDirection: 'row', gap: 10, alignItems: 'center', borderRadius: 12, padding: 14 },
  error: { color: theme.colors.roseDark, lineHeight: 21 },
});
