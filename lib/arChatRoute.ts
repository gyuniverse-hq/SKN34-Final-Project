import { isClosedLocalArChat } from './arChatAdjust';

// Only complete, single requests can enter either execution path.
const value = String.raw`[+\-]?\d+(?:\.\d+)?\s*(?:%|퍼센트|프로|percent\b)`;
const local = [
  /^(?:립스틱|립)\s*(?:좀\s*더\s*|조금\s*더\s*)?(?:연한\s*(?:거|색)(?:\s*없어)?)[?？.!]?$/i,
  /^코랄\s*룩\s*(?:보여\s*줘|보여주세요)[.!]?$/i,
  /^(?:is there a |show me a |a )?(?:little )?lighter lipstick[?!.]?$/i,
  /^(?:show me a )?coral look[.!]?$/i,
  /^(?:もう少し)?薄い色のリップはある[?？。]?$/,
  /^コーラルのルックを見せて[。]?$/,
  /^(?:有没有)?颜色更浅一点的口红[?？。]?$/,
  /^给我看看珊瑚色妆容[。]?$/,
];

const geometryAbsolute = [
  /^(?:하이라이터|쉐딩|셰이딩|컨투어|아이라인|아이라이너|블러셔|아이섀도|립|입술)\s*[을를]?\s*.+\s*(?:으로|로)\s*(?:설정(?:해\s*(?:줘(?:요)?|주세요)|하세요)?|(?:변경|조절)해\s*(?:줘(?:요)?|주세요)|(?:해|맞춰|바꿔)\s*(?:줘(?:요)?|주세요))[.!。]?$/i,
  /^(?:please\s+)?set\s+(?:the\s+)?(?:highlighter|contour|eyeliner|blush|eyeshadow|lips?)\s+to\s+.+(?:\s+please)?[.!]?$/i,
];

export function arChatRoute(text: string): 'server' | 'local' | 'clarification' {
  const query = text.trim();
  if (!query) return 'clarification';
  if (geometryAbsolute.some((pattern) => pattern.test(query))) return 'server';
  if (local.some((pattern) => pattern.test(query))) return 'local';
  if (/연하게|진하게|약하게|강하게|\blighter\b|\bheavier\b|\bstronger\b|薄く|濃く|淡|浓/i.test(query)) return 'server';
  if (!new RegExp(value, 'i').test(query) && isClosedLocalArChat(query)) return 'local';
  return 'server';
}
