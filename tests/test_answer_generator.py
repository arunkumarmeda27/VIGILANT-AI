import json
import re
from pathlib import Path

import pandas as pd
import pytest

from src.answer_generator import ComplianceAnswerGenerator
from src.retrieval_engine import AICTERetriever


ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = ROOT / "data/processed/knowledge_base/aicte_source_chunks.csv"


@pytest.fixture(scope="module")
def source_frame():
    return pd.read_csv(CHUNKS_PATH).fillna("")


@pytest.fixture(scope="module")
def generator():
    return ComplianceAnswerGenerator(AICTERetriever(CHUNKS_PATH))


def _source_row(frame, evidence):
    for _, row in frame.iterrows():
        normalized = re.sub(r"[^a-z0-9]+", " ", str(row["text"]).lower())
        if all(
            re.sub(r"[^a-z0-9]+", " ", term.lower()).strip() in normalized
            for term in evidence
        ):
            return row
    raise AssertionError(f"No source chunk contains evidence: {evidence}")


def _evidence_for(answer, chunk_id):
    return next(
        item for item in answer["evidence"]
        if item["citation"]["chunk_id"] == chunk_id
    )


def _verified_printed_page(frame, source_row):
    same_page = frame[
        (frame["source"].astype(str) == str(source_row["source"]))
        & (frame["pdf_page"].astype(str) == str(source_row["pdf_page"]))
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


def _assert_citation_matches_source(item, source_row, source_frame):
    citation = item["citation"]
    chunk_id = source_row["chunk_id"] if "chunk_id" in source_row.index else source_row.name
    assert citation["source_document"] == source_row["source"]
    assert str(citation["pdf_page"]) == str(source_row["pdf_page"])
    assert citation["chunk_id"] == chunk_id
    assert citation["printed_handbook_page"] == _verified_printed_page(
        source_frame, source_row
    )
    assert item["source_text"] == source_row["text"]


def test_new_institution_evidence_preserves_conditions_and_citations(
    generator, source_frame
):
    answer = generator.generate_answer(
        "What documents must be submitted under Annexure 1 for a new technical institution?"
    )
    expected = _source_row(
        source_frame,
        ("for the rest, an affidavit", "produced on completion of the building"),
    )
    item = _evidence_for(answer, expected["chunk_id"])

    assert answer["status"] == "source_evidence_found"
    json.dumps(answer)
    assert "as applicable" in re.sub(r"\s+", " ", item["text"]).lower()
    _assert_citation_matches_source(item, expected, source_frame)
    assert item["citation"]["printed_handbook_page"] == 77


@pytest.mark.parametrize(
    "question,evidence,last_text,expected_items",
    [
        (
            "What documents are required for a private lease of land?",
            ("private lease of land", "land conversion certificate"),
            "Mortgage of Land shall not be permissible.",
            7,
        ),
        (
            "What documents are required for a private lease of a building?",
            ("private lease of building", "complete building plan approved"),
            "Buildings constructed by Government Departments before 50 years",
            13,
        ),
    ],
)
def test_private_lease_answer_contains_complete_cited_lists(
    generator, source_frame, question, evidence, last_text, expected_items
):
    answer = generator.generate_answer(question)
    expected = _source_row(source_frame, evidence)
    cited_ids = {item["citation"]["chunk_id"] for item in answer["evidence"]}
    source_rows = source_frame.set_index("chunk_id")
    cited_text = []

    for chunk_id in cited_ids:
        item = _evidence_for(answer, chunk_id)
        source_row = source_rows.loc[chunk_id]
        _assert_citation_matches_source(item, source_row, source_frame)
        cited_text.append(item["text"])

    complete_text = "\n".join(cited_text)
    normalized = re.sub(r"\s+", " ", complete_text).lower()
    roman_values = {
        "i.": 1, "ii.": 2, "iii.": 3, "iv.": 4, "v.": 5, "vi.": 6,
        "vii.": 7, "viii.": 8, "ix.": 9, "x.": 10, "xi.": 11,
        "xii.": 12, "xiii.": 13,
    }
    labels = re.findall(
        r"(?im)^\s*(xiii|xii|xi|viii|vii|vi|iv|iii|ii|ix|x|v|i)\s*\.",
        complete_text,
    )
    item_numbers = {roman_values[f"{label.lower()}."] for label in labels}

    assert answer["status"] == "source_evidence_found"
    assert expected["chunk_id"] in cited_ids
    assert last_text.lower() in normalized
    assert set(range(1, expected_items + 1)).issubset(item_numbers)


@pytest.mark.parametrize(
    "question,evidence,item_number",
    [
        (
            "What is required for a Section 8 company?",
            ("section 8 of the companies act, 2013", "not profit making"),
            "x.",
        ),
        (
            "What is required for a PPP/BOT proposal?",
            ("proposal of ppp/ bot", "allocation of land/ building/ funds"),
            "xi.",
        ),
    ],
)
def test_organization_answers_quote_source_item_with_metadata(
    generator, source_frame, question, evidence, item_number
):
    answer = generator.generate_answer(question)
    expected = _source_row(source_frame, evidence)
    item = _evidence_for(answer, expected["chunk_id"])

    assert answer["status"] == "source_evidence_found"
    assert item_number in item["text"].lower()
    normalized_text = re.sub(r"[^a-z0-9]+", " ", item["text"].lower())
    assert all(
        re.sub(r"[^a-z0-9]+", " ", term.lower()).strip() in normalized_text
        for term in evidence
    )
    _assert_citation_matches_source(item, expected, source_frame)
    assert item["citation"]["printed_handbook_page"] == 77


def test_unrelated_question_reports_insufficient_evidence(generator):
    answer = generator.generate_answer("What is the shield thickness for a lunar colony?")

    assert answer["status"] == "insufficient_evidence"
    assert answer["answer"] == (
        "The available retrieved passages do not establish an answer to this question."
    )
    assert answer["evidence"] == []


def test_lease_duration_wording_is_separate_and_flagged_for_review(
    generator, source_frame
):
    answer = generator.generate_answer(
        "What is the live lease duration requirement for a program?",
        top_k=5,
    )
    maximum = _source_row(
        source_frame,
        ("The Live Lease has to be at least equal to Maximum", "duration of the program / course"),
    )
    five_year = _source_row(
        source_frame,
        ("at least live Lease of 5 years duration of programs",),
    )
    maximum_item = _evidence_for(answer, maximum["chunk_id"])
    five_year_item = _evidence_for(answer, five_year["chunk_id"])

    assert "at least equal to Maximum" in maximum_item["text"]
    assert "at least live Lease of 5 years duration of programs" in five_year_item["text"]
    _assert_citation_matches_source(maximum_item, maximum, source_frame)
    _assert_citation_matches_source(five_year_item, five_year, source_frame)
    assert maximum_item["citation"]["printed_handbook_page"] == 56
    assert five_year_item["citation"]["printed_handbook_page"] == 77
    assert len(answer["warnings"]) == 1
    assert answer["warnings"][0]["code"] == "ambiguous_live_lease_duration"
    assert {
        citation["chunk_id"] for citation in answer["warnings"][0]["citations"]
    } == {maximum["chunk_id"], five_year["chunk_id"]}