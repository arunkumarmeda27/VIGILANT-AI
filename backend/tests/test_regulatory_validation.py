import copy
import json

import pytest

from app.services.regulatory_validation import (
    DEFAULT_REGISTRY_PATH,
    RegistryValidationError,
    build_preview_context,
    evaluate_preview_eligibility,
    load_registry,
)


EXPECTED_RULE_IDS = {
    "DOCUMENT-0004",
    "DOCUMENT-0012",
    "DOCUMENT-0021",
    "INFRASTRUCTURE-0002",
}


def _write_registry(tmp_path, rules):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "registry_version": 1,
                "source": "AICTE Approval Process Handbook 2024-2027",
                "rules": rules,
            }
        ),
        encoding="utf-8",
    )
    return path


def _rule_by_id(rule_id):
    return next(rule for rule in load_registry() if rule["rule_id"] == rule_id)


def _approve_for_test(rule):
    approved = copy.deepcopy(rule)
    reviewed_at = "2026-10-24T12:00:00+00:00"
    approved["source_mapping_review"]["status"] = "verified"
    approved["source_mapping_review"]["reviewer"] = "Test Reviewer"
    approved["source_mapping_review"]["reviewed_at"] = reviewed_at
    approved["source_mapping_review"]["verified_mapping"] = {
        "section": approved["section"],
        "printed_page": approved["printed_page"],
        "pdf_page": approved["pdf_page"],
    }
    approved["currentness_review"]["status"] = "verified_current"
    approved["currentness_review"]["reviewer"] = "Test Reviewer"
    approved["currentness_review"]["reviewed_at"] = reviewed_at
    approved["applicability_review"]["status"] = "reviewed"
    approved["applicability_review"]["reviewer"] = "Test Reviewer"
    approved["applicability_review"]["reviewed_at"] = reviewed_at
    approved["preview_approved"] = True
    return approved


def test_all_four_rules_load_from_project_anchored_registry():
    rules = load_registry()

    assert {rule["rule_id"] for rule in rules} == EXPECTED_RULE_IDS
    assert DEFAULT_REGISTRY_PATH.is_absolute()
    assert DEFAULT_REGISTRY_PATH.is_file()


def test_all_rules_default_to_disabled_and_reviews_unfinished():
    for rule in load_registry():
        assert rule["preview_approved"] is False
        assert rule["currentness_review"]["status"] == "not_reviewed"
        assert rule["applicability_review"]["status"] == "unknown"
        assert evaluate_preview_eligibility(rule, None) == "unknown"


def test_duplicate_rule_ids_are_rejected(tmp_path):
    rule = _rule_by_id("DOCUMENT-0012")

    with pytest.raises(RegistryValidationError, match="Duplicate rule ID"):
        load_registry(_write_registry(tmp_path, [rule, copy.deepcopy(rule)]))


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda rule: rule.pop("handbook_version"), "missing required fields"),
        (lambda rule: rule.__setitem__("pdf_page", "97"), "positive integer"),
        (
            lambda rule: rule["currentness_review"].__setitem__("status", "approved"),
            "status is not allowed",
        ),
    ],
)
def test_malformed_registry_entries_are_rejected(tmp_path, mutate, message):
    rule = copy.deepcopy(_rule_by_id("DOCUMENT-0012"))
    mutate(rule)

    with pytest.raises(RegistryValidationError, match=message):
        load_registry(_write_registry(tmp_path, [rule]))


def test_document_0021_retains_wrong_mapping_and_stays_disabled():
    rule = _rule_by_id("DOCUMENT-0021")

    assert rule["section"] == "1.1(xii)"
    assert rule["printed_page"] == 77
    assert rule["pdf_page"] == 93
    assert rule["source_mapping_review"]["status"] == "needs_correction"
    assert rule["proposed_correction"]["section"] == (
        "Annexure-1, Private Lease of Building, item (v)"
    )
    assert rule["proposed_correction"]["printed_page"] == 78
    assert rule["proposed_correction"]["pdf_page"] == 94
    assert rule["preview_approved"] is False


def test_wrong_page_reference_cannot_be_silently_approved(tmp_path):
    rule = _approve_for_test(_rule_by_id("DOCUMENT-0012"))
    rule["pdf_page"] = 98

    with pytest.raises(RegistryValidationError, match="verified mapping"):
        load_registry(_write_registry(tmp_path, [rule]))


def test_approval_requires_recorded_reviewers_and_timestamps(tmp_path):
    rule = _approve_for_test(_rule_by_id("DOCUMENT-0012"))
    rule["currentness_review"]["reviewed_at"] = None

    with pytest.raises(RegistryValidationError, match="reviewers and timestamps"):
        load_registry(_write_registry(tmp_path, [rule]))


def test_unreviewed_currentness_returns_unknown_even_with_scope():
    rule = _approve_for_test(_rule_by_id("DOCUMENT-0012"))
    rule["currentness_review"]["status"] = "not_reviewed"
    scope = {
        "institution_type": "existing_technical_institution",
        "application_process": "eoa_self_disclosure",
    }

    assert evaluate_preview_eligibility(rule, scope) == "unknown"


def test_unknown_application_scope_returns_unknown():
    rule = _approve_for_test(_rule_by_id("DOCUMENT-0012"))
    scope = {"institution_type": "existing_technical_institution"}

    assert evaluate_preview_eligibility(rule, scope) == "unknown"


@pytest.mark.parametrize(
    "scope",
    [
        {"institution_type": "technical_institution"},
        {
            "institution_type": "technical_institution",
            "application_category": "unrelated_application",
        },
    ],
)
def test_infrastructure_rule_is_not_applied_to_every_application(scope):
    rule = _approve_for_test(_rule_by_id("INFRASTRUCTURE-0002"))

    assert evaluate_preview_eligibility(rule, scope) in {"unknown", "not_applicable"}


def test_registry_does_not_invent_certificate_expiry_policy():
    for rule in load_registry():
        encoded_rule = json.dumps(rule).casefold()
        assert "validity_period" not in encoded_rule
        assert "expiry_policy" not in encoded_rule
        assert "expires_after" not in encoded_rule


def test_matching_extracted_field_does_not_claim_authenticity_or_compliance():
    rule = _rule_by_id("DOCUMENT-0012")
    document_evidence = {
        "institution_name": {
            "value": "Example Institute",
            "status": "extracted",
            "evidence": "Institution Name: Example Institute",
            "confidence": None,
        }
    }
    result = build_preview_context(
        rule,
        {"institution_type": "existing_technical_institution"},
        document_evidence,
    )

    assert result["document_evidence"] == document_evidence
    assert result["rule_evidence"]["rule_id"] == "DOCUMENT-0012"
    assert result["evaluation_status"] == "unknown"
    assert result["eligibility"] == "unknown"
    assert "authenticity" in result["limitations"][1]
    assert "compliance" in result["limitations"][1]
    assert "authentic" not in result
    assert "compliant" not in result
