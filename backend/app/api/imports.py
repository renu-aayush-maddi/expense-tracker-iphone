"""Import endpoints.

POST /api/transactions/import/phonepe          <- called by the iPhone Shortcut
GET  /api/imports/pending                      <- imports waiting for review
GET  /api/imports/pending/{id}
POST /api/imports/pending/reprocess            <- re-run all pending through the latest parser
POST /api/imports/pending/{id}/confirm         <- save the reviewed transaction
DELETE /api/imports/pending/{id}               <- discard
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_import_user
from app.api.transactions import duplicate_http_error
from app.core.config import settings
from app.core.constants import SOURCE_PHONEPE
from app.core.rate_limit import RateLimiter
from app.core.timeutils import today_local
from app.db.session import get_db
from app.models import PendingImport, User
from app.schemas.imports import ImportResponse, PendingImportDetailOut, PendingImportOut, PhonePeImportRequest
from app.schemas.transaction import TransactionCreate, TransactionDetailOut, TransactionOut
from app.services import receipt_image, security_service, transaction_importer
from app.services.transaction_importer import SimilarTransactionError
from app.services.transaction_service import DuplicateTransactionError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["imports"])

import_limiter = RateLimiter(max_requests=settings.IMPORT_RATE_LIMIT_PER_MINUTE)
reprocess_limiter = RateLimiter(max_requests=5)

STATUS_CODES = {
    "created": status.HTTP_201_CREATED,
    "duplicate": status.HTTP_200_OK,
    "review_required": status.HTTP_202_ACCEPTED,
    "invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


IMPORT_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary",
                                            "description": "Original PhonePe receipt image (JPEG, PNG, HEIC/HEIF)"}},
                }
            },
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["ocr_text"],
                    "properties": {"ocr_text": {"type": "string", "description": "Legacy: OCR text from the phone"}},
                }
            },
        },
    }
}


def _bad_request(message: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=code, detail=message)


async def _read_receipt_upload(request: Request) -> bytes:
    """The `file` part of a multipart upload, size-checked. Content is validated later from its bytes."""
    try:
        form = await request.form(max_files=1, max_fields=5)
    except HTTPException:
        raise
    except Exception:  # malformed multipart body, too many files...
        raise _bad_request("Malformed upload. Send the receipt as multipart/form-data with a 'file' field.")
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise _bad_request("Attach the receipt image in a form field named 'file'.")
    data = await upload.read(settings.max_upload_bytes + 1)
    await upload.close()
    if len(data) > settings.max_upload_bytes:
        raise _bad_request(f"The image is larger than {settings.MAX_UPLOAD_MB} MB.", status.HTTP_413_CONTENT_TOO_LARGE)
    return data


@router.post(
    "/transactions/import/phonepe",
    response_model=ImportResponse,
    responses={200: {"model": ImportResponse}, 202: {"model": ImportResponse}, 422: {"model": ImportResponse}},
    status_code=status.HTTP_201_CREATED,
    openapi_extra=IMPORT_OPENAPI,
)
async def import_phonepe(
    request: Request,
    current_user: User = Depends(get_import_user),
    db: Session = Depends(get_db),
):
    """Import a PhonePe receipt.

    * multipart/form-data with `file=<original receipt image>` (JPEG/PNG/HEIC):
      server OCR -> existing parser -> validation -> OpenAI Vision only if OCR is unsure.
    * application/json `{"ocr_text": "..."}`: legacy text import (phone-side OCR).
    """
    import_limiter.hit(f"import:{current_user.id}")
    content_type = (request.headers.get("content-type") or "").lower()
    today = today_local()

    if content_type.startswith("multipart/form-data"):
        data = await _read_receipt_upload(request)
        try:
            receipt = receipt_image.load_receipt_image(data)
        except receipt_image.ImageValidationError as error:
            raise _bad_request(str(error))
        # OCR is CPU-bound: run it off the event loop.
        outcome = await run_in_threadpool(transaction_importer.import_image, db, current_user.id, receipt, today)
    elif content_type.startswith("application/json"):
        try:
            payload = PhonePeImportRequest.model_validate(await request.json())
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from None
        except ValueError:
            raise _bad_request("The request body isn't valid JSON.")
        outcome = await run_in_threadpool(
            transaction_importer.import_text, db, current_user.id, SOURCE_PHONEPE, payload.ocr_text, today
        )
        outcome.extraction_source = outcome.extraction_source or "text"
    else:
        raise _bad_request("Send the receipt image as multipart/form-data (field 'file').",
                           status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    # Log only the outcome and source – never receipt content.
    security_service.record_event(db, security_service.IMPORT_REQUEST, request=request, user=current_user,
                                  success=outcome.status in ("created", "duplicate"),
                                  reason=f"{outcome.status} via {outcome.extraction_source}")
    logger.info("PhonePe import for user %s: %s (source=%s)", current_user.id, outcome.status, outcome.extraction_source)

    response = ImportResponse(
        success=outcome.status in ("created", "duplicate"),
        status=outcome.status,
        message=outcome.message,
        extraction_source=outcome.extraction_source,
        transaction=TransactionOut.model_validate(outcome.transaction) if outcome.transaction else None,
        existing_transaction_id=outcome.existing.id if outcome.existing else None,
        review_id=outcome.pending.id if outcome.pending else None,
        parsed_data=outcome.parse_result.to_dict() if outcome.status in ("review_required", "invalid") and outcome.parse_result else None,
        issues=outcome.parse_result.issues if outcome.parse_result else [],
    )
    return JSONResponse(status_code=STATUS_CODES[outcome.status], content=response.model_dump(mode="json"))


def _pending_or_404(db: Session, user: User, pending_id: uuid.UUID) -> PendingImport:
    pending = db.scalar(select(PendingImport).where(PendingImport.id == pending_id, PendingImport.user_id == user.id))
    if pending is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending import not found.")
    return pending


@router.get("/imports/pending", response_model=list[PendingImportOut])
def list_pending(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(PendingImport).where(PendingImport.user_id == current_user.id).order_by(PendingImport.created_at.desc())
    ).all()


@router.post("/imports/pending/reprocess")
def reprocess_pending(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-run every pending import through the latest parser (+ LLM fallback).
    Returns how many were saved, were duplicates, or still need review."""
    reprocess_limiter.hit(f"reprocess:{current_user.id}")
    counts = transaction_importer.reprocess_pending(db, current_user.id, today_local())
    logger.info("Reprocessed pending imports for user %s: %s", current_user.id, counts)
    return counts


