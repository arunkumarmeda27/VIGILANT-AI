import re
import shutil
import time
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

import fitz
from PIL import Image
from pypdf import PdfReader

try:
    import pytesseract
    from pytesseract import Output
except ImportError:
    pytesseract = None
    Output = None


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
    regions: tuple[dict[str, Any], ...] = ()


_DATE = r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
FIELD_EXTRACTION_VERSION = 2
OCR_DPI = 150
_MAX_OCR_PIXELS = 20_000_000
_BLANK_PAGE_PREVIEW_PIXELS = 1_000_000
_BLANK_PAGE_MIN_LUMINANCE = 250
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
_FIELD_LABELS = {
    "institution_name": re.compile(
        r"^(?:institution(?:\s+name)?|issuing\s+institution)$", re.IGNORECASE
    ),
    "certificate_number": re.compile(
        r"^(?:certificate|registration|reference)\s*(?:number|no\.?|#|id)$",
        re.IGNORECASE,
    ),
    "issue_date": re.compile(
        r"^(?:issue\s+date|date\s+of\s+issue|issued\s+on)$", re.IGNORECASE
    ),
    "expiry_date": re.compile(
        r"^(?:expiry\s+date|expiration\s+date|valid\s+until|valid\s+through|expires\s+on)$",
        re.IGNORECASE,
    ),
}
_FIELD_VALUE_PATTERNS = {
    "institution_name": re.compile(r"^.{2,200}$"),
    "certificate_number": re.compile(r"^[A-Z0-9][A-Z0-9/_-]{1,}$", re.IGNORECASE),
    "issue_date": re.compile(rf"^{_DATE}$"),
    "expiry_date": re.compile(rf"^{_DATE}$"),
}
_ANY_FIELD_LABEL = re.compile(
    r"^(?:institution(?:\s+name)?|issuing\s+institution|"
    r"(?:certificate|registration|reference)\s*(?:number|no\.?|#|id)|"
    r"issue\s+date|date\s+of\s+issue|issued\s+on|"
    r"expiry\s+date|expiration\s+date|valid\s+until|valid\s+through|expires\s+on)$",
    re.IGNORECASE,
)


