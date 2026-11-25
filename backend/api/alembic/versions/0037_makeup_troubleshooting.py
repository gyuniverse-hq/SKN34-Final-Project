"""Add versioned, review-only makeup troubleshooting data schema."""

# ruff: noqa: E501
# Preserve the exact PostgreSQL DDL verified during the rollback rehearsal.

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

# Frozen schema: do not import current application models from a historical revision.
DDL = r"""
CREATE TABLE makeup_troubleshooting_release (
    dataset_version text PRIMARY KEY,
    provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    dataset_sha256 text NOT NULL CHECK (dataset_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    publish_status text NOT NULL DEFAULT 'draft' CHECK (publish_status IN ('draft','approved','retired')),
    reviewed_by text,
    reviewed_at timestamptz,
    CHECK (publish_status <> 'approved' OR (reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '' AND reviewed_at IS NOT NULL))
);
-- Approved means the currently active release, not a collection of historical releases.
CREATE UNIQUE INDEX ux_makeup_troubleshooting_single_active_release
    ON makeup_troubleshooting_release(publish_status) WHERE publish_status = 'approved';

CREATE TABLE makeup_troubleshooting_problem (
    dataset_version text REFERENCES makeup_troubleshooting_release(dataset_version) NOT NULL,
    problem_id text NOT NULL CHECK (problem_id ~ '^[A-Z]+-[0-9]+$'),
    category_number smallint NOT NULL CHECK (category_number BETWEEN 1 AND 16),
    category text NOT NULL CHECK (btrim(category) <> ''),
    question text NOT NULL CHECK (btrim(question) <> ''),
    clarifying_conditions text NOT NULL CHECK (btrim(clarifying_conditions) <> ''),
    selection_evidence_status text NOT NULL CHECK (selection_evidence_status IN ('direct_occurrence','reported_occurrence','broader_occurrence','safety_rationale','reviewer_accepted','needs_more_evidence')),
    PRIMARY KEY (dataset_version,problem_id)
);

CREATE TABLE makeup_troubleshooting_situation (
    dataset_version text NOT NULL,
    situation_id text NOT NULL CHECK (situation_id ~ '^[A-Z]+-[0-9]+-S[0-9]+$'),
    problem_id text NOT NULL,
    selection_condition text NOT NULL CHECK (btrim(selection_condition) <> ''),
    solution_draft text NOT NULL CHECK (btrim(solution_draft) <> ''),
    original_evidence_cell text NOT NULL CHECK (btrim(original_evidence_cell) <> ''),
    solution_evidence_scope text NOT NULL CHECK (solution_evidence_scope IN ('직접','안전','응용','조건부','추가 검수','원인 미확인')),
    safety_class text NOT NULL DEFAULT 'unreviewed' CHECK (safety_class IN ('unreviewed','general','safety_review_required')),
    service_status text NOT NULL DEFAULT 'draft' CHECK (service_status IN ('draft','approved','retired')),
    reviewed_by text,
    reviewed_at timestamptz,
    approval_basis text,
    PRIMARY KEY (dataset_version,situation_id),
    FOREIGN KEY (dataset_version,problem_id) REFERENCES makeup_troubleshooting_problem(dataset_version,problem_id),
    CHECK (left(situation_id,length(problem_id)+1) = problem_id || '-'),
    CHECK (service_status <> 'approved' OR (safety_class <> 'unreviewed' AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '' AND reviewed_at IS NOT NULL AND approval_basis IS NOT NULL AND btrim(approval_basis) <> ''))
);
CREATE INDEX ix_makeup_troubleshooting_situation_problem ON makeup_troubleshooting_situation(dataset_version,problem_id);

CREATE TABLE makeup_troubleshooting_source (
    dataset_version text REFERENCES makeup_troubleshooting_release(dataset_version) NOT NULL,
    source_id text NOT NULL CHECK (btrim(source_id) <> ''),
    source_role text NOT NULL CHECK (source_role IN ('problem_selection','solution')),
    title text NOT NULL CHECK (btrim(title) <> ''),
    links jsonb NOT NULL CHECK (jsonb_typeof(links) = 'array'),
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    source_type text,
    publisher text,
    checked_at timestamptz,
    usage_status text NOT NULL DEFAULT 'pending' CHECK (usage_status IN ('pending','approved','blocked','withdrawn')),
    reviewed_by text,
    reviewed_at timestamptz,
    PRIMARY KEY (dataset_version,source_id),
    UNIQUE (dataset_version,source_id,source_role),
    CHECK (usage_status <> 'approved' OR (checked_at IS NOT NULL AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> '' AND reviewed_at IS NOT NULL))
);

CREATE TABLE makeup_troubleshooting_problem_evidence (
    dataset_version text NOT NULL,
    problem_id text NOT NULL,
    evidence_position integer NOT NULL CHECK (evidence_position > 0),
    source_id text NOT NULL,
    source_role text NOT NULL DEFAULT 'problem_selection' CHECK (source_role = 'problem_selection'),
    relation text NOT NULL CHECK (relation IN ('direct_occurrence','reported_occurrence','broader_occurrence','safety_rationale','reviewer_accepted')),
    scope text NOT NULL CHECK (btrim(scope) <> ''),
    survey_products_nonzero integer,
    survey_products_with_data integer,
    metadata jsonb NOT NULL CHECK (jsonb_typeof(metadata) = 'object'),
    PRIMARY KEY (dataset_version,problem_id,evidence_position),
    FOREIGN KEY (dataset_version,problem_id) REFERENCES makeup_troubleshooting_problem(dataset_version,problem_id),
    FOREIGN KEY (dataset_version,source_id,source_role) REFERENCES makeup_troubleshooting_source(dataset_version,source_id,source_role),
    CHECK ((source_id = 'OY_SURVEY' AND survey_products_nonzero IS NOT NULL AND survey_products_with_data IS NOT NULL
        AND survey_products_nonzero > 0 AND survey_products_with_data >= survey_products_nonzero)
       OR (source_id <> 'OY_SURVEY' AND survey_products_nonzero IS NULL AND survey_products_with_data IS NULL))
);

CREATE TABLE makeup_troubleshooting_situation_evidence (
    dataset_version text NOT NULL,
    situation_id text NOT NULL,
    reference_position integer NOT NULL CHECK (reference_position > 0),
    source_id text NOT NULL,
    source_role text NOT NULL DEFAULT 'solution' CHECK (source_role = 'solution'),
    source_note text NOT NULL CHECK (btrim(source_note) <> ''),
    evidence_summary text CHECK (evidence_summary IS NULL OR btrim(evidence_summary) <> ''),
    applies_to text CHECK (applies_to IS NULL OR btrim(applies_to) <> ''),
    limitation text CHECK (limitation IS NULL OR btrim(limitation) <> ''),
    PRIMARY KEY (dataset_version,situation_id,reference_position),
    FOREIGN KEY (dataset_version,situation_id) REFERENCES makeup_troubleshooting_situation(dataset_version,situation_id),
    FOREIGN KEY (dataset_version,source_id,source_role) REFERENCES makeup_troubleshooting_source(dataset_version,source_id,source_role)
);

-- Candidate read path for ordinary makeup advice. Safety cases are excluded
-- until a separate reviewed handling contract exists. Source eligibility and
-- evidence completeness are checked dynamically, including subsequent withdrawal.
CREATE VIEW makeup_troubleshooting_serving AS
SELECT s.dataset_version,s.situation_id,s.problem_id,p.category,p.question,p.clarifying_conditions,
       s.selection_condition,s.solution_draft,s.solution_evidence_scope,
       evidence.solution_evidence
FROM makeup_troubleshooting_situation s
JOIN makeup_troubleshooting_problem p USING(dataset_version,problem_id)
JOIN makeup_troubleshooting_release r USING(dataset_version)
CROSS JOIN LATERAL (
    SELECT count(*) AS reference_count,
           bool_and(src.usage_status = 'approved'
                    AND e.evidence_summary IS NOT NULL
                    AND e.applies_to IS NOT NULL
                    AND e.limitation IS NOT NULL) AS all_eligible,
           jsonb_agg(jsonb_build_object(
               'source_id', src.source_id, 'title', src.title, 'links', src.links,
               'source_note', e.source_note, 'evidence_summary', e.evidence_summary,
               'applies_to', e.applies_to, 'limitation', e.limitation
           ) ORDER BY e.reference_position) AS solution_evidence
    FROM makeup_troubleshooting_situation_evidence e
    JOIN makeup_troubleshooting_source src
        ON (src.dataset_version,src.source_id,src.source_role) =
           (e.dataset_version,e.source_id,e.source_role)
    WHERE (e.dataset_version,e.situation_id) = (s.dataset_version,s.situation_id)
) evidence
WHERE r.publish_status = 'approved' AND s.service_status = 'approved'
  AND p.selection_evidence_status <> 'needs_more_evidence'
  AND s.safety_class = 'general'
  AND s.solution_evidence_scope NOT IN ('안전','추가 검수','원인 미확인')
  AND evidence.reference_count > 0 AND evidence.all_eligible IS TRUE;
"""


def upgrade() -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement.strip())


def downgrade() -> None:
    op.execute("DROP VIEW makeup_troubleshooting_serving")
    for table in (
        "makeup_troubleshooting_situation_evidence",
        "makeup_troubleshooting_problem_evidence",
        "makeup_troubleshooting_source",
        "makeup_troubleshooting_situation",
        "makeup_troubleshooting_problem",
        "makeup_troubleshooting_release",
    ):
        op.drop_table(table)
