import argparse
import re
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA_PATH = Path(__file__).resolve().parents[1] / "data/processed/knowledge_base/aicte_source_chunks.csv"

_CHECKLIST_EVIDENCE = (
    "building plan", "affidavit", "resolution", "occupancy certificate",
    "fire safety certificate", "bank manager", "registration document",
    "ownership of land", "private lease deed",
)
_PRIVATE_LAND_EVIDENCE = (
    "land conversion certificate", "title documents of the lessor",
    "encumbrance certificate", "resolution of the trust society company",
    "right to assign the leasehold right", "mortgage of land",
)
_PRIVATE_BUILDING_EVIDENCE = (
    "complete building plan", "occupancy completion certificate",
    "lease deed registered", "land use certificate", "floor plans sections",
    "proof of working capital", "audited statement of accounts",
    "certificate regarding minority status", "detailed project report",
)
_ROMAN_NUMBERS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
    "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11,
    "xii": 12, "xiii": 13,
}


def _normalize(text):
    text = str(text).lower()
    text = re.sub(r"\bannexure\s*[-–—]?\s*1\b", "annexure 1", text)
    text = re.sub(r"\bppp\s*/\s*bot\b", "ppp bot", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _printed_page(text):
    match = re.search(
        r"Approval\s+Process\s+Handbook\s+2024[-–]2027\s+(\d{1,3})\b",
        str(text),
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else "unknown"


def _roman_items(text):
    roman_numbers = {
        "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6,
        "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11,
        "xii": 12, "xiii": 13,
    }
    matches = re.findall(
        r"(?im)^[ \t]*(xiii|xii|xi|viii|vii|vi|iv|iii|ii|ix|x|v|i)[ \t]*\.",
        str(text),
    )
    return [_ROMAN_NUMBERS[item.lower()] for item in matches]


def _numbered_item_passage(text, item_number):
    source_text = str(text)
    pattern = re.compile(
        r"(?im)^[ \t]*(xiii|xii|xi|viii|vii|vi|iv|iii|ii|ix|x|v|i)[ \t]*\."
    )
    matches = list(pattern.finditer(source_text))
    for index, match in enumerate(matches):
        if _ROMAN_NUMBERS[match.group(1).lower()] == item_number:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source_text)
            return source_text[match.start():end].strip()
    if matches and _ROMAN_NUMBERS[matches[0].group(1).lower()] == item_number + 1:
        return source_text[:matches[0].start()].strip()
    return ""


def _classify_query(question):
    query = _normalize(question)
    if "private lease" in query and "building" in query:
        return "private_building"
    if "private lease" in query and "land" in query:
        return "private_land"
    if "fire safety" in query and "certificate" in query:
        return "fire_safety"
    if "section 8" in query and "company" in query:
        return "section_8"
    if ("ppp" in query and "bot" in query) or "ppp bot" in query:
        return "ppp_bot"
    if "new technical institution" in query or (
        "annexure 1" in query and ("document" in query or "submit" in query)
    ):
        return "new_institution"
    return None


class AICTERetriever:
    def __init__(self, data_path=DATA_PATH):
        data_path = Path(data_path)
        if not data_path.is_file():
            raise FileNotFoundError(f"Source chunks CSV not found: {data_path}")

        self.data = pd.read_csv(data_path).fillna("")
        required = {"chunk_id", "source", "pdf_page", "chunk_start_char", "chunk_end_char", "text"}
        missing = required - set(self.data.columns)
        if missing:
            raise ValueError(f"Source chunks CSV is missing required columns: {sorted(missing)}")

        self.data["text"] = self.data["text"].astype(str)
        self._printed_pages = self._build_printed_page_map()
        self._contexts, self._context_groups = self._build_contexts()
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            preprocessor=_normalize,
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
            token_pattern=r"(?u)\b[a-z0-9]+\b",
        )
        self.matrix = self.vectorizer.fit_transform(self.data["text"])

    def _build_contexts(self):
        texts = [str(text) for text in self.data["text"]]
        neighbors = [set() for _ in texts]
        numeric_pages = pd.to_numeric(self.data["pdf_page"], errors="coerce")
        numeric_starts = pd.to_numeric(self.data["chunk_start_char"], errors="coerce")
        numeric_ends = pd.to_numeric(self.data["chunk_end_char"], errors="coerce")
        ordered = sorted(
            range(len(self.data)),
            key=lambda idx: (
                str(self.data.iloc[idx]["source"]),
                numeric_pages.iloc[idx] if pd.notna(numeric_pages.iloc[idx]) else -1,
                numeric_starts.iloc[idx] if pd.notna(numeric_starts.iloc[idx]) else -1,
            ),
        )

        for left, right in zip(ordered, ordered[1:]):
            left_row, right_row = self.data.iloc[left], self.data.iloc[right]
            if str(left_row["source"]) != str(right_row["source"]):
                continue
            left_page, right_page = numeric_pages.iloc[left], numeric_pages.iloc[right]
            same_page_overlap = (
                pd.notna(left_page) and left_page == right_page
                and pd.notna(numeric_starts.iloc[right])
                and pd.notna(numeric_ends.iloc[left])
                and numeric_starts.iloc[right] < numeric_ends.iloc[left]
            )
            page_boundary_list_continuation = False
            if pd.notna(left_page) and pd.notna(right_page) and right_page == left_page + 1:
                left_items = _roman_items(left_row["text"])
                right_items = _roman_items(right_row["text"])
                page_boundary_list_continuation = bool(
                    left_items and right_items and right_items[0] == left_items[-1] + 1
                )
            if same_page_overlap or page_boundary_list_continuation:
                neighbors[left].add(right)
                neighbors[right].add(left)

        groups = []
        for start in range(len(texts)):
            group = set()
            pending = [start]
            while pending:
                current = pending.pop()
                if current in group:
                    continue
                group.add(current)
                pending.extend(neighbors[current] - group)
            groups.append(sorted(group))

        contexts = [
            _normalize("\n".join(texts[member] for member in group))
            for group in groups
        ]
        return contexts, groups

    def _build_printed_page_map(self):
        printed_pages = {}
        for _, row in self.data.iterrows():
            printed = _printed_page(row["text"])
            if printed != "unknown":
                key = (str(row["source"]), str(row["pdf_page"]))
                printed_pages.setdefault(key, set()).add(printed)
        return {
            key: next(iter(values)) if len(values) == 1 else "unknown"
            for key, values in printed_pages.items()
        }

    @staticmethod
    def _intent_bonus(intent, text, context):
        bonus = 0.0
        if intent == "new_institution":
            if "new technical institution" in context and "documents to be uploaded submitted shown" in context:
                bonus += 0.45
            bonus += min(sum(term in text for term in _CHECKLIST_EVIDENCE), 5) * 0.035
        elif intent == "private_land":
            if "private lease of land" in context:
                bonus += 0.28
            bonus += min(sum(term in text for term in _PRIVATE_LAND_EVIDENCE), 4) * 0.055
        elif intent == "private_building":
            if "private lease of building" in context:
                bonus += 0.32
            bonus += min(sum(term in text for term in _PRIVATE_BUILDING_EVIDENCE), 4) * 0.055
        elif intent == "fire_safety":
            if "valid fire safety certificate issued by the competent authority" in text:
                bonus += 0.38
        elif intent == "section_8":
            if "section 8 of the companies act 2013" in text and "not profit making" in text:
                bonus += 0.42
                if re.search(r"\bx in the case of a company established under section 8\b", text):
                    bonus += 0.50
                if "new technical institution" in context and "documents to be uploaded submitted shown" in context:
                    bonus += 0.35
        elif intent == "ppp_bot":
            if "proposal of ppp bot" in text and "allocation of land building funds" in text:
                bonus += 0.42
                if "new technical institution" in context and "documents to be uploaded submitted shown" in context:
                    bonus += 0.35
        return bonus

    def search(self, question, top_k=5):
        if not question or not question.strip():
            raise ValueError("Please enter a question.")
        if top_k <= 0:
            return []

        query_vector = self.vectorizer.transform([question])
        scores = cosine_similarity(query_vector, self.matrix).ravel()
        intent = _classify_query(question)
        if intent:
            for idx, row in self.data.iterrows():
                scores[idx] += self._intent_bonus(
                    intent,
                    _normalize(row["text"]),
                    self._contexts[idx],
                )
        ranked = scores.argsort()[::-1]

        results = []
        relevant_item = {"section_8": 10, "ppp_bot": 11}.get(intent)
        for idx in ranked:
            if scores[idx] <= 0:
                break
            row = self.data.iloc[idx]
            page_key = (str(row["source"]), str(row["pdf_page"]))
            context_chunks = []
            for context_idx in self._context_groups[idx]:
                if context_idx == idx:
                    continue
                context_row = self.data.iloc[context_idx]
                context_key = (str(context_row["source"]), str(context_row["pdf_page"]))
                context_chunks.append({
                    "chunk_id": context_row["chunk_id"],
                    "source_document": context_row["source"],
                    "pdf_page": context_row["pdf_page"],
                    "printed_handbook_page": self._printed_pages.get(context_key, "unknown"),
                    "text": context_row["text"],
                })
            results.append({
                "chunk_id": row["chunk_id"],
                "source": row["source"],
                "source_document": row["source"],
                "pdf_page": row["pdf_page"],
                "printed_handbook_page": self._printed_pages.get(page_key, "unknown"),
                "score": round(float(scores[idx]), 4),
                "text": row["text"],
                "matched_passage": (
                    _numbered_item_passage(row["text"], relevant_item)
                    if relevant_item is not None else ""
                ),
                "context_chunks": context_chunks,
            })
            if len(results) >= top_k:
                break
        return results


