import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n, type TranslationKey } from '@/lib/i18n';
import { buildGuideSteps, guideText } from '@/lib/lookGuide';
import type { ChatStyleRecipe } from '@/types';

export type StyleRecipeResultProps = {
  result?: ChatStyleRecipe;
  onStepChange?: (index: number) => void;
  onOpenProduct?: (productId: string) => void;
  onOpenAr?: (productId: string, shadeId: string) => void;
  onManualAr?: () => void;
  disabled?: boolean;
  heading: string;
  summary: string;
  browseImage: number;
  browseLabel: string;
  onBrowse: () => void;
  stepsLabel: string;
  stepNavigation: {
    previous: string;
    next: string;
    position: (current: number, total: number) => string;
  };
  recipe?: {
    title: string;
    subtitle?: string;
    image?: number | string;
    steps?: { title: string; description: string; image?: number | string }[];
    relatedProducts?: { label: string; products: { name: string; brand?: string }[] };
  };
};

export function StyleRecipeResult({ heading, summary, browseImage, browseLabel, onBrowse, recipe: previewRecipe, result, onStepChange, onOpenProduct, onOpenAr, onManualAr, disabled = false, stepsLabel, stepNavigation }: StyleRecipeResultProps) {
  const { t } = useI18n();
  const guides = result?.makeup ? buildGuideSteps({ lip: null, blush: null, eyeshadow: null, ...result.makeup }, result.steps.map((s) => s.zone)) : [];
  const recipe: StyleRecipeResultProps['recipe'] = result ? {
    title: result.title,
    subtitle: t(`chat.style.${result.basis}`),
    steps: result.steps.map((s) => {
      const guide = guides.find((g) => g.zone === s.zone);
      const genericKey = s.zone === 'blush' ? 'looks.guide.blush.apple' : s.zone === 'eyeliner' ? 'looks.guide.eyeliner.tightline' : `looks.guide.${s.zone}`;
      return { title: s.title, description: s.description ?? (s.guideKey
        ? guideText(guide ?? { zone: s.zone, textKey: genericKey as TranslationKey, extraKeys: [] }, t) : '') };
    }),
  } : previewRecipe;
  const [selectedStep, setSelectedStep] = useState(0);
  const stepCount = recipe?.steps?.length ?? 0;
  const stepIndex = Math.min(result?.currentStep ?? selectedStep, Math.max(0, stepCount - 1));
  const changeStep = (index: number) => { if (!disabled) { if (result) onStepChange?.(index); else setSelectedStep(index); } };
  const step = recipe?.steps?.[stepIndex];
  return (
    <View style={styles.container}>
      <View style={styles.answer}>
        <View style={styles.answerHeader}>
          <View style={styles.answerIcon}><Ionicons name="sparkles" size={14} color={theme.colors.rose} /></View>
          <Text style={styles.answerTitle}>{heading}</Text>
        </View>
        <Text style={styles.answerText}>{summary}</Text>
      </View>
      {result ? <View style={styles.recipeCopy}>
        <Text>{t(`chat.style.${result.basis}`)}</Text>
        {result.reviewStatus !== 'not_applicable' ? <Text>{t(result.reviewStatus === 'verified' ? 'chat.style.reviewed' : 'chat.style.unreviewed')}</Text> : null}
        {result.synthetic ? <Text>{t('chat.style.synthetic')}</Text> : null}
        {result.features.map((feature, index) => <Text key={index} style={styles.recipeSubtitle}>{feature}</Text>)}
        <Text style={styles.recipeSubtitle}>{t('chat.style.source')}: {result.source}</Text>
        <Text style={styles.recipeSubtitle}>{t('chat.style.version')}: {result.recipeVersion}</Text>
      </View> : null}
      {recipe ? (
        <View style={styles.recipe}>
          {recipe.image ? (
            <View style={styles.recipeHero}>
              <Image source={recipe.image} style={styles.recipeImage} contentFit="cover" alt={recipe.title} />
              <LinearGradient colors={['transparent', 'rgba(26,17,24,0.92)']} style={styles.recipeOverlay}>
                <Text accessibilityRole="header" style={[styles.recipeTitle, styles.overlayText]}>{recipe.title}</Text>
                {recipe.subtitle ? <Text style={[styles.recipeSubtitle, styles.overlayText]}>{recipe.subtitle}</Text> : null}
              </LinearGradient>
            </View>
          ) : (
            <View style={styles.recipeCopy}>
              <Text accessibilityRole="header" style={styles.recipeTitle}>{recipe.title}</Text>
              {recipe.subtitle ? <Text style={styles.recipeSubtitle}>{recipe.subtitle}</Text> : null}
            </View>
          )}
        </View>
      ) : null}
      {step ? (
        <View style={styles.steps}>
          <View style={styles.stepsHeader}>
            <Text accessibilityRole="header" style={styles.stepsTitle}>{stepsLabel}</Text>
            <Text accessibilityLiveRegion="polite" style={styles.stepPosition}>{stepNavigation.position(stepIndex + 1, stepCount)}</Text>
          </View>
          <View style={styles.step}>
            {step.image ? (
              <View style={styles.stepVisual}>
                <Image source={step.image} style={styles.stepImage} contentFit="cover" accessible={false} />
                <View style={[styles.stepNumber, styles.stepNumberOverlay]}><Text style={styles.stepNumberText}>{stepIndex + 1}</Text></View>
              </View>
            ) : <View style={styles.stepNumber}><Text style={styles.stepNumberText}>{stepIndex + 1}</Text></View>}
            <View style={styles.stepCopy}>
              <Text style={styles.stepTitle}>{step.title}</Text>
              <Text style={styles.stepDescription}>{step.description}</Text>
            </View>
          </View>
          {stepCount > 1 ? (
            <View style={styles.stepControls}>
              <Pressable accessibilityRole="button" accessibilityLabel={stepNavigation.previous}
                accessibilityState={{ disabled: disabled || stepIndex === 0 }} disabled={disabled || stepIndex === 0}
                onPress={() => changeStep(stepIndex - 1)} style={[styles.stepControl, stepIndex === 0 && styles.stepControlDisabled]}>
                <Ionicons name="chevron-back" size={18} color={theme.colors.rose} />
                <Text style={styles.stepControlText}>{stepNavigation.previous}</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={stepNavigation.next}
                accessibilityState={{ disabled: disabled || stepIndex === stepCount - 1 }} disabled={disabled || stepIndex === stepCount - 1}
                onPress={() => changeStep(stepIndex + 1)} style={[styles.stepControl, stepIndex === stepCount - 1 && styles.stepControlDisabled]}>
                <Text style={styles.stepControlText}>{stepNavigation.next}</Text>
                <Ionicons name="chevron-forward" size={18} color={theme.colors.rose} />
              </Pressable>
            </View>
          ) : null}
        </View>
      ) : null}
      {previewRecipe?.relatedProducts?.products.length && !result ? (
        <View style={styles.relatedProducts}>
          <Text accessibilityRole="header" style={styles.stepsTitle}>{previewRecipe.relatedProducts.label}</Text>
          {previewRecipe.relatedProducts.products.map((product, index) => (
            <View key={`${product.name}-${index}`} style={styles.relatedProduct}>
              {product.brand ? <Text style={styles.productBrand}>{product.brand}</Text> : null}
              <Text style={styles.productName}>{product.name}</Text>
            </View>
          ))}
        </View>
      ) : null}
      {result ? <View style={styles.relatedProducts}>
        {result.products.map((product, index) => <View key={index} style={styles.relatedProduct}>
          <Text style={styles.productName}>{product.label}</Text>
          <Text>{t(product.mappingStatus === 'verified' ? 'chat.style.mappingVerified' : 'chat.style.mappingUnknown')}</Text>
          {product.productId && onOpenProduct ? <Pressable accessibilityRole="button" accessibilityLabel={t('styleLooks.openProduct')} style={styles.stepControl}
            onPress={() => onOpenProduct(product.productId!)}><Text>{t('styleLooks.openProduct')}</Text></Pressable> : null}
          {product.arEligible && product.catalogValid && product.mappingStatus === 'verified' && product.productId && product.shadeId && onOpenAr ? <Pressable accessibilityRole="button" accessibilityLabel={t('styleLooks.tryAr')} style={styles.stepControl}
            disabled={disabled} accessibilityState={{ disabled }}
            onPress={() => { if (!disabled) onOpenAr(product.productId!, product.shadeId!); }}><Text>{t('styleLooks.tryAr')}</Text></Pressable> : null}
        </View>)}
        {onManualAr ? <Pressable accessibilityRole="button" accessibilityLabel={t('chat.style.manualAr')} onPress={onManualAr} style={styles.stepControl}><Text>{t('chat.style.manualAr')}</Text></Pressable> : null}
      </View> : null}
      <Pressable accessibilityRole="button" accessibilityLabel={browseLabel} onPress={onBrowse} style={styles.browse}>
        {!recipe?.image ? <Image source={browseImage} style={styles.browseImage} contentFit="cover" accessible={false} /> : null}
        <View style={styles.browseAction}><Text style={styles.browseText}>{browseLabel} ›</Text></View>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10 },
  answer: { alignSelf: 'flex-start', maxWidth: '94%', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, paddingHorizontal: 14, paddingVertical: 12 },
  answerHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 },
  answerIcon: { width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  answerText: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 22 },
  recipe: { overflow: 'hidden', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg },
  recipeHero: { minHeight: 240, justifyContent: 'flex-end' },
  recipeImage: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0 },
  recipeCopy: { gap: 4, padding: 14 },
  recipeOverlay: { gap: 4, paddingHorizontal: 14, paddingTop: 32, paddingBottom: 14 },
  overlayText: { color: theme.colors.white },
  recipeTitle: { color: theme.colors.ink, fontSize: theme.font.title, fontWeight: '800' },
  recipeSubtitle: { color: theme.colors.inkMuted, fontSize: theme.font.small, lineHeight: 19 },
  steps: { gap: 8 },
  stepsHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  stepsTitle: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700' },
  stepPosition: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  step: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, padding: 12, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, backgroundColor: theme.colors.card },
  stepNumber: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  stepNumberText: { color: theme.colors.rose, fontSize: theme.font.caption, fontWeight: '700' },
  stepVisual: { width: 54, height: 54 },
  stepImage: { width: 54, height: 54, borderRadius: theme.radius.sm },
  stepNumberOverlay: { position: 'absolute', left: 2, bottom: 2, width: 22, height: 22, borderRadius: 11 },
  stepCopy: { flex: 1, gap: 4 },
  stepTitle: { color: theme.colors.roseDark, fontSize: theme.font.small, fontWeight: '700' },
  stepDescription: { color: theme.colors.ink, fontSize: theme.font.small, lineHeight: 19 },
  stepControls: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  stepControl: { minHeight: 44, minWidth: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingHorizontal: 10 },
  stepControlDisabled: { opacity: 0.4 },
  stepControlText: { color: theme.colors.rose, fontSize: theme.font.small, fontWeight: '700' },
  relatedProducts: { gap: 8 },
  relatedProduct: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, padding: 12, gap: 3 },
  productBrand: { color: theme.colors.inkMuted, fontSize: theme.font.caption },
  productName: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700' },
  browse: { overflow: 'hidden', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.lg },
  browseImage: { width: '100%', aspectRatio: 623 / 418 },
  browseAction: { minHeight: 48, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12, backgroundColor: theme.colors.rose },
  browseText: { color: theme.colors.white, fontSize: theme.font.small, fontWeight: '700' },
});
