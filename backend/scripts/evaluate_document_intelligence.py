"""Run small deterministic checks against synthetic digital-PDF samples."""

import json
import tempfile
from pathlib import Path

import fitz

from app.services.document_processing import process_pdf


REGISTERED_TYPES = [{
    "id": "fire_safety_certificate",
    "display_name": "Fire Safety Certificate",
    "aliases": ["Fire Safety Certificate", "Fire Certificate"],
    "status": "active",
    "active_schema_version_id": 7,
}]

SCHEMA = {
    "fields": [
        {
            "id": "issuer_code",
            "label": "Issuer Code",
            "data_type": "string",
            "required": True,
        },
        {
            "id": "license_number",
            "label": "License Number",
            "data_type": "string",
            "required": True,
        },
    ]
}


def create_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 250), text)
    document.save(path)
    document.close()


def process_sample(
    path: Path,
    *,
    schema: dict | None,
    registered_types: list[dict] | None = None,
) -> dict:
    return process_pdf(
        path,
        max_file_size=1_000_000,
        max_pages=5,
        max_seconds=15,
        max_text_chars=20_000,
        ocr_page_timeout=5,
        registered_document_types=(
            REGISTERED_TYPES if registered_types is None else registered_types
        ),
        schema_definition=schema,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vigilant-document-eval-") as directory:
        root = Path(directory)
        known_pdf = root / "synthetic-known-type.pdf"
        unknown_pdf = root / "synthetic-unknown-type.pdf"
        ambiguous_pdf = root / "synthetic-ambiguous-type.pdf"
        create_pdf(
            known_pdf,
            "Fire Safety Certificate\nFire Certificate\n"
            "Certificate Number: FS-001\nIssuer Code: FD-42",
        )
        create_pdf(unknown_pdf, "Unrecognized synthetic supporting record.")
        create_pdf(ambiguous_pdf, "Permit Record\nLicense Record")

        known = process_sample(known_pdf, schema=SCHEMA)
        unknown = process_sample(unknown_pdf, schema=None)
        ambiguous = process_sample(
            ambiguous_pdf,
            schema=None,
            registered_types=[
                {
                    "id": "permit_record",
                    "display_name": "Permit Record Type",
                    "aliases": ["Permit Record"],
                    "status": "active",
                },
                {
                    "id": "license_record",
                    "display_name": "License Record Type",
                    "aliases": ["License Record"],
                    "status": "active",
                },
            ],
        )
        inactive = process_sample(
            known_pdf,
            schema=None,
            registered_types=[{**REGISTERED_TYPES[0], "status": "draft"}],
        )

    classification_checks = [
        (
            known["classification"]["status"] == "classified"
            and known["classification"]["candidate_document_type"]
            == "fire_safety_certificate"
        ),
        (
            unknown["classification"]["status"] == "needs_review"
            and unknown["classification"]["candidate_document_type"] is None
            and unknown["classification"]["abstention_reason"]
            == "unknown_document_type"
        ),
        (
            ambiguous["classification"]["status"] == "needs_review"
            and ambiguous["classification"]["candidate_document_type"] is None
            and set(ambiguous["classification"]["candidate_alternatives"])
            == {"permit_record", "license_record"}
        ),
        (
            inactive["classification"]["status"] == "needs_review"
            and inactive["classification"]["candidate_document_type"]
            == "fire_safety_certificate"
            and inactive["classification"]["abstention_reason"]
            == "inactive_registry_type"
        ),
    ]
    extraction_checks = [
        known["fields"]["certificate_number"]["value"] == "FS-001",
        (
            known["fields"]["issuer_code"]["raw_value"] == "FD-42"
            and known["fields"]["issuer_code"]["page"] == 1
            and known["fields"]["issuer_code"]["evidence"] == "Issuer Code: FD-42"
            and known["fields"]["issuer_code"]["coordinates"] is not None
        ),
        (
            known["fields"]["license_number"]["value"] is None
            and known["fields"]["license_number"]["status"] == "missing"
        ),
    ]
    report = {
        "evaluation_type": "synthetic functional check; not an accuracy benchmark",
        "classification": {
            "passed": sum(classification_checks),
            "total": len(classification_checks),
            "scope": "synthetic functional smoke checks; not accuracy metrics",
        },
        "schema_extraction_smoke_checks": {
            "passed": sum(extraction_checks),
            "total": len(extraction_checks),
            "scope": "synthetic functional smoke checks; not accuracy metrics",
        },
        "ocr": {
            "status": "not_evaluated",
            "reason": "This harness uses embedded digital text and includes no scanned ground-truth corpus.",
        },
    }
    print(json.dumps(report, indent=2))
    if not all(classification_checks) or not all(extraction_checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
