import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { theme } from '@/constants/theme';

export interface PracticeStepView {
  key: string;
  label: string;
  /** Already put on the face in this session */
  done: boolean;
}

export interface PracticePanelProps {
  title: string;
  intro: string;
  steps: PracticeStepView[];
  activeIndex: number;
  /** The look's sentences for the current step */
  text: string;
  /** Showing the finished look instead of the layers so far */
  peeking: boolean;
  labels: { prev: string; next: string; finish: string; peek: string; peekOff: string; exit: string };
  onPick: (index: number) => void;
  onPrev: () => void;
  onNext: () => void;
  onPeek: () => void;
  onExit: () => void;
}

/** The panel of the "do it yourself" mode: step chips in the look's order, the step's sentences, and back / next. */
export function PracticePanel({
  title,
  intro,
  steps,
  activeIndex,
  text,
  peeking,
  labels,
  onPick,
  onPrev,
  onNext,
  onPeek,
  onExit,
}: PracticePanelProps) {
  const last = activeIndex >= steps.length - 1;
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title} accessibilityRole="header">
          {title}
        </Text>
        <Chip label={peeking ? labels.peekOff : labels.peek} selected={peeking} onPress={onPeek} />
        <Chip label={labels.exit} onPress={onExit} />
      </View>
      <Text style={styles.intro}>{intro}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.steps}>
        {steps.map((step, i) => {
          const active = i === activeIndex;
          return (
            <Pressable
              key={step.key}
              onPress={() => onPick(i)}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              style={[styles.chip, active && styles.chipOn]}>
              {step.done ? (
                <Ionicons name="checkmark-circle" size={14} color={active ? theme.colors.white : theme.colors.success} />
              ) : null}
              <Text style={[styles.chipText, active && styles.chipTextOn]}>
                {i + 1}. {step.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      <View style={styles.card}>
        <Text style={styles.text}>{text}</Text>
      </View>
      <View style={styles.nav}>
        <Button label={labels.prev} variant="secondary" icon="chevron-back" disabled={activeIndex === 0} onPress={onPrev} style={styles.navBtn} />
        <Button label={last ? labels.finish : labels.next} icon={last ? 'checkmark' : 'chevron-forward'} onPress={onNext} style={styles.navBtn} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 10 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 16 },
  title: { flex: 1, fontSize: theme.font.title, fontWeight: '800', color: theme.colors.ink },
  intro: { paddingHorizontal: 16, fontSize: 12, color: theme.colors.inkMuted, lineHeight: 17 },
  steps: { gap: 8, paddingHorizontal: 16 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: theme.radius.pill,
    backgroundColor: theme.colors.surfaceAlt,
  },
  chipOn: { backgroundColor: theme.colors.rose },
  chipText: { fontSize: theme.font.small, fontWeight: '700', color: theme.colors.inkMuted },
  chipTextOn: { color: theme.colors.white },
  card: {
    marginHorizontal: 16,
    padding: theme.spacing.md,
    borderRadius: theme.radius.md,
    borderWidth: 1.5,
    borderColor: theme.colors.rose,
    backgroundColor: theme.colors.roseSoft,
  },
  text: { fontSize: theme.font.small, fontWeight: '600', color: theme.colors.ink, lineHeight: 20 },
  nav: { flexDirection: 'row', gap: 10, paddingHorizontal: 16 },
  navBtn: { flex: 1 },
});
