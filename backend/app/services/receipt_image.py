"""Validate and normalise an uploaded receipt image.

* The type is detected from the file's magic bytes – never trusted from the
  filename or the client's Content-Type.
* Supported: JPEG, PNG, HEIC/HEIF (iPhone). HEIC is decoded with pillow-heif
  (bundled libheif, no system packages needed).
* Decompression bombs and absurd dimensions are rejected.
* Everything happens in memory; nothing is written to disk or logged.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # HEIC/HEIF support (iPhone photos and some screenshots)
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:  # pragma: no cover - only if the dependency is missing
    HEIF_SUPPORTED = False

MAX_PIXELS = 40_000_000  # e.g. 5000 x 8000; bigger is not a receipt screenshot
MAX_SIDE = 12_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow raises DecompressionBombError above 2x this

HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}


class ImageValidationError(ValueError):
    """The upload is not an acceptable receipt image (-> HTTP 400)."""


@dataclass
class ReceiptImage:
    image: Image.Image  # RGB, orientation fixed
    format: str  # "jpeg" | "png" | "heif"
    sha256: str  # of the ORIGINAL upload (used to recognise re-shared receipts)
    original_bytes: int

    def resized(self, max_side: int) -> Image.Image:
        """Copy no larger than max_side on its longest edge (never upscaled)."""
        img = self.image
        scale = max_side / max(img.size)
        if scale >= 1:
            return img.copy()
        return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)

    def jpeg_bytes(self, max_side: int = 2048, quality: int = 88) -> bytes:
        """JPEG for the vision model / review screen (metadata like GPS is dropped)."""
        buffer = io.BytesIO()
        self.resized(max_side).save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()


def sniff_format(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brands = {data[8:12]} | {data[i:i + 4] for i in range(16, min(len(data), 64), 4)}
        if brands & HEIF_BRANDS:
            return "heif"
    return None


def load_receipt_image(data: bytes) -> ReceiptImage:
    if not data:
        raise ImageValidationError("The uploaded file is empty.")
    image_format = sniff_format(data)
    if image_format is None:
        raise ImageValidationError("Unsupported file type. Upload a JPEG, PNG or HEIC/HEIF image.")
    if image_format == "heif" and not HEIF_SUPPORTED:
        raise ImageValidationError("HEIC/HEIF images aren't supported on this server. Upload a JPEG or PNG.")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            width, height = opened.size
            if width < 50 or height < 50:
                raise ImageValidationError("The image is too small to be a receipt.")
            if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                raise ImageValidationError("The image dimensions are too large.")
            opened.load()
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError) as error:
        raise ImageValidationError("The image couldn't be read. It may be corrupted.") from error
    return ReceiptImage(image=image, format=image_format, sha256=hashlib.sha256(data).hexdigest(), original_bytes=len(data))
