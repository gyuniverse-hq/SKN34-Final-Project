import { Redirect, Stack, useRouter } from 'expo-router';
import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChatProducts } from '@/components/chat/ChatProducts';
import { IngredientResult } from '@/components/chat/IngredientResult';
import { StyleRecipeResult } from '@/components/chat/StyleRecipeResult';
import { theme } from '@/constants/theme';
import type { ChatCondition } from '@/lib/chatConditions';
import { useI18n } from '@/lib/i18n';
import type { Product } from '@/types';

const styleImage = require('@/assets/images/chat/style-recipe.png');
const productImage = require('@/assets/images/chat/product-recommendation.png');
type PreviewCategory = 'product' | 'ingredient' | 'style';

function PreviewContent() {
  const { t } = useI18n();
  const router = useRouter();
  const [category, setCategory] = useState<PreviewCategory>('product');
  const categories = [
    { id: 'product' as const, label: t('chat.ui.product') },
    { id: 'ingredient' as const, label: t('chat.ui.ingredient') },
    { id: 'style' as const, label: t('chat.ui.style') },
  ];
  const question = category === 'product'
    ? `${t('chat.ui.productQuestion2')} · ${t('chat.preview.conditionPrice')}`
    : category === 'ingredient' ? t('chat.ui.ingredientQuestion1') : t('chat.ui.styleQuestion1');
  const product: Product = {
    id: 'example-product', brand: t('chat.preview.brand'), name: t('chat.preview.product'),
    nameKo: t('chat.preview.product'), category: 'cheek', makeupZone: 'blush', texture: 'satin',
    priceKRW: 15000, volume: '', shades: [{ id: 'example-shade', name: '01', hex: '#C77882' }],
    description: '', keyIngredients: [], tags: [], imageUrl: '', searchKeyword: '',
  };
  const conditions: ChatCondition[] = [
    { kind: 'category', text: t('shop.cat.cheek'), required: true, value: 'cheek' },
    { kind: 'maxPrice', text: t('chat.preview.conditionPrice'), required: true, value: 20000 },
    { kind: 'fragranceFree', text: t('chat.preview.conditionFragrance'), required: true },
  ];

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen options={{ title: t('chat.preview.title') }} />
      <View style={styles.banner}>
        <Text style={styles.bannerText}>{t('chat.preview.notice')}</Text>
      </View>
      <View style={styles.tabs}>
        {categories.map((item) => (
          <Pressable key={item.id} accessibilityRole="button" accessibilityLabel={item.label}
            accessibilityState={{ selected: category === item.id }} onPress={() => setCategory(item.id)}
            style={[styles.tab, category === item.id && styles.selectedTab]}>
            <Text style={[styles.tabText, category === item.id && styles.selectedTabText]}>{item.label}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView key={category} contentContainerStyle={styles.content}>
        <View style={styles.question}><Text style={styles.questionText}>{question}</Text></View>
        {category === 'product' ? <View style={styles.result}>
          <View style={styles.answer}>
            <Text style={styles.answerTitle}>{t('chat.ui.product')}</Text>
            <Text style={styles.answerText}>{t('chat.preview.productSummary')}</Text>
          </View>
          <ChatProducts products={[product]} conditions={conditions} showIngredients={false}
            loading={false} failed={false} missingCount={0} disabledActions previewImage={productImage}
            onRetry={() => {}} onOpenProduct={() => {}} onOpenAr={() => {}} />
        </View> : null}
        {category === 'ingredient' ? <IngredientResult
          heading={t('chat.ui.ingredient')}
          summary={t('chat.preview.ingredientSummary')}
          notice={t('chat.ui.ingredientGeneralNotice')}
          labels={{
            product: t('chat.result.productInfo'),
            ingredients: t('chat.result.ingredientList'),
            source: t('chat.result.source'),
            unknown: t('chat.conditionUnknown'),
          }}
          product={{
            name: t('chat.preview.product'),
            brand: t('chat.preview.brand'),
            source: t('chat.preview.source'),
            checks: [{ label: t('chat.preview.conditionFragrance'), status: t('chat.conditionUnknown') }],
            ingredientNote: t('chat.ui.keyIngredientsNotice'),
            ingredients: [{
              name: t('chat.preview.ingredientName'),
              description: t('chat.preview.ingredientDescription'),
            }],
          }}
        /> : null}
        {category === 'style' ? <StyleRecipeResult
          heading={t('chat.ui.style')}
          summary={t('chat.preview.styleSummary')}
          browseImage={styleImage}
          browseLabel={t('chat.ui.styleBrowse')}
          onBrowse={() => router.push('/style-browse')}
          stepsLabel={t('chat.result.steps')}
          stepNavigation={{
            previous: t('chat.result.previousStep'),
            next: t('chat.result.nextStep'),
            position: (current, total) => t('chat.result.stepPosition', { current, total }),
          }}
          recipe={{
            title: t('chat.preview.styleTitle'),
            subtitle: t('chat.preview.styleSubtitle'),
            image: styleImage,
            steps: [
              { title: t('chat.preview.stepOne'), description: t('chat.preview.stepOneDescription'), image: styleImage },
              { title: t('chat.preview.stepTwo'), description: t('chat.preview.stepTwoDescription') },
            ],
            relatedProducts: {
              label: t('chat.relatedProducts'),
              products: [{ name: t('chat.preview.product'), brand: t('chat.preview.brand') }],
            },
          }}
        /> : null}
      </ScrollView>
      <View style={styles.composer}>
        <TextInput style={styles.input} editable={false} accessibilityState={{ disabled: true }}
          accessibilityLabel={t('chat.ui.placeholder')} placeholder={t('chat.ui.placeholder')} placeholderTextColor={theme.colors.inkFaint} />
        <Pressable disabled accessibilityRole="button" accessibilityLabel={t('chat.ui.send')}
          accessibilityState={{ disabled: true }} style={styles.send}>
          <Ionicons name="arrow-up" size={22} color={theme.colors.white} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

export default function ChatUiPreview() {
  return __DEV__ ? <PreviewContent /> : <Redirect href="/" />;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.colors.surface },
  banner: { paddingHorizontal: 16, paddingVertical: 12, backgroundColor: theme.colors.roseSoft, borderBottomWidth: 1, borderBottomColor: theme.colors.border },
  bannerText: { color: theme.colors.roseDark, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  tabs: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6, paddingHorizontal: 12, paddingTop: 10 },
  tab: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12, borderWidth: 1, borderColor: theme.colors.border, borderRadius: theme.radius.pill, backgroundColor: theme.colors.card },
  selectedTab: { borderColor: theme.colors.rose, backgroundColor: theme.colors.roseSoft },
  tabText: { color: theme.colors.ink, fontSize: theme.font.caption, fontWeight: '600' },
  selectedTabText: { color: theme.colors.roseDark },
  content: { padding: 16, paddingBottom: 28, gap: 12 },
  question: { alignSelf: 'flex-end', maxWidth: '88%', borderRadius: theme.radius.md, backgroundColor: theme.colors.roseSoft, padding: 12 },
  questionText: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 22 },
  result: { gap: 10 },
  answer: { alignSelf: 'flex-start', maxWidth: '94%', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, padding: 14, gap: 8 },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  answerText: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 22 },
  composer: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingVertical: 10, borderTopWidth: 1, borderColor: theme.colors.border, backgroundColor: theme.colors.card },
  input: { flex: 1, minHeight: 44, color: theme.colors.inkFaint, fontSize: theme.font.body },
  send: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.inkFaint },
});