def _ocr_page_with_regions(
    document: fitz.Document,
    page_number: int,
    timeout: int,
) -> tuple[str, float | None, tuple[dict[str, Any], ...]]:
    if pytesseract is None or Output is None:
        raise DocumentProcessingError("Tesseract OCR Python package is unavailable")
    page = document.load_page(page_number)
    pixmap = page.get_pixmap(dpi=OCR_DPI, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    result = pytesseract.image_to_data(
        image,
        output_type=Output.DICT,
        timeout=timeout,
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    line_boxes: dict[tuple[int, int, int], list[int]] = {}
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
            if all(key in result for key in ("left", "top", "width", "height")):
                left = int(result["left"][index])
                top = int(result["top"][index])
                right = left + int(result["width"][index])
                bottom = top + int(result["height"][index])
                if line_key not in line_boxes:
                    line_boxes[line_key] = [left, top, right, bottom]
                else:
                    box = line_boxes[line_key]
                    box[0] = min(box[0], left)
                    box[1] = min(box[1], top)
                    box[2] = max(box[2], right)
                    box[3] = max(box[3], bottom)
    confidence = sum(confidences) / len(confidences) / 100 if confidences else None
    text = "\n".join(" ".join(words) for words in lines.values())
    regions = tuple(
        {
            "text": " ".join(lines[key]),
            "coordinates": {
                "x": box[0],
                "y": box[1],
                "width": box[2] - box[0],
                "height": box[3] - box[1],
            },
            "coordinate_space": "rendered_page_pixels",
            "confidence": None,
        }
        for key, box in line_boxes.items()
    )
    return text, confidence, regions


def _ocr_page(document: fitz.Document, page_number: int, timeout: int) -> tuple[str, float | None]:
    text, confidence, _ = _ocr_page_with_regions(document, page_number, timeout)
    return text, confidence


def _digital_text_regions(page: fitz.Page) -> tuple[dict[str, Any], ...]:
    regions = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            boxes = [span["bbox"] for span in spans if span.get("bbox")]
            if not boxes:
                continue
            regions.append({
                "text": text,
                "coordinates": {
                    "x": min(box[0] for box in boxes),
                    "y": min(box[1] for box in boxes),
                    "width": max(box[2] for box in boxes) - min(box[0] for box in boxes),
                    "height": max(box[3] for box in boxes) - min(box[1] for box in boxes),
                },
                "coordinate_space": "pdf_points",
                "confidence": None,
            })
    return tuple(regions)


def _is_uniformly_blank_page(page: fitz.Page) -> bool:
    area = page.rect.width * page.rect.height
    if area <= 0:
        return False
    scale = min(0.25, sqrt(_BLANK_PAGE_PREVIEW_PIXELS / area))
    preview = page.get_pixmap(
        matrix=fitz.Matrix(scale, scale),
        colorspace=fitz.csGRAY,
        alpha=False,
    )
    return all(pixel >= _BLANK_PAGE_MIN_LUMINANCE for pixel in preview.samples)


def _extract_fields(pages: list[PageText]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {
        name: {
            "value": None,
            "page": None,
            "evidence": None,
            "raw_value": None,
            "normalized_value": None,
            "confidence": None,
            "status": "missing",
            "method": None,
            "extractor_version": f"deterministic_label_parser_{FIELD_EXTRACTION_VERSION}",
            "coordinates": None,
        }
        for name in _FIELD_PATTERNS
    }
    for page in pages:
        lines = [" ".join(line.split()) for line in page.text.splitlines()]
        for index, normalized_line in enumerate(lines):
            for field_name, pattern in _FIELD_PATTERNS.items():
                if fields[field_name]["value"] is not None:
                    continue
                match = pattern.match(normalized_line)
                if match:
                    value = match.group(1).strip()
                else:
                    label = _FIELD_LABELS[field_name]
                    next_index = index + 1
                    while next_index < len(lines) and not lines[next_index]:
                        next_index += 1
                    value = (
                        lines[next_index]
                        if label.fullmatch(normalized_line)
                        and next_index < len(lines)
                        and not _ANY_FIELD_LABEL.fullmatch(lines[next_index])
                        and _FIELD_VALUE_PATTERNS[field_name].fullmatch(lines[next_index])
                        else None
                    )
                    if value is not None:
                        normalized_line = f"{normalized_line}: {value}"
                if value:
                    fields[field_name] = {
                        "value": value,
                        "raw_value": value,
                        "normalized_value": None,
                        "page": page.number,
                        "evidence": normalized_line[:500],
                        "confidence": page.confidence,
                        "status": "extracted",
                        "method": page.method,
                        "extractor_version": f"deterministic_label_parser_{FIELD_EXTRACTION_VERSION}",
                        "coordinates": _matching_region(page.regions, normalized_line),
                    }
    return fields


_FIELD_ALIASES = {
    "organization_name": ("institution name", "organization name", "organisation name"),
    "registration_number": ("registration number", "registration no"),
    "application_reference_number": ("application reference number", "application number"),
    "license_number": ("license number", "licence number", "license no", "licence no"),
    "licence_number": ("license number", "licence number", "license no", "licence no"),
    "issuing_authority": ("issuing authority", "issued by", "issuing department"),
    "validity_period": ("validity period", "valid for"),
    "financial_value": ("financial value", "amount", "total amount"),
    "professional_credentials": ("professional credentials", "professional qualification"),
}


def _matching_region(
    regions: tuple[dict[str, Any], ...],
    excerpt: str,
) -> dict[str, Any] | None:
    target = " ".join(excerpt.split()).casefold()
    for region in regions:
        candidate = " ".join(str(region.get("text", "")).split()).casefold()
        if target and (target in candidate or candidate in target):
            return region.get("coordinates")
    return None


def _extract_schema_fields(
    pages: list[PageText],
    schema_definition: dict[str, Any],
    base_fields: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    fields = dict(base_fields)
    schema_fields = schema_definition.get("fields", [])
    for spec in schema_fields:
        field_id = spec.get("id")
        if not isinstance(field_id, str) or fields.get(field_id, {}).get("value") is not None:
            continue
        labels = [
            str(spec.get("label", "")).strip(),
            field_id.replace("_", " "),
            *_FIELD_ALIASES.get(field_id, ()),
        ]
        labels = list(dict.fromkeys(label for label in labels if label))
        patterns = [
            re.compile(rf"^\s*{re.escape(label)}\s*[:\-]\s*(.*?)\s*$", re.IGNORECASE)
            for label in labels
        ]
        bare_labels = [re.compile(rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE) for label in labels]
        found = None
        for page in pages:
            lines = [" ".join(line.split()) for line in page.text.splitlines()]
            for index, line in enumerate(lines):
                matched = next((pattern.match(line) for pattern in patterns if pattern.match(line)), None)
                raw_value = matched.group(1).strip() if matched else None
                evidence = line
                if not raw_value and any(pattern.fullmatch(line) for pattern in bare_labels):
                    next_line = next(
                        (candidate for candidate in lines[index + 1:] if candidate),
                        None,
                    )
                    if next_line and not any(pattern.fullmatch(next_line) for pattern in bare_labels):
                        raw_value = next_line
                        evidence = f"{line}: {next_line}"
                if raw_value:
                    found = {
                        "value": raw_value,
                        "raw_value": raw_value,
                        "normalized_value": None,
                        "page": page.number,
                        "evidence": evidence[:500],
                        "confidence": page.confidence,
                        "status": "extracted",
                        "method": page.method,
                        "extractor_version": f"schema_label_parser_{FIELD_EXTRACTION_VERSION}",
                        "coordinates": _matching_region(page.regions, line),
                    }
                    break
            if found:
                break
        if found:
            fields[field_id] = found
        else:
            fields.setdefault(field_id, {
                "value": None,
                "raw_value": None,
                "normalized_value": None,
                "page": None,
                "evidence": None,
                "confidence": None,
                "status": "missing",
                "method": None,
                "extractor_version": f"schema_label_parser_{FIELD_EXTRACTION_VERSION}",
                "coordinates": None,
            })
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
    registered_document_types: list[dict[str, Any]] | None = None,
    schema_definition: dict[str, Any] | None = None,
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
        ocr_failed = False
        ocr_unavailable = False
        unreadable_pages: list[int] = []
        blank_pages: list[int] = []
        text_chars_used = 0
        configured_tesseract = tesseract_cmd or (shutil.which("tesseract") if pytesseract is not None else None)
        ocr_available = pytesseract is not None and configured_tesseract is not None
        ocr_version = None
        ocr_languages: list[str] = []
        if tesseract_cmd and pytesseract is not None:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        if ocr_available and pytesseract is not None:
            try:
                ocr_version = str(pytesseract.get_tesseract_version())
                ocr_languages = sorted(pytesseract.get_languages(config=""))
            except Exception:
                ocr_available = False
                warnings.append("Tesseract capability probe failed; scanned-page OCR is unavailable.")

        with rendered_pdf:
            if rendered_pdf.page_count != page_count:
                raise DocumentProcessingError("PDF page count could not be verified")
            for index, pdf_page in enumerate(reader.pages):
                if time.monotonic() - started > max_seconds:
                    raise DocumentLimitError("PDF processing exceeded its time limit")

                extracted = pdf_page.extract_text(extraction_mode="plain") or ""
                page_regions = _digital_text_regions(rendered_pdf.load_page(index))
                remaining_text_chars = max_text_chars - text_chars_used
                if len(extracted) > remaining_text_chars:
                    extracted = extracted[:remaining_text_chars]
                    warnings.append("Extracted text was truncated at the configured limit")
                text_chars_used += len(extracted)

                has_embedded_text = bool(extracted.strip())
                rendered_page = rendered_pdf.load_page(index)
                has_page_images = bool(rendered_page.get_images(full=True))
                page_method = "text"
                page_confidence = None
                regions = page_regions
                if not has_embedded_text and _is_uniformly_blank_page(rendered_page):
                    blank_pages.append(index + 1)
                    pages.append(PageText(index + 1, extracted, page_method, None, page_regions))
                    continue
                if len(extracted.strip()) < 40 and has_page_images:
                    if ocr_available:
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
                            ocr_text, confidence, ocr_regions = _ocr_page_with_regions(rendered_pdf, index, timeout)
                        except pytesseract.TesseractNotFoundError:
                            ocr_available = False
                            ocr_unavailable = True
                            warnings.append("Tesseract OCR is not installed or configured")
                            pages.append(PageText(index + 1, extracted, "text", None, page_regions))
                            continue
                        except RuntimeError as exc:
                            if "timeout" in str(exc).lower():
                                raise DocumentLimitError("OCR exceeded its per-page time limit") from exc
                            ocr_failed = True
                            unreadable_pages.append(index + 1)
                            warnings.append(f"OCR failed on page {index + 1}; that page may require manual review.")
                            pages.append(PageText(index + 1, extracted, "text", None, page_regions))
                            continue
                        except Exception:
                            ocr_failed = True
                            unreadable_pages.append(index + 1)
                            warnings.append(f"OCR failed on page {index + 1}; that page may require manual review.")
                            pages.append(PageText(index + 1, extracted, "text", None, page_regions))
                            continue
                        if ocr_text:
                            remaining_text_chars = max_text_chars - text_chars_used
                            if len(ocr_text) > remaining_text_chars:
                                ocr_text = ocr_text[:remaining_text_chars]
                                warnings.append("Extracted text was truncated at the configured limit")
                            extracted = f"{extracted.rstrip()}\n{ocr_text}".strip() if has_embedded_text else ocr_text
                            text_chars_used += len(extracted)
                            page_method = "mixed" if has_embedded_text else "ocr"
                            page_confidence = confidence
                            regions = (*page_regions, *ocr_regions)
                        else:
                            unreadable_pages.append(index + 1)
                            warnings.append(f"No text was recognized on image-based page {index + 1}.")
                        pages.append(PageText(index + 1, extracted, page_method, page_confidence, tuple(regions)))
                    else:
                        ocr_unavailable = True
                        pages.append(PageText(index + 1, extracted, "text", None, page_regions))
                else:
                    pages.append(PageText(index + 1, extracted, "text", None, page_regions))

        has_text = any(page.text.strip() for page in pages)
        if ocr_unavailable and not has_text:
            processing_status = "ocr_unavailable"
            warnings.append("Scanned pages were not OCR processed; install and configure Tesseract to extract their text")
        elif ocr_failed or unreadable_pages or (ocr_unavailable and has_text):
            processing_status = "partial"
        elif not has_text:
            processing_status = "empty"
            warnings.append(
                "Blank page(s) were detected; OCR was not needed."
                if blank_pages
                else "No extractable text or image content was found in the PDF"
            )
        else:
            processing_status = "completed"

        methods = {page.method for page in pages if page.text.strip()}
        extraction_method = (
            "mixed" if "mixed" in methods or methods == {"text", "ocr"}
            else "ocr" if methods == {"ocr"}
            else "text" if methods == {"text"}
            else "none"
        )
        from app.services.document_classification import classify_document_text

        classification = classify_document_text(pages, registered_document_types or [])
        fields = _extract_fields(pages)
        if schema_definition is not None:
            fields = _extract_schema_fields(pages, schema_definition, fields)
        if time.monotonic() - started > max_seconds:
            raise DocumentLimitError("PDF processing exceeded its time limit")
        return {
            "processing_status": processing_status,
            "extraction_method": extraction_method,
            "pages_processed": len(pages),
            "pages": [
                {
                    "page": page.number,
                    "text": page.text,
                    "method": page.method,
                    "confidence": page.confidence,
                    "regions": list(page.regions),
                }
                for page in pages
            ],
            "ocr": {
                "engine": "tesseract" if ocr_version else None,
                "engine_version": ocr_version,
                "languages": ocr_languages,
                "available": ocr_available,
            },
            "processing_duration_ms": round((time.monotonic() - started) * 1000, 2),
            "unreadable_pages": unreadable_pages,
            "blank_pages": blank_pages,
            "field_extraction_version": FIELD_EXTRACTION_VERSION,
            "fields": fields,
            "classification": classification,
            "warnings": list(dict.fromkeys(warnings)),
        }
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentProcessingError("PDF is malformed or could not be processed") from exc
