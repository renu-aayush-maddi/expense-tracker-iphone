"""Admin: transactions across all users. Read + soft delete/restore only:
admins never silently edit someone's financial data."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.admin.common import paginate
from app.api.deps import require_permission
from app.core.permissions import Permission, can_act_on
from app.db.session import get_db
from app.models import Transaction, User
from app.schemas.admin import AdminTransactionDetail, AdminTransactionRow, Page, ReasonRequest, mask
from app.services import audit_service
from app.services.admin_service import now

router = APIRouter(prefix="/transactions", tags=["admin: transactions"])

SORTS = {"date": Transaction.transaction_date, "amount": Transaction.amount, "created": Transaction.created_at,
         "merchant": Transaction.merchant_name}


def _row(t: Transaction, email: str) -> dict:
    return {
        "id": t.id, "user_id": t.user_id, "user_email": email, "merchant_name": t.merchant_name, "amount": t.amount,
        "category": t.category, "transaction_date": t.transaction_date, "source": t.source,
        "is_reimbursable": t.is_reimbursable, "created_at": t.created_at, "deleted_at": t.deleted_at,
    }


def _detail(t: Transaction, email: str) -> dict:
    return {
        **_row(t, email),
        "transaction_time": t.transaction_time, "payment_method": t.payment_method, "bank": t.bank,
        "utr_masked": mask(t.utr), "phonepe_transaction_id_masked": mask(t.phonepe_transaction_id, 6),
        "account_last4": t.account_last4, "extraction_method": t.extraction_method,
        "deleted_reason": t.deleted_reason, "updated_at": t.updated_at,
        # raw OCR text and notes are intentionally NOT exposed to admins (least privilege)
    }


@router.get("", response_model=Page[AdminTransactionRow])
def list_transactions(
    user_id: uuid.UUID | None = None,
    user: str | None = Query(default=None, max_length=100, description="search by user email"),
    merchant: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=50),
    source: str | None = Query(default=None, max_length=30),
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: Decimal | None = Query(default=None, ge=0),
    max_amount: Decimal | None = Query(default=None, ge=0),
    deleted: Literal["exclude", "include", "only"] = "exclude",
    sort_by: Literal["date", "amount", "created", "merchant"] = "created",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    admin: User = Depends(require_permission(Permission.TRANSACTIONS_VIEW)),
    db: Session = Depends(get_db),
):
    query = select(Transaction, User.email).join(User, User.id == Transaction.user_id)
    if user_id:
        query = query.where(Transaction.user_id == user_id)
    if user:
        query = query.where(or_(User.email.ilike(f"%{user}%"), User.full_name.ilike(f"%{user}%")))
    if merchant:
        query = query.where(Transaction.merchant_name.ilike(f"%{merchant}%"))
    if category:
        query = query.where(Transaction.category == category)
    if source:
        query = query.where(Transaction.source == source)
    if date_from:
        query = query.where(Transaction.transaction_date >= date_from)
    if date_to:
        query = query.where(Transaction.transaction_date <= date_to)
    if min_amount is not None:
        query = query.where(Transaction.amount >= min_amount)
    if max_amount is not None:
        query = query.where(Transaction.amount <= max_amount)
    if deleted == "exclude":
        query = query.where(Transaction.deleted_at.is_(None))
    elif deleted == "only":
        query = query.where(Transaction.deleted_at.is_not(None))
    column = SORTS[sort_by]
    query = query.order_by(column.desc() if sort_order == "desc" else column.asc(), Transaction.id)
    rows, total, pages = paginate(db, query, page, page_size)
    return {"items": [_row(t, email) for t, email in rows], "total": total, "page": page,
            "page_size": page_size, "pages": pages}


def _ensure_can_modify(admin: User, owner: User) -> None:
    if owner.id != admin.id and not can_act_on(admin.role, owner.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can change administrators' data.")


def _get(db: Session, transaction_id: uuid.UUID) -> tuple[Transaction, User]:
    row = db.execute(
        select(Transaction, User).join(User, User.id == Transaction.user_id).where(Transaction.id == transaction_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
    return row


@router.get("/{transaction_id}", response_model=AdminTransactionDetail)
def get_transaction(transaction_id: uuid.UUID, request: Request,
                    admin: User = Depends(require_permission(Permission.TRANSACTIONS_VIEW)),
                    db: Session = Depends(get_db)):
    transaction, owner = _get(db, transaction_id)
    audit_service.record(db, "TRANSACTION_VIEWED", actor=admin, request=request, resource_type="transaction",
                         resource_id=transaction.id, target=owner)
    return _detail(transaction, owner.email)


@router.post("/{transaction_id}/delete", response_model=AdminTransactionDetail)
def delete_transaction(transaction_id: uuid.UUID, payload: ReasonRequest, request: Request,
                       admin: User = Depends(require_permission(Permission.TRANSACTIONS_MANAGE)),
                       db: Session = Depends(get_db)):
    """Soft delete: hidden from the user and all totals, kept in the database."""
    transaction, owner = _get(db, transaction_id)
    _ensure_can_modify(admin, owner)
    if transaction.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already deleted.")
    transaction.deleted_at = now()
    transaction.deleted_by_id = admin.id
    transaction.deleted_reason = payload.reason
    audit_service.record(db, "TRANSACTION_DELETED", actor=admin, request=request, resource_type="transaction",
                         resource_id=transaction.id, target=owner,
                         details={"reason": payload.reason, "amount": str(transaction.amount),
                                  "date": transaction.transaction_date.isoformat(), "merchant": transaction.merchant_name},
                         commit=False)
    db.commit()
    return _detail(transaction, owner.email)


@router.post("/{transaction_id}/restore", response_model=AdminTransactionDetail)
def restore_transaction(transaction_id: uuid.UUID, payload: ReasonRequest, request: Request,
                        admin: User = Depends(require_permission(Permission.TRANSACTIONS_MANAGE)),
                        db: Session = Depends(get_db)):
    transaction, owner = _get(db, transaction_id)
    _ensure_can_modify(admin, owner)
    if transaction.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This transaction isn't deleted.")
    transaction.deleted_at = transaction.deleted_by_id = transaction.deleted_reason = None
    audit_service.record(db, "TRANSACTION_RESTORED", actor=admin, request=request, resource_type="transaction",
                         resource_id=transaction.id, target=owner, details={"reason": payload.reason}, commit=False)
    db.commit()
    return _detail(transaction, owner.email)
