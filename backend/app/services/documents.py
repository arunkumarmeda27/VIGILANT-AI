import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, NamedTuple


class InvalidPDFError(Exception):
    pass


class DocumentTooLargeError(Exception):
    pass


class DocumentStorageError(Exception):
    pass


class StoredPDF(NamedTuple):
    storage_key: str
    original_filename: str
    sha256: str
    file_size: int


def store_pdf(
    file: BinaryIO,
    original_filename: str,
    storage_directory: Path,
    max_size_bytes: int,
) -> StoredPDF:
    if not original_filename.lower().endswith(".pdf"):
        raise InvalidPDFError

    try:
        storage_directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-",
            suffix=".tmp",
            dir=storage_directory,
        )
    except OSError as exc:
        raise DocumentStorageError from exc

    temporary_path = Path(temporary_name)
    stored_path: Path | None = None

    try:
        digest = hashlib.sha256()
        size = 0
        header = bytearray()
        tail = b""

        with os.fdopen(descriptor, "wb") as destination:
            while chunk := file.read(64 * 1024):
                size += len(chunk)
                if size > max_size_bytes:
                    raise DocumentTooLargeError

                if len(header) < 1024:
                    header.extend(chunk[:1024 - len(header)])
                tail = (tail + chunk)[-1024:]
                digest.update(chunk)
                destination.write(chunk)

        if b"%PDF-" not in header or b"%%EOF" not in tail:
            raise InvalidPDFError

        storage_key = f"{uuid.uuid4().hex}.pdf"
        stored_path = storage_directory / storage_key
        os.replace(temporary_path, stored_path)

        safe_filename = original_filename.replace("\\", "/").rsplit("/", 1)[-1]
        safe_filename = "".join(
            character for character in safe_filename
            if ord(character) >= 32 and ord(character) != 127
        )[:512]
        if not safe_filename:
            safe_filename = "document.pdf"

        return StoredPDF(storage_key, safe_filename, digest.hexdigest(), size)
    except Exception as exc:
        try:
            temporary_path.unlink(missing_ok=True)
            if stored_path is not None:
                stored_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise DocumentStorageError from cleanup_error
        if isinstance(exc, OSError):
            raise DocumentStorageError from exc
        raise
