import { describe, expect, it } from "vitest";
import type { LipEvalProduct } from "../api/types";
import {
  buildLipEvalCsv,
  panelProgress,
  slotProgress,
} from "./lipEvalExport";

function slot(
  overrides: Partial<LipEvalProduct["slots"][number]> & { raterId: number },
): LipEvalProduct["slots"][number] {
  return {
    label: `관리자${overrides.raterId}`,
    hasBare: false,
    hasReal: false,
    hasAr: false,
    readyForAr: false,
    scored: false,
    technical: null,
    naturalness: null,
    scoredAt: null,
    imageUrls: { bare: null, real: null, ar: null },
    ...overrides,
  };
}

function product(
  overrides: Partial<LipEvalProduct> & { id: string; sortOrder: number },
): LipEvalProduct {
  const slots =
    overrides.slots ||
    [1, 2, 3, 4, 5].map((raterId) => slot({ raterId }));
  return {
    brand: "3CE",
    name: "소프트 매트 립스틱",
    shade: "머머링",
    aggregate: {
      scoredCount: slots.filter((s) => s.scored).length,
      finalized: slots.every((s) => s.scored),
      naturalnessMean: null,
      technicalOverallPassRate: null,
      metricMeans: null,
    },
    ...overrides,
    slots,
  };
}

describe("lipEvalExport", () => {
  it("슬롯 진행 상태를 구분한다", () => {
    expect(slotProgress(slot({ raterId: 1 }))).toBe("empty");
    expect(slotProgress(slot({ raterId: 1, readyForAr: true }))).toBe("refs");
    expect(slotProgress(slot({ raterId: 1, scored: true, readyForAr: true }))).toBe(
      "scored",
    );
  });

  it("패널 전체 진행을 집계한다", () => {
    const items = [
      product({
        id: "a",
        sortOrder: 1,
        slots: [
          slot({
            raterId: 1,
            scored: true,
            naturalness: {
              criteriaVersion: "ext-b",
              scores: {},
              mean: 4.2,
              briefReason: "",
              model: null,
            },
          }),
          slot({ raterId: 2, readyForAr: true }),
          slot({ raterId: 3 }),
          slot({ raterId: 4 }),
          slot({ raterId: 5 }),
        ],
      }),
    ];
    expect(panelProgress(items)).toEqual({
      scored: 1,
      refs: 1,
      empty: 3,
      total: 5,
      finalized: 0,
      products: 1,
    });
  });

  it("CSV에 제품×관리자 행과 점수를 넣는다", () => {
    const metric = (value: number) => ({
      value,
      bareValue: null,
      beatsBare: null,
      passLine: null,
      verdict: "pass" as const,
    });
    const items = [
      product({
        id: 'lip,"01"',
        sortOrder: 1,
        brand: "3CE",
        shade: "머머링",
        slots: [
          slot({
            raterId: 1,
            scored: true,
            naturalness: {
              criteriaVersion: "ext-b",
              scores: {},
              mean: 4.5,
              briefReason: "ok",
              model: null,
            },
            technical: {
              criteriaVersion: "v1",
              overall: "pass",
              items: {
                delta_e: metric(1.23456),
                ssim: metric(0.9),
                mae: metric(0.1),
                miou: metric(0.8),
                lpips: metric(0.05),
              },
            },
            scoredAt: "2026-11-24T00:00:00Z",
          }),
          slot({ raterId: 2 }),
          slot({ raterId: 3 }),
          slot({ raterId: 4 }),
          slot({ raterId: 5 }),
        ],
        aggregate: {
          scoredCount: 1,
          finalized: false,
          naturalnessMean: 4.5,
          technicalOverallPassRate: 1,
          metricMeans: null,
        },
      }),
    ];
    const csv = buildLipEvalCsv(items);
    expect(csv.startsWith("sortOrder,productId,")).toBe(true);
    expect(csv).toContain('"lip,""01"""');
    expect(csv).toContain("4.5");
    expect(csv).toContain("1.2346");
    expect(csv).toContain("pass");
    expect(csv.trim().split("\n")).toHaveLength(6);
  });
});
