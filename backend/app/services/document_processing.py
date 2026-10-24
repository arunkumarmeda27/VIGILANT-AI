import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import pytesseract
from PIL import Image
from pypdf import PdfReader
from pytesseract import Output


class DocumentProcessingError(Exception):
    pass


class DocumentLimitError(DocumentProcessingError):
    pass


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    method: str
    confidence: float | None


_DATE = r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
_MAX_OCR_PIXELS = 20_000_000
_FIELD_PATTERNS = {
    "institution_name": re.compile(
        r"^(?:issuing\s+)?institution(?:\s+name)?\s*[:\-]\s*(.+?)\s*$",
        re.IGNORECASE,
    ),
    "certificate_number": re.compile(
        r"^(?:certificate|registration|reference)\s*(?:number|no\.?|#|id)\s*[:\-]\s*([A-Z0-9][A-Z0-9/_-]{1,})\s*$",
        re.IGNORECASE,
    ),
    "issue_date": re.compile(
        rf"^(?:issue\s+date|date\s+of\s+issue|issued\s+on)\s*[:\-]\s*({_DATE})\b",
        re.IGNORECASE,
    ),
    "expiry_date": re.compile(
        rf"^(?:expiry\s+date|expiration\s+date|valid\s+until|valid\s+through|expires\s+on)\s*[:\-]\s*({_DATE})\b",
        re.IGNORECASE,
    ),
}


def _ocr_page(document: fitz.Document, page_number: int, timeout: int) -> tuple[str, float | None]:
    page = document.load_page(page_number)
    pixmap = page.get_pixmap(dpi=150, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    result = pytesseract.image_to_data(
        image,
        output_type=Output.DICT,
        timeout=timeout,
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for index, (text, raw_confidence) in enumerate(zip(result["text"], result["conf"])):
        word = text.strip()
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            continue
        if word and confidence >= 0:
            line_key = (
                int(result["block_num"][index]),
                int(result["par_num"][index]),
                int(result["line_num"][index]),
            )
            lines.setdefault(line_key, []).append(word)
            confidences.append(confidence)
    confidence = sum(confidences) / len(confidences) / 100 if confidences else None
    text = "\n".join(" ".join(words) for words in lines.values())
    return text, confidence


def _extract_fields(pages: list[PageText]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {
        name: {
            "value": None,
            "page": None,
            "evidence": None,
            "confidence": None,
            "status": "missing",
        }
        for name in _FIELD_PATTERNS
    }
    for page in pages:
        for line in page.text.splitlines():
            normalized_line = " ".join(line.split())
            for field_name, pattern in _FIELD_PATTERNS.items():
                if fields[field_name]["value"] is not None:
                    continue
                match = pattern.match(normalized_line)
                if match:
                    fields[field_name] = {
                        "value": match.group(1).strip(),
                        "page": page.number,
                        "evidence": normalized_line[:500],
                        "confidence": page.confidence,
                        "status": "extracted",
                    }
    return fields


def process_pdf(
    path: Path,
    *,
    max_file_size: int,
    max_pages: int,
    max_seconds: int,
    max_text_chars: int,
    ocr_page_timeout: int,
    tesseract_cmd: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        if not path.is_file():
            raise DocumentProcessingError("Stored PDF is unavailable")
        if path.stat().st_size > max_file_size:
            raise DocumentLimitError("PDF exceeds the processing file size limit")

        reader = PdfReader(str(path), strict=False)
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise DocumentLimitError(f"PDF exceeds the {max_pages}-page processing limit")

        try:
            rendered_pdf = fitz.open(path)
        except Exception as exc:
            raise DocumentProcessingError("PDF could not be opened for page rendering") from exc

        pages: list[PageText] = []
        warnings: list[str] = []
        ocr_needed = False
        text_chars_used = 0
        ocr_available = bool(tesseract_cmd or shutil.which("tesseract"))
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        with rendered_pdf:
            if rendered_pdf.page_count != page_count:
                raise DocumentProcessingError("PDF page count could not be verified")
            for index, pdf_page in enumerate(reader.pages):
                if time.monotonic() - started > max_seconds:
                    raise DocumentLimitError("PDF processing exceeded its time limit")

                extracted = pdf_page.extract_text(extraction_mode="plain") or ""
                remaining_text_chars = max_text_chars - text_chars_used
                if len(extracted) > remaining_text_chars:
                    extracted = extracted[:remaining_text_chars]
                    warnings.append("Extracted text was truncated at the configured limit")
                text_chars_used += len(extracted)

                if len(extracted.strip()) < 40:
                    ocr_needed = True
                    if ocr_available:
                        rendered_page = rendered_pdf.load_page(index)
                        pixel_count = (
                            rendered_page.rect.width
                            * rendered_page.rect.height
                            * (150 / 72) ** 2
                        )
                        if pixel_count > _MAX_OCR_PIXELS:
                            raise DocumentLimitError("PDF page exceeds the OCR rendering size limit")
                        remaining = max_seconds - (time.monotonic() - started)
                        if remaining <= 0:
                            raise DocumentLimitError("PDF processing exceeded its time limit")
                        timeout = max(1, min(ocr_page_timeout, int(remaining)))
                        try:
                            ocr_text, confidence = _ocr_page(rendered_pdf, index, timeout)
                        except pytesseract.TesseractNotFoundError as exc:
                            ocr_available = False
                            warnings.append("Tesseract OCR is not installed or configured")
                            pages.append(PageText(index + 1, extracted, "text", None))
                            continue
                        except RuntimeError as exc:
                            if "timeout" in str(exc).lower():
                                raise DocumentLimitError("OCR exceeded its per-page time limit") from exc
                            raise DocumentProcessingError("OCR could not process a PDF page") from exc
                        except Exception as exc:
                            raise DocumentProcessingError("OCR could not process a PDF page") from exc
                        if ocr_text:
                            remaining_text_chars = max_text_chars - text_chars_used
                            if len(ocr_text) > remaining_text_chars:
                                ocr_text = ocr_text[:remaining_text_chars]
                                warnings.append("Extracted text was truncated at the configured limit")
                            extracted = ocr_text
                            text_chars_used += len(extracted)
                        pages.append(PageText(index + 1, extracted, "ocr", confidence))
                    else:
                        pages.append(PageText(index + 1, extracted, "text", None))
                else:
                    pages.append(PageText(index + 1, extracted, "text", None))

        has_text = any(page.text.strip() for page in pages)
        if ocr_needed and not ocr_available:
            processing_status = "ocr_unavailable"
            warnings.append("Scanned pages were not OCR processed; install and configure Tesseract to extract their text")
        else:
            processing_status = "completed"
            if not has_text:
                warnings.append("No extractable text was found in the PDF")

        methods = {page.method for page in pages if page.text.strip()}
        extraction_method = (
            "mixed" if methods == {"text", "ocr"}
            else "ocr" if methods == {"ocr"}
            else "text" if methods == {"text"}
            else "none"
        )
        if time.monotonic() - started > max_seconds:
            raise DocumentLimitError("PDF processing exceeded its time limit")
        return {
            "processing_status": processing_status,
            "extraction_method": extraction_method,
            "pages_processed": len(pages),
            "fields": _extract_fields(pages),
            "warnings": list(dict.fromkeys(warnings)),
        }
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError("PDF is malformed or could not be processed") from exc
