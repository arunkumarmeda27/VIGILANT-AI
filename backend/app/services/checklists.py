"""Operator-configurable synthetic document checklists and conservative date parsing."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHECKLIST_PATH = (
    PROJECT_ROOT / "data" / "processed" / "application_checklists.json"
)


class ChecklistConfigError(ValueError):
    """Raised when the synthetic checklist configuration is invalid."""


def load_checklists(path: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    try:
        with (path or DEFAULT_CHECKLIST_PATH).open(encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ChecklistConfigError from exc

    categories = config.get("categories") if isinstance(config, dict) else None
    if not isinstance(categories, dict) or not categories:
        raise ChecklistConfigError("categories must be a non-empty object")
    for category, requirements in categories.items():
        if not isinstance(category, str) or not category or not isinstance(requirements, dict):
            raise ChecklistConfigError("category definitions are invalid")
        for document_type, spec in requirements.items():
            if (
                not isinstance(document_type, str)
                or not document_type
                or not isinstance(spec, dict)
                or not isinstance(spec.get("required_fields"), list)
                or not all(isinstance(field, str) and field for field in spec["required_fields"])
            ):
                raise ChecklistConfigError("document requirements are invalid")
            expiry_field = spec.get("expiry_field")
            if expiry_field is not None and (
                not isinstance(expiry_field, str) or expiry_field not in spec["required_fields"]
            ):
                raise ChecklistConfigError("expiry_field must also be a required field")
    return categories


def parse_unambiguous_date(value: str) -> date | None:
    """Parse ISO dates and numeric dates only where day/month order is unambiguous."""
    normalized = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass

    import re

    match = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", normalized)
    if not match:
        return None
    first, second, year = map(int, match.groups())
    if first > 12 and second <= 12:
        day, month = first, second
    elif second > 12 and first <= 12:
        month, day = first, second
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None
