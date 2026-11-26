"""Normalized makeup troubleshooting data; the serving view is migration-owned."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base

PREFIX = "makeup_troubleshooting_"


def column(name, type_=sa.Text, *, nullable=False, default=None):
    return sa.Column(name, type_, nullable=nullable, server_default=default)


def check(expression):
    return sa.CheckConstraint(expression)


def fk(columns, target, target_columns):
    return sa.ForeignKeyConstraint(columns, [f"{PREFIX}{target}.{c}" for c in target_columns])


class MakeupTroubleshootingReleaseRow(Base):
    __table__ = sa.Table(
        PREFIX + "release",
        Base.metadata,
        column("dataset_version"),
        column("provenance", JSONB),
        column("dataset_sha256"),
        column("created_at", sa.DateTime(timezone=True), default=sa.text("CURRENT_TIMESTAMP")),
        column("publish_status", default=sa.text("'draft'")),
        column("reviewed_by", nullable=True),
        column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("dataset_version"),
        check("jsonb_typeof(provenance) = 'object'"),
        check("dataset_sha256 ~ '^[0-9a-f]{64}$'"),
        check("publish_status IN ('draft','approved','retired')"),
        check(
            "publish_status <> 'approved' OR (reviewed_by IS NOT NULL "
            "AND btrim(reviewed_by) <> '' AND reviewed_at IS NOT NULL)"
        ),
        sa.Index(
            "ux_makeup_troubleshooting_single_active_release",
            "publish_status",
            unique=True,
            postgresql_where=sa.text("publish_status = 'approved'"),
        ),
    )


class MakeupTroubleshootingProblemRow(Base):
    __table__ = sa.Table(
        PREFIX + "problem",
        Base.metadata,
        column("dataset_version"),
        column("problem_id"),
        column("category_number", sa.SmallInteger),
        column("category"),
        column("question"),
        column("clarifying_conditions"),
        column("selection_evidence_status"),
        sa.PrimaryKeyConstraint("dataset_version", "problem_id"),
        fk(["dataset_version"], "release", ["dataset_version"]),
        check("problem_id ~ '^[A-Z]+-[0-9]+$'"),
        check("category_number BETWEEN 1 AND 16"),
        check("btrim(category) <> ''"),
        check("btrim(question) <> ''"),
        check("btrim(clarifying_conditions) <> ''"),
        check(
            "selection_evidence_status IN ('direct_occurrence','reported_occurrence',"
            "'broader_occurrence','safety_rationale','reviewer_accepted','needs_more_evidence')"
        ),
    )


class MakeupTroubleshootingSituationRow(Base):
    __table__ = sa.Table(
        PREFIX + "situation",
        Base.metadata,
        column("dataset_version"),
        column("situation_id"),
        column("problem_id"),
        column("selection_condition"),
        column("solution_draft"),
        column("original_evidence_cell"),
        column("solution_evidence_scope"),
        column("safety_class", default=sa.text("'unreviewed'")),
        column("service_status", default=sa.text("'draft'")),
        column("reviewed_by", nullable=True),
        column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        column("approval_basis", nullable=True),
        sa.PrimaryKeyConstraint("dataset_version", "situation_id"),
        fk(["dataset_version", "problem_id"], "problem", ["dataset_version", "problem_id"]),
        check("situation_id ~ '^[A-Z]+-[0-9]+-S[0-9]+$'"),
        check("btrim(selection_condition) <> ''"),
        check("btrim(solution_draft) <> ''"),
        check("btrim(original_evidence_cell) <> ''"),
        check(
            "solution_evidence_scope IN ('직접','안전','응용','조건부','추가 검수','원인 미확인')"
        ),
        check("safety_class IN ('unreviewed','general','safety_review_required')"),
        check("service_status IN ('draft','approved','retired')"),
        check("left(situation_id,length(problem_id)+1) = problem_id || '-'"),
        check(
            "service_status <> 'approved' OR (safety_class <> 'unreviewed' "
            "AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '' "
            "AND reviewed_at IS NOT NULL AND approval_basis IS NOT NULL "
            "AND btrim(approval_basis) <> '')"
        ),
        sa.Index("ix_makeup_troubleshooting_situation_problem", "dataset_version", "problem_id"),
    )


class MakeupTroubleshootingSourceRow(Base):
    __table__ = sa.Table(
        PREFIX + "source",
        Base.metadata,
        column("dataset_version"),
        column("source_id"),
        column("source_role"),
        column("title"),
        column("links", JSONB),
        column("metadata", JSONB),
        column("source_type", nullable=True),
        column("publisher", nullable=True),
        column("checked_at", sa.DateTime(timezone=True), nullable=True),
        column("usage_status", default=sa.text("'pending'")),
        column("reviewed_by", nullable=True),
        column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("dataset_version", "source_id"),
        fk(["dataset_version"], "release", ["dataset_version"]),
        sa.UniqueConstraint("dataset_version", "source_id", "source_role"),
        check("btrim(source_id) <> ''"),
        check("source_role IN ('problem_selection','solution')"),
        check("btrim(title) <> ''"),
        check("jsonb_typeof(links) = 'array'"),
        check("jsonb_typeof(metadata) = 'object'"),
        check("usage_status IN ('pending','approved','blocked','withdrawn')"),
        check(
            "usage_status <> 'approved' OR (checked_at IS NOT NULL "
            "AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '' AND reviewed_at IS NOT NULL)"
        ),
    )
    # Avoid the declarative Base.metadata attribute name collision.
    __mapper_args__ = {"properties": {"source_metadata": __table__.c.metadata}}


class MakeupTroubleshootingProblemEvidenceRow(Base):
    __table__ = sa.Table(
        PREFIX + "problem_evidence",
        Base.metadata,
        column("dataset_version"),
        column("problem_id"),
        column("evidence_position", sa.Integer),
        column("source_id"),
        column("source_role", default=sa.text("'problem_selection'")),
        column("relation"),
        column("scope"),
        column("survey_products_nonzero", sa.Integer, nullable=True),
        column("survey_products_with_data", sa.Integer, nullable=True),
        column("metadata", JSONB),
        sa.PrimaryKeyConstraint("dataset_version", "problem_id", "evidence_position"),
        fk(["dataset_version", "problem_id"], "problem", ["dataset_version", "problem_id"]),
        fk(
            ["dataset_version", "source_id", "source_role"],
            "source",
            ["dataset_version", "source_id", "source_role"],
        ),
        check("evidence_position > 0"),
        check("source_role = 'problem_selection'"),
        check(
            "relation IN ('direct_occurrence','reported_occurrence','broader_occurrence',"
            "'safety_rationale','reviewer_accepted')"
        ),
        check("btrim(scope) <> ''"),
        check("jsonb_typeof(metadata) = 'object'"),
        check(
            "((source_id = 'OY_SURVEY' AND survey_products_nonzero IS NOT NULL "
            "AND survey_products_with_data IS NOT NULL AND survey_products_nonzero > 0 "
            "AND survey_products_with_data >= survey_products_nonzero) "
            "OR (source_id <> 'OY_SURVEY' AND survey_products_nonzero IS NULL "
            "AND survey_products_with_data IS NULL))"
        ),
    )
    __mapper_args__ = {"properties": {"evidence_metadata": __table__.c.metadata}}


class MakeupTroubleshootingSituationEvidenceRow(Base):
    __table__ = sa.Table(
        PREFIX + "situation_evidence",
        Base.metadata,
        column("dataset_version"),
        column("situation_id"),
        column("reference_position", sa.Integer),
        column("source_id"),
        column("source_role", default=sa.text("'solution'")),
        column("source_note"),
        column("evidence_summary", nullable=True),
        column("applies_to", nullable=True),
        column("limitation", nullable=True),
        sa.PrimaryKeyConstraint("dataset_version", "situation_id", "reference_position"),
        fk(["dataset_version", "situation_id"], "situation", ["dataset_version", "situation_id"]),
        fk(
            ["dataset_version", "source_id", "source_role"],
            "source",
            ["dataset_version", "source_id", "source_role"],
        ),
        check("reference_position > 0"),
        check("source_role = 'solution'"),
        check("btrim(source_note) <> ''"),
        check("evidence_summary IS NULL OR btrim(evidence_summary) <> ''"),
        check("applies_to IS NULL OR btrim(applies_to) <> ''"),
        check("limitation IS NULL OR btrim(limitation) <> ''"),
    )
