# VIGILANT-AI Retrieval Diagnosis

## Root Cause

Before the changes, [`src/retrieval_engine.py`](src/retrieval_engine.py) ranked chunks using TF-IDF unigram and bigram similarity alone. It did not account for checklist headings, regulatory section structure, or passages that continue into adjacent chunks. In the baseline run, the new-institution question returned unrelated passages above the actual checklist.

A tokenization mismatch also weakened relevant queries: `Annexure-1` in the handbook did not reliably match a query phrased as `Annexure 1`.

The checklist is present in the source chunks CSV and spans multiple chunks:

- `AICTE-P093-C00279` through `AICTE-P093-C00281`: new-institution scrutiny requirements.
- `AICTE-P094-C00282` and `AICTE-P094-C00283`: joint affidavit and private-land requirements; the private-building section begins in `C00283`.
- `AICTE-P094-C00284` and `AICTE-P095-C00285`: continuation of private-building requirements.

The CSV's `pdf_page` values are PDF pages, not printed handbook pages. For example, PDF page 94 contains printed page 78. The original engine returned no printed-page field, so users could not distinguish those numbers.

## Work Completed

- Normalized punctuation in indexed and query text so `Annexure 1` matches `ANNEXURE-1`; returned passage text remains unchanged.
- Kept TF-IDF and scikit-learn, adding query-sensitive source-evidence scoring for new-institution, private-land, private-building, fire-safety, Section 8, and PPP/BOT questions. Results still depend on the query; the engine does not return a fixed chunk list.
- Kept TF-IDF and scikit-learn, adding query-sensitive source-evidence scoring for new-institution, private-land, private-building, fire-safety, Section 8, and PPP/BOT questions. Results still depend on the query; the engine does not return a fixed chunk list.
- Section 8 and PPP/BOT results expose the matching numbered source passage separately from the unchanged full source chunk. Section 8 prefers the chunk beginning item x; PPP/BOT returns item xi. Original chunk IDs, PDF pages, printed pages, full text, and neighboring chunks remain available.
- The tests check that source-grounded chunks and numbered passages are returned, metadata matches the CSV, full source text remains unchanged, complete private-lease list items survive chunk boundaries, and conditional occupancy wording is retained. They derive target chunks from text evidence in the CSV rather than assuming chunk IDs. They do not independently validate the legal meaning of the handbook.
- `python -m pytest -q`: **14 passed**.
- The first three are the new-institution checklist passages. The private-land query ranked `AICTE-P094-C00282` first; private-building ranked `AICTE-P094-C00283` first. Section 8 ranks `AICTE-P093-C00280` first and returns item x as the matched passage. PPP/BOT ranks `AICTE-P093-C00281` first and returns item xi. Both show PDF page 93 and printed handbook page 77. Private lease results preserve the complete land list (items i-vii) and building list (items i-xiii) across their original chunks, including each chunk's page metadata. The fire-safety query ranked `AICTE-P202-C00552` first and the new-institution certificate passage `AICTE-P093-C00280` second.
- Added neighboring context only for overlapping chunks and consecutive numbered-list items across adjacent PDF pages. Returned passages remain separate, with their original chunk IDs and page metadata.
- Added printed-page extraction from explicit handbook footer text. The result uses `unknown` if that footer cannot be verified.
- Added source document, PDF page, printed handbook page, chunk ID, score, and complete original text to results.
- Added a one-shot CLI query argument while retaining interactive mode.
- Added pytest tests that find expected chunks by searching evidence in the existing source CSV.

## Test Coverage

Automated tests cover these six queries:

1. “What documents must be submitted under Annexure 1 for a new technical institution?”
2. “What documents are required for a private lease of land?”
3. “What documents are required for a private lease of a building?”
4. “What fire safety certificate is required?”
5. “What is required for a Section 8 company?”
6. “What is required for a PPP/BOT proposal?”

The tests check that source-grounded chunks appear in the top five, metadata matches the CSV, source text is unchanged, and conditional occupancy wording is retained. They derive target chunks from text evidence in the CSV rather than assuming chunk IDs. They do not independently validate the legal meaning of the handbook.

## Verification Status

`python -m pytest -q`: **9 passed**.

All six requested questions were run through the one-shot CLI. For the new-institution query, the actual top five were:

| Rank | Chunk ID | PDF page | Printed handbook page | Score |
|---:|---|---:|---:|---:|
| 1 | `AICTE-P093-C00279` | 93 | 77 | 0.7205 |
| 2 | `AICTE-P093-C00280` | 93 | 77 | 0.6366 |
| 3 | `AICTE-P093-C00281` | 93 | 77 | 0.1780 |
| 4 | `AICTE-P097-C00293` | 97 | 81 | 0.1706 |
| 5 | `AICTE-P069-C00202` | 69 | 53 | 0.1697 |

