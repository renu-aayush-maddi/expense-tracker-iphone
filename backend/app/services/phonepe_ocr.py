"""Server-side OCR for receipt images (replaces the iPhone's built-in OCR).

Engine: RapidOCR (PaddleOCR PP-OCRv6 models compiled to ONNX, run with
onnxruntime). Chosen because it
  * installs with pip only – no system packages, works on Render's native Python runtime,
  * ships its ~31 MB models inside the wheel (no downloads at runtime),
  * is accurate on screenshots (it reads "¥183"/"□183" for ₹183 – the existing parser handles that),
  * fits in Render's free 512 MB instance when images are downscaled first
    (measured ~320-420 MB process RSS at a 900-1100 px longest side).

The engine is loaded lazily on the first image and reused. Only one OCR runs at
a time (it's CPU/RAM heavy). Swap the engine by changing `_run_engine` only.
OCR text is never logged.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from app.core.config import settings
from app.services.receipt_image import ReceiptImage

logger = logging.getLogger("app.ocr")

_engine = None
_engine_lock = threading.Lock()
_ocr_semaphore = threading.Semaphore(1)


@dataclass
class OcrResult:
    text: str = ""
    lines: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    engine: str = "rapidocr"
    duration_ms: int = 0
    error: str | None = None  # error type if OCR failed (never the message/content)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.lines)

    @property
    def mean_confidence(self) -> float:
        return round(sum(self.scores) / len(self.scores), 3) if self.scores else 0.0

    @property
    def min_digit_line_confidence(self) -> float:
        """Lowest confidence among lines containing digits (amounts, IDs, dates) – where errors hurt."""
        digit_scores = [s for line, s in zip(self.lines, self.scores) if any(c.isdigit() for c in line)]
        return round(min(digit_scores), 3) if digit_scores else 0.0

    def summary(self) -> dict:
        """Safe metadata for logs/review (no text)."""
        return {
            "engine": self.engine,
            "lines": len(self.lines),
            "mean_confidence": self.mean_confidence,
            "min_digit_line_confidence": self.min_digit_line_confidence,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr import RapidOCR  # imported lazily: keeps app startup light

            _engine = RapidOCR(
                params={
                    "Global.log_level": "error",
                    "Global.use_cls": False,  # receipts are upright; saves time and memory
                    "Global.min_side_len": 1,
                    "Global.max_side_len": 4000,  # we resize ourselves (see OCR_MAX_IMAGE_SIDE)
                    "Det.limit_type": "min",
                    "Det.limit_side_len": 32,  # never upscale for detection
                    "Rec.rec_batch_num": 1,
                    "EngineConfig.onnxruntime.intra_op_num_threads": 1,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                    "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
                }
            )
        return _engine


def _run_engine(image_rgb) -> tuple[list[str], list[float]]:
    bgr = np.asarray(image_rgb)[:, :, ::-1]  # OpenCV expects BGR
    output = _get_engine()(bgr)
    lines = [str(t).strip() for t in (output.txts or ())]
    scores = [float(s) for s in (output.scores or ())]
    kept = [(line, score) for line, score in zip(lines, scores) if line]
    return [line for line, _ in kept], [score for _, score in kept]


def is_available() -> bool:
    if not settings.OCR_ENABLED:
        return False
    try:
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


def extract_text_from_image(receipt: ReceiptImage) -> OcrResult:
    """Run OCR on a validated receipt image. Never raises: failures come back in `error`."""
    if not is_available():
        return OcrResult(error="OcrUnavailable")
    started = time.perf_counter()
    try:
        image = receipt.resized(settings.OCR_MAX_IMAGE_SIDE)
        with _ocr_semaphore:
            lines, scores = _run_engine(image)
        result = OcrResult(text="\n".join(lines), lines=lines, scores=scores)
    except Exception as error:  # engine errors must not break the import – vision/review take over
        result = OcrResult(error=type(error).__name__)
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info("OCR completed: %s", result.summary())
    return result
