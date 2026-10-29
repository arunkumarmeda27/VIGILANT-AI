"""Conservative, content-based document type suggestions for the demo workflow."""

import json
from pathlib import Path
from typing import Any

from app.services.document_processing import PageText


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CLASSIFICATION_PATH = (
    PROJECT_ROOT / "data" / "processed" / "document_categories.json"
)


class DocumentClassificationConfigError(ValueError):
    """Raised when the operator-maintained category config is invalid."""


def _load_categories(path: Path | None = None) -> list[dict[str, Any]]:
    try:
        with (path or DEFAULT_CLASSIFICATION_PATH).open(encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentClassificationConfigError from exc

    categories = config.get("categories") if isinstance(config, dict) else None
    if not isinstance(categories, list) or not categories:
        raise DocumentClassificationConfigError("categories must be a non-empty list")

    seen: set[str] = set()
    for category in categories:
        if not isinstance(category, dict):
            raise DocumentClassificationConfigError("each category must be an object")
        document_type = category.get("document_type")
        signals = category.get("signals")
        if (
            not isinstance(document_type, str)
            or not document_type.strip()
            or document_type in seen
            or not isinstance(signals, list)
            or not signals
            or not all(isinstance(signal, str) and signal.strip() for signal in signals)
        ):
            raise DocumentClassificationConfigError("category definitions are invalid")
        seen.add(document_type)
    return categories


def classify_document_text(
    pages: list[PageText], *, config_path: Path | None = None
) -> dict[str, Any]:
    """Suggest a type only from configured text signals; never auto-verify a document."""
    categories = _load_categories(config_path)
    matches_by_type: dict[str, list[dict[str, Any]]] = {}

    for category in categories:
        document_type = category["document_type"]
        evidence: list[dict[str, Any]] = []
        seen_signals: set[str] = set()
        for page in pages:
            for line in page.text.splitlines():
                normalized_line = " ".join(line.split())
                folded_line = normalized_line.casefold()
                for signal in category["signals"]:
                    folded_signal = signal.strip().casefold()
                    if folded_signal in folded_line and folded_signal not in seen_signals:
                        seen_signals.add(folded_signal)
                        evidence.append({
                            "page": page.number,
                            "signal": signal,
                            "excerpt": normalized_line[:300],
                        })
        if evidence:
            matches_by_type[document_type] = evidence

    if not matches_by_type:
        return {
            "status": "needs_review",
            "candidate_document_type": None,
            "match_strength": "none",
            "evidence": [],
            "explanation": "No configured category signals were found in extracted text; assign the document type manually.",
        }

    highest = max(len(evidence) for evidence in matches_by_type.values())
    winners = [
        document_type
        for document_type, evidence in matches_by_type.items()
        if len(evidence) == highest
    ]
    if len(winners) != 1:
        return {
            "status": "needs_review",
            "candidate_document_type": None,
            "match_strength": "possible",
            "evidence": [
                {"document_type": name, **match}
                for name in winners
                for match in matches_by_type[name]
            ],
            "explanation": "Extracted text matches multiple configured categories equally; reviewer classification is required.",
        }

    candidate = winners[0]
    evidence = matches_by_type[candidate]
    strength = "strong" if len(evidence) >= 2 else "possible"
    return {
        "status": "classified" if strength == "strong" else "needs_review",
        "candidate_document_type": candidate,
        "match_strength": strength,
        "evidence": evidence,
        "explanation": (
            f"Extracted text matched {len(evidence)} configured signal(s) for '{candidate}'. "
            "This is a type suggestion only; confirm it against the document."
        ),
    }
