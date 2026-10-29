import type { ProductCategory } from '@/types';

export type ChatCondition = {
  kind: 'category' | 'maxPrice' | 'fragranceFree' | 'moisturizing';
  text: string;
  required: boolean;
  value?: ProductCategory | number;
};

const CATEGORIES: { value: ProductCategory; pattern: RegExp }[] = [
  { value: 'lip', pattern: /립(?:스틱|틴트|밤|\s*제품)?|\blip(?:stick| tint| balm)?\b|リップ|口红|唇膏|唇釉/i },
  { value: 'cheek', pattern: /블러셔|볼터치|\bblush(?:er)?\b|チーク|腮红/i },
  { value: 'eye', pattern: /아이섀도|아이섀도우|\beye\s?shadow\b|アイシャドウ|眼影/i },
  { value: 'base', pattern: /파운데이션|\bfoundation\b|ファンデーション|粉底/i },
  { value: 'skincare', pattern: /스킨케어|\bskin\s?care\b|スキンケア|护肤/i },
  { value: 'suncare', pattern: /선크림|자외선\s?차단제|\bsunscreen\b|日焼け止め|防晒/i },
];

// Only show filter candidates for explicit shopping requests, never general how-to questions.
const SHOPPING = /추천|찾아|골라|제품|상품|화장품|\b(?:recommend|suggest|find|shop|product|buy)\b|おすすめ|探して|商品|推荐|找(?:找|一款)?|产品|商品/i;
const GENERAL_QUESTION = /바르는\s*법|사용\s*방법|화장법|메이크업\s*방법|\bhow\s+(?:to|do|can)\b|使い方|塗り方|怎么用|如何使用/i;
const NEGATION = /^\s*(?:(?:건|것|제품)(?:은|는)?\s*)?(?:아니|말고|빼|제외|싫|불필요|필요\s*없|는\s*아니|은\s*아니|不要|以外|ではない)/i;

export function extractChatConditions(message: string): ChatCondition[] {
  if (!SHOPPING.test(message) || GENERAL_QUESTION.test(message)) return [];

  const conditions: ChatCondition[] = [];
  const categories: ChatCondition[] = [];
  for (const { value, pattern } of CATEGORIES) {
    const match = pattern.exec(message);
    if (match && !NEGATION.test(message.slice(match.index + match[0].length))) {
      categories.push({ kind: 'category', text: match[0], required: true, value });
    }
  }
  if (categories.length === 1) conditions.push(categories[0]);

  const koreanPrice = /(?:^|[^\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:\s*만\s*(\d{1,4})?)?\s*원\s*이하/i.exec(message);
  const englishPrice = /\b(at most|up to|under|less than)\s*(?:₩\s*|krw\s*)(\d{1,3}(?:,\d{3})+|\d+)(?![\d,]|\.\d)/i.exec(message);
  const price = koreanPrice ?? englishPrice;
  if (price && !NEGATION.test(message.slice(price.index + price[0].length)) &&
      !/\bnot\s*$/i.test(message.slice(0, price.index))) {
    const amount = koreanPrice ? koreanPrice[1] : englishPrice![2];
    const exclusive = !koreanPrice && englishPrice && /^(?:under|less than)$/i.test(englishPrice[1]);
    const value = Number(amount.replaceAll(',', '')) * (koreanPrice && /만/.test(koreanPrice[0]) ? 10000 : 1)
      + Number(koreanPrice?.[2] ?? 0) - (exclusive ? 1 : 0);
    if (Number.isSafeInteger(value) && value >= 0) {
      const text = koreanPrice ? price[0].slice(price[0].indexOf(amount)) : price[0];
      conditions.push({ kind: 'maxPrice', text: text.trim(), required: true, value });
    }
  }

  const fragrance = /향료\s*(?:없음|없는|무첨가|제외)|무향료|\bfragrance[ -]free\b|\b(?:without|no)\s+(?:added\s+)?fragrance\b|香料(?:不使用|無添加)|不含香料/i.exec(message);
  if (fragrance && !NEGATION.test(message.slice(fragrance.index + fragrance[0].length))) {
    conditions.push({ kind: 'fragranceFree', text: fragrance[0], required: true });
  }

  const moisturizing = /촉촉(?:함|한|하게)?\s*(?:우선|선호|좋아)|촉촉한(?=\s*(?:립|블러셔|파운데이션|제품|화장품))|보습\s*(?:우선|선호)|\b(?:prefer|prioriti[sz]e)\s+(?:hydrating|moisturi[sz]ing|hydration|moisture)\b|\b(?:hydrating|moisturi[sz]ing)(?=\s+(?:lip|blush|foundation|product))|保湿(?:を)?優先|优先保湿/i.exec(message);
  const afterMoisturizing = moisturizing ? message.slice(moisturizing.index + moisturizing[0].length) : '';
  if (moisturizing && !NEGATION.test(afterMoisturizing) &&
      !/(?:안|덜|\bnot(?:\s+(?:a|an))?|\bnon-)\s*$/i.test(message.slice(0, moisturizing.index)) &&
      !/^\s*(?:(?:립(?:\s*제품)?|블러셔|파운데이션|제품|화장품)(?:은|는|이|가|을|를)?\s*)?(?:말고|싫|아니|빼|제외)/i.test(afterMoisturizing)) {
    conditions.push({ kind: 'moisturizing', text: moisturizing[0], required: false });
  }
  return conditions;
}
