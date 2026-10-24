import argparse
import re
from pathlib import Path

from src.retrieval_engine import AICTERetriever, DATA_PATH


MINIMUM_RELEVANCE_SCORE = 0.10

_MAXIMUM_DURATION = re.compile(
    r"\bat least equal to maximum\s+duration of the program\s*/\s*course\b",
    re.IGNORECASE,
)
_FIVE_YEAR_DURATION = re.compile(
    r"\bat least live lease of 5 years duration of programs\b",
    re.IGNORECASE,
)


class ComplianceAnswerGenerator:
    """Build citation-first answers from retrieved source text, without paraphrasing."""

    def __init__(self, retriever=None, minimum_relevance_score=MINIMUM_RELEVANCE_SCORE):
        if minimum_relevance_score < 0:
            raise ValueError("minimum_relevance_score must be non-negative")
        self.retriever = retriever or AICTERetriever()
        self.minimum_relevance_score = minimum_relevance_score

    def generate_answer(self, question, top_k=5):
        if not question or not question.strip():
            raise ValueError("Please enter a question.")

        results = self.retriever.search(question, top_k=top_k)
        relevant_results = [
            result for result in results
            if float(result.get("score", 0)) >= self.minimum_relevance_score
        ]
        if not relevant_results:
            return {
                "question": question,
                "status": "insufficient_evidence",
                "answer": "The available retrieved passages do not establish an answer to this question.",
                "evidence": [],
                "warnings": [],
            }

        evidence = self._collect_evidence(relevant_results)
        warnings = self._lease_duration_warnings(evidence)
        return {
            "question": question,
            "status": "source_evidence_found",
            "answer": (
                "The passages below are direct handbook text retrieved for this question. "
                "Conditions, exceptions, and scope are preserved. Neighboring passages are "
                "context only; no additional applicability or requirements have been inferred."
            ),
            "evidence": evidence,
            "warnings": warnings,
        }

    @staticmethod
    def _citation(passage):
        def plain_scalar(value):
            return value.item() if hasattr(value, "item") else value

        return {
            "source_document": passage["source_document"],
            "pdf_page": plain_scalar(passage["pdf_page"]),
            "printed_handbook_page": plain_scalar(passage["printed_handbook_page"]),
            "chunk_id": passage["chunk_id"],
        }

    def _collect_evidence(self, results):
        evidence = []
        seen_chunks = set()

        def add(passage, evidence_type, score=None):
            chunk_id = str(passage["chunk_id"])
            if chunk_id in seen_chunks:
                return
            seen_chunks.add(chunk_id)
            source_text = str(passage["text"])
            matched_passage = str(passage.get("matched_passage", "")).strip()
            evidence.append({
                "text": matched_passage or source_text,
                "source_text": source_text,
                "evidence_type": "matched_passage" if matched_passage else evidence_type,
                "retrieval_score": score,
                "citation": self._citation(passage),
            })

        for result in results:
            add(result, "retrieved_chunk", float(result["score"]))
        for result in results:
            for context in result.get("context_chunks", []):
                add(context, "neighbor_context")
        return evidence

    @staticmethod
    def _lease_duration_warnings(evidence):
        maximum_statement = None
        five_year_statement = None
        for item in evidence:
            text = item["source_text"]
            if maximum_statement is None and _MAXIMUM_DURATION.search(text):
                maximum_statement = item["citation"]
            if five_year_statement is None and _FIVE_YEAR_DURATION.search(text):
                five_year_statement = item["citation"]

        if maximum_statement is None or five_year_statement is None:
            return []
        return [{
            "code": "ambiguous_live_lease_duration",
            "message": (
                "The retrieved passages use different live-lease duration wording. "
                "They are shown separately and are not reconciled; human review is required."
            ),
            "citations": [maximum_statement, five_year_statement],
        }]


def _print_answer(answer):
    print(f"Question: {answer['question']}")
    print(f"\n{answer['answer']}")
    for index, item in enumerate(answer["evidence"], 1):
        citation = item["citation"]
        if item["evidence_type"] == "neighbor_context":
            print(f"\n[{index}] Neighboring source context (scope not inferred)")
        elif item["evidence_type"] == "matched_passage":
            print(f"\n[{index}] Matched numbered passage")
        else:
            print(f"\n[{index}] Direct retrieval result")
        print(item["text"])
        print(
            "Source: {source_document} | PDF page: {pdf_page} | "
            "Printed handbook page: {printed_handbook_page} | Chunk: {chunk_id}".format(
                **citation
            )
        )
        if item["text"] != item["source_text"]:
            print("Full source chunk:")
            print(item["source_text"])
    for warning in answer["warnings"]:
        print(f"\nHuman review: {warning['message']}")
        for citation in warning["citations"]:
            print(
                "Source: {source_document} | PDF page: {pdf_page} | "
                "Printed handbook page: {printed_handbook_page} | Chunk: {chunk_id}".format(
                    **citation
                )
            )


def main():
    parser = argparse.ArgumentParser(
        description="Generate a citation-first answer from AICTE handbook passages."
    )
    parser.add_argument("question", nargs="+", help="Regulatory question to search.")
    parser.add_argument("--data", type=Path, default=DATA_PATH, help="Path to source chunks CSV.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of retrieval results to use.")
    args = parser.parse_args()

    generator = ComplianceAnswerGenerator(AICTERetriever(args.data))
    _print_answer(generator.generate_answer(" ".join(args.question), top_k=args.top_k))


if __name__ == "__main__":
    main()