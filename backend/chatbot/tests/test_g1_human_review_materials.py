from tests import g1_human_review_materials as materials


def test_missing_review_evidence_is_not_presented_as_a_real_answer(tmp_path):
    report = materials.make_materials([], tmp_path)
    assert report.count("상태: NOT_RUN") == 18
    assert report.count("실행 또는 검증된 증빙이 없습니다.") == 18
    assert "판정: PASS" not in report


def test_only_verified_real_evidence_gets_review_material(monkeypatch, tmp_path):
    obs = {
        "caseId": "G1-GEN-01",
        "caseRevision": 1,
        "variantId": "default",
        "environment": "E3",
        "runId": "test-run",
        "isMock": False,
        "isSynthetic": False,
        "response": {"answer": "시험 답변", "products": []},
        "llmModelId": "test-model",
        "responseEvidenceRef": "test-run/response_snapshot.json",
    }
    monkeypatch.setattr(materials, "verify_evidence", lambda *args: False)
    assert "시험 답변" not in materials.make_materials([obs], tmp_path)
    monkeypatch.setattr(materials, "verify_evidence", lambda *args: True)
    report = materials.make_materials([obs], tmp_path)
    assert "시험 답변" in report
    assert "test-run/response_snapshot.json" in report
    assert report.count("실행 또는 검증된 증빙이 없습니다.") == 17
    assert "판정: PASS" not in report
