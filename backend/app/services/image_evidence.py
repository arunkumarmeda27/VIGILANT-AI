import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO, Any

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError


SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
ANALYSIS_VERSION = "deterministic-image-quality-v1"
MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class InvalidEvidenceImage(ValueError):
    pass


class EvidenceImageTooLarge(ValueError):
    pass


class EvidenceImageStorageError(OSError):
    pass


def _quality_analysis(image: Image.Image) -> dict[str, Any]:
    grayscale = image.convert("L")
    statistics = ImageStat.Stat(grayscale)
    brightness = round(statistics.mean[0], 2)
    contrast = round(statistics.stddev[0], 2)
    edge_contrast = round(
        ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).stddev[0],
        2,
    )
    warnings = []
    if brightness < 20:
        warnings.append("image_is_very_dark")
    elif brightness > 245:
        warnings.append("image_is_very_bright")
    if contrast < 12:
        warnings.append("low_grayscale_contrast")
    if edge_contrast < 4:
        warnings.append("low_edge_contrast_possible_blur_or_flat_content")

    return {
        "task": "image_quality_assessment",
        "analysis_version": ANALYSIS_VERSION,
        "status": "quality_limited" if warnings else "quality_reviewable",
        "dimensions": {"width": image.width, "height": image.height},
        "metrics": {
            "mean_grayscale_brightness_0_255": brightness,
            "grayscale_standard_deviation_0_255": contrast,
            "edge_standard_deviation_0_255": edge_contrast,
        },
        "warnings": warnings,
        "method": (
            "Pillow grayscale mean and standard deviation plus FIND_EDGES standard "
            "deviation; thresholds are heuristic image-quality flags, not "
            "object detection, compliance, authenticity, or calibrated model confidence."
        ),
        "model": None,
        "human_review_required": True,
    }


def store_and_assess_image(
    file: BinaryIO,
    filename: str,
    content_type: str | None,
    storage_directory: Path,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> tuple[str, str, str, int, dict[str, Any]]:
    extension = Path(filename).suffix.lower()
    expected_content_type = SUPPORTED_IMAGE_TYPES.get(extension)
    if expected_content_type is None or (
        content_type and content_type.lower() not in {expected_content_type, "application/octet-stream"}
    ):
        raise InvalidEvidenceImage("Only PNG and JPEG image evidence is supported")

    image_directory = storage_directory / "image-evidence"
    try:
        image_directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".image-upload-",
            suffix=".tmp",
            dir=image_directory,
        )
    except OSError as exc:
        raise EvidenceImageStorageError("Could not prepare image storage") from exc

    temporary_path = Path(temporary_name)
    target_path: Path | None = None
    digest = hashlib.sha256()
    size = 0
    try:
        expected_format = "PNG" if extension == ".png" else "JPEG"
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := file.read(64 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise EvidenceImageTooLarge("Image exceeds the maximum allowed size")
                digest.update(chunk)
                destination.write(chunk)
        if size == 0:
            raise InvalidEvidenceImage("Image evidence file is empty")
        try:
            with Image.open(temporary_path) as image:
                if image.format != expected_format:
                    raise InvalidEvidenceImage("Image content does not match its filename extension")
                if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                    raise EvidenceImageTooLarge("Image dimensions exceed the supported limit")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise EvidenceImageTooLarge("Image pixel count exceeds the supported limit")
                image.verify()
            with Image.open(temporary_path) as image:
                image.load()
                analysis = _quality_analysis(image)
                width, height = image.size
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise InvalidEvidenceImage("Image content is malformed or unsupported") from exc

        storage_key = f"{uuid.uuid4().hex}{extension}"
        target_path = image_directory / storage_key
        os.replace(temporary_path, target_path)
        safe_filename = Path(filename.replace("\\", "/")).name
        safe_filename = "".join(
            character for character in safe_filename
            if ord(character) >= 32 and ord(character) != 127
        )[:255] or f"evidence{extension}"
        analysis["dimensions"] = {"width": width, "height": height}
        return storage_key, safe_filename, digest.hexdigest(), size, analysis
    except Exception as exc:
        try:
            temporary_path.unlink(missing_ok=True)
            if target_path is not None:
                target_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            raise EvidenceImageStorageError("Could not clean up temporary image") from cleanup_error
        if isinstance(exc, (InvalidEvidenceImage, EvidenceImageTooLarge)):
            raise
        if isinstance(exc, OSError):
            raise EvidenceImageStorageError("Could not store image evidence") from exc
        raise
