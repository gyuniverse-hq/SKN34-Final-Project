"""Render the VISHUE deployment diagram as a Korean PNG without browser rendering."""

from __future__ import annotations

from math import atan2, cos, sin
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "deliverables" / "vishue-system-architecture.png"
FONT_DIR = Path(r"C:\Windows\Fonts")

COLORS = {
    "background": "#F8F6F5",
    "ink": "#311521",
    "text": "#3F4750",
    "muted": "#59636F",
    "burgundy": "#7A1F3D",
    "rose": "#C76B86",
    "rose_fill": "#FFF5F7",
    "panel": "#FFFFFF",
    "border": "#E9DFE3",
    "node_border": "#D6C5CC",
    "store": "#FFFBEC",
    "store_border": "#D9B85C",
    "external": "#F2F7FF",
    "external_border": "#8AA6CA",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "malgunbd.ttf" if bold else "malgun.ttf"
    return ImageFont.truetype(FONT_DIR / filename, size=size)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int, *, bold: bool = False, fill: str = COLORS["text"]) -> None:
    draw.text(xy, value, font=font(size, bold), fill=fill)


def card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    lines: list[str],
    *,
    fill: str = COLORS["panel"],
    border: str = COLORS["node_border"],
    title_size: int = 19,
    line_size: int = 15,
    note: str | None = None,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=16, fill=fill, outline=border, width=2)
    text(draw, (x1 + 24, y1 + 22), title, title_size, bold=True, fill=COLORS["ink"])
    y = y1 + 58
    for line in lines:
        text(draw, (x1 + 24, y), line, line_size)
        y += line_size + 11
    if note:
        text(draw, (x1 + 24, y2 - 31), note, 13, bold=True, fill=COLORS["burgundy"])


def arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], *, color: str = COLORS["burgundy"], width: int = 3, dashed: bool = False) -> None:
    for start, end in zip(points, points[1:]):
        if dashed:
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = max(abs(dx), abs(dy))
            for offset in range(0, length, 13):
                ratio_a = offset / length
                ratio_b = min(offset + 7, length) / length
                draw.line(
                    (
                        start[0] + dx * ratio_a,
                        start[1] + dy * ratio_a,
                        start[0] + dx * ratio_b,
                        start[1] + dy * ratio_b,
                    ),
                    fill=color,
                    width=width,
                )
        else:
            draw.line((start, end), fill=color, width=width)
    before, tip = points[-2], points[-1]
    angle = atan2(tip[1] - before[1], tip[0] - before[0])
    wing = 12
    left = (tip[0] - wing * cos(angle - 0.45), tip[1] - wing * sin(angle - 0.45))
    right = (tip[0] - wing * cos(angle + 0.45), tip[1] - wing * sin(angle + 0.45))
    draw.polygon([tip, left, right], fill=color)


