import type { FalseLashLookId } from '@/lib/falseLashLooks';
import type { MascaraLookId } from '@/lib/mascaraLooks';
import type { MakeupZone } from '@/types';

/** One catalog shade per AR zone. Hexes come from catalog.json, not from this file. */
export type DemoLookSlot = {
  zone: MakeupZone;
  productId: string;
  shadeId: string;
  /**
   * 'video' = the same product and shade the video lists. 'similar' = the closest catalog shade by color
   * (the video SKU or its hex is not in the catalog); never a measured match. `video` names the video product.
   */
  match: 'video' | 'similar';
  video?: string;
  /** Closed mascara shape from the video product type (not measured from frames). */
  style?: MascaraLookId;
  /** Attached lashes (mascara slot only). */
  lashes?: FalseLashLookId;
  /** 'video' = the video lists this false-lash product; 'recommended' = the video lists none, a user-picked style. */
  lashSource?: 'video' | 'recommended';
  /** Eyeshadow second color (outer corner and lower lash line), from the video's second shadow. */
  to?: { productId: string; shadeId: string };
};

/**
 * Six demo looks from the 2026-11-04 AR try-on sheet (3 K-style, 3 K-celebrity).
 * These are catalog product+shade pairs for painting, not mappingVerified reviews.
 * 'similar' slots were picked by CIE ΔE against a reference color: the same video product's shade stored
 * under another zone, or the nearest color of the video's color name when the catalog has no hex.
 * Lips use the tint or lipstick that carries the color, not the liner or the top gloss.
 */
