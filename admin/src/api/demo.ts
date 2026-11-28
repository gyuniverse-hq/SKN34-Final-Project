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
  if (url.pathname === "/ops/recommendations")
    return {
      arPaletteMode: "legacy",
      arPaletteExperiment: null,
      cartRecommendationExperiment: null,
      counts: {
        recommendationImpressions: 12,
        skincareEvents: 4,
        cartRecommendationVisits: 2,
      },
    };
  if (url.pathname === "/ops/chatbot")
    return {
      configured: false,
      baseUrl: null,
      healthz: null,
      readyz: null,
      error: "demo mode",
    };
  if (url.pathname === "/ops/system")
    return {
      env: "demo",
      adminEnabled: true,
      alembicHead: "0036",
      lipEvalDir: "runtime/lip-eval",
      lipEvalDirExists: false,
      llmConfigured: false,
      chatbotBaseUrl: null,
      corsOriginCount: 0,
    };
  if (url.pathname === "/lip-eval/naturalness-criteria")
    return {
      version: "naturalness-techlang-v1.1",
      title: "립 AR 자연스러움 (테크니컬 지표 사람말 · 1~5)",
      scale: {
        min: 1,
        max: 5,
        note: "점수는 문항별 likert 앵커를 본다. 높을수록 AR이 실바름에 더 가깝다.",
      },
      items: [
        {
          id: "delta_e",
          label: "ΔE",
          text: "AR로 올린 입술과 실제로 바른 입술의 색이 얼마나 비슷해 보이는가?",
          likert: {
            "1": "누가 봐도 색이 완전히 다름 (다른 호수·다른 톤처럼 보임)",
            "2": "색 차이가 크고 한눈에 어긋남",
            "3": "비슷한 계열이지만 밝기·채도·톤이 꽤 다름",
            "4": "대체로 같고 작은 색감 차이만 있음",
            "5": "실제 립 색과 AR 색이 거의 동일함",
          },
        },
        {
          id: "ssim",
          label: "SSIM",
          text: "AR로 올린 입술과 실제로 바른 입술의 모양·명암·결 느낌이 얼마나 비슷해 보이는가?",
          likert: {
            "1": "모양·명암·결이 전혀 다른 입술처럼 보임",
            "2": "형태나 명암·결 느낌이 크게 어긋남",
            "3": "대체로 비슷하나 명암·결 일부가 어색",
            "4": "모양·명암·결이 잘 맞고 사소한 차이만 있음",
            "5": "실바름과 구조·결 느낌이 거의 구분되지 않음",
          },
        },
        {
          id: "mae",
          label: "MAE",
          text: "AR로 올린 입술과 실제로 바른 입술이 전체적으로 얼마나 비슷해 보이는가?",
          likert: {
            "1": "전체 인상이 완전히 다른 결과",
            "2": "전체적으로 크게 달라 보임",
            "3": "비슷한 인상이나 어색한 부분이 분명함",
            "4": "전체적으로 잘 맞고 작은 이질감만 있음",
            "5": "전체 인상이 실바름과 거의 같음",
          },
        },
        {
          id: "miou",
          label: "mIoU",
          text: "AR 색이 입술 영역·윤곽에 얼마나 잘 맞게 올라가 있는가?",
          likert: {
            "1": "색이 피부·이 등으로 크게 나가거나 입술과 무관한 위치",
            "2": "이탈·이중선·큰 번짐이 눈에 띔",
            "3": "대체로 맞지만 입꼬리·경계 일부가 어색",
            "4": "윤곽을 잘 따르고 사소한 흔들림만 있음",
            "5": "입술 영역·윤곽에 자연스럽게 정확히 맞음",
          },
        },
        {
          id: "lpips",
          label: "LPIPS",
          text: "AR로 올린 입술이 실제로 바른 입술과 얼마나 자연스럽게 비슷해 보이는가?",
          likert: {
            "1": "스티커·페인트·필터처럼 명백히 다름",
            "2": "합성 티·플라스틱감이 강해 실바름과 확연히 다름",
            "3": "비슷해 보이나 떠 보이거나 부자연스러운 부분이 있음",
            "4": "대체로 실바름처럼 자연스럽고 작은 어색함만 있음",
            "5": "실바름과 구분하기 어려울 정도로 자연스럽게 비슷함",
          },
        },
      ],
    };
  return { items: [], nextCursor: null };
}
