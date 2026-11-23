import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';
import type { KnowledgeEvidence } from '@/types';

export function KnowledgeCitations({ evidence }: { evidence: KnowledgeEvidence[] }) {
  const { t } = useI18n();
  if (!evidence.length) return null;

  return (
    <View style={styles.sources}>
      <Text accessibilityRole="header" style={styles.heading}>{t('chat.knowledge.sources')}</Text>
      {evidence.map((source) => (
        <View key={source.id} style={styles.source}>
          <Text style={styles.title}>
            [{source.id}] {source.title || t('chat.knowledge.document', { id: source.documentId })}
          </Text>
          <Text style={styles.location}>
            {t('chat.knowledge.paragraph', { order: source.blockOrder })} · {source.startUtf16}–{source.endUtf16}
          </Text>
          <Text style={styles.quote}>{source.quote.trim()}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  sources: { marginTop: 8, gap: 6 },
  heading: { color: theme.colors.inkMuted, fontSize: 13, fontWeight: '600' },
  source: { borderColor: theme.colors.border, borderWidth: 1, borderRadius: 8, padding: 10, gap: 4 },
  title: { color: theme.colors.ink, fontWeight: '600' },
  location: { color: theme.colors.inkMuted, fontSize: 12 },
  quote: { color: theme.colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
