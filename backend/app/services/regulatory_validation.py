import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "regulatory_rules"
    / "fire_safety_preview_registry.json"
)

_SOURCE_MAPPING_STATUSES = {
    "not_reviewed",
    "verified",
    "needs_correction",
    "rejected",
}
_CURRENTNESS_STATUSES = {
    "not_reviewed",
    "verified_current",
    "superseded",
    "unknown",
}
_APPLICABILITY_STATUSES = {"unknown", "reviewed"}
_REVIEW_FIELDS = {"status", "reviewer", "reviewed_at", "notes"}
_REQUIRED_RULE_FIELDS = {
    "rule_id",
    "document_type",
    "candidate_requirement",
    "clause_text",
    "handbook_version",
    "source_path",
    "section",
    "printed_page",
    "pdf_page",
    "scope",
    "source_mapping_review",
    "currentness_review",
    "applicability_review",
    "preview_approved",
}
_REQUIRED_SCOPE_FIELDS = {
    "known_scope",
    "allowed_facts",
    "required_facts",
    "conditions",
}


class RegistryValidationError(ValueError):
    """Raised when the static regulatory registry is malformed or unsafe."""


def _validate_timestamp(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise RegistryValidationError(f"{field} must be an ISO-8601 string or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryValidationError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RegistryValidationError(f"{field} must include a timezone")


def _validate_review(
    review: Any,
    *,
    field: str,
    allowed_statuses: set[str],
) -> None:
    if not isinstance(review, dict):
        raise RegistryValidationError(f"{field} must be an object")
    if not _REVIEW_FIELDS.issubset(review):
        raise RegistryValidationError(f"{field} is missing review metadata")
    if not isinstance(review["status"], str) or review["status"] not in allowed_statuses:
        raise RegistryValidationError(f"{field}.status is not allowed")
    if review["reviewer"] is not None and not isinstance(review["reviewer"], str):
        raise RegistryValidationError(f"{field}.reviewer must be a string or null")
    if not isinstance(review["notes"], str):
        raise RegistryValidationError(f"{field}.notes must be a string")
    _validate_timestamp(review["reviewed_at"], f"{field}.reviewed_at")


def _validate_verified_mapping(rule: dict[str, Any]) -> None:
    review = rule["source_mapping_review"]
    verified_mapping = review.get("verified_mapping")
    if review["status"] == "verified":
        expected_mapping = {
            "section": rule["section"],
            "printed_page": rule["printed_page"],
            "pdf_page": rule["pdf_page"],
        }
        if verified_mapping != expected_mapping:
            raise RegistryValidationError(
                f"{rule['rule_id']} verified mapping does not match its source reference"
            )
    elif verified_mapping is not None:
        raise RegistryValidationError(
            f"{rule['rule_id']} cannot have a verified mapping unless status is verified"
        )


def _validate_rule(rule: Any) -> None:
    if not isinstance(rule, dict):
        raise RegistryValidationError("Each rule must be an object")
    missing_fields = _REQUIRED_RULE_FIELDS - rule.keys()
    if missing_fields:
        raise RegistryValidationError(
            f"Rule is missing required fields: {', '.join(sorted(missing_fields))}"
        )
    for field in (
        "rule_id",
        "document_type",
        "candidate_requirement",
        "clause_text",
        "handbook_version",
        "source_path",
        "section",
    ):
        if not isinstance(rule[field], str) or not rule[field].strip():
            raise RegistryValidationError(f"{field} must be a non-empty string")
    for field in ("printed_page", "pdf_page"):
        if type(rule[field]) is not int or rule[field] < 1:
            raise RegistryValidationError(f"{field} must be a positive integer")
    if not isinstance(rule["preview_approved"], bool):
        raise RegistryValidationError("preview_approved must be a boolean")

    scope = rule["scope"]
    if not isinstance(scope, dict) or not _REQUIRED_SCOPE_FIELDS.issubset(scope):
        raise RegistryValidationError("scope is missing required metadata")
    if not isinstance(scope["known_scope"], str):
        raise RegistryValidationError("scope.known_scope must be a string")
    if not isinstance(scope["allowed_facts"], dict):
        raise RegistryValidationError("scope.allowed_facts must be an object")
    if not isinstance(scope["required_facts"], list) or not all(
        isinstance(fact, str) and fact for fact in scope["required_facts"]
    ):
        raise RegistryValidationError("scope.required_facts must be a list of strings")
    if not isinstance(scope["conditions"], list) or not all(
        isinstance(condition, str) for condition in scope["conditions"]
    ):
        raise RegistryValidationError("scope.conditions must be a list of strings")
    for fact, allowed_values in scope["allowed_facts"].items():
        if not isinstance(fact, str) or not isinstance(allowed_values, list) or not all(
            isinstance(value, str) and value for value in allowed_values
        ):
            raise RegistryValidationError("scope.allowed_facts values must be string lists")
    if not set(scope["required_facts"]).issubset(scope["allowed_facts"]):
        raise RegistryValidationError(
            "Every required scope fact must have explicitly allowed values"
        )

    _validate_review(
        rule["source_mapping_review"],
        field="source_mapping_review",
        allowed_statuses=_SOURCE_MAPPING_STATUSES,
    )
    _validate_review(
        rule["currentness_review"],
        field="currentness_review",
        allowed_statuses=_CURRENTNESS_STATUSES,
    )
    _validate_review(
        rule["applicability_review"],
        field="applicability_review",
        allowed_statuses=_APPLICABILITY_STATUSES,
    )
    _validate_verified_mapping(rule)

    if rule["preview_approved"] and not (
        rule["source_mapping_review"]["status"] == "verified"
        and rule["currentness_review"]["status"] == "verified_current"
        and rule["applicability_review"]["status"] == "reviewed"
    ):
        raise RegistryValidationError(
            f"{rule['rule_id']} cannot be preview-approved before all reviews pass"
        )
    if rule["preview_approved"] and any(
        not rule[field]["reviewer"] or not rule[field]["reviewed_at"]
        for field in (
            "source_mapping_review",
            "currentness_review",
            "applicability_review",
        )
    ):
        raise RegistryValidationError(
            f"{rule['rule_id']} cannot be preview-approved without recorded reviewers and timestamps"
        )


def load_registry(path: Path | None = None) -> list[dict[str, Any]]:
    """Load and validate the static registry; no CSV data is used to enable rules."""
    registry_path = path or DEFAULT_REGISTRY_PATH
    try:
        with registry_path.open(encoding="utf-8") as registry_file:
            data = json.load(registry_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryValidationError("Could not load the regulatory rule registry") from exc

    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise RegistryValidationError("Registry must contain a rules list")
    if type(data.get("registry_version")) is not int or data["registry_version"] != 1:
        raise RegistryValidationError("Unsupported or missing registry_version")
    if not isinstance(data.get("source"), str) or not data["source"].strip():
        raise RegistryValidationError("Registry source must be a non-empty string")

    rule_ids: set[str] = set()
    for rule in data["rules"]:
        _validate_rule(rule)
        if rule["rule_id"] in rule_ids:
            raise RegistryValidationError(f"Duplicate rule ID: {rule['rule_id']}")
        rule_ids.add(rule["rule_id"])
    return data["rules"]


def evaluate_preview_eligibility(
    rule: Mapping[str, Any],
    application_scope: Mapping[str, str] | None,
) -> str:
    """Return eligibility only; this function does not assess document contents."""
    if not rule.get("preview_approved", False):
        return "unknown"
    if (
        rule["source_mapping_review"]["status"] != "verified"
        or rule["currentness_review"]["status"] != "verified_current"
        or rule["applicability_review"]["status"] != "reviewed"
    ):
        return "unknown"
    if application_scope is None:
        return "unknown"

    scope = rule["scope"]
    required_facts = scope["required_facts"]
    if any(
        fact not in application_scope or not application_scope[fact]
        for fact in required_facts
    ):
        return "unknown"

    for fact in required_facts:
        if application_scope[fact] not in scope["allowed_facts"][fact]:
            return "not_applicable"
    return "eligible_for_preview"


def evaluate_rule_result(
    rule: Mapping[str, Any],
    document_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Perform limited field checks without treating extraction as compliance evidence.
    """
    rule_id = rule["rule_id"]
    fields = document_evidence.get("fields", {})

    if rule_id == "FS-001":
        cert_no = fields.get("certificate_number", {})
        if cert_no.get("status") == "extracted" and cert_no.get("value"):
            return {
                "status": "Needs review",
                "explanation": (
                    "A certificate number was extracted, but its authenticity and "
                    "regulatory validity were not verified."
                ),
                "evidence": cert_no.get("evidence"),
                "rule_id": rule_id,
            }
        return {
            "status": "Not evaluated",
            "explanation": (
                "A certificate number was not extracted; there is insufficient "
                "evidence to assess this candidate check."
            ),
            "evidence": None,
            "rule_id": rule_id,
        }

    if rule_id == "FS-002":
        expiry = fields.get("expiry_date", {})
        if expiry.get("status") != "extracted" or not expiry.get("value"):
            return {
                "status": "Not evaluated",
                "explanation": (
                    "An expiry date was not extracted; there is insufficient "
                    "evidence to assess this candidate check."
                ),
                "evidence": None,
                "rule_id": rule_id,
            }

        try:
            expiry_date = datetime.fromisoformat(expiry["value"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return {
                "status": "Needs review",
                "explanation": (
                    "The extracted expiry date could not be interpreted reliably; "
                    "a reviewer must check it against the source document."
                ),
                "evidence": expiry.get("evidence"),
                "rule_id": rule_id,
            }

        date_observation = (
            "is before today"
            if expiry_date.date() < datetime.now(timezone.utc).date()
            else "is not before today"
        )
        return {
            "status": "Needs review",
            "explanation": (
                f"The extracted expiry date {date_observation}; the date check "
                "does not establish legal validity or compliance. A reviewer must "
                "confirm the source and applicable policy."
            ),
            "evidence": expiry.get("evidence"),
            "rule_id": rule_id,
        }

    return {
        "status": "Not evaluated",
        "explanation": (
            f"No evaluator is implemented for rule {rule_id}; it was not evaluated."
        ),
        "evidence": None,
        "rule_id": rule_id,
    }


def build_preview_context(
    rule: Mapping[str, Any],
    application_scope: Mapping[str, str] | None,
    document_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep extracted document evidence distinct from its regulatory source."""
    eligibility = evaluate_preview_eligibility(rule, application_scope)
    if not rule.get("preview_approved", False):
        reason = "Rule is not explicitly approved for preview; no rule evaluation was performed."
    elif eligibility == "unknown":
        reason = "Application scope or required review evidence is unavailable; applicability is unknown."
    elif eligibility == "not_applicable":
        reason = "The verified application scope does not match this rule."
    else:
        reason = "Rule is eligible for preview; document-field comparison is not implemented."

    return {
        "eligibility": eligibility,
        "evaluation_status": (
            "not_assessed" if eligibility == "eligible_for_preview" else "unknown"
        ),
        "check_reason": reason,
        "document_evidence": dict(document_evidence),
        "candidate_rule": {
            "rule_id": rule["rule_id"],
            "document_type": rule["document_type"],
            "candidate_requirement": rule["candidate_requirement"],
            "clause_text": rule["clause_text"],
            "scope": rule["scope"],
            "source_mapping_review": rule["source_mapping_review"],
            "currentness_review": rule["currentness_review"],
            "applicability_review": rule["applicability_review"],
            "preview_approved": rule["preview_approved"],
        },
        "rule_evidence": {
            "rule_id": rule["rule_id"],
            "clause_text": rule["clause_text"],
            "source": {
                "handbook_version": rule["handbook_version"],
                "source_path": rule["source_path"],
                "section": rule["section"],
                "printed_page": rule["printed_page"],
                "pdf_page": rule["pdf_page"],
            },
        },
        "limitations": [
            "Extracted fields, including OCR output, are unverified evidence.",
            "This preview does not determine document authenticity or institutional compliance.",
            "No certificate validity duration or expiry policy is inferred.",
        ],
    }
