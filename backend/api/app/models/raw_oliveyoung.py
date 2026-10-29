"""올리브영 수집 원본(raw) 테이블.

이름 규칙: raw_<출처>_<데이터>  (출처 oy = 올리브영)
  · 앱 서빙 테이블(products / shades / looks / look_items / stores)과 같은 스키마에
    공존하므로 접두어로 구분한다. 다른 출처는 raw_kcia_* / raw_mfds_* 로 별도 모듈.

채우는 쪽: 공통·메이크업 21테이블 = 올리브영 수집기(oliveyoung_erd_v30)
          스킨케어 전용 1테이블   = raw_oy_skincare_attr (스킨케어 수집기)

API 는 이 테이블을 읽지 않는다. 앱 반영 경로는
  raw_oy_* -> 변환 -> backend/api/seed/catalog.json -> seed_catalog -> products/shades
여기 모델은 Alembic 이 스키마를 관리하도록(메타데이터 등록) 두는 정의다.

운영 전제
  · 수집기가 CSV 없이 DB 에 직접 적재한다.
  · 월 1회 전체 수집: 상품·옵션은 갱신(upsert), 가격·리뷰·색은 새 시점 이력 추가
  · 일 1회 증분 수집: 신규/옵션수 변경만 상세 수집, 사라진 것은 지우지 않고 delisted_at 표기
  · 수집 공란은 NULL 이므로 기본키 외에는 모두 nullable 이다.
"""

from datetime import datetime

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# ───────────────────────── 수집 실행 / 코드 테이블 ─────────────────────────


class RawOyCrawlRunRow(Base):
    __tablename__ = "raw_oy_crawl_run"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    script_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 실행이 끝날 때 채운다
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOyBrandRow(Base):
    __tablename__ = "raw_oy_brand"

    brand_code: Mapped[str] = mapped_column(Text, primary_key=True)
    brand_name_ko: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOySupplierRow(Base):
    __tablename__ = "raw_oy_supplier"

    supplier_code: Mapped[str] = mapped_column(Text, primary_key=True)
    supplier_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOyCategoryRow(Base):
    """올리브영 카테고리 트리. 부모가 자식보다 늦게 수집될 수 있어 자기참조 FK는 걸지 않는다."""

    __tablename__ = "raw_oy_category"
    __table_args__ = (Index("ix_raw_oy_category_parent", "parent_category_no"),)

    category_no: Mapped[str] = mapped_column(Text, primary_key=True)
    # 최상위 1행만 NULL
    parent_category_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOyTextureTypeRow(Base):
    """제형 7종 고정표. ar_gloss / ar_matte 는 수집값이 아니라 팀이 정할 AR 렌더 수치."""

    __tablename__ = "raw_oy_texture_type"

    texture_code: Mapped[str] = mapped_column(Text, primary_key=True)
    # shimmer 는 광택축 바깥이라 NULL
    gloss_axis: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ar_gloss: Mapped[float | None] = mapped_column(REAL, nullable=True)
    ar_matte: Mapped[float | None] = mapped_column(REAL, nullable=True)


class RawOySurveyQuestionRow(Base):
    __tablename__ = "raw_oy_survey_question"

    question_code: Mapped[str] = mapped_column(Text, primary_key=True)
    question_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOySurveyAnswerRow(Base):
    __tablename__ = "raw_oy_survey_answer"
    __table_args__ = (Index("ix_raw_oy_answer_question", "question_code"),)

    answer_code: Mapped[str] = mapped_column(Text, primary_key=True)
    question_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_survey_question.question_code"), nullable=True
    )
    answer_name: Mapped[str | None] = mapped_column(Text, nullable=True)


# ───────────────────────── 상품 / 옵션(호수) ─────────────────────────


