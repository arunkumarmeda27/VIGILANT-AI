import argparse
from pathlib import Path

import fitz


def create_synthetic_pdf(output_path: Path) -> None:
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = fitz.open()
    try:
        page = document.new_page()
        heading_space = page.insert_textbox(
            fitz.Rect(48, 45, 548, 130),
            "SYNTHETIC DEMONSTRATION ONLY\nNOT ISSUED BY ANY AUTHORITY\nNOT VALID FOR SUBMISSION",
            fontsize=18,
            fontname="helv",
            color=(0.7, 0.05, 0.05),
            align=fitz.TEXT_ALIGN_CENTER,
        )
        content_space = page.insert_textbox(
            fitz.Rect(70, 165, 530, 760),
            "Sample data for local document extraction testing.\n\n"
            "Institution Name: Example Synthetic Institute\n"
            "Certificate No: SYNTHETIC-FS-0001\n"
            "Issue Date: 2026-01-15\n\n"
            "This file is fictional test input. It has no issuer, signature, "
            "seal, legal effect, or regulatory status.",
            fontsize=12,
            fontname="helv",
            color=(0.12, 0.15, 0.2),
            lineheight=1.5,
        )
        if heading_space < 0 or content_space < 0:
            raise ValueError("Synthetic PDF text does not fit on its page")
        document.save(output_path, garbage=4, deflate=True)
    except Exception:
        document.close()
        output_path.unlink(missing_ok=True)
        raise
    document.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an explicitly fictional PDF for local extraction demos."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination PDF path. Existing files are never overwritten.",
    )
    args = parser.parse_args()
    create_synthetic_pdf(args.output)
    print(f"Created synthetic test PDF: {args.output.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
