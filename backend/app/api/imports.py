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

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
from app.services import transaction_importer
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


@router.post(
    "/transactions/import/phonepe",
    response_model=ImportResponse,
    responses={200: {"model": ImportResponse}, 202: {"model": ImportResponse}, 422: {"model": ImportResponse}},
    status_code=status.HTTP_201_CREATED,
)
def import_phonepe(
    payload: PhonePeImportRequest,
    current_user: User = Depends(get_import_user),
    db: Session = Depends(get_db),
):
    import_limiter.hit(f"import:{current_user.id}")

    outcome = transaction_importer.import_text(db, current_user.id, SOURCE_PHONEPE, payload.ocr_text, today_local())
    # Log only the outcome – never the OCR text, it contains financial details.
    logger.info("PhonePe import for user %s: %s", current_user.id, outcome.status)

    response = ImportResponse(
        success=outcome.status in ("created", "duplicate"),
        status=outcome.status,
        message=outcome.message,
        transaction=TransactionOut.model_validate(outcome.transaction) if outcome.transaction else None,
        existing_transaction_id=outcome.existing.id if outcome.existing else None,
        review_id=outcome.pending.id if outcome.pending else None,
        parsed_data=outcome.parse_result.to_dict() if outcome.status in ("review_required", "invalid") else None,
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
    return _pending_or_404(db, current_user, pending_id)


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