@router.get("/imports/pending/{pending_id}", response_model=PendingImportDetailOut)
def get_pending(pending_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pending = _pending_or_404(db, current_user, pending_id)
    detail = PendingImportDetailOut.model_validate(pending, from_attributes=True)
    detail.has_image = pending.image_content_type is not None  # without loading the image bytes
    return detail


@router.get("/imports/pending/{pending_id}/image")
def get_pending_image(pending_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The receipt image of an image import awaiting review – only for its owner, never cached publicly."""
    pending = _pending_or_404(db, current_user, pending_id)
    if not pending.image_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No image stored for this import.")
    return Response(content=pending.image_data, media_type=pending.image_content_type or "image/jpeg",
                    headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"})


@router.post(
    "/imports/pending/{pending_id}/confirm",
    response_model=TransactionDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def confirm_pending(
    pending_id: uuid.UUID,
    payload: TransactionCreate,
    allow_similar: bool = Query(default=False, description="Save even if a similar transaction exists"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pending = _pending_or_404(db, current_user, pending_id)
    try:
        return transaction_importer.confirm_pending(db, pending, payload.model_dump(), allow_similar=allow_similar)
    except DuplicateTransactionError as error:
        raise duplicate_http_error(error)
    except SimilarTransactionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A transaction with the same date, amount and merchant already exists.",
                "existing_transaction_id": str(error.existing.id),
                "similar": True,
            },
        )


@router.delete("/imports/pending/{pending_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_pending(pending_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pending = _pending_or_404(db, current_user, pending_id)
    db.delete(pending)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
