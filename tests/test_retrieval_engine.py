import re
from pathlib import Path

import pandas as pd
import pytest

from src.retrieval_engine import AICTERetriever


ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = ROOT / "data/processed/knowledge_base/aicte_source_chunks.csv"

CASES = [
    (
        "What documents must be submitted under Annexure 1 for a new technical institution?",
        ("documents to be uploaded/submitted / shown for setting up a", "new technical institution"),
    ),
    (
        "What documents are required for a private lease of land?",
        ("private lease of land", "land conversion certificate"),
    ),
    (
        "What documents are required for a private lease of a building?",
        ("private lease of building", "complete building plan approved"),
    ),
    (
        "What fire safety certificate is required?",
        ("valid fire safety certificate issued by the competent authority",),
    ),
    (
        "What is required for a Section 8 company?",
        ("section 8 of the companies act, 2013", "not profit making"),
    ),
    (
        "What is required for a PPP/BOT proposal?",
        ("proposal of ppp/ bot", "allocation of land/ building/ funds"),
    ),
]


def _normalized(text):
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _evidence_chunk(frame, evidence):
    for _, row in frame.iterrows():
        normalized = _normalized(row["text"])
        if all(term in normalized for term in evidence):
            return row
    raise AssertionError(f"No source chunk contains the expected source evidence: {evidence}")


def _verified_printed_page(frame, row):
    same_page = frame[
        (frame["source"].astype(str) == str(row["source"]))
        & (frame["pdf_page"].astype(str) == str(row["pdf_page"]))
    ]
    pages = set()
    for text in same_page["text"]:
        match = re.search(
            r"Approval\s+Process\s+Handbook\s+2024[-–]2027\s+(\d{1,3})\b",
            str(text),
            re.IGNORECASE,
        )
        if match:
            pages.add(int(match.group(1)))
    return next(iter(pages)) if len(pages) == 1 else "unknown"


def _roman_item_numbers(text):
    values = {
        "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
        "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11,
        "xii": 12, "xiii": 13,
    }
    labels = re.findall(
        r"(?im)^\s*(xiii|xii|xi|viii|vii|vi|iv|iii|ii|ix|x|v|i)\s*\.",
        str(text),
    )
    return {values[label.lower()] for label in labels}


def _source_row_by_evidence(frame, evidence):
    for _, row in frame.iterrows():
        normalized_text = re.sub(r"[^a-z0-9]+", " ", str(row["text"]).lower())
        if all(
            re.sub(r"[^a-z0-9]+", " ", term.lower()).strip() in normalized_text
            for term in evidence
        ):
            return row
    raise AssertionError(f"No source chunk contains the expected source evidence: {evidence}")


@pytest.fixture(scope="module")
def source_frame():
    return pd.read_csv(CHUNKS_PATH).fillna("")


@pytest.fixture(scope="module")
def retriever():
    return AICTERetriever(CHUNKS_PATH)


@pytest.mark.parametrize("question,evidence", CASES)
def test_source_evidence_ranks_near_top(question, evidence, source_frame, retriever):
    expected = _evidence_chunk(source_frame, evidence)
    results = retriever.search(question, top_k=5)
    result_ids = [result["chunk_id"] for result in results]

    assert expected["chunk_id"] in result_ids, (
        f"Expected source-grounded chunk {expected['chunk_id']} near the top; got {result_ids}"
    )
    result = next(item for item in results if item["chunk_id"] == expected["chunk_id"])
    assert result["source_document"] == expected["source"]
    assert result["source"] == expected["source"]
    assert str(result["pdf_page"]) == str(expected["pdf_page"])
    assert result["text"] == expected["text"]
    assert isinstance(result["score"], float) and result["score"] > 0
    assert result["printed_handbook_page"] == _verified_printed_page(source_frame, expected)


def test_annexure_hyphen_normalization_and_conditional_source_text(retriever, source_frame):
    query = "What documents must be submitted under Annexure 1 for a new technical institution?"
    results = retriever.search(query, top_k=5)
    expected = _evidence_chunk(
        source_frame,
        ("for the rest, an affidavit", "produced on completion of the building"),
    )
    by_id = {result["chunk_id"]: result for result in results}

    assert expected["chunk_id"] in by_id
    assert "as applicable" in _normalized(by_id[expected["chunk_id"]]["text"])
    assert any("ANNEXURE-1" in result["text"] for result in results)


def test_printed_page_is_unknown_without_explicit_footer(tmp_path, source_frame):
    sample = source_frame.iloc[[1]].copy()
    sample["text"] = "A source passage without a printed handbook footer."
    path = tmp_path / "chunks.csv"
    sample.to_csv(path, index=False)

    result = AICTERetriever(path).search("source passage", top_k=1)[0]
    assert result["printed_handbook_page"] == "unknown"


