"""Fixed lip AR panel catalog: 11 products × 5 raters (eval period)."""

from __future__ import annotations

LIP_EVAL_RATERS: list[dict] = [
    {"id": 1, "label": "관리자1"},
    {"id": 2, "label": "관리자2"},
    {"id": 3, "label": "관리자3"},
    {"id": 4, "label": "관리자4"},
    {"id": 5, "label": "관리자5"},
]

LIP_EVAL_PRODUCTS: list[dict] = [
    {
        "id": "lip-01-3ce-murmuring",
        "brand": "3CE",
        "name": "소프트 매트 립스틱",
        "shade": "머머링",
        "sortOrder": 1,
    },
    {
        "id": "lip-02-romand-cream-buns",
        "brand": "롬앤",
        "name": "글래스팅 컬러 글로스",
        "shade": "크림 반즈",
        "sortOrder": 2,
    },
    {
        "id": "lip-03-peripera-kongkong",
        "brand": "페리페라",
        "name": "무드 글로이 틴트",
        "shade": "콩콩라떼",
        "sortOrder": 3,
    },
    {
        "id": "lip-04-peripera-hipsaeng",
        "brand": "페리페라",
        "name": "무드 블러 밤",
        "shade": "힙생힙사",
        "sortOrder": 4,
    },
    {
        "id": "lip-05-lilybyred-vanillabean",
        "brand": "릴리바이레드",
        "name": "스윗 라이어 밀키 틴트",
        "shade": "바닐라빈 크림인 척",
        "sortOrder": 5,
    },
    {
        "id": "lip-06-peripera-mocha",
        "brand": "페리페라",
        "name": "무드 블러 틴트",
        "shade": "집에모카",
        "sortOrder": 6,
    },
    {
        "id": "lip-07-bbia-peanut",
        "brand": "삐아",
        "name": "오버글레이즈",
        "shade": "땅콩당",
        "sortOrder": 7,
    },
    {
        "id": "lip-08-wakemake-sootipingk",
        "brand": "웨이크메이크",
        "name": "소프트 블러링 밤 스틱",
        "shade": "수티핑크",
        "sortOrder": 8,
    },
    {
        "id": "lip-09-apieu-pecan",
        "brand": "에이쁘",
        "name": "블러 틴 팟",
        "shade": "피칸버터",
        "sortOrder": 9,
    },
    {
        "id": "lip-10-hince-raw-rose",
        "brand": "힌스",
        "name": "로 글로우 젤 틴트",
        "shade": "로 로즈",
        "sortOrder": 10,
    },
    {
        "id": "lip-11-hince-cinnamon",
        "brand": "힌스",
        "name": "로 글로우 젤 틴트",
        "shade": "시나몬",
        "sortOrder": 11,
    },
]

RATER_IDS = {r["id"] for r in LIP_EVAL_RATERS}
PRODUCT_IDS = {p["id"] for p in LIP_EVAL_PRODUCTS}
