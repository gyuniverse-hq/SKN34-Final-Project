import Ionicons from '@expo/vector-icons/Ionicons';
import { StyleSheet, Text, View } from 'react-native';
import { theme } from '@/constants/theme';
import { useI18n } from '@/lib/i18n';

export function LookPostAuthor({ displayName, createdAt, compact = false }: {
  displayName?: string | null;
  createdAt?: string;
  compact?: boolean;
}) {
  const { t, language } = useI18n();
  const name = displayName || t('community.member');
  const date = createdAt ? new Date(createdAt) : undefined;
  const dateLabel = date && Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat(language, { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
    : undefined;
  return (
    <View style={styles.author}>
      {!compact ? <View style={styles.avatar} accessible={false}>
        <Ionicons name="person-outline" size={15} color={theme.colors.roseDark} />
      </View> : null}
      <View style={styles.nameBlock}>
        <Text style={[styles.name, compact && styles.compactName]}>{name}</Text>
        {dateLabel ? <Text style={styles.date}>{dateLabel}</Text> : null}
      </View>
    </View>
  );
}

export function LookPostVotes({ count }: { count: number }) {
  const { t } = useI18n();
  return (
    <View style={styles.votes}>
      <Ionicons name="heart-outline" size={17} color={theme.colors.roseDark} />
      <Text style={styles.voteLabel}>{t('community.count', { count })}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  author: { flexDirection: 'row', alignItems: 'center', gap: 8, minWidth: 0, flexShrink: 1 },
  avatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.colors.roseSoft, alignItems: 'center', justifyContent: 'center' },
  nameBlock: { minWidth: 0, flexShrink: 1, gap: 2 },
  name: { fontSize: 14, color: theme.colors.ink, fontWeight: '700' },
  compactName: { fontSize: 12, color: theme.colors.inkMuted, fontWeight: '600' },
  date: { fontSize: 13, color: theme.colors.inkMuted },
  votes: { flexDirection: 'row', alignItems: 'center', gap: 5, flexShrink: 1 },
  voteLabel: { fontSize: 14, color: theme.colors.roseDark, fontWeight: '600', flexShrink: 1 },
});
