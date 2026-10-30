import re
from datetime import date, datetime
from math import isfinite
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.models import DocumentSchemaVersion, DocumentType
from app.schemas.document_registry import SchemaDefinition


def _normalize(value: Any, configuration: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    if configuration.get("trim", True):
        value = value.strip()
    if configuration.get("remove_whitespace", False):
        value = re.sub(r"\s+", "", value)
    case = configuration.get("case", "preserve")
    if case == "upper":
        return value.upper()
    if case == "lower":
        return value.lower()
    return value


def _normalize_schema_value(value: Any, field: dict[str, Any]) -> tuple[Any, str]:
    normalized = _normalize(value, field["normalization"])
    data_type = field["data_type"]
    if not isinstance(normalized, str):
        return normalized, "schema_configuration"
    candidate = normalized.strip()
    if data_type == "integer" and re.fullmatch(r"[+-]?\d+", candidate):
        return int(candidate), "integer_parse"
    if data_type == "number" and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", candidate):
        parsed = float(candidate)
        if isfinite(parsed):
            return parsed, "decimal_parse"
    if data_type == "boolean":
        folded = candidate.casefold()
        if folded in {"true", "yes"}:
            return True, "explicit_boolean_parse"
        if folded in {"false", "no"}:
            return False, "explicit_boolean_parse"
    if data_type == "date":
        iso_candidate = candidate.replace("/", "-")
        try:
            return date.fromisoformat(iso_candidate).isoformat(), "iso_date_parse"
        except ValueError:
            pass
        match = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", candidate)
        if match:
            first, second, year = (int(part) for part in match.groups())
            if first > 12 and 1 <= second <= 12:
                try:
                    return date(year, second, first).isoformat(), "unambiguous_day_first_date_parse"
                except ValueError:
                    pass
            if second > 12 and 1 <= first <= 12:
                try:
                    return date(year, first, second).isoformat(), "unambiguous_month_first_date_parse"
                except ValueError:
                    pass
        return value, "ambiguous_or_invalid_date"
    return normalized, "schema_configuration"


def _matches_type(value: Any, data_type: str) -> bool:
    if data_type == "string":
        return isinstance(value, str)
    if data_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    if data_type == "boolean":
        return isinstance(value, bool)
    if data_type == "date":
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False
    if data_type == "datetime":
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value)
            return True
        except ValueError:
            return False
    if data_type == "enum":
        return isinstance(value, str)
    if data_type == "array":
        return isinstance(value, list)
    if data_type == "object":
        return isinstance(value, dict)
    return False


def _valid_constraints(value: Any, field: dict[str, Any]) -> bool:
    constraints = field.get("constraints") or {}
    if isinstance(value, str):
        if constraints.get("min_length") is not None and len(value) < constraints["min_length"]:
            return False
        if constraints.get("max_length") is not None and len(value) > constraints["max_length"]:
            return False
        if constraints.get("pattern") and re.search(constraints["pattern"], value) is None:
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if constraints.get("minimum") is not None and value < constraints["minimum"]:
            return False
        if constraints.get("maximum") is not None and value > constraints["maximum"]:
            return False
    if isinstance(value, list):
        if constraints.get("min_items") is not None and len(value) < constraints["min_items"]:
            return False
        if constraints.get("max_items") is not None and len(value) > constraints["max_items"]:
            return False
        item_type = field.get("items_type")
        if item_type and not all(_matches_type(item, item_type) for item in value):
            return False
    if isinstance(value, dict):
        properties = field.get("object_properties") or {}
        if set(value) - set(properties):
            return False
        if set(field.get("object_required_properties") or []) - set(value):
            return False
        if not all(
            _matches_type(value[key], property_type)
            for key, property_type in properties.items()
            if key in value
        ):
            return False
    if field.get("data_type") == "enum":
        return value.casefold() in {
            allowed.casefold() for allowed in field.get("enum_values", [])
        }
    return True


def validate_extracted_fields(
    schema_definition: dict[str, Any],
    extracted_fields: dict[str, Any],
) -> dict[str, Any]:
    """Validate extracted values without changing their original values or evidence."""
    try:
        definition = SchemaDefinition.model_validate(schema_definition)
    except ValidationError:
        return {
            "status": "unavailable",
            "fields": [],
            "unlisted_extracted_fields": sorted(extracted_fields),
        }

    field_results: list[dict[str, Any]] = []
    has_invalid = False
    for schema_field in definition.fields:
        spec = schema_field.model_dump(mode="json")
        extracted = extracted_fields.get(spec["id"])
        value = extracted.get("value") if isinstance(extracted, dict) else None
        if value is None:
            missing_status = "missing_required" if spec["required"] else "missing_optional"
            has_invalid = has_invalid or spec["required"]
            field_results.append({
                "field_id": spec["id"],
                "label": spec["label"],
                "status": missing_status,
                "required": spec["required"],
                "value": None,
                "source": extracted,
            })
            continue

        normalized_value, normalization_method = _normalize_schema_value(value, spec)
        valid = _matches_type(normalized_value, spec["data_type"]) and _valid_constraints(
            normalized_value, spec
        )
        field_results.append({
            "field_id": spec["id"],
            "label": spec["label"],
            "status": "valid" if valid else "invalid",
            "required": spec["required"],
            "value": value,
            "raw_value": extracted.get("raw_value", value),
            "normalized_value": normalized_value,
            "normalization_method": normalization_method,
            "source": extracted,
        })
        has_invalid = has_invalid or not valid

    return {
        "status": "invalid" if has_invalid else "valid",
        "fields": field_results,
        "unlisted_extracted_fields": sorted(set(extracted_fields) - {
            field.id for field in definition.fields
        }),
    }


