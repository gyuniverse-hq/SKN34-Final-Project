export type Role = "admin" | "viewer";
export interface Staff {
  userId: string;
  email: string | null;
  role: Role;
}
export type Status =
  "pending" | "paid" | "preparing" | "shipped" | "delivered" | "canceled";
export interface Order {
  id: string;
  userId: string;
  amountKRW: number;
  orderName: string;
  status: Status;
  createdAt: string | null;
  paidAt: string | null;
  paymentKey: string | null;
  nextStatuses: Status[];
  lines?: {
    id: number;
    productId: string;
    productName: string;
    shadeId: string | null;
    quantity: number;
    unitPriceKRW: number;
  }[];
}
export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}
export interface Shade {
  id: string;
  name: string;
  hex: string;
  measureMethod: string | null;
  colorSource: string | null;
  colorConfidence: number | null;
}
export interface Product {
  id: string;
  name: string;
  brand: string;
  category: string;
  priceKRW: number;
  isVisible: boolean;
  stock: number | null;
  shadeCount: number;
  measurementMethods: string[];
  shades?: Shade[];
}
export interface Estimate {
  estimate: number | null;
  low: number | null;
  high: number | null;
  n: number;
}
export type Factor =
  "total" | "texture" | "shading" | "gloss" | "boundary" | "adhesion";
export interface PairedComparison {
  previousRendererCommit: string;
  method: "face-paired-bootstrap";
  totalDelta: Estimate;
}
export interface EvalSummary {
  factors: Record<Factor, Estimate>;
  reliability: {
    raterCount: number;
    icc21: number | null;
    icc2k: number | null;
    normalizedIcc: number | null;
    alpha: number | null;
  };
  mdc95: number | null;
  finishes: { label: string; total: Estimate }[];
  mouths: { label: string; total: Estimate }[];
  itaBins: { label: string; total: Estimate }[];
  correlations: { metric: string; spearman: number | null }[];
  vlmVerdict: string;
  unmeasured: string[];
}
export interface EvalRun {
  id: string;
  kind: "human" | "bench" | "judge";
  createdAt: string;
  rendererCommit: string;
  rendererDirty: boolean;
  rubricVersion: string;
  metricVersion: string;
  benchmarkSha256: string;
  summaryJson: EvalSummary & {
    pairedComparison?: PairedComparison | null;
    codeMetrics?: { metric: string; value: Estimate }[];
  };
}
export interface Audit {
  id: string;
  actorUserId: string | null;
  action: string;
  targetType: string;
  targetId: string;
  beforeJson: unknown;
  afterJson: unknown;
  requestId: string;
  createdAt: string;
}
