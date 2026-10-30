import re
from typing import Any, Mapping, Optional
from dataclasses import dataclass

@dataclass
class ComparisonResult:
    field: str
    category: str  # MATCH, POSSIBLE_MISMATCH, INSUFFICIENT_EVIDENCE, NOT_APPLICABLE
    val1: Optional[str]
    val2: Optional[str]
    norm1: Optional[str]
    norm2: Optional[str]
    doc1_id: int
    doc2_id: int
    explanation: str
    human_review_recommended: bool

class ConsistencyService:
    def __init__(self):
        # Define which fields are comparable across documents
        # Format: field_name -> (normalization_fn, meaningful_comparison_bool)
        self.comparable_fields = {
            "institution_name": (self._normalize_text, True),
            "certificate_number": (self._normalize_id, True),
            "issue_date": (self._normalize_date, True),
            "expiry_date": (self._normalize_date, True),
        }

    def _normalize_text(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        # Trim whitespace, normalize repeated spaces, case-insensitive
        normalized = " ".join(text.lower().split())
        # Conservative punctuation normalization (removing common separators)
        normalized = re.sub(r"[,.\-]", " ", normalized)
        return " ".join(normalized.split())

    def _normalize_id(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        # IDs: uppercase, no whitespace or common separators
        return re.sub(r"[\s\-,./]", "", text).upper()

    def _normalize_date(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        # Basic date normalization (trimming/case)
        return " ".join(text.lower().split())

    def compare_fields(self, field_name: str, val1: Any, doc1_id: int, val2: Any, doc2_id: int) -> ComparisonResult:
        if field_name not in self.comparable_fields:
            return ComparisonResult(
                field=field_name,
                category="NOT_APPLICABLE",
                val1=str(val1) if val1 else None,
                val2=str(val2) if val2 else None,
                norm1=None,
                norm2=None,
                doc1_id=doc1_id,
                doc2_id=doc2_id,
                explanation="Field is not configured for cross-document comparison.",
                human_review_recommended=False
            )

        norm_fn, is_meaningful = self.comparable_fields[field_name]

        v1 = val1.get("value") if isinstance(val1, dict) else val1
        v2 = val2.get("value") if isinstance(val2, dict) else val2

        # Handle missing values
        if v1 is None or v2 is None:
            return ComparisonResult(
                field=field_name,
                category="INSUFFICIENT_EVIDENCE",
                val1=str(v1) if v1 else None,
                val2=str(v2) if v2 else None,
                norm1=norm_fn(v1),
                norm2=norm_fn(v2),
                doc1_id=doc1_id,
                doc2_id=doc2_id,
                explanation="One or both documents are missing the required field for comparison.",
                human_review_recommended=True
            )

        n1 = norm_fn(v1)
        n2 = norm_fn(v2)

        if n1 == n2:
            return ComparisonResult(
                field=field_name,
                category="MATCH",
                val1=v1,
                val2=v2,
                norm1=n1,
                norm2=n2,
                doc1_id=doc1_id,
                doc2_id=doc2_id,
                explanation="Extracted values are consistent across documents.",
                human_review_recommended=False
            )

        return ComparisonResult(
            field=field_name,
            category="POSSIBLE_MISMATCH",
            val1=v1,
            val2=v2,
            norm1=n1,
                norm2=n2,
            doc1_id=doc1_id,
            doc2_id=doc2_id,
            explanation=(
                f"Extracted values for {field_name} differ between documents. "
                "This is a discrepancy indicator only; a human reviewer must verify "
                "the source documents. It does not establish which value is correct "
                "or whether either underlying fact is false."
            ),
            human_review_recommended=True
        )