def main() -> None:
    image = Image.new("RGB", (1920, 1200), COLORS["background"])
    draw = ImageDraw.Draw(image)

    text(draw, (70, 50), "VISHUE — 운영 시스템 구성도", 34, bold=True, fill=COLORS["ink"])
    text(draw, (70, 95), "실제 구현 및 운영 계획 기준 · 모바일 AR 메이크업 · 카탈로그 · GraphRAG 챗봇", 16, fill=COLORS["muted"])
    draw.rounded_rectangle((1512, 47, 1837, 92), radius=22, fill="#F7E8ED")
    text(draw, (1540, 61), "운영 배포 예정 · AWS ap-northeast-2", 13, bold=True, fill=COLORS["burgundy"])

    draw.rounded_rectangle((60, 155, 455, 865), radius=24, fill=COLORS["panel"], outline=COLORS["border"], width=2)
    text(draw, (88, 181), "사용자 기기 · iOS / Android / Web", 18, bold=True, fill=COLORS["burgundy"])
    card(draw, (88, 225, 426, 395), "Expo React Native 앱", ["Expo Router · React Query · Zustand", "YouTube 룩 · 제품 · 구매 연결", "HTTPS JSON + Supabase Access Token"], note="모바일·웹 클라이언트")
    card(draw, (88, 427, 426, 647), "기기 내 AR / 피부 분석", ["Camera + WebView + MediaPipe", "Face Landmarker · ITA° · MST", "립 · 치크 · 아이섀도 렌더링"], fill=COLORS["rose_fill"], border=COLORS["rose"], note="얼굴 영상·이미지는 서버 전송 금지")
    card(draw, (88, 680, 426, 825), "Supabase Auth", ["이메일 코드 · Google 로그인", "JWT 발급 · 백엔드 JWKS 검증"], fill=COLORS["external"], border=COLORS["external_border"])

    draw.rounded_rectangle((510, 150, 1855, 255), radius=20, fill=COLORS["panel"], outline=COLORS["border"], width=2)
    text(draw, (540, 175), "배포 흐름 · GitOps", 18, bold=True, fill=COLORS["burgundy"])
    stages = [(740, "GitHub Actions"), (1000, "GHCR 이미지"), (1245, "태그 갱신 PR"), (1500, "Argo CD → EKS")]
    for x, label in stages:
        fill = COLORS["rose_fill"] if "Argo" in label else COLORS["panel"]
        border = COLORS["rose"] if "Argo" in label else COLORS["node_border"]
        draw.rounded_rectangle((x, 169, x + 180, 231), radius=12, fill=fill, outline=border, width=2)
        text(draw, (x + 25, 188), label, 17, bold=True, fill=COLORS["ink"])
    arrow(draw, [(920, 200), (1000, 200)])
    arrow(draw, [(1180, 200), (1245, 200)])
    arrow(draw, [(1425, 200), (1500, 200)])

    draw.rounded_rectangle((510, 290, 1440, 990), radius=26, fill="#FFF9FA", outline=COLORS["rose"], width=3)
    text(draw, (542, 318), "AWS 운영 환경 · VPC / EKS 클러스터", 18, bold=True, fill=COLORS["burgundy"])
    text(draw, (542, 347), "EKS 노드 2대, 2개 AZ · Terraform으로 인프라 관리 · Helm + Argo CD 배포", 13, fill=COLORS["muted"])
    card(draw, (548, 395, 898, 505), "Envoy Gateway", ["/api/* → api · /api/chat → chatbot", "TLS 종단 · 단일 API 진입점"])
    card(draw, (548, 550, 898, 735), "vishue-api · FastAPI", ["카탈로그 · 제품/셰이드 · 룩", "판매처 · YouTube 메타데이터", "셰이드 추천 · 회원 API"], note="Alembic initContainer · /healthz · /readyz")
    card(draw, (975, 550, 1395, 735), "vishue-chatbot · FastAPI", ["Neo4j 기반 GraphRAG 챗봇", "외부 LLM API 호출 · 응답 합성", "API HTTP 계약으로 카탈로그 조회"], note="LangGraph·MCP·자체 LLM 서버는 미도입")
    card(draw, (548, 790, 898, 940), "sync-graph · CronJob", ["배포 후 1회 + 30분 주기", "API → Neo4j 단방향 동기화"], note="Neo4j 직접 수정 금지")
    card(draw, (975, 790, 1395, 940), "AWS Secrets Manager", ["API 키 · DB 연결값 · LLM 설정", "External Secrets Operator → K8s Secret"], fill="#F6F9FD", border=COLORS["external_border"], note="앱 번들·Git에 비밀값 미포함")

    draw.rounded_rectangle((1490, 290, 1855, 990), radius=26, fill=COLORS["panel"], outline=COLORS["border"], width=2)
    text(draw, (1520, 318), "관리형 데이터 / 외부 연동", 18, bold=True, fill=COLORS["burgundy"])
    card(draw, (1520, 380, 1825, 505), "Amazon RDS PostgreSQL 17", ["제품 · 셰이드 · 룩 · 매장", "원본 데이터 · api만 쓰기 권한"], fill=COLORS["store"], border=COLORS["store_border"])
    card(draw, (1520, 535, 1825, 647), "ElastiCache Redis", ["캐시 · 레이트 리밋 · TLS"], fill=COLORS["store"], border=COLORS["store_border"])
    card(draw, (1520, 677, 1825, 789), "Neo4j AuraDB", ["챗봇 전용 그래프 사본"], fill=COLORS["store"], border=COLORS["store_border"])
    card(draw, (1520, 819, 1825, 949), "외부 API", ["YouTube Data · 네이버 쇼핑", "LLM API (챗봇 추론)"], fill=COLORS["external"], border=COLORS["external_border"])

    arrow(draw, [(426, 310), (475, 310), (475, 450), (548, 450)])
    text(draw, (462, 420), "HTTPS", 13, bold=True, fill=COLORS["muted"])
    arrow(draw, [(723, 505), (723, 550)])
    arrow(draw, [(898, 450), (975, 450), (975, 550)])
    arrow(draw, [(898, 600), (930, 600), (930, 520), (1465, 520), (1465, 442), (1520, 442)])
    arrow(draw, [(898, 640), (945, 640), (945, 535), (1465, 535), (1465, 591), (1520, 591)])
    arrow(draw, [(1185, 735), (1185, 790)])
    arrow(draw, [(898, 865), (1465, 865), (1465, 733), (1520, 733)])
    arrow(draw, [(1395, 642), (1465, 642), (1465, 884), (1520, 884)])
    arrow(draw, [(723, 790), (723, 735)], dashed=True, color=COLORS["muted"], width=2)
    text(draw, (742, 754), "API HTTP 동기화", 13, bold=True, fill=COLORS["muted"])
    arrow(draw, [(975, 855), (930, 855), (930, 700), (898, 700)], dashed=True, color=COLORS["muted"], width=2)
    arrow(draw, [(1185, 790), (1185, 735)], dashed=True, color=COLORS["muted"], width=2)
    text(draw, (1204, 755), "시크릿 주입", 13, bold=True, fill=COLORS["muted"])

    draw.rounded_rectangle((60, 1040, 1855, 1145), radius=20, fill=COLORS["ink"])
    text(draw, (92, 1063), "운영 원칙", 18, bold=True, fill="#FFFFFF")
    text(draw, (92, 1100), "① 얼굴 영상은 기기 내에서만 처리   ② PostgreSQL이 카탈로그 원본   ③ Neo4j는 API를 통한 읽기 전용 사본   ④ Terraform · Helm · Argo CD GitOps", 15, fill="#F6D9E2")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, "PNG", optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