export const DEMO_LOOK_AR: Record<string, DemoLookSlot[]> = {
  // 딸기 토끼상
  'ZAozXs-ZZik': [
    { zone: 'foundation', productId: 'oy-a000000233171', shadeId: '19nc', match: 'video', video: '비디비치 블랙 퍼펙션 커버 핏 쿠션 19nc라이트' },
    { zone: 'contour', productId: 'oy-a000000201055', shadeId: '02-2', match: 'video', video: '롬앤 베러 댄 컨투어 02그레이쿨' },
    { zone: 'highlighter', productId: 'oy-a000000176088', shadeId: 'a000000176088-010', match: 'similar', video: '세잔느 펄 글로우 하이라이터 (피치 펄)' },
    { zone: 'blush', productId: 'oy-a000000250315', shadeId: '02', match: 'similar', video: '에이오유 보들 크림 블러셔 01 하츄볼 (피치 바닐라 핑크)' },
    { zone: 'brow', productId: 'oy-a000000138671', shadeId: '09', match: 'video', video: '페리페라 스키니 브로우 토프브라운' },
    {
      zone: 'eyeshadow', productId: 'oy-a000000217606', shadeId: '04', match: 'similar',
      video: '웨이크메이크 소프트 블러링 아이 팔레트 25 헬씨 코랄블러링',
      to: { productId: 'oy-a000000174309', shadeId: 'a000000174309-027' },
    },
    { zone: 'eyeliner', productId: 'oy-a000000199182', shadeId: '05', match: 'video', video: '투쿨포스쿨 아트클래스 스머징 트임라이너 05 포쉬' },
    // Video SKU (neozen slim metal black) has no stored hex; the closest black mascara in the catalog.
    { zone: 'mascara', productId: 'oy-a000000198027', shadeId: '01', match: 'similar', video: '네오젠 더마로지 슬림 메탈 마스카라 블랙', style: 'slim', lashes: 'upper', lashSource: 'recommended' },
    { zone: 'lip', productId: 'oy-a000000230581', shadeId: '14', match: 'video', video: '컬러그램 탕후루 탱글 틴트 14호 잔망피치' },
  ],
  // 연말 수상템 활용
  '4QR0tre9yBI': [
    { zone: 'foundation', productId: 'oy-a000000209870', shadeId: '21c', match: 'video', video: '클리오 킬커버 파운웨어 쿠션 란제리' },
    { zone: 'contour', productId: 'oy-a000000145650', shadeId: '1', match: 'video', video: '투쿨포스쿨 바이로댕 쉐이딩 1호 클래식' },
    { zone: 'highlighter', productId: 'oy-a000000176088', shadeId: 'a000000176088-012', match: 'video', video: '글린트 하이라이터 02 다이아몬드 베일' },
    { zone: 'blush', productId: 'oy-a000000203529', shadeId: 'cr01', match: 'similar', video: '퓌 블러셔 멜로우 02 선샤인구아바' },
    { zone: 'brow', productId: 'oy-a000000219593', shadeId: '8', match: 'video', video: '키스미 헤비 로테이션 컬러링 브로우 8호' },
    // Reference: 투쿨포스쿨 프로타주 02 로지듀 #D68D91 (stored under eyeliner).
    { zone: 'eyeshadow', productId: 'oy-a000000219570', shadeId: '104', match: 'similar', video: '투쿨포스쿨 프로타주 펜슬 02 로지듀 (+웨이크메이크 02 생기블러링)' },
    { zone: 'eyeliner', productId: 'oy-a000000203438', shadeId: '02', match: 'video', video: '키스미 히로인 스무스 리퀴드 아이라이너 02 브라운' },
    { zone: 'mascara', productId: 'oy-a000000198027', shadeId: '01', match: 'similar', video: '클리오 킬래쉬 수퍼프루프 마스카라', style: 'long', lashes: 'upper_dense', lashSource: 'recommended' },
    { zone: 'lip', productId: 'oy-a000000241210', shadeId: '03', match: 'video', video: '롬앤 쥬시래스팅 틴트 베어그레이프' },
  ],
  // 청초 물복숭아
  'kWI7_DkDjZ0': [
    { zone: 'foundation', productId: 'oy-a000000247764', shadeId: '20-2', match: 'video', video: '에스쁘아 프로 테일러 실크 스킨 레이어 쿠션 20 바닐라' },
    { zone: 'highlighter', productId: 'oy-a000000234040', shadeId: '02', match: 'video', video: '에뛰드 슈팅 빔 하이라이터 02 핑크하트보석' },
    { zone: 'blush', productId: 'oy-a000000250442', shadeId: 'p205', match: 'video', video: '딘토 소프트글로우 리퀴드 치크 P205 파르 유스티티아' },
    // Reference: 디어에이 0.9mm 브로우 01 쿨 애쉬 (grey brown); the catalog has no 디어에이 brow.
    { zone: 'brow', productId: 'oy-a000000180551', shadeId: '01', match: 'similar', video: '디어에이 0.9mm 브로우 펜슬 01 쿨 애쉬' },
    {
      zone: 'eyeshadow', productId: 'oy-a000000250307', shadeId: '06', match: 'video', video: '원정요 메탈 샤워 펜슬 06 리코타핑크',
      to: { productId: 'oy-a000000174309', shadeId: 'a000000174309-133' },
    },
    // Video SKU (클리오 킬 래쉬 파인 03 뮤트얼그레이) has no stored hex; closest soft black.
    { zone: 'mascara', productId: 'oy-a000000205718', shadeId: 'a000000205718-006', match: 'similar', video: '클리오 킬 래쉬 슈퍼프루프 마스카라 파인 03 뮤트얼그레이', style: 'fine', lashes: 'wispies', lashSource: 'video' },
    { zone: 'lip', productId: 'oy-a000000201123', shadeId: '219', match: 'video', video: '딘토 블러글로이 립 틴트 219 아베 마리아' },
  ],
  // 카리나 멧갈라
  n5otfjJSSQc: [
    { zone: 'foundation', productId: 'oy-a000000251851', shadeId: '23n', match: 'video', video: '네이밍 올데이 마스터 쿠션 23N' },
    { zone: 'contour', productId: 'oy-a000000176894', shadeId: '02', match: 'video', video: '데이지크 브이컷 블렌딩 쉐딩 쿨블렌딩' },
    { zone: 'highlighter', productId: 'oy-a000000263862', shadeId: 'a000000263862-007', match: 'video', video: '오프라 하이라이터 스타아일랜드' },
    { zone: 'blush', productId: 'oy-a000000137964', shadeId: '16', match: 'video', video: '릴리바이레드 러브빔 치크밤 꿀복빔' },
    { zone: 'brow', productId: 'oy-a000000154277', shadeId: '02', match: 'video', video: '키스미 헤비로테이션 내추럴 파우더 아이브로우 애쉬브라운' },
    {
      zone: 'eyeshadow', productId: 'oy-a000000174309', shadeId: 'a000000174309-057', match: 'video', video: '홀리카홀리카 마이페이브 피스 아이섀도우 베이비타로',
      to: { productId: 'oy-a000000174309', shadeId: 'a000000174309-011' },
    },
    { zone: 'eyeliner', productId: 'oy-a000000171017', shadeId: '01', match: 'video', video: '토니모리 백젤 아이라이너 블랙' },
    { zone: 'mascara', productId: 'oy-a000000185925', shadeId: '02', match: 'similar', video: '뮤드 볼륨 업 스키니 마스카라 웜블랙 (+에뛰드 컬픽스 블랙)', style: 'volume_skinny', lashes: 'upper_lower', lashSource: 'video' },
    { zone: 'lip', productId: 'oy-a000000229303', shadeId: '03', match: 'video', video: '에이오유 매트바 슴슴바' },
  ],
  // 설윤 뿌까
  e1gSkUdG6Bo: [
    // Reference: 미샤 M 퍼펙트 커버 비비크림 EX 20 쿨 베이지; the catalog only has 미샤 M초보양 비비.
    { zone: 'foundation', productId: 'oy-a000000210065', shadeId: '21', match: 'similar', video: '미샤 M 퍼펙트 커버 비비크림 EX 20 쿨 베이지' },
    { zone: 'contour', productId: 'oy-a000000180297', shadeId: '03', match: 'video', video: '페리페라 브이 쉐딩 03 그레이쉬쿨' },
    { zone: 'highlighter', productId: 'oy-a000000232152', shadeId: '02', match: 'video', video: '캔메이크 무뉴토 하이라이터 02 로즈 쿼츠' },
    { zone: 'blush', productId: 'oy-a000000225392', shadeId: '8', match: 'video', video: '비디비치 페탈 글로우 크림 블러시 08 보타닉 피치' },
    { zone: 'brow', productId: 'oy-a000000138671', shadeId: '03', match: 'video', video: '페리페라 스피디 스키니 브로우 03 내추럴 브라운' },
    { zone: 'eyeshadow', productId: 'oy-a000000168405', shadeId: '09', match: 'video', video: '삐아 레디 투 웨어 아이 섀도우 09 모태분위기' },
    { zone: 'eyeliner', productId: 'oy-a000000185974', shadeId: 'a000000185974-010', match: 'video', video: '키스미 스무스 리퀴드 아이라이너 N 차콜 브라운' },
    { zone: 'mascara', productId: 'oy-a000000185925', shadeId: '02', match: 'similar', video: '에뛰드 컬 픽스 마스카라 01 블랙', style: 'long_curl', lashes: 'natural', lashSource: 'video' },
    { zone: 'lip', productId: 'oy-a000000233656', shadeId: '01', match: 'video', video: '이더앤 듀이 시럽 틴트 01 멜트어웨이' },
  ],
  // 윈터 또렷 청초
  fDqBPI1SaWY: [
    { zone: 'foundation', productId: 'oy-a000000207117', shadeId: '01', match: 'video', video: '어뮤즈 세라믹 스킨 퍼펙터 파운데이션 01 포슬린' },
    { zone: 'contour', productId: 'oy-a000000201055', shadeId: '02-2', match: 'video', video: '롬앤 베러 댄 컨투어 02 그레이쿨' },
    // Reference: 투에이앤 퓨어글래시 하이라이터 슈가베일 (pale pearl); the catalog has no 투에이앤.
    { zone: 'highlighter', productId: 'oy-a000000176088', shadeId: 'a000000176088-018', match: 'similar', video: '투에이앤 퓨어글래시 하이라이터 슈가베일' },
    { zone: 'blush', productId: 'oy-a000000225392', shadeId: '04', match: 'video', video: '비디비치 페탈 글로우 크림 블러시 피오니밀크' },
    { zone: 'brow', productId: 'oy-a000000148567', shadeId: 'a000000148567-006', match: 'video', video: '힌스 시그니처 브로우 펜슬 P006 라이트브라운' },
    {
      zone: 'eyeshadow', productId: 'oy-a000000174310', shadeId: 'a000000174310-009', match: 'video', video: '홀리카홀리카 마이페이브 피스 아이글리츠 위티',
      to: { productId: 'oy-a000000174309', shadeId: 'a000000174309-027' },
    },
    // Reference: 에이프릴스킨 트임 라이너 02 다크브라운; the catalog has no 에이프릴스킨 liner.
    { zone: 'eyeliner', productId: 'oy-a000000185974', shadeId: 'a000000185974-010', match: 'similar', video: '에이프릴스킨 트임 라이너 02 다크브라운' },
    { zone: 'mascara', productId: 'oy-a000000198027', shadeId: '01', match: 'similar', video: '네오젠 더마로지 슬림 메탈 마스카라 블랙', style: 'slim', lashes: 'winged', lashSource: 'video' },
    { zone: 'lip', productId: 'oy-a000000223676', shadeId: '02', match: 'video', video: '컬러그램 누드 컬러 커버틴트 웜누디' },
  ],
};

export function demoLookVideoId(lookId: string): string {
  return lookId.replace(/^(celebrity|style)-/, '');
}

export function demoLookSlots(lookId: string): DemoLookSlot[] {
  return DEMO_LOOK_AR[demoLookVideoId(lookId)] ?? [];
}
