import Ionicons from '@expo/vector-icons/Ionicons';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';

export type IngredientResultProps = {
  heading: string;
  summary: string;
  notice: string;
  product?: {
    name: string;
    brand?: string;
    source?: string;
    ingredients?: { name: string; description: string }[];
    ingredientNote?: string;
    checks?: { label: string; status: string }[];
  };
  labels: { product: string; ingredients: string; source: string; unknown?: string };
};

export function IngredientResult({ heading, summary, notice, product, labels }: IngredientResultProps) {
  return (
    <View style={styles.result}>
      <View style={styles.answer}>
        <View style={styles.answerHeader}>
          <View style={styles.answerIcon}>
            <Ionicons name="flask-outline" size={14} color={theme.colors.rose} />
          </View>
          <Text style={styles.answerTitle}>{heading}</Text>
        </View>
        <Text style={styles.summary}>{summary}</Text>
      </View>
      {product ? (
        <View style={styles.panel}>
          <Text style={styles.label}>{labels.product}</Text>
          {product.brand ? <Text style={styles.secondary}>{product.brand}</Text> : null}
          <Text style={styles.productName}>{product.name}</Text>
          {product.source || labels.unknown ? <Text style={styles.secondary}>{labels.source}: {product.source || labels.unknown}</Text> : null}
        </View>
      ) : null}
      {product?.ingredients?.length ? (
        <View style={styles.panel}>
          <Text style={styles.label}>{labels.ingredients}</Text>
          {product.ingredients.map((ingredient, index) => (
            <View key={`${ingredient.name}-${index}`} style={styles.ingredient}>
              <View style={styles.ingredientIcon}>
                <Ionicons name="leaf-outline" size={18} color={theme.colors.success} />
              </View>
              <View style={styles.ingredientText}>
                <Text style={styles.ingredientName}>{ingredient.name}</Text>
                <Text style={styles.secondary}>{ingredient.description}</Text>
              </View>
            </View>
          ))}
          {product.ingredientNote ? <Text style={styles.secondary}>{product.ingredientNote}</Text> : null}
        </View>
      ) : null}
      {product?.checks?.length ? (
        <View style={styles.checks}>
          {product.checks.map((check, index) => (
            <View key={`${check.label}-${index}`} style={styles.checkRow}>
              <Text style={styles.checkLabel}>{check.label}</Text>
              <Text style={styles.checkStatus}>{check.status}</Text>
            </View>
          ))}
        </View>
      ) : null}
      <View style={styles.notice}>
        <Ionicons name="information-circle-outline" size={19} color={theme.colors.rose} />
        <Text style={styles.noticeText}>{notice}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  result: { gap: 10 },
  answer: { alignSelf: 'flex-start', maxWidth: '94%', backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, paddingHorizontal: 14, paddingVertical: 12, gap: 8 },
  answerHeader: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  answerIcon: { width: 26, height: 26, borderRadius: 13, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft },
  answerTitle: { color: theme.colors.roseDark, fontSize: theme.font.caption, fontWeight: '700' },
  summary: { color: theme.colors.ink, fontSize: theme.font.body, lineHeight: 23 },
  panel: { backgroundColor: theme.colors.card, borderColor: theme.colors.border, borderWidth: 1, borderRadius: theme.radius.md, padding: 12, gap: 5 },
  label: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  productName: { color: theme.colors.ink, fontSize: theme.font.body, fontWeight: '700', lineHeight: 22 },
  secondary: { color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 19 },
  ingredient: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingTop: 8 },
  ingredientIcon: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.pill },
  ingredientText: { flex: 1, gap: 3 },
  ingredientName: { color: theme.colors.ink, fontSize: theme.font.small, fontWeight: '700', lineHeight: 19 },
  checks: { backgroundColor: theme.colors.roseSoft, borderRadius: theme.radius.md, padding: 12, gap: 6 },
  checkRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  checkLabel: { flex: 1, color: theme.colors.ink, fontSize: theme.font.small, lineHeight: 20 },
  checkStatus: { flexShrink: 1, color: theme.colors.warning, fontSize: theme.font.small, fontWeight: '700', textAlign: 'right', lineHeight: 20 },
  notice: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, backgroundColor: theme.colors.cream, borderRadius: theme.radius.md, paddingHorizontal: 14, paddingVertical: 12 },
  noticeText: { flex: 1, color: theme.colors.inkMuted, fontSize: theme.font.caption, lineHeight: 19 },
});