def resolve_document_schema(
    db: Session,
    document_type_id: str,
    filename: str,
    application_category: str | None = None,
) -> tuple[dict[str, Any], DocumentSchemaVersion | None]:
    document_type = db.query(DocumentType).filter(DocumentType.id == document_type_id).first()
    if document_type is None:
        return {
            "status": "unknown_type",
            "document_type_id": document_type_id,
            "reason": "The selected document type is not present in the registry.",
        }, None
    if document_type.status != "active":
        return {
            "status": "inactive_type",
            "document_type_id": document_type.id,
            "registry_status": document_type.status,
            "reason": "The selected document type is not active.",
        }, None
    application_categories = document_type.application_categories or []
    if application_categories and (
        application_category is None
        or application_category.casefold() not in {
            category.casefold() for category in application_categories
        }
    ):
        return {
            "status": "not_applicable",
            "document_type_id": document_type.id,
            "registry_status": document_type.status,
            "reason": "The document type is not configured for this application category.",
        }, None

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in (document_type.supported_file_formats or []):
        return {
            "status": "unsupported_format",
            "document_type_id": document_type.id,
            "registry_status": document_type.status,
            "reason": "The file format is not supported by this document type.",
        }, None

    version = (
        db.query(DocumentSchemaVersion)
        .filter(
            DocumentSchemaVersion.document_type_id == document_type.id,
            DocumentSchemaVersion.status == "active",
        )
        .order_by(DocumentSchemaVersion.activated_at.desc(), DocumentSchemaVersion.id.desc())
        .first()
    )
    if version is None:
        return {
            "status": "unavailable",
            "document_type_id": document_type.id,
            "registry_status": document_type.status,
            "reason": "No active schema version is available for this document type.",
        }, None
    return {
        "status": "ready",
        "document_type_id": document_type.id,
        "schema_version_id": version.id,
        "schema_version": version.schema_version,
        "registry_status": document_type.status,
    }, version


def validate_document_schema(
    context: dict[str, Any],
    version: DocumentSchemaVersion | None,
    extracted_fields: dict[str, Any],
    processing_status: str,
) -> dict[str, Any]:
    if processing_status in {"failed", "empty", "unreadable", "ocr_unavailable"}:
        return {
            "status": "blocked",
            "document_type_id": context.get("document_type_id"),
            "schema_version_id": context.get("schema_version_id"),
            "schema_version": context.get("schema_version"),
            "schema_resolution_status": context["status"],
            "reason": (
                f"Document processing status is '{processing_status}'; "
                "schema validation was not performed."
            ),
            "fields": [],
            "unlisted_extracted_fields": sorted(extracted_fields),
            "human_review_required": True,
            "disclaimer": "Schema status is not a determination of authenticity or regulatory compliance.",
        }
    if context["status"] != "ready":
        return {
            **context,
            "fields": [],
            "unlisted_extracted_fields": sorted(extracted_fields),
            "human_review_required": True,
            "disclaimer": "Schema status is not a determination of authenticity or regulatory compliance.",
        }
    if processing_status in {"pending", "processing"}:
        return {
            **context,
            "status": "pending",
            "reason": f"Document processing status is '{processing_status}'; schema validation is incomplete.",
            "fields": [],
            "unlisted_extracted_fields": sorted(extracted_fields),
            "human_review_required": True,
            "disclaimer": "Schema status is not a determination of authenticity or regulatory compliance.",
        }
    if version is None:
        return {
            "status": "unavailable",
            "document_type_id": context["document_type_id"],
            "fields": [],
            "unlisted_extracted_fields": sorted(extracted_fields),
            "human_review_required": True,
            "disclaimer": "Schema status is not a determination of authenticity or regulatory compliance.",
        }

    result = validate_extracted_fields(version.definition, extracted_fields)
    if processing_status == "partial":
        return {
            **context,
            **result,
            "data_shape_status": result["status"],
            "status": "partial",
            "reason": "Extraction was partial; available field values were checked and require human review.",
            "human_review_required": True,
            "disclaimer": "Partial schema validation does not establish document authenticity or regulatory compliance.",
        }
    return {
        **context,
        **result,
        "human_review_required": True,
        "disclaimer": "Schema validation checks data shape only; it does not establish document authenticity or regulatory compliance.",
    }
