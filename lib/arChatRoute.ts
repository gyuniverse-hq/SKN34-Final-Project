// Only complete, single requests can enter either execution path.
const value = String.raw`[+\-]?\d+(?:\.\d+)?\s*(?:%|퍼센트|프로|percent\b)`;
const absolute = [
  String.raw`(?:립|입술|그거|그것|이거|이것)\s*(?:(?:진하기|강도)\s*)?[을를]?\s*` + value +
    String.raw`\s*으?로\s*(?:설정(?:해\s*(?:줘(?:요)?|주세요)|하세요)?|(?:변경|조절)해\s*(?:줘(?:요)?|주세요)|(?:해|맞춰|바꿔)\s*(?:줘(?:요)?|주세요))`,
  String.raw`(?:please\s+)?set\s+(?:the\s+)?lips?(?:\s+intensity)?\s+to\s*` + value + String.raw`(?:\s+please)?`,
  String.raw`リップ(?:の(?:強度|濃さ))?を\s*` + value + String.raw`\s*に(?:設定|変更)して(?:ください)?`,
  String.raw`(?:请)?(?:把|将)?(?:唇妆|口红)(?:强度)?\s*(?:设为|设置为|调到|调至)\s*` + value,
].map((pattern) => new RegExp('^(?:' + pattern + ')[.!。]?$', 'i'));

const local = [
  /^(?:립스틱|립)\s*(?:좀\s*더\s*|조금\s*더\s*)?(?:연한\s*(?:거|색)(?:\s*없어)?|연하게\s*해\s*줘)[?？.!]?$/i,
  /^블러셔[를을]?\s*(?:조금\s*더\s*|좀\s*더\s*)?(?:은은하게|부드럽게|소프트하게)\s*해\s*줘[.!]?$/i,
  /^코랄\s*룩\s*(?:보여\s*줘|보여주세요)[.!]?$/i,
  /^(?:is there a |show me a |a )?(?:little )?lighter lipstick[?!.]?$/i,
  /^(?:make (?:the )?)?blush (?:a little )?softer[.!]?$/i,
  /^(?:show me a )?coral look[.!]?$/i,
  /^(?:もう少し)?薄い色のリップはある[?？。]?$/,
  /^チークを(?:もう少し)?やわらかくして[。]?$/,
  /^コーラルのルックを見せて[。]?$/,
  /^(?:有没有)?颜色更浅一点的口红[?？。]?$/,
  /^腮红再柔和一点[。]?$/,
  /^给我看看珊瑚色妆容[。]?$/,
];

export function arChatRoute(text: string): 'server' | 'local' | 'clarification' {
  const query = text.trim();
  if (absolute.some((pattern) => pattern.test(query))) return 'server';
  if (local.some((pattern) => pattern.test(query))) return 'local';
  return 'clarification';
}