class RawOyProductRow(Base):
    __tablename__ = "raw_oy_product"
    __table_args__ = (
        Index("ix_raw_oy_product_brand", "brand_code"),
        Index("ix_raw_oy_product_supplier", "supplier_code"),
        Index("ix_raw_oy_product_category", "category_no"),
        Index("ix_raw_oy_product_stdcat", "std_category_code"),
        # 증분 수집에서 "판매중인 것만" 빠르게 훑기
        Index(
            "ix_raw_oy_product_active",
            "goods_no",
            postgresql_where=text("delisted_at IS NULL"),
        ),
        # 상품명 부분일치 검색(검수 작업용)
        Index(
            "ix_raw_oy_product_name_trgm",
            "goods_name",
            postgresql_using="gin",
            postgresql_ops={"goods_name": "gin_trgm_ops"},
        ),
    )

    goods_no: Mapped[str] = mapped_column(Text, primary_key=True)
    brand_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_brand.brand_code"), nullable=True
    )
    supplier_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_supplier.supplier_code"), nullable=True
    )
    category_no: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_category.category_no"), nullable=True
    )
    # 올영 표준분류명(립틴트·쿠션 등). 메이크업/스킨케어 구분에 쓴다
    std_category_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    goods_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sale_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_new: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 증분 수집에서 목록에서 사라지면 기록한다(행을 지우지 않는다)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawOyProductNoticeRow(Base):
    __tablename__ = "raw_oy_product_notice"

    goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), primary_key=True
    )
    volume: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_spec: Mapped[str | None] = mapped_column(Text, nullable=True)
    shelf_life: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_country: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 전성분 원문. 성분 파싱·검수의 원천
    ingredients_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_extra: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawOyProductOptionRow(Base):
    __tablename__ = "raw_oy_product_option"
    __table_args__ = (Index("ix_raw_oy_option_goods", "goods_no"),)

    # goods_no-optionNumber
    option_id: Mapped[str] = mapped_column(Text, primary_key=True)
    goods_no: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), nullable=True
    )
    # '000','001' 처럼 선행 0 이 의미를 가지므로 문자열
    option_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 단일상품·세트 옵션은 호수가 없다
    shade_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    shade_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_representative: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 증분 수집용: 옵션이 목록에서 사라졌을 때 표기(현재 수집기는 채우지 않는다)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawOySkincareAttrRow(Base):
    """스킨케어 전용 속성. 스킨케어 수집기만 채우며 메이크업 상품은 행이 없다."""

    __tablename__ = "raw_oy_skincare_attr"

    goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), primary_key=True
    )
    # 'Y'/'N'/'?' — 불명값 '?' 가 있어 Boolean 이 아니다
    is_functional: Mapped[str | None] = mapped_column(Text, nullable=True)
    # '미백', '자외선차단' … 다중은 '|' 구분
    functional_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    functional_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # '모든피부|건성' … 다중은 '|' 구분
    skin_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    skin_type_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    # '50+' 처럼 '+' 가 붙어 숫자가 아니다
    spf: Mapped[str | None] = mapped_column(Text, nullable=True)
    pa: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ───────────────────────── 가격 / 색 / 제형 (이력 테이블) ─────────────────────────


class RawOyPriceSnapshotRow(Base):
    __tablename__ = "raw_oy_price_snapshot"
    __table_args__ = (
        # 같은 시점 재적재(재시도·이어받기)에서 중복 생성 방지
        UniqueConstraint("option_id", "collected_at", name="uq_raw_oy_price_option_time"),
        Index("ix_raw_oy_price_option", "option_id"),
        # 최신 행이 옵션당 하나만 있도록 강제.
        # 수집기는 같은 트랜잭션에서 기존 is_latest 를 false 로 바꾼 뒤 새 행을 넣어야 한다.
        Index(
            "uq_raw_oy_price_latest",
            "option_id",
            unique=True,
            postgresql_where=text("is_latest"),
        ),
    )

    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    option_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), nullable=True
    )
    list_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_benefit_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_discount: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_sold_out: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_latest: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawOyOptionColorRow(Base):
    __tablename__ = "raw_oy_option_color"
    __table_args__ = (Index("ix_raw_oy_color_run", "run_id"),)

    option_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), primary_key=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    # 색을 못 뽑으면 NULL 이고 사유가 color_note 에 들어간다
    hex_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    lab_l: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lab_a: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lab_b: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # swatch / color_chip / pencil_tip / none
    color_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 근거 이미지(raw_oy_image.image_id). 적재 순서 때문에 FK 없는 소프트 참조로 둔다
    color_image_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    color_confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)
    color_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_oy_crawl_run.run_id"), nullable=True
    )
    # 사람이 확정한 행만 표기
    is_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class RawOyProductTextureRow(Base):
    __tablename__ = "raw_oy_product_texture"

    goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), primary_key=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    # 브로우·라이너·마스카라는 제형 축이 비해당이라 NULL
    texture_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_texture_type.texture_code"), nullable=True
    )
    judge_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ───────────────────────── 이미지 ─────────────────────────


