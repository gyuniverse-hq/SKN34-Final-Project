import type { TechMetricId } from "../api/types";

export type NaturalnessCriteriaItem = {
  id: TechMetricId | string;
  label: string;
  text: string;
  likert: Record<string, string>;
};

export type NaturalnessCriteria = {
  version: string;
  title: string;
  scale: { min: number; max: number; note: string };
  items: NaturalnessCriteriaItem[];
};

export function itemById(
  criteria: NaturalnessCriteria | undefined,
  id: string,
): NaturalnessCriteriaItem | undefined {
  return criteria?.items.find((item) => item.id === id);
}

export function anchorFor(
  criteria: NaturalnessCriteria | undefined,
  id: string,
  score: number | null | undefined,
): string | null {
  if (!criteria || score == null) return null;
  const item = itemById(criteria, id);
  if (!item) return null;
  return item.likert[String(score)] ?? null;
}
