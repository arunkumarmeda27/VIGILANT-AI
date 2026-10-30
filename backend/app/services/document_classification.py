"""Registry-backed, deterministic document type suggestions."""

import re
from typing import Any

from app.services.document_processing import PageText


CLASSIFIER_NAME = "registry_alias_matcher"
CLASSIFIER_VERSION = "1"


def _contains_phrase(text: str, phrase: str) -> bool:
    escaped = re.escape(phrase.strip().casefold())
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text.casefold()))


def classify_document_text(
    pages: list[PageText],
    registered_types: list[dict[str, Any]],
) -> dict[str, Any]:
    """Suggest a registered type from text aliases without changing the selected type."""
    extracted_text = "\n".join(page.text for page in pages if page.text.strip())
    base_result = {
        "classifier": CLASSIFIER_NAME,
        "classifier_version": CLASSIFIER_VERSION,
        "score_kind": "heuristic_match_ratio",
        "human_review_required": True,
    }
    if not extracted_text.strip():
        return {
            **base_result,
            "status": "needs_review",
            "candidate_document_type": None,
            "candidate_alternatives": [],
            "heuristic_score": None,
            "registry_status": None,
            "schema_version_id": None,
            "match_strength": "none",
            "abstention_reason": "insufficient_text",
            "evidence": [],
            "explanation": "No text was extracted; assign or confirm the document type manually.",
        }

    matches: list[dict[str, Any]] = []
    for registered_type in registered_types:
        type_id = registered_type.get("id")
        if not isinstance(type_id, str) or not type_id:
            continue
        aliases = registered_type.get("aliases")
        aliases = aliases if isinstance(aliases, list) else []
        display_name = registered_type.get("display_name")
        phrases = list(dict.fromkeys(
            phrase.strip()
            for phrase in [*aliases, display_name, type_id.replace("_", " ")]
            if isinstance(phrase, str) and phrase.strip()
        ))
        matched = [
            {"signal": phrase, "page": page.number, "excerpt": line[:300]}
            for phrase in phrases
            for page in pages
            for line in page.text.splitlines()
            if _contains_phrase(line, phrase)
        ]
        if matched:
            matches.append({
                "document_type": registered_type,
                "signals": matched,
                "unique_signal_count": len({item["signal"].casefold() for item in matched}),
                "signal_count": max(1, len(phrases)),
            })

    if not matches:
        return {
            **base_result,
            "status": "needs_review",
            "candidate_document_type": None,
            "candidate_alternatives": [],
            "heuristic_score": None,
            "registry_status": None,
            "schema_version_id": None,
            "match_strength": "none",
            "abstention_reason": "unknown_document_type",
            "evidence": [],
            "explanation": "No active or draft registry type matched the extracted text; manual type selection is required.",
        }

    matches.sort(
        key=lambda item: (
            item["unique_signal_count"],
            len(item["signals"]),
            item["document_type"].get("id", ""),
        ),
        reverse=True,
    )
    best = matches[0]
    best_rank = (best["unique_signal_count"], len(best["signals"]))
    tied = [
        item for item in matches
        if (item["unique_signal_count"], len(item["signals"])) == best_rank
    ]
    if len(tied) > 1:
        return {
            **base_result,
            "status": "needs_review",
            "candidate_document_type": None,
            "candidate_alternatives": [
                item["document_type"]["id"] for item in tied
            ],
            "heuristic_score": None,
            "registry_status": None,
            "schema_version_id": None,
            "match_strength": "possible",
            "abstention_reason": "ambiguous_match",
            "evidence": [
                {
                    **signal,
                    "document_type": item["document_type"]["id"],
                }
                for item in tied
                for signal in item["signals"]
            ],
            "explanation": "Extracted text matches multiple registry types equally; reviewer classification is required.",
        }

    registry_type = best["document_type"]
    registry_status = registry_type.get("status", "unknown")
    score = best["unique_signal_count"] / best["signal_count"]
    strength = "strong" if best["unique_signal_count"] >= 2 else "possible"
    if registry_status != "active":
        status_value = "needs_review"
        abstention_reason = "inactive_registry_type"
        explanation = (
            f"Text matched inactive registry type '{registry_type['id']}'; it cannot be selected automatically."
        )
    elif best["unique_signal_count"] < 2:
        status_value = "needs_review"
        abstention_reason = "low_confidence"
        explanation = (
            f"Text matched one configured signal for '{registry_type['id']}'; reviewer confirmation is required."
        )
    else:
        status_value = "classified"
        abstention_reason = None
        explanation = (
            f"Text matched {best['unique_signal_count']} configured registry aliases for "
            f"'{registry_type['id']}'. This is a type suggestion only; its heuristic score is not "
            "a calibrated probability, and it must be confirmed against the document."
        )
    return {
        **base_result,
        "status": status_value,
        "candidate_document_type": registry_type["id"],
        "candidate_alternatives": [],
        "heuristic_score": round(score, 4),
        "registry_status": registry_status,
        "schema_version_id": registry_type.get("active_schema_version_id"),
        "match_strength": strength,
        "abstention_reason": abstention_reason,
        "evidence": [
            {**signal, "document_type": registry_type["id"]}
            for signal in best["signals"]
        ],
        "explanation": explanation,
    }