class RawOyImageRow(Base):
    __tablename__ = "raw_oy_image"
    __table_args__ = (
        # 월간 전체 수집에서 같은 이미지가 중복되지 않게 하는 조회 인덱스.
        # 유니크 제약을 걸지 않는 이유: option_id 가 NULL 인 상품단위 이미지가 있어
        # 표준 UNIQUE 로는 묶이지 않는다. 중복 방지는 수집기가 상품 단위로
        # "기존 이미지 삭제 -> 새로 삽입"(전체 재수집) 하는 방식으로 보장한다.
        Index("ix_raw_oy_image_identity", "goods_no", "image_type", "image_url"),
        Index("ix_raw_oy_image_goods", "goods_no"),
        Index("ix_raw_oy_image_option", "option_id"),
    )

    image_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    goods_no: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), nullable=True
    )
    # 상품단위 이미지(썸네일·상세설명)는 호수가 없다
    option_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), nullable=True
    )
    # thumbnail / color_chip / color_compare / option / description
    image_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawOyImageAppliedRow(Base):
    """같은 URL 이 여러 상품에 재사용되므로 이미지 판정은 URL 기준 1회만 한다."""

    __tablename__ = "raw_oy_image_applied"

    image_url: Mapped[str] = mapped_column(Text, primary_key=True)
    applied_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_conf: Mapped[float | None] = mapped_column(REAL, nullable=True)
    judged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ───────────────────────── 리뷰 / 설문 ─────────────────────────


class RawOyReviewSummaryRow(Base):
    __tablename__ = "raw_oy_review_summary"
    __table_args__ = (
        UniqueConstraint("goods_no", "collected_at", name="uq_raw_oy_revsum_goods_time"),
        Index("ix_raw_oy_revsum_goods", "goods_no"),
        Index(
            "uq_raw_oy_revsum_latest",
            "goods_no",
            unique=True,
            postgresql_where=text("is_latest"),
        ),
    )

    summary_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    goods_no: Mapped[str | None] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), nullable=True
    )
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_avg: Mapped[float | None] = mapped_column(REAL, nullable=True)
    rating_5_pct: Mapped[float | None] = mapped_column(REAL, nullable=True)
    rating_4_pct: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 해당 별점 리뷰가 0건이면 조회 결과에서 항목이 빠져 NULL 이 된다
    rating_3_pct: Mapped[float | None] = mapped_column(REAL, nullable=True)
    rating_2_pct: Mapped[float | None] = mapped_column(REAL, nullable=True)
    rating_1_pct: Mapped[float | None] = mapped_column(REAL, nullable=True)
    ai_positive_ratio: Mapped[float | None] = mapped_column(REAL, nullable=True)
    ai_negative_ratio: Mapped[float | None] = mapped_column(REAL, nullable=True)
    is_latest: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawOyReviewAiFeatureRow(Base):
    __tablename__ = "raw_oy_review_ai_feature"
    __table_args__ = (Index("ix_raw_oy_revfeat_goods", "goods_no"),)

    goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOyReviewSurveyRow(Base):
    __tablename__ = "raw_oy_review_survey"
    __table_args__ = (
        Index("ix_raw_oy_revsurvey_goods", "goods_no"),
        Index("ix_raw_oy_revsurvey_answer", "answer_code"),
    )

    goods_no: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product.goods_no"), primary_key=True
    )
    answer_code: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_survey_answer.answer_code"), primary_key=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    percentage: Mapped[float | None] = mapped_column(REAL, nullable=True)


# ───────────────────────── 성분 ─────────────────────────


class RawOyIngredientRow(Base):
    __tablename__ = "raw_oy_ingredient"
    __table_args__ = (
        UniqueConstraint("ingredient_norm", name="uq_raw_oy_ingredient_norm"),
        # 성분명 부분일치 검색(검수 작업용)
        Index(
            "ix_raw_oy_ingredient_name_trgm",
            "ingredient_name",
            postgresql_using="gin",
            postgresql_ops={"ingredient_name": "gin_trgm_ops"},
        ),
    )

    ingredient_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ingredient_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NFKC + 공백/CI/함량 제거 + 대문자. 같은 성분 판정 키이자 upsert 기준
    ingredient_norm: Mapped[str | None] = mapped_column(Text, nullable=True)


class RawOyOptionIngredientRow(Base):
    __tablename__ = "raw_oy_option_ingredient"
    __table_args__ = (Index("ix_raw_oy_optingr_ingredient", "ingredient_id"),)

    option_id: Mapped[str] = mapped_column(
        Text, ForeignKey("raw_oy_product_option.option_id"), primary_key=True
    )
    ingredient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_oy_ingredient.ingredient_id"), primary_key=True
    )
    # 전성분 표기 순서
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ───────────────────────── 수집 로그 ─────────────────────────


class RawOyCrawlLogRow(Base):
    """goods_no 는 실패 상품·카테고리 단위 로그도 담기므로 FK 를 걸지 않는다(기록 보존 우선)."""

    __tablename__ = "raw_oy_crawl_log"
    __table_args__ = (Index("ix_raw_oy_crawllog_run", "run_id"),)

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_oy_crawl_run.run_id"), nullable=True
    )
    goods_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    step: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
