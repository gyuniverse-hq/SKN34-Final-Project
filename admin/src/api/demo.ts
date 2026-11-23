import fixture from "./demo-eval.json";
const product = {
  id: "demo-lip",
  name: "시연용 립 컬러",
  brand: "VISHUE Demo",
  category: "lip",
  priceKRW: 18000,
  isVisible: true,
  stock: 12,
  shadeCount: 1,
  measurementMethods: ["estimated"],
  shades: [
    {
      id: "rose",
      name: "Rose",
      hex: "#b5555e",
      measureMethod: "estimated",
      colorSource: "demo",
      colorConfidence: null,
    },
  ],
};
const order = {
  id: "DEMO-ORDER",
  userId: "demo-use…",
  amountKRW: 18000,
  orderName: "시연용 립 컬러",
  status: "paid",
  createdAt: "2026-11-12T00:00:00Z",
  paidAt: "2026-11-12T00:01:00Z",
  paymentKey: "demo…",
  nextStatuses: ["preparing", "canceled"],
  lines: [
    {
      id: 1,
      productId: product.id,
      productName: product.name,
      shadeId: "rose",
      quantity: 1,
      unitPriceKRW: 18000,
    },
  ],
};
const run = { id: "demo-eval", createdAt: "2026-11-12T00:00:00Z", ...fixture };
export function demoResponse(path: string): unknown {
  const url = new URL(path, "http://localhost");
  if (url.pathname === "/eval-runs")
    return { items: url.searchParams.get("kind") === "human" ? [run] : [] };
  if (url.pathname === "/products")
    return {
      items:
        (!url.searchParams.get("category") ||
          url.searchParams.get("category") === product.category) &&
        (!url.searchParams.get("query") ||
          `${product.name} ${product.brand}`
            .toLowerCase()
            .includes(url.searchParams.get("query")!.toLowerCase()))
          ? [product]
          : [],
      nextCursor: null,
    };
  if (url.pathname === "/products/demo-lip") return product;
  if (url.pathname === "/orders")
    return {
      items:
        !url.searchParams.get("status") ||
        url.searchParams.get("status") === order.status
          ? [order]
          : [],
      nextCursor: null,
    };
  if (url.pathname === "/orders/DEMO-ORDER") return order;
  return { items: [], nextCursor: null };
}
