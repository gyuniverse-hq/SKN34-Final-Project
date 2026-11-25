import type { LipEvalProduct, LipEvalSlot } from "../api/types";

export type SlotProgress = "empty" | "refs" | "scored";

export function slotProgress(slot: LipEvalSlot): SlotProgress {
  if (slot.scored) return "scored";
  if (slot.readyForAr) return "refs";
  return "empty";
}

export function panelProgress(items: LipEvalProduct[]) {
  let scored = 0;
  let refs = 0;
  let empty = 0;
  let finalized = 0;
  for (const product of items) {
    if (product.aggregate.finalized) finalized += 1;
    for (const slot of product.slots) {
      const p = slotProgress(slot);
      if (p === "scored") scored += 1;
      else if (p === "refs") refs += 1;
      else empty += 1;
    }
  }
  const total = scored + refs + empty;
  return { scored, refs, empty, total, finalized, products: items.length };
}

function csvEscape(value: string | number | null | undefined): string {
  if (value == null) return "";
  const text = String(value);
  if (/[",\n\r]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function metricValue(
  slot: LipEvalSlot,
  key: "delta_e" | "ssim" | "mae" | "miou" | "lpips",
): string {
  const item = slot.technical?.items?.[key];
  if (!item || item.value == null) return "";
  return Number(item.value).toFixed(4);
}

/** Flat CSV: one row per product×rater slot, plus product aggregate columns. */
export function buildLipEvalCsv(items: LipEvalProduct[]): string {
  const header = [
    "sortOrder",
    "productId",
    "brand",
    "name",
    "shade",
    "raterId",
    "raterLabel",
    "status",
    "naturalnessMean",
    "technicalOverall",
    "deltaE",
    "ssim",
    "mae",
    "miou",
    "lpips",
    "scoredAt",
    "productScoredCount",
    "productNaturalnessMean",
    "productTechPassRate",
    "productFinalized",
  ];
  const lines = [header.join(",")];
  for (const product of items) {
    for (const slot of product.slots) {
      lines.push(
        [
          product.sortOrder,
          product.id,
          product.brand,
          product.name,
          product.shade,
          slot.raterId,
          slot.label,
          slotProgress(slot),
          slot.naturalness?.mean ?? "",
          slot.technical?.overall ?? "",
          metricValue(slot, "delta_e"),
          metricValue(slot, "ssim"),
          metricValue(slot, "mae"),
          metricValue(slot, "miou"),
          metricValue(slot, "lpips"),
          slot.scoredAt ?? "",
          product.aggregate.scoredCount,
          product.aggregate.naturalnessMean ?? "",
          product.aggregate.technicalOverallPassRate ?? "",
          product.aggregate.finalized ? "1" : "0",
        ]
          .map(csvEscape)
          .join(","),
      );
    }
  }
  return `${lines.join("\n")}\n`;
}

export function downloadTextFile(filename: string, content: string, mime = "text/csv;charset=utf-8") {
  const blob = new Blob(["\uFEFF", content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
