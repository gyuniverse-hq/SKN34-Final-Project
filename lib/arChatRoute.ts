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

export function arChatRoute(text: string): 'server' | 'local' | 'clarification' {
  const query = text.trim();
  if (!query) return 'clarification';
  if (local.some((pattern) => pattern.test(query))) return 'local';
  return 'server';
}
