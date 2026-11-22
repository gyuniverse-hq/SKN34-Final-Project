/** Recognize requests to find looks without treating product shopping as a look search. */
export function wantsStyleSearch(text: string, hasSuggestions: boolean): boolean {
  if (/제품|상품|가격|성분|향료|product|price|ingredient|商品|製品|产品|成分/i.test(text)) return false;
  const look = /룩|스타일|メイク|ルック|妆容|造型|\blook\b|\bstyle\b/i.test(text);
  const makeup = /화장|메이크업|makeup|メイク|化妆|妆容/i.test(text);
  const want = /싶|추천|찾아|골라|어울|해볼|하고\s*가|want|suggest|recommend|find|おすすめ|したい|想要|推荐/i.test(text);
  const focus = /눈|립|입술|블러셔|펄|반짝|상황|출근|데이트|하객|등교|분위기|조건|eye|lip|mood|sparkle|目元|リップ|眼妆|唇|雰囲気|条件/i.test(text);
  const change = /더|덜|바꿔|변경|강조|연하게|진하게|말고|제외|빼|취소|상관없|less|more|change|remove|控えめ|もっと|更|淡|変え|改/i.test(text);
  const alternative = /(?:다른|새로운|different|another).{0,12}(?:룩|분위기|메이크업|look|mood)/i.test(text);
  const refine = (focus && change) || alternative;
  return (look && want) || (makeup && want) || (hasSuggestions && refine);
}

/** A number is a selection only when the user explicitly chooses it. */
export function selectedLookOrdinal(text: string): number | undefined {
  if (!/할게|선택|골라|고를게|choose|select|にする|选择/i.test(text)) return;
  const match = text.match(/(첫|두|세|1|2|3)\s*(?:번(?:째)?|번째)|\b(first|second|third)\b/i);
  const word = match?.[1] ?? match?.[2]?.toLowerCase();
  return word ? ({ 첫: 0, 두: 1, 세: 2, '1': 0, '2': 1, '3': 2, first: 0, second: 1, third: 2 } as Record<string, number>)[word] : undefined;
}

export function refersToPreviousLooks(text: string): boolean {
  return /(?:아까|앞서|이전|전에).{0,20}(?:추천|제안).{0,12}(?:룩|스타일|것|거)|(?:earlier|previous).{0,20}(?:look|suggestion)|(?:さっき|前).{0,20}ルック|之前.{0,20}(?:推荐|妆容)/i.test(text);
}