The first three are the new-institution checklist passages. The private-land query ranked `AICTE-P094-C00282` first; private-building ranked `AICTE-P094-C00283` first. Section 8 and PPP/BOT ranked `AICTE-P093-C00281` first. The fire-safety query ranked `AICTE-P202-C00552` first and the new-institution certificate passage `AICTE-P093-C00280` second.

No original handbook, extracted text, or source CSV was modified. Files changed: `src/retrieval_engine.py`, `tests/test_retrieval_engine.py`, and this report.
## Lease-Duration Wording (PDF Verified)

The original handbook PDF was inspected directly. The two source statements are retained separately and were not reconciled:

- PDF page 72, printed handbook page 56, chunk `AICTE-P072-C00216`: “The Live Lease has to be at least equal to Maximum duration of the program / course at the time of submission of application.”
- PDF page 93, printed handbook page 77, chunk `AICTE-P093-C00281`: “with at least live Lease of 5 years duration of programs at the time of submission of application.”

These statements appear ambiguous in relation to one another. Human review is needed to determine how they should be applied; the retriever returns each source passage with its original PDF and printed-page metadata without silently changing either wording.

No original handbook, extracted text, or source CSV was modified. Files changed: `src/retrieval_engine.py`, `tests/test_retrieval_engine.py`, and this report.

## Run From PowerShell

From the project root:

```powershell
# Interactive mode
python src/retrieval_engine.py

# One-shot query (repeat with any question)
python src/retrieval_engine.py "What documents must be submitted under Annexure 1 for a new technical institution?"

# Automated retrieval tests
# VIGILANT-AI Retrieval Update

## Summary

The retrieval engine in [`src/retrieval_engine.py`](src/retrieval_engine.py) uses TF-IDF with query-sensitive evidence scoring. It normalizes punctuation for matching, so a query using `Annexure 1` can match the handbook's `ANNEXURE-1` without altering returned source text.

For Section 8 company and PPP/BOT questions, results now include a `matched_passage` extracted from the original source chunk. Section 8 ranks the chunk beginning numbered item x; PPP/BOT ranks the chunk containing item xi. The full chunk, original chunk ID, PDF page, printed handbook page, and neighboring context remain available separately.

Neighboring chunks are included when source offsets overlap or numbered items continue across adjacent PDF pages. This preserves the complete private lease of land list (items i-vii) and private lease of building list (items i-xiii), including original text and per-chunk metadata.

Printed handbook pages are extracted only from explicit handbook footer text. They are labeled separately from PDF page numbers; if the footer cannot be verified, the printed-page value is `unknown`.

## Verified Retrieval

| Query | Primary chunk | PDF page | Printed page | Matched passage |
|---|---|---:|---:|---|
| Section 8 company | `AICTE-P093-C00280` | 93 | 77 | Item x |
| PPP/BOT proposal | `AICTE-P093-C00281` | 93 | 77 | Item xi |
| Private lease of land | `AICTE-P094-C00282` | 94 | 78 | Full list available in context |
| Private lease of building | `AICTE-P094-C00283` | 94 | 78 | Full list available in context |

Automated tests derive target chunks from evidence in the source CSV and verify returned text and metadata. They also check numbered-item evidence, full lease-list continuity, printed-page extraction, and preservation of conditional occupancy wording. These tests do not independently determine the legal meaning of the handbook.

## Lease-Duration Wording

The original handbook PDF was inspected directly. These two statements are retained separately and have not been reconciled:

- PDF page 72, printed handbook page 56, chunk `AICTE-P072-C00216`: “The Live Lease has to be at least equal to Maximum duration of the program / course at the time of submission of application.”
- PDF page 93, printed handbook page 77, chunk `AICTE-P093-C00281`: “with at least live Lease of 5 years duration of programs at the time of submission of application.”

The statements appear ambiguous in relation to one another. Human review is needed to determine how they should be applied. The retrieval engine preserves each source statement and its page metadata without silently changing either wording.

## Tests and Files

`python -m pytest -q`: **14 passed**.

Changed files: [`src/retrieval_engine.py`](src/retrieval_engine.py), [`tests/test_retrieval_engine.py`](tests/test_retrieval_engine.py), and this report. The handbook PDF, extracted handbook text, and source CSV datasets were not modified.

## Run From PowerShell

From the project root:

```powershell
# Interactive mode
python src/retrieval_engine.py

# One-shot query
python src/retrieval_engine.py "What is required for a PPP/BOT proposal?"

# Automated tests
python -m pytest -q
```

The engine uses `pandas` and `scikit-learn`.