def test_missing_csv_reports_path(tmp_path):
    missing = tmp_path / "missing.csv"
    with pytest.raises(FileNotFoundError, match="Source chunks CSV not found"):
        AICTERetriever(missing)


@pytest.mark.parametrize(
    "question,evidence",
    [
        (
            "What is required for a Section 8 company?",
            (
                "Section 8 of the Companies Act, 2013",
                "not profit making",
            ),
        ),
        (
            "What is required for a PPP/BOT proposal?",
            ("proposal of PPP/ BOT", "allocation of Land/ Building/ funds"),
        ),
    ],
)
def test_organization_queries_rank_annexure_checklist_first(
    question, evidence, source_frame, retriever
):
    expected = _source_row_by_evidence(source_frame, evidence)
    result = retriever.search(question, top_k=1)[0]

    assert result["chunk_id"] == expected["chunk_id"]
    assert str(result["pdf_page"]) == str(expected["pdf_page"])
    assert result["source"] == expected["source"]
    assert result["text"] == expected["text"]
    context = [result, *result["context_chunks"]]
    assert any("ANNEXURE-1" in item["text"] for item in context)
    assert any("New Technical Institution" in item["text"] for item in context)
    full_context = _normalized("\n".join(item["text"] for item in context))
    assert all(_normalized(term) in full_context for term in evidence)
    passage_evidence = (evidence[0],) if "section 8" in question.lower() else evidence
    assert all(
        _normalized(term) in _normalized(result["matched_passage"])
        for term in passage_evidence
    )
    if "section 8" in question.lower():
        assert "section 8 of the companies act" in _normalized(result["matched_passage"])
        assert "proposal of ppp" not in _normalized(result["matched_passage"])
        assert result["matched_passage"].lstrip().lower().startswith("x.")
    else:
        assert set(_roman_item_numbers(result["matched_passage"])) == {11}
    assert result["printed_handbook_page"] == _verified_printed_page(source_frame, expected)


@pytest.mark.parametrize(
    "question,evidence,last_item",
    [
        (
            "What documents are required for a private lease of land?",
            ("private lease of land", "land conversion certificate"),
            "Mortgage of Land shall not be permissible.",
        ),
        (
            "What documents are required for a private lease of a building?",
            ("private lease of building", "complete building plan approved"),
            "Buildings constructed by Government Departments before 50 years",
        ),
    ],
)
def test_private_lease_lists_are_complete_in_original_context(
    question, evidence, last_item, source_frame, retriever
):
    expected = _source_row_by_evidence(source_frame, evidence)
    result = retriever.search(question, top_k=1)[0]
    context_chunks = [result, *result["context_chunks"]]
    source_rows = source_frame.set_index("chunk_id")

    assert result["chunk_id"] == expected["chunk_id"]
    for chunk in context_chunks:
        original = source_rows.loc[chunk["chunk_id"]]
        assert chunk["source_document"] == original["source"]
        assert str(chunk["pdf_page"]) == str(original["pdf_page"])
        assert chunk["text"] == original["text"]

    complete_text = "\n".join(chunk["text"] for chunk in context_chunks)
    assert last_item.lower() in complete_text.lower()
    maximum_item = 7 if "land?" in question else 13
    assert set(range(1, maximum_item + 1)).issubset(_roman_item_numbers(complete_text))


def test_both_lease_duration_statements_remain_distinct_in_search(source_frame, retriever):
    annexure_statement = _source_row_by_evidence(
        source_frame,
        ("at least live Lease of 5 years duration of programs",),
    )
    clause_statement = _source_row_by_evidence(
        source_frame,
        ("The Live Lease has to be at least equal to Maximum", "duration of the program / course"),
    )
    assert str(annexure_statement["pdf_page"]) == "93"
    assert str(clause_statement["pdf_page"]) == "72"

    results = retriever.search("What is the live lease duration requirement for a program?", top_k=20)
    by_id = {result["chunk_id"]: result for result in results}
    for expected in (annexure_statement, clause_statement):
        assert expected["chunk_id"] in by_id
        assert by_id[expected["chunk_id"]]["text"] == expected["text"]
        assert str(by_id[expected["chunk_id"]]["pdf_page"]) == str(expected["pdf_page"])
        assert by_id[expected["chunk_id"]]["source_document"] == expected["source"]
        assert by_id[expected["chunk_id"]]["printed_handbook_page"] == _verified_printed_page(
            source_frame, expected
        )
    assert "at least live lease of 5 years duration of programs" in _normalized(
        by_id[annexure_statement["chunk_id"]]["text"]
    )
    assert "the live lease has to be at least equal to maximum duration of the program / course" in _normalized(
        by_id[clause_statement["chunk_id"]]["text"]
    )
