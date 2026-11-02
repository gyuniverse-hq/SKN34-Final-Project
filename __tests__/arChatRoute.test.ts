import { arChatRoute } from '@/lib/arChatRoute';

it.each([0, 1, 50, 100])('routes absolute lip %s percent only to the server', (percent) => {
  expect(arChatRoute(`립 진하기를 ${percent}%로 설정해 줘.`)).toBe('server');
});

it.each([
  '립스틱 좀 더 연한 거 없어?', '블러셔를 조금 더 은은하게 해줘', '코랄 룩 보여줘',
  'Is there a lighter lipstick?', 'Make the blush a little softer', 'Show me a coral look',
  'もう少し薄い色のリップはある？', 'チークをもう少しやわらかくして', 'コーラルのルックを見せて',
  '有没有颜色更浅一点的口红？', '腮红再柔和一点', '给我看看珊瑚色妆容',
])('preserves the single local request: %s', (text) => {
  expect(arChatRoute(text)).toBe('local');
});

it.each([
  '', '립을 조금 바꿔줘', '코랄 룩 보여주고 립 진하기를 50%로 설정해 줘',
  '립스틱 좀 더 연한 거 없어? 블러셔도 은은하게 해줘',
  '코랄 룩 보여줘 하지 마', 'do not show me a coral look',
  '블러셔 50%로 설정해 줘', '립 강도를 50%로 올리고 상품 추천해 줘',
])('does not partially execute an ambiguous, negative, or compound request: %s', (text) => {
  expect(arChatRoute(text)).toBe('clarification');
});