def _print_results(results):
    if not results:
        print("No matching passages found. Try different wording.")
        return
    for rank, result in enumerate(results, 1):
        print(f"\n[{rank}] {result['source_document']} | "
              f"PDF page: {result['pdf_page']} | "
              f"Printed handbook page: {result['printed_handbook_page']} | "
              f"Score: {result['score']} | Chunk: {result['chunk_id']}")
        if result["matched_passage"]:
            print("Relevant numbered item:")
            print(result["matched_passage"])
            print("Full source chunk:")
        print("-" * 72)
        print(result["text"])


def main():
    parser = argparse.ArgumentParser(description="Search the AICTE handbook source chunks.")
    parser.add_argument("query", nargs="*", help="Optional one-shot query; omit to use interactive mode.")
    parser.add_argument("--data", type=Path, default=DATA_PATH, help="Path to the source chunks CSV.")
    args = parser.parse_args()

    try:
        retriever = AICTERetriever(args.data)
    except (FileNotFoundError, ValueError, pd.errors.ParserError) as error:
        parser.error(str(error))

    if args.query:
        question = " ".join(args.query)
        try:
            _print_results(retriever.search(question, top_k=5))
        except ValueError as error:
            parser.error(str(error))
        return

    print("VIGILANT-AI | AICTE Handbook Retrieval")
    print("Type a question, or 'exit' to quit.")
    while True:
        question = input("\nQuestion: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        try:
            _print_results(retriever.search(question, top_k=5))
        except ValueError as error:
            print(error)


if __name__ == "__main__":
    main()
